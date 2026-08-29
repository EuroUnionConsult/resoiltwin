"""Cliente do Copernicus Climate Data Store (reanalise meteorologica).

O CDS e assincrono: submeter devolve um jobID, o estado passa por
accepted -> running -> successful|failed, e so depois ha um ficheiro para
descarregar. As tres operacoes estao separadas (submit/wait/download) para
que quem chama possa sondar, desistir ou retomar sem repetir a submissao.

Tudo o que esta aqui codificado sobre o formato dos pedidos foi medido contra
a API real a 29/08/2026, nao lido da documentacao:

- autenticacao por cabecalho PRIVATE-TOKEN (nao Bearer, nao Basic);
- AgERA5 com estatistica diaria NAO leva `time` -- com `time` a API responde
  "not a valid combination of values";
- `version` tem de ser "2_0" (1.0 e 1.1 estao descontinuadas);
- `area` e [Norte, Oeste, Sul, Este];
- ERA5-Land exige `data_format` e `download_format`, os dois;
- uma caixa menor do que a celula da grelha devolve MultiAdaptorNoDataError:
  [39.05, -9.26, 39.02, -9.22] (~3 km) falha, [39.24, -9.44, 38.84, -9.04]
  (~40 km) funciona.
"""

import logging
import tempfile
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
from netCDF4 import Dataset, num2date

from resoiltwin.weather.metrics import UNIDADE_POR_METRICA, WeatherMetric

logger = logging.getLogger(__name__)

DATASET_AGERA5 = "sis-agrometeorological-indicators"
DATASET_ERA5_LAND = "reanalysis-era5-land"

VERSAO_AGERA5 = "2_0"
RESOLUCAO_AGERA5_GRAUS = 0.1

# A grelha do AgERA5 e de 0,1 graus (~9 km) e a AOI de Turcifal tem ~2,5 km:
# pedir a caixa da parcela devolve MultiAdaptorNoDataError, nao uma serie
# vazia. 0,4 graus e o lado da caixa que foi medida a funcionar a 29/08/2026
# -- quatro celulas de lado, folga suficiente para o subconjunto nunca cair
# entre nos da grelha.
LADO_MINIMO_GRAUS = 0.4

# margem para nao alargar uma caixa que ja tem o lado minimo e so parece
# menor por causa da aritmetica de virgula flutuante (-9.04 - -9.44 da
# 0.3999999999999999, nao 0.4).
_TOLERANCIA_GRAUS = 1e-9

_ESTADO_BOM = "successful"
_ESTADOS_MAUS = ("failed", "dismissed")

_MAGIA_ZIP = b"PK\x03\x04"
_NOMES_LAT = ("lat", "latitude")
_NOMES_LON = ("lon", "longitude")
_NOMES_TEMPO = ("time", "valid_time")


def _kelvin_para_celsius(valor: float) -> float:
    return valor - 273.15


def _sem_conversao(valor: float) -> float:
    return valor


def _joule_por_dia_para_watt(valor: float) -> float:
    """J m-2 dia-1 para W m-2: dividir pelos segundos de um dia."""
    return valor / 86400.0


# variavel do AgERA5 -> (estatistica, metrica do vocabulario, conversao de unidade).
# A estatistica a None significa "nao enviar `statistic`": ha variaveis do AgERA5
# que ja sao diarias por definicao e recusam o campo.
_VARIAVEIS_AGERA5: dict[str, tuple[str | None, WeatherMetric, object]] = {
    "2m_temperature": ("24_hour_mean", WeatherMetric.air_temperature, _kelvin_para_celsius),
    "precipitation_flux": (None, WeatherMetric.precipitation, _sem_conversao),
    "solar_radiation_flux": (None, WeatherMetric.solar_radiation, _joule_por_dia_para_watt),
}


def expandir_area(area: list[float], lado_minimo: float = LADO_MINIMO_GRAUS) -> tuple[list[float], bool]:
    """Alarga uma caixa pequena de mais para a grelha, mantendo-a centrada.

    Devolve `(caixa, alargada)` -- a caixa que deve mesmo ser pedida e se
    houve alargamento. Devolver so a caixa nova nao chegava: quem grava a
    proveniencia precisa de saber que o que foi pedido nao e o que foi
    passado, senao o `evidence` afirma uma area que nunca foi transferida.
    """
    if len(area) != 4:
        raise ValueError("area tem de ser [Norte, Oeste, Sul, Este], quatro numeros")
    norte, oeste, sul, este = (float(x) for x in area)
    if norte < sul:
        raise ValueError(f"Norte ({norte}) tem de ser maior ou igual a Sul ({sul})")
    if este < oeste:
        raise ValueError(f"Este ({este}) tem de ser maior ou igual a Oeste ({oeste})")

    alargada = False
    if norte - sul < lado_minimo - _TOLERANCIA_GRAUS:
        centro = (norte + sul) / 2
        norte, sul = centro + lado_minimo / 2, centro - lado_minimo / 2
        alargada = True
    if este - oeste < lado_minimo - _TOLERANCIA_GRAUS:
        centro = (este + oeste) / 2
        este, oeste = centro + lado_minimo / 2, centro - lado_minimo / 2
        alargada = True
    if not alargada:
        return [float(x) for x in area], False

    nova = [round(norte, 6), round(oeste, 6), round(sul, 6), round(este, 6)]
    logger.info("caixa alargada de %s para %s (lado minimo %s graus)", list(area), nova, lado_minimo)
    return nova, True


