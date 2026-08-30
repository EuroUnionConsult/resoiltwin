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
import math
import tempfile
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy.ma
from netCDF4 import Dataset, num2date

from resoiltwin.weather.metrics import (
    UNIDADE_POR_METRICA, AggregationOperator, WeatherMetric, proveniencia_de_agregacao,
)

logger = logging.getLogger(__name__)

DATASET_AGERA5 = "sis-agrometeorological-indicators"
DATASET_ERA5_LAND = "reanalysis-era5-land"

VERSAO_AGERA5 = "2_0"
RESOLUCAO_AGERA5_GRAUS = 0.1

# A grelha do AgERA5 e de 0,1 graus (~9 km) e a AOI de Turcifal tem ~2,5 km:
# pedir a caixa da parcela devolve MultiAdaptorNoDataError, nao uma serie
# vazia. 0,4 graus e o lado da caixa MEDIDO a funcionar a 29/08/2026 -- nao e
# o minimo provado: nao se procurou o menor lado que ainda passa. Alargar de
# mais nao contamina o valor, porque o que se le do ficheiro e uma unica
# celula (a do sitio) e nao a media da caixa; o alargamento e so transporte.
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


# variavel do AgERA5 -> (estatistica, nome dentro do NetCDF, metrica do
# vocabulario, conversao de unidade).
# A estatistica a None significa "nao enviar `statistic`": ha variaveis do AgERA5
# que ja sao diarias por definicao e recusam o campo.
#
# O segundo campo e o nome com que a variavel aparece DENTRO do ficheiro, que
# nao e o nome com que se pede. Sem ele nao havia como confirmar que o que se
# leu e o que se pediu: o `variable` que vai para o `evidence` vem do pedido, e
# uma divergencia entre pedido e ficheiro gravava um valor de uma grandeza com
# o nome de outra -- e ainda convertido pela formula da grandeza errada, porque
# a conversao tambem e escolhida pelo nome pedido.
#
# Os quatro nomes foram lidos de ficheiros reais do CDS a 30/08/2026 (AgERA5
# final-v2.0.0, dia 2026-08-10, area de Turcifal). Se o Copernicus mudar o
# nome numa versao futura, a ingestao passa a recusar-se em voz alta em vez de
# gravar outra coisa em silencio -- que e a troca que se quer.
#
# `reference_evapotranspiration` e a evapotranspiracao de referencia que o
# AgERA5 ja traz calculada, e nao uma conta feita aqui: o ficheiro de
# 2026-08-10 declara `long_name` "Penman-Monteith reference evapotranspiration
# according to the FAO56 approach" e `units` "mm d-1". Sai em milimetros por
# dia, que e ja a unidade do vocabulario, por isso nao ha conversao -- e o
# pedido nao leva `statistic`, medido a 30/08/2026 com o CDS a aceitar o
# corpo sem ele.
_VARIAVEIS_AGERA5: dict[str, tuple[str | None, str, WeatherMetric, object]] = {
    "2m_temperature": ("24_hour_mean", "Temperature_Air_2m_Mean_24h",
                       WeatherMetric.air_temperature, _kelvin_para_celsius),
    "precipitation_flux": (None, "Precipitation_Flux",
                           WeatherMetric.precipitation, _sem_conversao),
    "solar_radiation_flux": (None, "Solar_Radiation_Flux",
                             WeatherMetric.solar_radiation, _joule_por_dia_para_watt),
    "reference_evapotranspiration": (None, "ReferenceET_PenmanMonteith_FAO56",
                                     WeatherMetric.reference_evapotranspiration,
                                     _sem_conversao),
}

