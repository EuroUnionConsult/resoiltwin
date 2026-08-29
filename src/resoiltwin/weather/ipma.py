"""Cliente das observacoes de estacao do IPMA (api.ipma.pt/open-data).

E a outra fonte da camada meteorologica, e a unica das duas que e mesmo uma
medicao: por tras de cada valor esta um instrumento numa estacao real, nao a
saida de um modelo. Em troca, tem duas propriedades que decidem tudo o que
esta escrito neste modulo:

1. **So existem as ultimas 24 horas.** Nao ha arquivo, nao ha parametro de
   data, nao ha paginacao para tras -- o observations.json e uma janela
   deslizante de 24 instantes horarios. Isto nao e uma limitacao a contornar:
   e o que a fonte e. O historico constroi-se a partir do dia em que a
   sincronizacao comecar a correr, e e a desduplicacao que permite corre-la de
   hora a hora sem duplicar as 23 horas que se repetem de cada vez.

2. **O valor em falta e -99, nao `null`.** Uma temperatura de -99 graus passa
   em qualquer validacao de tipo, uma humidade de -99 por cento tambem, e uma
   precipitacao de -99 mm entra num total acumulado como chuva negativa. A
   leitura de 29/08/2026 tinha 5985 celulas a -99 em sete campos diferentes
   (e 675 registos inteiros a `null`), portanto o filtro nao e sobre a
   temperatura: e sobre todos os campos.

Tudo o que esta aqui codificado sobre o formato foi medido contra o feed real
a 29/08/2026, nao lido da documentacao:

- os dois ficheiros respondem 200 sem credencial nenhuma;
- stations.json e uma lista de features GeoJSON, com `geometry.coordinates`
  em [lon, lat] e `idEstacao` como INTEIRO;
- observations.json e {instante: {id_estacao_em_TEXTO: registo | null}}, com
  24 instantes e 222 estacoes;
- os carimbos vem sem fuso e sao UTC (ver `_instante_utc`);
- `radiacao` vem em kJ/m2 acumulados na hora, nao em W/m2.
"""

import logging
from datetime import datetime, timezone

import httpx

from resoiltwin.weather.metrics import UNIDADE_POR_METRICA, WeatherMetric, proveniencia_de_estacao

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ipma.pt/open-data/observation/meteorology/stations"
URL_ESTACOES = f"{BASE_URL}/stations.json"
URL_OBSERVACOES = f"{BASE_URL}/observations.json"

COLECCAO_IPMA = "ipma-stations-observations"

# Versao do NOSSO processamento, nao do feed: o IPMA nao versiona nada. E o
# que distingue estas linhas de um reprocessamento futuro com outro mapa de
# campos ou outra conversao de unidades -- muda-la reescreve a serie ao lado
# da antiga em vez de colidir com ela, porque entra na chave de identidade.
VERSAO_IPMA = "1"

# O sentinela de "em falta". Numero, nao `null`: e todo o problema.
VALOR_EM_FALTA = -99.0

# tolerancia da comparacao com o sentinela. O JSON traz -99.0 exacto, mas
# comparar floats por igualdade e uma armadilha que so custa a descobrir no
# dia em que a origem passar a mandar -98.99999.
_TOLERANCIA_EM_FALTA = 1e-6

# Tecto de proximidade. Nao e uma lei da fisica, e uma politica: a rede do
# IPMA no continente tem ~120 estacoes e a mais proxima de Turcifal fica a
# 5,3 km. Uma estacao a 250 km nao e a meteorologia daquele campo, e atribuir
# essa serie ao sitio -- com proveniencia impecavel, distancia gravada e tudo
# -- era dar ar de dado local a uma coisa que nao o e. Quem tiver um caso
# legitimo passa o raio por argumento e fica escrito na chamada.
RAIO_MAXIMO_KM = 50.0

_TIMEOUT_S = 30.0


def _sem_conversao(valor: float) -> float:
    return valor


def _kilojoule_por_hora_para_watt(valor: float) -> float:
    """kJ/m2 acumulados numa hora para W/m2: 3600 kJ/m2 numa hora sao 1000 W/m2.

    Confirmado contra o feed real: o percentil 90 das estacoes ao meio-dia
    solar de 29/08/2026 dava 3373 kJ/m2/h, ou seja 937 W/m2 -- o valor certo
    para um dia limpo de agosto em Portugal continental. Lido como se ja
    fosse W/m2, o mesmo numero seria tres vezes a constante solar.
    """
    return valor / 3.6