def inputs_agera5(variavel: str, statistic: str | None, ano: str, mes: str,
                  dias: list[str], area: list[float]) -> dict:
    """Corpo do pedido ao AgERA5. Nunca leva `time` -- ver docstring do modulo."""
    corpo = {
        "variable": [variavel],
        "year": ano,
        "month": mes,
        "day": list(dias),
        "version": VERSAO_AGERA5,
        "area": list(area),
    }
    if statistic is not None:
        corpo["statistic"] = [statistic]
    return corpo


def inputs_era5_land(variaveis: list[str], ano: str, mes: str, dias: list[str],
                     horas: list[str], area: list[float]) -> dict:
    """Corpo do pedido ao ERA5-Land.

    Ao contrario do AgERA5, este leva `time` (e horario, nao diario) e exige
    os dois campos de formato: sem `data_format` ou sem `download_format` o
    pedido e recusado.
    """
    return {
        "variable": list(variaveis),
        "year": ano,
        "month": mes,
        "day": list(dias),
        "time": list(horas),
        "area": list(area),
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


class CDSClient:
    """Fala HTTP com o CDS. Nao sabe nada da base de dados, como o CDSEClient."""

    def __init__(self, api_url: str, api_key: str, transport=None, timeout: float = 180.0,
                 intervalo_sondagem_s: float = 5.0):
        self._base = api_url.rstrip("/")
        self._key = api_key
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)
        self._intervalo = intervalo_sondagem_s

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self._key, "Content-Type": "application/json"}

    def submit(self, dataset: str, inputs: dict) -> str:
        """Submete um pedido e devolve o jobID."""
        url = f"{self._base}/retrieve/v1/processes/{dataset}/execution"
        r = self._client.post(url, json={"inputs": inputs}, headers=self._headers())
        if r.status_code >= 400:
            raise _erro_resposta(r, f"CDS recusou o pedido a {dataset}")
        job_id = (r.json() or {}).get("jobID")
        if not job_id:
            # sem jobID nao ha nada para sondar; deixar passar daria um wait()
            # sobre None e um erro muito mais longe da causa.
            raise RuntimeError(
                f"CDS aceitou o pedido a {dataset} com {r.status_code} mas a resposta nao "
                f"traz jobID: {r.text[:200]}")
        return job_id

    def wait(self, job_id: str, timeout_s: float = 900.0) -> str:
        """Sonda o job ate terminar. Devolve o estado final ('successful').

        Um job falhado levanta RuntimeError com o traceback que o CDS guarda
        em /results -- /jobs/{id} so devolve `status`, e um 'failed' seco nao
        diz se a caixa era pequena de mais, se a variavel nao existe ou se a
        data esta fora do periodo coberto.
        """
        inicio = time.monotonic()
        while True:
            estado = self._estado(job_id)
            if estado == _ESTADO_BOM:
                return estado
            if estado in _ESTADOS_MAUS:
                raise RuntimeError(
                    f"CDS: o job {job_id} terminou em '{estado}': {self._motivo_de_falha(job_id)}")
            decorrido = time.monotonic() - inicio
            if decorrido >= timeout_s:
                raise TimeoutError(
                    f"CDS: o job {job_id} ainda estava em '{estado}' ao fim de {decorrido:.0f}s "
                    f"(tecto {timeout_s:.0f}s). O job nao foi cancelado -- continua a correr no "
                    f"CDS e pode ser retomado em {self._base}/retrieve/v1/jobs/{job_id}.")
            time.sleep(min(self._intervalo, max(timeout_s - decorrido, 0.0)))

    def download(self, job_id: str, destino) -> Path:
        """Descarrega o resultado do job para `destino` e devolve o caminho.

        Se `destino` for uma pasta existente, o ficheiro fica la dentro com o
        nome que vem no href.
        """
        href = self._href_do_resultado(job_id)
        destino = Path(destino)
        if destino.is_dir():
            destino = destino / (Path(httpx.URL(href).path).name or f"{job_id}.nc")
        destino.parent.mkdir(parents=True, exist_ok=True)
        # sem os headers do CDS de proposito: o href aponta para o object store,
        # um host diferente, e a chave da API nao tem nada que ir para la.
        r = self._client.get(href)
        if r.status_code >= 400:
            raise _erro_resposta(r, f"CDS: falhou a transferencia do resultado do job {job_id}")
        destino.write_bytes(r.content)
        return destino

    def agera5_diario(self, area: list[float], date_from: str, date_to: str,
                      variaveis: list[str] | None = None, timeout_s: float = 900.0) -> list[dict]:
        """Serie diaria do AgERA5 para a caixa dada, ja normalizada.

        Orquestra submit/wait/download por cada variavel e por cada mes (o
        corpo do CDS leva um ano e um mes de cada vez), converte as unidades
        para o vocabulario de `weather.metrics` e devolve uma linha por dia e
        por metrica. Cada linha carrega a caixa que foi mesmo pedida --
        `area_requested` -- e nao a que foi passada, que pode ter sido
        alargada por ser menor do que a celula da grelha.
        """
        variaveis = list(variaveis) if variaveis else ["2m_temperature"]
        desconhecidas = [v for v in variaveis if v not in _VARIAVEIS_AGERA5]
        if desconhecidas:
            raise ValueError(
                f"variaveis do AgERA5 nao suportadas: {desconhecidas}. "
                f"Suportadas: {sorted(_VARIAVEIS_AGERA5)}")
        caixa, alargada = expandir_area(area)
        meses = _meses_do_intervalo(date_from, date_to)

        linhas: list[dict] = []
        for variavel in variaveis:
            statistic, metrica, converte = _VARIAVEIS_AGERA5[variavel]
            for (ano, mes), dias in meses:
                corpo = inputs_agera5(variavel, statistic, ano, mes, dias, caixa)
                job_id = self.submit(DATASET_AGERA5, corpo)
                self.wait(job_id, timeout_s=timeout_s)
                with tempfile.TemporaryDirectory() as pasta:
                    ficheiro = self.download(job_id, Path(pasta) / f"{job_id}.nc")
                    serie, cell_lat, cell_lon = ler_serie_netcdf(ficheiro)
                for dia, valor in serie:
                    linhas.append({
                        "date": dia,
                        "metric": metrica,
                        "value": converte(valor),
                        "unit": UNIDADE_POR_METRICA[metrica],
                        "variable": variavel,
                        "dataset": DATASET_AGERA5,
                        "cell_lat": cell_lat,
                        "cell_lon": cell_lon,
                        "cell_size_deg": RESOLUCAO_AGERA5_GRAUS,
                        "area_original": [float(x) for x in area],
                        "area_requested": caixa,
                        "area_expanded": alargada,
                    })
        linhas.sort(key=lambda linha: (linha["date"], linha["metric"]))
        return linhas

    def _estado(self, job_id: str) -> str:
        r = self._client.get(f"{self._base}/retrieve/v1/jobs/{job_id}", headers=self._headers())
        if r.status_code >= 400:
            raise _erro_resposta(r, f"CDS: falhou a consulta ao estado do job {job_id}")
        return (r.json() or {}).get("status", "")

    def _resultados(self, job_id: str) -> httpx.Response:
        return self._client.get(f"{self._base}/retrieve/v1/jobs/{job_id}/results",
                                headers=self._headers())

    def _href_do_resultado(self, job_id: str) -> str:
        r = self._resultados(job_id)
        if r.status_code >= 400:
            raise _erro_resposta(r, f"CDS: o job {job_id} nao tem resultado para descarregar")
        href = (((r.json() or {}).get("asset") or {}).get("value") or {}).get("href")
        if not href:
            raise RuntimeError(
                f"CDS: o resultado do job {job_id} nao traz asset.value.href: {r.text[:200]}")
        return href

    def _motivo_de_falha(self, job_id: str) -> str:
        """Le a razao real da falha, que so existe em /jobs/{id}/results.

        Mesmo principio do `_erro_resposta` do CDSE: sem isto ficava-se com
        'failed' e o operador nao sabia se o problema era a caixa, a variavel
        ou a data. O traceback do CDS pode ter varios KB e a linha util e a
        ultima (a excepcao), por isso guarda-se a cauda, nao a cabeca.
        """
        try:
            r = self._resultados(job_id)
        except httpx.HTTPError as erro:
            return f"(nao foi possivel ler /results: {erro})"
        corpo = {}
        if r.text:
            try:
                corpo = r.json()
            except ValueError:
                corpo = {}
        motivo = corpo.get("traceback") or corpo.get("detail") or corpo.get("title")
        if not motivo:
            return r.text[:400] if r.text else "(o CDS nao deu razao nenhuma)"
        motivo = str(motivo).strip()
        return motivo if len(motivo) <= 600 else "..." + motivo[-600:]