# O que cada numero do AgERA5 RESUME, que nao e o `statistic` do pedido.
#
# A tabela e separada da de cima de proposito, e a razao e o achado: as duas
# respondem a perguntas diferentes. A de cima diz o que enviar ao CDS -- e tres
# das quatro variaveis nao levam `statistic` nenhum, porque a API o recusa em
# variaveis que ja sao diarias por definicao. **Mas as quatro sao agregados de
# 24 horas.** Copiar o campo do pedido para o `evidence` gravava `null` na
# precipitacao, na radiacao e na evapotranspiracao, e um `null` ali lia-se como
# "isto nao e um agregado" -- o contrario da verdade, escrito com ar de
# proveniencia.
#
# Um dia carimbado a meia-noite com o valor de 24 horas nao e uma medicao
# daquele instante, e sem estas duas chaves nao havia nada na linha por onde o
# aprender. Mais agudo na radiacao, onde a reanalise (185-350 W/m2, media de
# 24 h) e a estacao (0-872 W/m2, media de 1 h) escrevem a MESMA metrica na
# MESMA unidade com uma ordem de grandeza de diferenca ao meio-dia.
#
# Uma variavel nova que entre em `_VARIAVEIS_AGERA5` e falte aqui rebenta com
# KeyError na primeira linha que produzir -- em voz alta, e nao com uma chave
# em falta no `evidence`. Ha um teste que prende as duas tabelas uma a outra
# antes de se chegar la.
#
# - `2m_temperature`: media de 24 h (`24_hour_mean` no pedido).
# - `precipitation_flux`: mm acumulados no dia -- um TOTAL, nao uma media.
# - `solar_radiation_flux`: J m-2 no dia a dividir por 86400 s, que e a
#   irradiancia MEDIA das 24 horas. E o par directo da media horaria da estacao.
# - `reference_evapotranspiration`: mm no dia, tambem um total.
_AGREGACAO_AGERA5: dict[str, dict] = {
    "2m_temperature": proveniencia_de_agregacao(AggregationOperator.mean, 24),
    "precipitation_flux": proveniencia_de_agregacao(AggregationOperator.total, 24),
    "solar_radiation_flux": proveniencia_de_agregacao(AggregationOperator.mean, 24),
    "reference_evapotranspiration": proveniencia_de_agregacao(AggregationOperator.total, 24),
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
        if not api_url or not api_key:
            # sem isto, um .env sem CDS_API_URL dava AttributeError no rstrip("/"),
            # longe da causa. O .env.example passou a declarar as duas.
            raise ValueError(
                "CDSClient precisa de api_url e api_key. Em desenvolvimento vem do .env "
                "(CDS_API_URL e CDS_API_KEY, ver .env.example); em CI ou producao, exportar "
                "as duas antes de arrancar.")
        self._base = api_url.rstrip("/")
        self._key = api_key
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)
        self._intervalo = intervalo_sondagem_s

    def close(self) -> None:
        """Fecha a ligacao.

        Mesma razao do `IPMAClient.close`, e agora com um consumidor a exigi-la:
        a rota `POST /sites/{code}/weather/sync` constroi um cliente por
        pedido HTTP. Sem fechar, cada sincronizacao deixava um pool de ligacoes
        para tras a espera do colector de lixo.
        """
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self._key, "Content-Type": "application/json"}

    def submit(self, dataset: str, inputs: dict) -> str:
        """Submete um pedido e devolve o jobID."""
        url = f"{self._base}/retrieve/v1/processes/{dataset}/execution"
        r = self._client.post(url, json={"inputs": inputs}, headers=self._headers())
        if r.status_code >= 400:
            raise _erro_resposta(r, f"CDS recusou o pedido a {dataset}")
        job_id = _corpo_json(r).get("jobID")
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

    def agera5_diario(self, area: list[float], lat_sitio: float, lon_sitio: float,
                      date_from: str, date_to: str, variaveis: list[str] | None = None,
                      timeout_s: float = 900.0) -> list[dict]:
        """Serie diaria do AgERA5 no ponto de grelha do sitio, ja normalizada.

        Orquestra submit/wait/download por cada variavel e por cada mes (o
        corpo do CDS leva um ano e um mes de cada vez), converte as unidades
        para o vocabulario de `weather.metrics` e devolve uma linha por dia e
        por metrica.

        O valor de cada linha e o da **celula que contem o sitio**, nao a media
        da caixa transferida. A caixa foi alargada por imposicao da API (uma
        caixa menor do que a celula devolve MultiAdaptorNoDataError), portanto
        e um detalhe de transporte: uma media de 0,4 x 0,4 graus seriam ~2000
        km2, do tamanho de um distrito, e o `cell_size_deg: 0.1` que acompanha
        a linha passaria a descrever uma coisa diferente do valor -- que e
        exactamente a afirmacao local-mas-nao-local que a Task 1 desta fase
        existe para impedir.

        `area_requested` e `area_expanded` continuam na linha: dizem quanto foi
        transferido, mesmo que so se leia uma celula dele.

        Cada linha leva ainda `masked_days_dropped`: quantos dias DESTA
        variavel a celula do sitio nao tinha dado e por isso nao existem na
        serie. Zero e uma afirmacao, nao a ausencia da chave.

        E leva `source_file`: o nome que a ORIGEM deu ao ficheiro de onde
        aquele dia foi lido. Nao e cosmetica de auditoria. Os membros do zip
        do AgERA5 chamam-se, por exemplo,
        `...AgERA5_20260810_final-v2.0.0.area-subset...nc`, e um marcador
        `final-` so significa alguma coisa se existir um nao-final: e a
        reanalise a dizer, no proprio nome, que ha valores que ela ainda pode
        rever. Sem esta chave nenhuma linha da base sabia dizer de que
        ficheiro veio, e portanto ninguem podia perguntar a uma linha se ela
        e preliminar. Nao resolve o que fazer quando a origem revê -- isso
        muda a chave de identidade e e decisao de ambito -- mas e a metade
        que faz a pergunta passar a ser possivel.
        """
        variaveis = list(variaveis) if variaveis else ["2m_temperature"]
        desconhecidas = [v for v in variaveis if v not in _VARIAVEIS_AGERA5]
        if desconhecidas:
            raise ValueError(
                f"variaveis do AgERA5 nao suportadas: {desconhecidas}. "
                f"Suportadas: {sorted(_VARIAVEIS_AGERA5)}")
        caixa, alargada = expandir_area(area)
        # validado contra a AOI ORIGINAL, nao contra a caixa alargada: o
        # alargamento acrescenta ~0,2 graus por lado, e validar contra ele
        # deixava passar um sitio a ~20 km fora da propria AOI.
        _garantir_sitio_dentro([float(x) for x in area], lat_sitio, lon_sitio)
        meses = _meses_do_intervalo(date_from, date_to)

        linhas: list[dict] = []
        for variavel in variaveis:
            statistic, nome_no_ficheiro, metrica, converte = _VARIAVEIS_AGERA5[variavel]
            # a conta e POR VARIAVEL e atravessa os meses: o `masked_days_dropped`
            # que vai na linha e "quantos dias desta serie a celula nao tinha", e
            # uma serie e uma variavel de ponta a ponta. Por isso as linhas desta
            # variavel sao juntas a parte e so carimbadas quando os meses todos
            # ja foram lidos.
            desta_variavel: list[dict] = []
            sem_dado: list[str] = []
            for (ano, mes), dias in meses:
                corpo = inputs_agera5(variavel, statistic, ano, mes, dias, caixa)
                job_id = self.submit(DATASET_AGERA5, corpo)
                self.wait(job_id, timeout_s=timeout_s)
                with tempfile.TemporaryDirectory() as pasta:
                    # a PASTA, e nao um caminho com um nome nosso: o `download`
                    # so fica com o nome que vem no href quando o destino e um
                    # directorio, e ate aqui o ficheiro chamava-se `{job_id}.nc`
                    # -- um nome inventado por nos. Como o nome do ficheiro
                    # passou a ser proveniencia gravada, gravar o nosso era
                    # gravar uma identidade que a origem nunca emitiu.
                    ficheiro = self.download(job_id, Path(pasta))
                    serie, cell_lat, cell_lon, dias_sem_dado = ler_serie_netcdf(
                        ficheiro, lat_sitio, lon_sitio, nome_no_ficheiro)
                sem_dado.extend(dias_sem_dado)
                for dia, valor, ficheiro_de_origem in serie:
                    desta_variavel.append({
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
                        "area_requested": list(caixa),
                        "area_expanded": alargada,
                        # copia por linha, e nao a referencia partilhada da
                        # tabela: duas linhas a apontar para o mesmo dicionario
                        # deixam quem escreva numa a alterar as outras -- a
                        # mesma armadilha que a caixa aqui em cima ja evita.
                        "aggregation": dict(_AGREGACAO_AGERA5[variavel]),
                        # o nome do ficheiro de onde ESTE dia saiu. Ver o
                        # bloco do `source_file` na docstring: e por dia e nao
                        # por pedido, porque um zip mensal pode misturar um
                        # membro `final-v2.0.0` com um preliminar.
                        "source_file": ficheiro_de_origem,
                    })
            for linha in desta_variavel:
                linha["masked_days_dropped"] = len(sem_dado)
            linhas.extend(desta_variavel)
        linhas.sort(key=lambda linha: (linha["date"], linha["metric"]))
        return linhas

    def _estado(self, job_id: str) -> str:
        r = self._client.get(f"{self._base}/retrieve/v1/jobs/{job_id}", headers=self._headers())
        if r.status_code >= 400:
            raise _erro_resposta(r, f"CDS: falhou a consulta ao estado do job {job_id}")
        estado = _corpo_json(r).get("status")
        if not estado:
            # um 200 com HTML de proxy, ou com um corpo que nao e o do CDS,
            # daria estado vazio: sondar isso ate ao tecto seria esperar por
            # uma resposta que nunca vem, com o diagnostico errado no fim.
            raise RuntimeError(
                f"CDS: a resposta ao estado do job {job_id} nao traz `status` "
                f"({r.status_code}): {r.text[:200] or '(corpo vazio)'}")
        return estado

    def _resultados(self, job_id: str) -> httpx.Response:
        return self._client.get(f"{self._base}/retrieve/v1/jobs/{job_id}/results",
                                headers=self._headers())

    def _href_do_resultado(self, job_id: str) -> str:
        r = self._resultados(job_id)
        if r.status_code >= 400:
            raise _erro_resposta(r, f"CDS: o job {job_id} nao tem resultado para descarregar")
        asset = _corpo_json(r).get("asset")
        valor = asset.get("value") if isinstance(asset, dict) else None
        href = valor.get("href") if isinstance(valor, dict) else None
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
        corpo = _corpo_json(r)
        motivo = corpo.get("traceback") or corpo.get("detail") or corpo.get("title")
        if not motivo:
            return r.text[:400] if r.text else "(o CDS nao deu razao nenhuma)"
        motivo = str(motivo).strip()
        return motivo if len(motivo) <= 600 else "..." + motivo[-600:]