# campo do feed -> (metrica do vocabulario, conversao para a unidade canonica).
#
# `pressao` e `idDireccVento` ficam de fora: nao ha metrica para nenhuma das
# duas em weather.metrics, e acrescentar `air_pressure` aqui era alargar o
# vocabulario pela porta das traseiras, numa tarefa que nao e a dele.
#
# `intensidadeVentoKM` tambem fica de fora, mas por outra razao: e a MESMA
# grandeza que `intensidadeVento`, em km/h. Gravar as duas dava duas linhas
# de wind_speed para o mesmo instante, e a chave de identidade so admite uma.
_CAMPOS: dict[str, tuple[WeatherMetric, object]] = {
    "temperatura": (WeatherMetric.air_temperature, _sem_conversao),
    "humidade": (WeatherMetric.relative_humidity, _sem_conversao),
    "precAcumulada": (WeatherMetric.precipitation, _sem_conversao),
    "intensidadeVento": (WeatherMetric.wind_speed, _sem_conversao),
    "radiacao": (WeatherMetric.solar_radiation, _kilojoule_por_hora_para_watt),
}

# Intervalo fisicamente possivel de cada metrica, ja na unidade canonica.
#
# Nao e controlo de qualidade -- e a rede de seguranca para o sentinela que
# ainda nao vimos. O -99 esta filtrado pelo nome; se o IPMA passar a usar
# outro codigo (-990, -9999), sem esta guarda ele entrava na serie como um
# valor, com proveniencia de estacao real e tudo. Os limites sao largos de
# proposito: nenhuma leitura plausivel do continente lhes toca, portanto o
# que os viola nao e uma leitura -- e outra coisa disfarcada de leitura.
_LIMITES_FISICOS: dict[WeatherMetric, tuple[float, float]] = {
    WeatherMetric.air_temperature: (-30.0, 55.0),
    WeatherMetric.relative_humidity: (0.0, 100.0),
    WeatherMetric.precipitation: (0.0, 250.0),
    WeatherMetric.wind_speed: (0.0, 75.0),
    WeatherMetric.solar_radiation: (0.0, 1500.0),
}