def ler_serie_netcdf(caminho) -> tuple[list[tuple[str, float]], float, float]:
    """Le um NetCDF do AgERA5 e devolve ([(data, valor)], cell_lat, cell_lon).

    O valor de cada dia e a media espacial das celulas da caixa: a caixa foi
    alargada para satisfazer a grelha, portanto tem varias celulas e escolher
    uma a olho seria arbitrario. As coordenadas devolvidas sao o centro da
    caixa lida, que e o que a proveniencia da celula precisa de registar.

    O CDS entrega uns pedidos como .nc solto e outros dentro de um zip; os
    dois casos sao tratados aqui para que quem chama nao tenha de adivinhar.
    """
    caminho = Path(caminho)
    with caminho.open("rb") as f:
        e_zip = f.read(4) == _MAGIA_ZIP
    if not e_zip:
        return _ler_netcdf_solto(caminho)
    with zipfile.ZipFile(caminho) as z:
        membros = [n for n in z.namelist() if n.lower().endswith(".nc")]
        if not membros:
            raise RuntimeError(f"o zip {caminho.name} do CDS nao traz nenhum .nc: {z.namelist()}")
        destino = caminho.parent / Path(membros[0]).name
        destino.write_bytes(z.read(membros[0]))
    return _ler_netcdf_solto(destino)