def ler_serie_netcdf(
    caminho, lat_sitio: float, lon_sitio: float, nome_variavel: str
) -> tuple[list[tuple[str, float, str]], float, float, list[str]]:
    """Le a variavel `nome_variavel` de um NetCDF do AgERA5 no ponto de grelha do sitio.

    Devolve ([(data, valor, ficheiro)], cell_lat, cell_lon, dias_sem_dado), onde
    cell_lat/cell_lon sao as coordenadas **reais da celula escolhida** -- nao o
    centro da caixa transferida. E o que faz com que o `cell_size_deg: 0.1` da
    linha descreva mesmo o valor que a acompanha, e o que da significado a
    distancia que a `proveniencia_de_celula` da Task 1 calcula entre o sitio e
    a celula.

    **Um dia sem dado na celula nao entra na serie, e e CONTADO.** Ver
    `_e_sem_dado` para o defeito que isto fecha. Duas decisoes, e as duas
    tinham alternativa:

    - **recusa-se a LEITURA, e nao o NO.** Saltar para o no seguinte quando
      este nao tem dado era trocar o valor daquele sitio pelo valor de outro
      sitio -- e, pior, faze-lo dia a dia, porque a mascara e por instante:
      dias diferentes da mesma serie sairiam de celulas diferentes debaixo de
      uma proveniencia unica que so descreve uma delas. E exactamente a
      afirmacao que o bloco do zip aqui ao lado ja recusa quando dois membros
      escolhem celulas diferentes. Um no mascarado costuma se-lo por estar
      fora do dominio (mar), e o vizinho tem outro clima.
    - **o dia simplesmente nao existe**, como qualquer outro dia que a origem
      ainda nao publicou -- e ha um a jusante que ja trata disso: o job passa a
      declarar a janela que cobriu. O que nao pode e desaparecer sem conta,
      por isso a lista de dias saltados sobe ate ao `evidence` de cada linha
      da variavel (`masked_days_dropped`). E a mesma disciplina que o caminho
      do IPMA adoptou a 30/08/2026 para as leituras fora do intervalo fisico:
      descartar e contar, porque zero e uma afirmacao e a ausencia da chave
      nao e nada.

    Escolher a celula que contem o sitio nao e arbitrario: e a unica escolha
    nao-arbitraria possivel. A media da caixa seria uma media de ~2000 km2
    apresentada como um valor de 9 km.

    O CDS entrega uns pedidos como .nc solto e outros dentro de um zip; os
    dois casos sao tratados aqui para que quem chama nao tenha de adivinhar.

    **O zip traz um .nc POR DIA, e sao lidos todos.** Ler so o primeiro membro
    era o defeito que a primeira ingestao real desta camada revelou, a
    29/08/2026: um pedido de 1 de Julho a 29 de Agosto, com tres variaveis,
    gravou 6 linhas -- uma por variavel e por mes, porque de cada zip mensal so
    saia o primeiro dia -- onde havia 159 para trazer, e o job veio `succeeded`
    na mesma. Nao havia nada a distinguir isso de um sucesso: o `rows_written`
    e a unica pista, e um numero baixo nao levanta a mao sozinho. O teste que
    existia embrulhava UM ficheiro num zip e provava que o caminho do zip
    abria -- nao que o zip fosse lido ate ao fim, que e outra afirmacao.

    **O terceiro campo de cada par e o ficheiro de onde AQUELE dia saiu**, e e
    por dia e nao por chamada. Num zip, e o nome do membro tal como esta la
    dentro -- nao o nome com que ele foi extraido para o disco, que leva um
    indice nosso a frente. E o nome do membro e que carrega o token de versao
    da origem (`...20260810_final-v2.0.0...`): um zip mensal pode trazer os
    primeiros dias ja finais e os ultimos ainda preliminares, e uma identidade
    por chamada nao distinguia os dois.

    **`nome_variavel` e obrigatorio de proposito.** Quem le tem de dizer o que
    espera encontrar, e o ficheiro tem de o trazer. Deixa-lo opcional era
    manter aberto o buraco que este parametro fecha: antes, a variavel era a
    primeira tridimensional que aparecesse, portanto ninguem confirmava que o
    que se leu era o que se tinha pedido -- nem quando so havia uma.
    """
    caminho = Path(caminho)
    with caminho.open("rb") as f:
        e_zip = f.read(4) == _MAGIA_ZIP
    if not e_zip:
        serie, cell_lat, cell_lon, sem_dado = _ler_netcdf_solto(
            caminho, lat_sitio, lon_sitio, nome_variavel)
        return ([(dia, valor, caminho.name) for dia, valor in serie],
                cell_lat, cell_lon, sem_dado)
    with zipfile.ZipFile(caminho) as z:
        membros = sorted(n for n in z.namelist() if n.lower().endswith(".nc"))
        if not membros:
            raise RuntimeError(f"o zip {caminho.name} do CDS nao traz nenhum .nc: {z.namelist()}")
        serie: list[tuple[str, float, str]] = []
        sem_dado: list[str] = []
        celula: tuple[float, float] | None = None
        for i, membro in enumerate(membros):
            # o indice no nome do ficheiro extraido, e nao so o basename: dois
            # membros em pastas diferentes podem chamar-se o mesmo, e o segundo
            # sobrescrevia o primeiro em silencio -- a mesma classe de perda
            # que este bloco acabou de deixar de ter.
            destino = caminho.parent / f"{i:04d}-{Path(membro).name}"
            destino.write_bytes(z.read(membro))
            parcial, cell_lat, cell_lon, parcial_sem_dado = _ler_netcdf_solto(
                destino, lat_sitio, lon_sitio, nome_variavel)
            if celula is None:
                celula = (cell_lat, cell_lon)
            elif (cell_lat, cell_lon) != celula:
                # a celula acompanha a serie inteira e e ela que da sentido a
                # distancia gravada em cada linha. Dois membros a apontar para
                # celulas diferentes querem dizer que a grelha mudou dentro do
                # mesmo pedido, e devolver uma das duas era assinar a serie
                # toda com uma proveniencia que so vale para parte dela.
                raise RuntimeError(
                    f"{caminho.name}: o membro {membro} escolheu a celula {cell_lat},{cell_lon} "
                    f"e os anteriores tinham escolhido {celula[0]},{celula[1]}. A serie levaria "
                    "uma proveniencia que nao descreve todas as suas linhas.")
            # o nome do MEMBRO, e nao o `destino.name` que acabou de ser
            # escrito: o destino leva o indice a frente para dois membros
            # homonimos nao se sobreporem, e esse prefixo e nosso. O que tem de
            # ficar na linha e o nome que a origem emitiu.
            serie.extend((dia, valor, membro) for dia, valor in parcial)
            sem_dado.extend(parcial_sem_dado)
    datas = [d for d, _, _ in serie]
    if len(set(datas)) != len(datas):
        # duas leituras para o mesmo dia nao sao um duplicado inofensivo: a
        # desduplicacao a gravar ficava com uma delas sem dizer qual, e o valor
        # da serie passava a depender da ordem dos membros do zip.
        duplicadas = sorted({d for d in datas if datas.count(d) > 1})
        raise RuntimeError(
            f"{caminho.name}: o zip trouxe o mesmo dia em mais do que um membro "
            f"({', '.join(duplicadas)}). O ficheiro nao e a serie diaria que se pediu.")
    serie.sort(key=lambda entrada: entrada[0])
    return serie, celula[0], celula[1], sorted(sem_dado)