class IPMAClient:
    """Fala HTTP com o open-data do IPMA. Nao sabe nada da base de dados.

    Sem credencial nenhuma, ao contrario do CDS e do CDSE: os dois ficheiros
    sao publicos e respondem 200 a um GET simples. Nao ha token para guardar
    nem para renovar, e por isso nao ha nada aqui que se pareca com o
    `token()` dos outros dois clientes.
    """

    def __init__(self, transport=None, timeout: float = _TIMEOUT_S, base_url: str = BASE_URL):
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)

    def stations(self) -> list[dict]:
        """A rede de estacoes, ja com as coordenadas na ordem certa.

        Devolve dicionarios normalizados (station_id, station_name, lat, lon)
        e nao as features cruas de proposito: a traducao de [lon, lat] para
        (lat, lon) e a conversao do idEstacao para texto acontecem UMA vez,
        aqui, e nao em cada sitio que consome estacoes. Cada copia dessa
        traducao era mais um sitio onde a ordem se podia trocar.
        """
        dados = self._json(URL_ESTACOES)
        if not isinstance(dados, list):
            raise RuntimeError(
                f"IPMA: {URL_ESTACOES} devolveu {type(dados).__name__} e nao a lista de "
                "features esperada. Um 200 com HTML de proxy nao e uma rede sem estacoes.")
        estacoes = []
        for feature in dados:
            estacao = _estacao_da_feature(feature)
            if estacao is None:
                # uma feature partida nao pode derrubar a rede toda: sao 222 e
                # a que interessa e a mais proxima do sitio
                logger.warning("IPMA: feature de estacao ignorada por estar incompleta: %r", feature)
                continue
            estacoes.append(estacao)
        if not estacoes:
            raise RuntimeError(
                f"IPMA: {URL_ESTACOES} nao trouxe nenhuma estacao utilizavel "
                f"({len(dados)} features lidas).")
        return estacoes

    def nearest_station(self, lat: float, lon: float,
                        raio_maximo_km: float = RAIO_MAXIMO_KM) -> dict:
        """A estacao mais proxima de um ponto, com a distancia ja calculada.

        A distancia sai da `proveniencia_de_estacao` da Task 1 -- a mesma
        funcao que depois grava a distancia em cada linha. Uma segunda formula
        aqui, so para ordenar, podia divergir da que fica gravada: a estacao
        escolhida por um criterio e a distancia declarada por outro.

        O desempate e pelo id, para que duas estacoes a igual distancia nao
        troquem de lugar entre execucoes e a serie do sitio nao mude de
        instrumento sem nada a assinalar.
        """
        candidatas = sorted(
            (dict(estacao, **{"distance_km": _distancia_km(estacao, lat, lon)})
             for estacao in self.stations()),
            key=lambda estacao: (estacao["distance_km"], estacao["station_id"]),
        )
        proxima = candidatas[0]
        if proxima["distance_km"] > raio_maximo_km:
            raise ValueError(
                f"a estacao do IPMA mais proxima de ({lat}, {lon}) e '{proxima['station_name']}' "
                f"a {proxima['distance_km']:.1f} km, acima do tecto de {raio_maximo_km:.0f} km. "
                "Uma serie dessa distancia nao e a meteorologia deste sitio; se for mesmo para "
                "usar, o raio passa-se por argumento e fica escrito na chamada.")
        return proxima

    def observations(self) -> dict:
        """As ultimas 24 horas de todas as estacoes, tal como vem.

        Devolvido cru (instante -> id -> registo) e nao normalizado porque a
        normalizacao depende da estacao escolhida, que este metodo nao sabe
        qual e; quem a faz e `linhas_da_estacao`.
        """
        dados = self._json(URL_OBSERVACOES)
        if not isinstance(dados, dict):
            raise RuntimeError(
                f"IPMA: {URL_OBSERVACOES} devolveu {type(dados).__name__} e nao o mapa de "
                "instantes esperado.")
        return dados

    def _json(self, url: str):
        try:
            r = self._client.get(url)
        except httpx.HTTPError as erro:
            raise RuntimeError(f"IPMA: falhou o pedido a {url}: {erro}") from erro
        if r.status_code >= 400:
            raise RuntimeError(
                f"IPMA: {url} respondeu {r.status_code} - {r.text[:200] or '(corpo vazio)'}")
        try:
            return r.json()
        except ValueError as erro:
            # um 200 com HTML (portal, proxy, pagina de manutencao) e o caso
            # real: sem isto vinha um JSONDecodeError sem dizer de que URL
            raise RuntimeError(
                f"IPMA: {url} respondeu {r.status_code} com um corpo que nao e JSON: "
                f"{r.text[:200] or '(corpo vazio)'}") from erro


def linhas_da_estacao(observacoes: dict, station_id: str) -> list[dict]:
    """Serie normalizada de UMA estacao, a partir do feed cru das 24 horas.

    Uma linha por instante e por metrica, com o valor ja na unidade do
    vocabulario. O que nao produz linha nenhuma: os campos a -99, os registos
    a `null` e os campos sem metrica (pressao, direccao do vento, vento em
    km/h).

    A estacao ausente do feed nao da uma serie vazia -- da erro. Zero linhas e
    indistinguivel de "a estacao existe e nao mediu nada", e um job succeeded
    com zero linhas por causa de um id que nunca bateu certo e exactamente o
    tipo de sucesso vazio que nao se descobre a olhar para o estado.
    """
    identificador = str(station_id)
    linhas: list[dict] = []
    aparece = False
    for instante in sorted(observacoes):
        registos = observacoes[instante] or {}
        if identificador not in registos:
            continue
        aparece = True
        registo = registos[identificador]
        if registo is None:
            # hora sem leitura nenhuma: acontece no feed real (675 casos em
            # 5328 a 29/08/2026) e nao e erro, e ausencia
            continue
        quando = _instante_utc(instante)
        for campo, (metrica, converte) in _CAMPOS.items():
            bruto = registo.get(campo)
            if bruto is None:
                continue
            bruto = float(bruto)
            if _em_falta(bruto):
                continue
            valor = converte(bruto)
            _garantir_plausivel(metrica, valor, campo, bruto, identificador, instante)
            linhas.append({
                "date": quando,
                "metric": metrica,
                "value": valor,
                "unit": UNIDADE_POR_METRICA[metrica],
                "field": campo,
                "dataset": COLECCAO_IPMA,
            })
    if not aparece:
        raise ValueError(
            f"a estacao '{identificador}' nao aparece em nenhum dos {len(observacoes)} instantes "
            "do feed do IPMA. Isto nao e uma estacao sem leituras: e um id que nunca bateu certo "
            "-- provavelmente por o stations.json o dar como inteiro e o observations.json o usar "
            "como chave de texto.")
    linhas.sort(key=lambda linha: (linha["date"], linha["metric"]))
    return linhas