def _ler_netcdf_solto(caminho: Path) -> tuple[list[tuple[str, float]], float, float]:
    ds = Dataset(str(caminho))
    try:
        nome_tempo = _primeiro_nome(ds, _NOMES_TEMPO)
        nome_lat = _primeiro_nome(ds, _NOMES_LAT)
        nome_lon = _primeiro_nome(ds, _NOMES_LON)
        coordenadas = {nome_tempo, nome_lat, nome_lon}
        candidatas = [v for nome, v in ds.variables.items()
                      if nome not in coordenadas and v.ndim == 3]
        if not candidatas:
            raise RuntimeError(
                f"{caminho.name}: nenhuma variavel (tempo, lat, lon) no ficheiro; "
                f"variaveis presentes: {sorted(ds.variables)}")
        var = candidatas[0]
        tempo = ds.variables[nome_tempo]
        datas = num2date(tempo[:], tempo.units, getattr(tempo, "calendar", "standard"))
        serie = [(f"{d.year:04d}-{d.month:02d}-{d.day:02d}", float(var[i].mean()))
                 for i, d in enumerate(datas)]
        cell_lat = float(ds.variables[nome_lat][:].mean())
        cell_lon = float(ds.variables[nome_lon][:].mean())
    finally:
        ds.close()
    return serie, cell_lat, cell_lon


def _primeiro_nome(ds, nomes: tuple[str, ...]) -> str:
    for nome in nomes:
        if nome in ds.variables:
            return nome
    raise RuntimeError(f"o ficheiro nao traz nenhuma de {nomes}; tem {sorted(ds.variables)}")


def _meses_do_intervalo(date_from: str, date_to: str) -> list[tuple[tuple[str, str], list[str]]]:
    """Parte um intervalo de datas nos meses que o corpo do CDS aceita.

    O pedido leva um ano e um mes de cada vez, com a lista de dias; um
    intervalo que atravesse a fronteira do mes tem de dar dois pedidos, senao
    metade da serie desaparecia em silencio.
    """
    inicio, fim = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if inicio > fim:
        raise ValueError(f"date_from ({date_from}) e posterior a date_to ({date_to})")
    meses: dict[tuple[str, str], list[str]] = {}
    dia = inicio
    while dia <= fim:
        meses.setdefault((f"{dia.year:04d}", f"{dia.month:02d}"), []).append(f"{dia.day:02d}")
        dia += timedelta(days=1)
    return sorted(meses.items())


def _erro_resposta(r: httpx.Response, prefixo: str) -> RuntimeError:
    """Formata um erro do CDS com o corpo, nao so o codigo HTTP.

    Mesmo papel do helper homonimo em resoiltwin.eo.cdse: o CDS responde no
    formato de problema HTTP (type/title/detail) e e ai que esta a razao. Um
    raise_for_status() seco deitava-a fora. Se o corpo nao for JSON (proxy,
    WAF, pagina de erro), degrada para o texto truncado.
    """
    corpo = {}
    if r.text:
        try:
            corpo = r.json()
        except ValueError:
            corpo = {}
    codigo = corpo.get("type") or corpo.get("title") or r.status_code
    descricao = corpo.get("detail") or corpo.get("traceback")
    if descricao is None:
        descricao = r.text[:200] if r.text else "(corpo vazio)"
    return RuntimeError(f"{prefixo}: {r.status_code} {codigo} - {descricao}")