def _ler_netcdf_solto(caminho: Path, lat_sitio: float, lon_sitio: float,
                      nome_variavel: str) -> tuple[list[tuple[str, float]], float, float]:
    ds = Dataset(str(caminho))
    try:
        nome_tempo = _primeiro_nome(ds, _NOMES_TEMPO)
        nome_lat = _primeiro_nome(ds, _NOMES_LAT)
        nome_lon = _primeiro_nome(ds, _NOMES_LON)
        coordenadas = {nome_tempo, nome_lat, nome_lon}
        # a variavel e escolhida PELO NOME, e nao pela primeira tridimensional
        # que aparecer. Duas coisas passavam em silencio com a escolha por
        # posicao: um ficheiro com mais do que uma variavel de dados dava uma
        # das duas sem dizer qual, e um ficheiro com uma variavel que nao era a
        # pedida era lido na mesma. Nos dois casos o `variable` do `evidence`
        # vem do PEDIDO, portanto a divergencia nao aparecia em lado nenhum: a
        # base ficava com o valor de uma grandeza sob o nome de outra, ja
        # convertido pela formula errada, com proveniencia completa.
        tridimensionais = sorted(nome for nome, v in ds.variables.items()
                                 if nome not in coordenadas and v.ndim == 3)
        if nome_variavel not in ds.variables:
            raise RuntimeError(
                f"{caminho.name}: pediu-se a variavel {nome_variavel} e o ficheiro nao a traz. "
                f"Variaveis de dados presentes: {tridimensionais or '(nenhuma)'}; "
                f"variaveis todas: {sorted(ds.variables)}")
        var = ds.variables[nome_variavel]
        if var.ndim != 3:
            # sem isto, indexar uma variavel de outra forma com um tuplo de
            # tres daria IndexError longe daqui, ou pior, um valor de um sitio
            # que nao e o que se pediu.
            raise RuntimeError(
                f"{caminho.name}: a variavel {nome_variavel} tem {var.ndim} dimensoes "
                f"{tuple(var.dimensions)} e esperavam-se tres (tempo, lat, lon)")
        lats = [float(x) for x in ds.variables[nome_lat][:]]
        lons = [float(x) for x in ds.variables[nome_lon][:]]
        i_lat = _indice_mais_proximo(lats, lat_sitio, "latitude", caminho.name)
        i_lon = _indice_mais_proximo(lons, lon_sitio, "longitude", caminho.name)
        pos_tempo, pos_lat, pos_lon = _posicoes_das_dimensoes(var, nome_tempo, nome_lat, nome_lon)
        tempo = ds.variables[nome_tempo]
        datas = num2date(tempo[:], tempo.units, getattr(tempo, "calendar", "standard"))
        serie = []
        sem_dado = []
        for i, d in enumerate(datas):
            indice = [0, 0, 0]
            indice[pos_tempo], indice[pos_lat], indice[pos_lon] = i, i_lat, i_lon
            dia = f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
            bruto = var[tuple(indice)]
            if _e_sem_dado(bruto):
                sem_dado.append(dia)
                continue
            serie.append((dia, float(bruto)))
        cell_lat, cell_lon = lats[i_lat], lons[i_lon]
    finally:
        ds.close()
    if sem_dado:
        logger.info("%s: %d dia(s) sem dado na celula %s,%s (%s)",
                    caminho.name, len(sem_dado), cell_lat, cell_lon, ", ".join(sem_dado))
    return serie, cell_lat, cell_lon, sem_dado