def _em_falta(valor: float) -> bool:
    """-99 e o "em falta" do IPMA, em qualquer campo."""
    return abs(valor - VALOR_EM_FALTA) <= _TOLERANCIA_EM_FALTA


def _garantir_plausivel(metrica: WeatherMetric, valor: float, campo: str, bruto: float,
                        station_id: str, instante: str) -> None:
    minimo, maximo = _LIMITES_FISICOS[metrica]
    if minimo <= valor <= maximo:
        return
    raise ValueError(
        f"a estacao '{station_id}' deu {campo}={bruto} em {instante}, que da "
        f"{valor:.3f} {UNIDADE_POR_METRICA[metrica]} -- fora do intervalo fisicamente possivel "
        f"[{minimo}, {maximo}]. O sentinela conhecido do IPMA e {VALOR_EM_FALTA}; um valor "
        "absurdo diferente desse quer dizer que a origem mudou de convencao, e grava-lo era "
        "por na serie um numero que ninguem mediu.")


def _instante_utc(texto: str) -> datetime:
    """O carimbo do IPMA para um instante consciente do fuso.

    O feed escreve "2026-08-29T14:00", sem fuso, e e UTC. Medido, nao
    assumido: a 29/08/2026, com o ficheiro lido as 15:21 UTC, o instante mais
    recente era o das 14:00 (uma hora de atraso de publicacao, nao duas e
    meia), e o percentil 90 da radiacao das 125 estacoes caia no bloco das
    13:00, que e o meio-dia solar em Portugal continental. Lido como hora
    local de Lisboa (UTC+1 em agosto), o pico de radiacao ficava uma hora
    antes do meio-dia solar.

    Gravar isto como naive era pior do que errar o fuso: a coluna e
    timestamptz e o Postgres aplicaria o fuso da sessao, portanto o mesmo
    ficheiro dava instantes diferentes conforme a maquina que o ingerisse.
    """
    quando = datetime.fromisoformat(str(texto))
    if quando.tzinfo is not None:
        return quando.astimezone(timezone.utc)
    return quando.replace(tzinfo=timezone.utc)


def _estacao_da_feature(feature) -> dict | None:
    """Uma feature do stations.json normalizada, ou None se estiver incompleta."""
    if not isinstance(feature, dict):
        return None
    propriedades = feature.get("properties") or {}
    coordenadas = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coordenadas) < 2 or propriedades.get("idEstacao") is None:
        return None
    # GeoJSON e [lon, lat] -- longitude PRIMEIRO. Trocar os dois nao rebenta
    # (-9,179 e uma latitude valida e 39,04 uma longitude valida): poe Dois
    # Portos na Tanzania e devolve uma distancia com ar plausivel para o sitio
    # errado. E a mesma familia de defeito da distancia 28% acima do real que
    # este projecto ja publicou uma vez.
    lon, lat = float(coordenadas[0]), float(coordenadas[1])
    return {
        # inteiro no stations.json, chave de TEXTO no observations.json: sem
        # esta conversao a procura da serie nao encontra nada, e nao encontrar
        # nada e silencioso
        "station_id": str(propriedades["idEstacao"]),
        "station_name": str(propriedades.get("localEstacao") or ""),
        "lat": lat,
        "lon": lon,
    }


def _distancia_km(estacao: dict, lat: float, lon: float) -> float:
    return proveniencia_de_estacao(
        estacao["station_id"], estacao["station_name"], estacao["lat"], estacao["lon"], lat, lon,
    )["distance_km"]