def _e_sem_dado(valor) -> bool:
    """O no nao tem dado neste instante: mascarado, ou nao finito.

    A ordem importa e nao e estilistica. `float()` sobre um elemento MASCARADO
    de um `MaskedArray` do numpy nao levanta nada: emite um UserWarning
    ("converting a masked element to nan") e devolve `nan`. Perguntar pela
    mascara TEM de vir antes da conversao, senao a conversao ja aconteceu e o
    que se tem em maos e um nan indistinguivel de um nan que estivesse mesmo
    escrito no ficheiro.

    O segundo teste nao e redundante: um produtor pode escrever `nan` ou
    `inf` em bruto, sem `_FillValue` nenhum declarado, e nesse caso nao ha
    mascara nenhuma para apanhar.

    Isto era, a 30/08/2026, o pior defeito silencioso desta camada. Um dia
    mascarado entrava na base como `value_numeric = NaN`, `value_qualifier =
    exact`, `quality_flag = valid`, com proveniencia completa e contado no
    `rows_written` de um job `succeeded`. A base tambem nao o impedia --
    `NaN IS NOT NULL` e verdadeiro e `double precision` aceita NaN -- e no
    PostgreSQL o NaN propaga-se pelos agregados: UM dia mascarado punha
    `avg()`, `max()` e `sum()` a devolver NaN para aquela metrica daquele
    sitio, para sempre.
    """
    if numpy.ma.is_masked(valor):
        return True
    return not math.isfinite(float(valor))


def _indice_mais_proximo(valores: list[float], alvo: float, rotulo: str, ficheiro: str) -> int:
    """Indice do no de grelha mais proximo do alvo, de forma deterministica.

    O desempate e pelo indice mais baixo (a chave de ordenacao leva o proprio
    indice a seguir a distancia): um sitio exactamente a meio de duas celulas
    tem de escolher sempre a mesma, senao a mesma parcela mudava de celula
    entre execucoes e a proveniencia deixava de ser reproduzivel.
    """
    if not valores:
        raise RuntimeError(f"{ficheiro}: o eixo de {rotulo} esta vazio")
    # o `min` do Python ja devolve o PRIMEIRO minimo, portanto o `i` na chave e
    # redundante hoje. Fica escrito de proposito: o desempate por indice mais
    # baixo e a garantia de reprodutibilidade, e deixa-lo implicito convidava a
    # "simplificar" para um max() ou um sorted(reverse=True) que o inverteria
    # sem que nenhum teste tivesse de mudar de nome.
    melhor = min(range(len(valores)), key=lambda i: (abs(valores[i] - alvo), i))
    meio_passo = _passo_da_grelha(valores) / 2
    if abs(valores[melhor] - alvo) > meio_passo + _TOLERANCIA_GRAUS:
        raise RuntimeError(
            f"{ficheiro}: o no de {rotulo} mais proximo ({valores[melhor]}) esta a "
            f"{abs(valores[melhor] - alvo):.3f} graus do sitio ({alvo}), mais do que meio passo "
            f"de grelha ({meio_passo:.3f}). O criterio e meio passo, nao um passo: meio passo e "
            "a distancia maxima possivel quando o no existe mesmo; com um passo inteiro um "
            "sitio a 11 km de distancia recebia a celula da borda, que e um valor de outro "
            "sitio com ar de local.")
    return melhor


def _passo_da_grelha(valores: list[float]) -> float:
    if len(valores) < 2:
        return RESOLUCAO_AGERA5_GRAUS
    return min(abs(b - a) for a, b in zip(valores, valores[1:], strict=False))


def _posicoes_das_dimensoes(var, nome_tempo: str, nome_lat: str, nome_lon: str) -> tuple[int, int, int]:
    """Onde estao tempo/lat/lon nas dimensoes da variavel.

    O AgERA5 vem em (time, lat, lon), mas indexar por posicao fixa era assumir
    que nunca muda; se os nomes das dimensoes estiverem la, usa-se a ordem
    real do ficheiro.
    """
    dims = list(var.dimensions)
    if all(nome in dims for nome in (nome_tempo, nome_lat, nome_lon)):
        return dims.index(nome_tempo), dims.index(nome_lat), dims.index(nome_lon)
    return 0, 1, 2


def _garantir_sitio_dentro(caixa: list[float], lat_sitio: float, lon_sitio: float) -> None:
    """O sitio tem de cair dentro da AOI, senao a celula lida seria a da borda."""
    norte, oeste, sul, este = caixa
    if not (sul <= lat_sitio <= norte and oeste <= lon_sitio <= este):
        raise ValueError(
            f"o sitio ({lat_sitio}, {lon_sitio}) esta fora da AOI {caixa}; "
            "a celula lida seria a da borda, um valor de outro sitio")


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


def _corpo_json(r: httpx.Response) -> dict:
    """Corpo da resposta como dict, ou {} quando nao ha dict nenhum.

    Quatro formas reais, todas reproduzidas, em que o `.get()` directo rebentava
    a tratar o erro -- o mesmo defeito que ja tinha aparecido no cliente do
    Sentinel Hub:

      500 com `null`                -> AttributeError: 'NoneType' has no attribute 'get'
      500 com [{"detail": "x"}]     -> AttributeError: 'list' has no attribute 'get'
      201 com HTML (proxy ou WAF)   -> json.decoder.JSONDecodeError
      200 com HTML no estado do job -> json.decoder.JSONDecodeError

    O `(r.json() or {})` cobria so o primeiro, e so onde estava escrito. O pior
    dos quatro era o `_motivo_de_falha`: um job FALHADO cujo /results voltasse
    com `null` rebentava com AttributeError em vez de levantar o RuntimeError
    com o traceback -- perdia-se exactamente a informacao que a funcao existe
    para dar, no momento em que mais faz falta.
    """
    if not r.text:
        return {}
    try:
        corpo = r.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _erro_resposta(r: httpx.Response, prefixo: str) -> RuntimeError:
    """Formata um erro do CDS com o corpo, nao so o codigo HTTP.

    Mesmo papel do helper homonimo em resoiltwin.eo.cdse: o CDS responde no
    formato de problema HTTP (type/title/detail) e e ai que esta a razao. Um
    raise_for_status() seco deitava-a fora. Se o corpo nao for JSON (proxy,
    WAF, pagina de erro), degrada para o texto truncado.
    """
    corpo = _corpo_json(r)
    codigo = corpo.get("type") or corpo.get("title") or r.status_code
    descricao = corpo.get("detail") or corpo.get("traceback")
    if descricao is None:
        descricao = r.text[:200] if r.text else "(corpo vazio)"
    return RuntimeError(f"{prefixo}: {r.status_code} {codigo} - {descricao}")
