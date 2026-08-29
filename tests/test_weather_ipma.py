"""Ingestao das estacoes do IPMA: o que se grava, o que se recusa a gravar.

Nenhum teste toca a rede. O cliente e o IPMAClient REAL, ligado a um
httpx.MockTransport que devolve o formato exacto dos dois ficheiros do feed
aberto -- lidos a 29/08/2026 -- em vez de um duplo que devolve linhas ja
normalizadas. E de proposito: a ordem [lon, lat] do GeoJSON e o -99 do IPMA
so existem no formato de origem, e um duplo que devolvesse dicionarios ja
limpos nunca chegaria a exercer nenhuma das duas.
"""

from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, JobStatus, QualityFlag, SourceType, ValueQualifier,
)
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.models import Aoi, IngestionJob, Observation, Site
from resoiltwin.weather.ingest import PROCESSING_VERSION_IPMA, sync_ipma
from resoiltwin.weather.ipma import (
    ALTURA_SOLAR_DE_NOITE_GRAUS,
    ATRASO_MINIMO_DA_PUBLICACAO,
    COLECCAO_IPMA,
    RAIO_MAXIMO_KM,
    URL_ESTACOES,
    URL_OBSERVACOES,
    VALOR_EM_FALTA,
    IPMAClient,
    altura_solar_graus,
    linhas_da_estacao,
)
from resoiltwin.weather.metrics import WeatherMetric

# o ponto canonico do sitio de Turcifal, o mesmo de tests/test_geo.py e de
# tests/test_weather_ingest.py
TURCIFAL_LON, TURCIFAL_LAT = -9.240247, 39.037317
PORTO_LON, PORTO_LAT = -8.641731, 41.177928

# Quatro estacoes REAIS do stations.json de 29/08/2026, com as coordenadas
# tal como vem do feed: [lon, lat]. Dois Portos e a mais proxima de Turcifal
# (5,34 km) e S. Gens a mais proxima do Porto (0,76 km).
DOIS_PORTOS = (1210739, "Torres Vedras, Dois Portos", -9.179, 39.04389444)
SANTA_CRUZ = (1210746, "Santa Cruz (Aerodromo)", -9.3790388, 39.12594166)
S_GENS = (1210649, "S. Gens", -8.64445, 41.18445)
OLHAO = (1210881, "Olhao, EPPO", -7.821, 37.033)

ID_DOIS_PORTOS = "1210739"
ID_S_GENS = "1210649"
DISTANCIA_DOIS_PORTOS_KM = 5.3399

# Duas horas seguidas. A data e deliberadamente ANTIGA em relacao ao dia em
# que a suite corre: a janela nominal do job (as ultimas 24 horas) nunca
# coincide com ela, portanto qualquer teste sobre o intervalo do job so passa
# se o job passar a declarar o que foi mesmo gravado.
INSTANTES = ("2026-08-20T13:00", "2026-08-20T14:00")
DIA_DOS_INSTANTES = date(2026, 8, 20)
NOITE = "2026-08-20T02:00"          # sol a -35 graus em Dois Portos
# o por do sol em Dois Portos a 20/08/2026 e as 19:20 UTC: as 20:00 o sol ja
# esta a -7,2 graus, mas as 19:00 estava a +3,9 -- a hora acumulada teve sol
CREPUSCULO = "2026-08-20T20:00"

# relogio fixo para os testes que dependem do "agora": bem depois do feed, para
# a guarda de atraso de publicacao passar sem depender do dia em que a suite
# corre
AGORA = datetime(2026, 8, 20, 14, 50, tzinfo=timezone.utc)
# o instante mais recente do feed dos testes, e as duas fronteiras do atraso
# minimo derivadas da constante de producao em vez de escritas a mao: com o
# numero repetido aqui, mudar a politica deixava os testes a afirmar a antiga.
# Quem fixa a POLITICA com numeros a mao sao os dois testes mais abaixo.
MAIS_RECENTE = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)
NO_LIMITE = MAIS_RECENTE + ATRASO_MINIMO_DA_PUBLICACAO
RECENTE_DE_MAIS = NO_LIMITE - timedelta(minutes=1)

# atraso de publicacao REAL da origem, medido duas vezes contra a rede a
# 29/08/2026: Last-Modified 17:35:03 para um ficheiro cujo instante mais
# recente e 17:00. E o que o duplo imita por omissao.
ATRASO_DE_PUBLICACAO_REAL = timedelta(minutes=35)

# a mesma publicacao real, escrita na forma `-0000` -- sintaxe legal de RFC
# 5322 que quer dizer "sem fuso conhecido" e que o parser devolve como naive
SEM_FUSO = "Thu, 20 Aug 2026 14:35:00 -0000"

# Instantes escolhidos pela altura solar nas DUAS pontas da hora acumulada,
# calculada uma vez e escrita aqui a mao. Sao eles que fixam a politica da
# guarda solar -- limiar, tecto e largura da janela -- sem derivar nada das
# constantes de producao.
#
#   instante              ponta de tras   ponta da frente   o que fixa
#   2026-01-15T19:00        -4,63            -27,07         limiar nao e 0
#   2026-08-20T21:00        -7,24            -26,64         limiar nao e -18; janela nao e 3h
#   2026-08-20T05:00       -20,62             +0,19         a ponta da FRENTE conta
#   2026-08-20T02:00       -38,26            -29,05         noite fechada
CREPUSCULO_DE_JANEIRO = "2026-01-15T19:00"
DEPOIS_DO_CREPUSCULO = "2026-08-20T21:00"
MADRUGADA = "2026-08-20T05:00"

# temperatura, humidade, precAcumulada, intensidadeVento e radiacao: cinco
# campos do feed com metrica no vocabulario. pressao e idDireccVento nao tem.
METRICAS_POR_REGISTO = 5


def _feature(id_estacao: int, nome: str, lon: float, lat: float) -> dict:
    """Uma feature do stations.json, com as coordenadas na ordem do GeoJSON."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"idEstacao": id_estacao, "localEstacao": nome},
    }


ESTACOES = [_feature(*OLHAO), _feature(*SANTA_CRUZ), _feature(*DOIS_PORTOS), _feature(*S_GENS)]


def _registo(**trocas) -> dict:
    """Um registo horario do observations.json, com os oito campos do feed."""
    campos = {
        "temperatura": 24.6,
        "humidade": 77.0,
        "precAcumulada": 0.2,
        "intensidadeVento": 2.6,
        "intensidadeVentoKM": 9.4,
        "radiacao": 3600.0,
        # pressao e direccao do vento com valores REAIS, e nao com o -99 que o
        # filtro descarta a jusante: com o sentinela aqui, os testes que dizem
        # "a pressao nao e ingerida" passavam na mesma se a pressao passasse a
        # ser ingerida, porque o valor nunca sobreviveria ao filtro. Um teste
        # que nao pode falhar nao e um teste.
        "pressao": 1013.2,
        "idDireccVento": 8,
    }
    campos.update(trocas)
    return campos


def _observacoes_do_feed(**trocas) -> dict:
    """{instante: {id_estacao: registo}}, a forma exacta do observations.json."""
    feed = {
        instante: {
            ID_DOIS_PORTOS: _registo(),
            ID_S_GENS: _registo(temperatura=19.0, humidade=88.0),
        }
        for instante in INSTANTES
    }
    feed.update(trocas)
    return feed


def _transport(estacoes=None, observacoes=None, urls=None, publicado="auto"):
    """Duplo dos dois ficheiros do feed.

    `publicado` e o `Last-Modified` do observations.json, que e contra o que a
    guarda de fuso mede. Por omissao imita a origem: 35 minutos depois do
    instante mais recente, o atraso de publicacao medido a 29/08/2026. `None`
    serve as respostas sem cabecalho nenhum, que e o caminho de recurso.
    """
    def handler(request):
        if urls is not None:
            urls.append(str(request.url))
        caminho = request.url.path
        if caminho.endswith("stations.json"):
            return httpx.Response(200, json=ESTACOES if estacoes is None else estacoes)
        if caminho.endswith("observations.json"):
            feed = _observacoes_do_feed() if observacoes is None else observacoes
            if isinstance(publicado, datetime):
                cabecalhos = {"Last-Modified": format_datetime(publicado, usegmt=True)}
            elif isinstance(publicado, str):
                # cabecalho cru, para os casos que o duplo nao pode construir:
                # texto ilegivel e a forma `-0000`, que e naive
                cabecalhos = {"Last-Modified": publicado}
            else:
                cabecalhos = {}
            return httpx.Response(200, json=feed, headers=cabecalhos)
        return httpx.Response(404, text=f"caminho nao servido pelo duplo: {caminho}")

    return httpx.MockTransport(handler)


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto).replace(tzinfo=timezone.utc)


# quanto tempo depois da publicacao e que o duplo finge que o job correu. O
# cliente confronta o Last-Modified com o relogio antes de o aceitar, portanto
# um duplo com o relogio parado a horas de distancia do cabecalho ja nao
# descreve nada de real -- e a sanidade recusava o cabecalho por antiguidade.
DEPOIS_DE_PUBLICAR = timedelta(minutes=15)


def _cliente(estacoes=None, observacoes=None, relogio=None, urls=None,
             publicado="auto") -> IPMAClient:
    """Cliente real ligado ao duplo, com o tempo coerente com o feed.

    Por omissao a publicacao e o relogio saem do PROPRIO feed -- 35 minutos
    depois do instante mais recente, lido 15 minutos depois disso -- e nao de
    uma constante. Com uma constante, qualquer teste que use um feed noutra
    hora do dia ficava com o cabecalho no futuro do relogio, a sanidade
    recusava-o, e o teste falhava por uma razao que nao e a dele.
    """
    feed = _observacoes_do_feed() if observacoes is None else observacoes
    if publicado == "auto":
        publicado = _instante(max(feed)) + ATRASO_DE_PUBLICACAO_REAL if feed else None
    if relogio is None and isinstance(publicado, datetime):
        publicado_em = publicado
        relogio = lambda: publicado_em + DEPOIS_DE_PUBLICAR         # noqa: E731
    return IPMAClient(transport=_transport(estacoes, feed, urls, publicado),
                      relogio=relogio or (lambda: AGORA))


def _feed_de_um_instante(instante: str, **campos) -> dict:
    """Feed com uma so hora, para os testes que fixam a politica solar."""
    return {instante: {ID_DOIS_PORTOS: _registo(**campos)}}


# --- o cliente: ler o feed sem trocar a ordem das coordenadas ---------------

def test_the_geojson_coordinates_are_read_as_lon_lat():
    """[lon, lat], nao [lat, lon].

    Trocar os dois nao rebenta -- -9,179 e uma latitude valida e 39,04 uma
    longitude valida -- e a distancia que sai continua a ter ar plausivel. E
    por isso que a asercao e sobre os numeros e sobre o pais: com a ordem
    trocada, Dois Portos deixava de estar em Portugal continental.
    """
    estacoes = {e["station_id"]: e for e in _cliente().stations()}
    dois_portos = estacoes[ID_DOIS_PORTOS]

    assert dois_portos["lat"] == pytest.approx(39.04389444)
    assert dois_portos["lon"] == pytest.approx(-9.179)
    # Portugal continental: latitude entre 36 e 42,2, longitude entre -9,6 e -6,1.
    # com a ordem trocada, esta estacao caia na Tanzania.
    assert 36.0 < dois_portos["lat"] < 42.2
    assert -9.6 < dois_portos["lon"] < -6.1


def test_station_ids_are_text_because_the_observations_are_keyed_by_text():
    """O stations.json traz idEstacao como INTEIRO e o observations.json usa o
    mesmo id como CHAVE DE TEXTO. Sem normalizar, a procura da serie da
    estacao nao encontrava nada -- e nao encontrar nada nao rebenta, escreve
    zero linhas com o job a dizer succeeded."""
    ids = [e["station_id"] for e in _cliente().stations()]

    assert all(isinstance(i, str) for i in ids)
    assert ID_DOIS_PORTOS in ids


def test_the_nearest_station_to_turcifal_is_dois_portos():
    proxima = _cliente().nearest_station(TURCIFAL_LAT, TURCIFAL_LON)

    assert proxima["station_id"] == ID_DOIS_PORTOS
    assert proxima["station_name"] == "Torres Vedras, Dois Portos"
    assert proxima["distance_km"] == pytest.approx(DISTANCIA_DOIS_PORTOS_KM, abs=0.001)


def test_the_nearest_station_to_porto_is_a_different_one():
    """A escolha e mesmo por proximidade, e nao a primeira da lista."""
    proxima = _cliente().nearest_station(PORTO_LAT, PORTO_LON)

    assert proxima["station_id"] == ID_S_GENS
    assert proxima["distance_km"] == pytest.approx(0.76, abs=0.01)


def test_a_station_beyond_the_ceiling_is_refused_instead_of_used():
    """So ha estacoes no Algarve e o sitio e em Turcifal: 250 km nao e a
    meteorologia daquele campo, por muito que seja a estacao mais proxima."""
    cliente = _cliente(estacoes=[_feature(*OLHAO)])

    with pytest.raises(ValueError, match="km"):
        cliente.nearest_station(TURCIFAL_LAT, TURCIFAL_LON)


def test_the_ceiling_is_a_policy_and_can_be_widened_on_purpose():
    proxima = _cliente(estacoes=[_feature(*OLHAO)]).nearest_station(
        TURCIFAL_LAT, TURCIFAL_LON, raio_maximo_km=400.0)

    assert proxima["station_id"] == "1210881"
    assert proxima["distance_km"] > RAIO_MAXIMO_KM


def test_a_feature_without_coordinates_is_skipped_not_fatal():
    sem_geometria = {"type": "Feature", "geometry": {"type": "Point", "coordinates": []},
                     "properties": {"idEstacao": 999, "localEstacao": "Sem coordenadas"}}
    estacoes = _cliente(estacoes=[sem_geometria, _feature(*DOIS_PORTOS)]).stations()

    assert [e["station_id"] for e in estacoes] == [ID_DOIS_PORTOS]


def test_an_http_error_is_reported_with_the_body():
    def handler(request):
        return httpx.Response(503, text="upstream indisponivel")

    cliente = IPMAClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="503"):
        cliente.stations()


def test_a_body_that_is_not_the_expected_shape_is_refused():
    """Um 200 com HTML de proxy nao e uma lista de estacoes vazia."""
    def handler(request):
        return httpx.Response(200, text="<html>portal de autenticacao</html>")

    cliente = IPMAClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        cliente.stations()


# --- o -99: o "em falta" do IPMA, em todos os campos -----------------------

def test_a_full_record_gives_one_row_per_metric():
    linhas = linhas_da_estacao(_observacoes_do_feed(), ID_DOIS_PORTOS)

    assert len(linhas) == METRICAS_POR_REGISTO * len(INSTANTES)
    assert {linha["metric"] for linha in linhas} == {
        WeatherMetric.air_temperature, WeatherMetric.relative_humidity,
        WeatherMetric.precipitation, WeatherMetric.wind_speed, WeatherMetric.solar_radiation,
    }


@pytest.mark.parametrize("campo, metrica", [
    ("temperatura", WeatherMetric.air_temperature),
    ("humidade", WeatherMetric.relative_humidity),
    ("precAcumulada", WeatherMetric.precipitation),
    ("intensidadeVento", WeatherMetric.wind_speed),
    ("radiacao", WeatherMetric.solar_radiation),
])
def test_a_missing_value_is_dropped_in_every_field(campo, metrica):
    """-99 e o "em falta" do IPMA, e aparece em qualquer um dos campos.

    Uma temperatura de -99 graus passa em qualquer validacao de tipo; uma
    humidade de -99 por cento tambem, e uma precipitacao de -99 mm ainda por
    cima entra nos totais como se fosse chuva negativa. O teste percorre os
    cinco campos, e nao so a temperatura, porque o filtro escrito uma vez so
    no campo obvio e exactamente o defeito que isto tem de apanhar.
    """
    feed = _observacoes_do_feed(**{
        INSTANTES[0]: {ID_DOIS_PORTOS: _registo(**{campo: VALOR_EM_FALTA})},
        INSTANTES[1]: {ID_DOIS_PORTOS: _registo()},
    })
    linhas = linhas_da_estacao(feed, ID_DOIS_PORTOS)

    primeira_hora = [linha for linha in linhas if linha["date"].hour == 13]
    assert len(primeira_hora) == METRICAS_POR_REGISTO - 1
    assert metrica not in {linha["metric"] for linha in primeira_hora}
    # a hora seguinte, completa, continua la: o filtro tira o valor em falta,
    # nao a serie
    assert len([linha for linha in linhas if linha["date"].hour == 14]) == METRICAS_POR_REGISTO


def test_a_record_that_is_null_for_one_hour_is_skipped():
    """No feed real ha horas em que a estacao aparece com `null` em vez de
    registo -- 675 das 5328 celulas lidas a 29/08/2026."""
    feed = _observacoes_do_feed(**{INSTANTES[0]: {ID_DOIS_PORTOS: None}})
    linhas = linhas_da_estacao(feed, ID_DOIS_PORTOS)

    assert len(linhas) == METRICAS_POR_REGISTO
    assert {linha["date"].hour for linha in linhas} == {14}


def test_a_station_absent_from_the_feed_is_reported_instead_of_giving_zero_rows():
    """O texto procurado e o da guarda DA AUSENCIA, e nao so o id da estacao.

    Ha duas guardas que acabam em zero linhas -- "nao aparece no feed" e
    "aparece e nao mediu nada" -- e as duas nomeiam a estacao. Com o id como
    criterio, este teste passava com a primeira guarda apagada, porque a
    segunda disparava por ela. Foi um sobrevivente da ronda de mutacao desta
    correccao, nao uma suposicao.
    """
    with pytest.raises(ValueError, match="nao aparece em nenhum"):
        linhas_da_estacao(_observacoes_do_feed(), "9999999")


def test_a_value_outside_the_physical_range_fails_loudly():
    """A guarda existe para o sentinela que ainda nao vimos.

    O -99 esta filtrado pelo nome; se o IPMA passar a usar outro codigo (um
    -990, por exemplo), a alternativa a esta guarda era grava-lo como
    temperatura. Falhar o job e recuperavel; um numero absurdo na serie
    canonica, com proveniencia de estacao real, nao e.
    """
    feed = _observacoes_do_feed(**{INSTANTES[0]: {ID_DOIS_PORTOS: _registo(temperatura=-990.0)}})

    with pytest.raises(ValueError, match="temperatura"):
        linhas_da_estacao(feed, ID_DOIS_PORTOS)


def test_pressure_and_wind_direction_are_not_ingested():
    """Nao ha metrica no vocabulario para nenhuma das duas, e inventar
    `air_pressure` aqui era acrescentar vocabulario pela porta das traseiras."""
    linhas = linhas_da_estacao(_observacoes_do_feed(), ID_DOIS_PORTOS)

    assert all(linha["field"] not in ("pressao", "idDireccVento") for linha in linhas)


def test_wind_speed_comes_from_the_field_in_metres_per_second():
    """O feed traz a mesma grandeza duas vezes: intensidadeVento (m/s) e
    intensidadeVentoKM (km/h). O vocabulario pede m/s."""
    linhas = linhas_da_estacao(_observacoes_do_feed(), ID_DOIS_PORTOS)
    vento = [linha for linha in linhas if linha["metric"] == WeatherMetric.wind_speed]

    assert {linha["value"] for linha in vento} == {2.6}
    assert {linha["unit"] for linha in vento} == {"m/s"}


def test_radiation_is_converted_from_kilojoule_per_hour_to_watt():
    """3600 kJ/m2 numa hora sao exactamente 1000 W/m2."""
    linhas = linhas_da_estacao(_observacoes_do_feed(), ID_DOIS_PORTOS)
    radiacao = [linha for linha in linhas if linha["metric"] == WeatherMetric.solar_radiation]

    assert {linha["value"] for linha in radiacao} == {1000.0}
    assert {linha["unit"] for linha in radiacao} == {"W/m2"}


def test_the_units_are_the_ones_the_vocabulary_declares():
    linhas = linhas_da_estacao(_observacoes_do_feed(), ID_DOIS_PORTOS)
    unidades = {linha["metric"]: linha["unit"] for linha in linhas}

    assert unidades == {
        WeatherMetric.air_temperature: "degC",
        WeatherMetric.relative_humidity: "percent",
        WeatherMetric.precipitation: "mm",
        WeatherMetric.wind_speed: "m/s",
        WeatherMetric.solar_radiation: "W/m2",
    }


def test_the_hour_is_read_as_utc():
    """O carimbo do IPMA vem sem fuso. E UTC: a 29/08/2026, com o feed lido as
    15:21 UTC, o instante mais recente era o das 14:00, e o maximo de radiacao
    do conjunto das estacoes caia no bloco das 13:00 UTC -- o meio-dia solar
    em Portugal continental. Lido como hora local (UTC+1), o pico ficaria uma
    hora antes do meio-dia solar e o feed teria duas horas e meia de atraso.
    """
    linhas = linhas_da_estacao(_observacoes_do_feed(), ID_DOIS_PORTOS)
    momentos = sorted({linha["date"] for linha in linhas})

    assert momentos == [
        datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc),
    ]


# --- o cliente le sempre o mesmo sitio, e fecha-se ------------------------

def test_the_client_reads_the_canonical_urls_and_nothing_else():
    """Os URL lidos sao os mesmos que ficam no `source_url` de cada linha.

    E o que impede a proveniencia de divergir do que foi mesmo lido: se o
    cliente pudesse apontar para outro sitio, as linhas continuavam a declarar
    o URL canonico.
    """
    urls = []
    _cliente(urls=urls).observations()

    assert set(urls) == {URL_ESTACOES, URL_OBSERVACOES}


def test_there_is_no_mirror_knob_that_lies_about_the_source_url():
    """`base_url` existiu e nunca era lido: o cliente construia-se apontado a
    um espelho e continuava a ir ao sitio real. Um parametro que nao faz nada e
    pior do que nao existir -- promete uma coisa que nao acontece."""
    with pytest.raises(TypeError):
        IPMAClient(transport=_transport(), base_url="https://espelho.interno/ipma")


def test_the_client_closes_its_connection():
    """A ingestao corre de hora a hora durante meses; um cliente por execucao
    deixado ao recolector sao sockets abandonados."""
    with _cliente() as cliente:
        cliente.stations()

    assert cliente._client.is_closed


def test_the_station_list_is_fetched_once_per_client():
    """A rede de estacoes e precisa duas vezes numa so sincronizacao (para
    escolher a estacao e para as coordenadas da guarda de radiacao) e nao muda
    dentro de uma execucao. Sem cache eram tres transferencias do mesmo
    ficheiro de 48 kB por hora."""
    urls = []
    cliente = _cliente(urls=urls)
    cliente.stations()
    cliente.nearest_station(TURCIFAL_LAT, TURCIFAL_LON)
    cliente.observations()

    assert urls.count(URL_ESTACOES) == 1


# --- guarda de fuso horario: o feed tem de estar no passado ---------------

def test_a_feed_that_is_too_recent_is_refused():
    """Se a origem passar a carimbar em hora local, "15:00" passa a significar
    14:00 UTC e a serie fica uma hora adiantada, MISTURADA com as horas
    correctas que ja la estao -- e nada rebenta, porque a desduplicacao so ve
    uma hora nova. O que se observa de fora e o atraso de publicacao: em hora
    local ele colapsa de ~1 h para ~0."""
    cliente = _cliente(publicado=RECENTE_DE_MAIS)

    with pytest.raises(ValueError, match="atraso minimo"):
        cliente.observations()


def test_a_delay_of_five_minutes_is_not_enough():
    """Fixa a POLITICA por baixo, com o numero escrito a mao.

    Os testes que derivam as fronteiras da constante de producao sao cegos a
    ela mudar de valor -- foi isso que o mutante `aa` mostrou. Cinco minutos de
    atraso e um feed plausivel que a politica tem de recusar; se a politica
    mudar, este teste tem de mudar com ela, de proposito.
    """
    cliente = _cliente(publicado=datetime(2026, 8, 20, 14, 5, tzinfo=timezone.utc))

    with pytest.raises(ValueError, match="atraso minimo"):
        cliente.observations()


def test_the_real_publication_delay_of_thirty_five_minutes_is_accepted():
    """E fixa a politica por CIMA, que e o lado que bloqueou esta tarefa.

    A origem publica 35 minutos depois do instante mais recente (medido duas
    vezes contra a rede a 29/08/2026: Last-Modified 17:35:03 para um ficheiro
    que acaba em 17:00). A versao anterior exigia 30 minutos, ou seja cinco de
    folga: seis minutos de aceleracao da origem e TODOS os jobs horarios
    passavam a falhar, a acusar a origem de ter mudado de fuso, e com o feed a
    ser uma janela deslizante isso e perda definitiva.

    O que este teste garante, exactamente: que o minimo nao passa de 35
    minutos. NAO garante que ele nao volte aos 30 -- para isso e preciso o
    `test_the_minimum_delay_is_exactly_ten_minutes`, que fixa o valor pelos
    dois lados. Enquanto so este existia, repor os 30 minutos que bloquearam a
    ronda 1 deixava a suite verde.
    """
    cliente = _cliente(publicado=MAIS_RECENTE + ATRASO_DE_PUBLICACAO_REAL)

    assert cliente.observations()


def test_the_delay_is_measured_against_the_publication_not_the_reading():
    """O atraso de LEITURA e o de PUBLICACAO sao grandezas diferentes.

    Foi a confusao entre as duas que pos o minimo em 30 minutos: uma leitura
    unica de 1h06 (publicacao + tempo desde ela) foi tomada por propriedade da
    fonte. Aqui o ficheiro foi publicado 5 minutos depois do instante mais
    recente -- atraso de publicacao pequeno de mais, portanto recusado -- mas
    lido duas horas depois disso. Quem decidisse pelo relogio via um atraso de
    leitura de 2h05 e aceitava-o; o que decide e a publicacao.
    """
    cliente = _cliente(publicado=MAIS_RECENTE + timedelta(minutes=5),
                       relogio=lambda: MAIS_RECENTE + timedelta(hours=2, minutes=5))

    with pytest.raises(ValueError, match="Last-Modified da origem"):
        cliente.observations()


def test_a_feed_stamped_in_local_time_is_refused():
    """O caso real que a guarda existe para apanhar, com os numeros medidos.

    Se a origem carimbar em hora local de Lisboa, o ficheiro publicado as
    17:35 UTC acaba num instante rotulado 18:00. Lido como UTC, o atraso
    aparente e -25 minutos.
    """
    feed = {"2026-08-29T18:00": {ID_DOIS_PORTOS: _registo()}}
    cliente = _cliente(observacoes=feed,
                       publicado=datetime(2026, 8, 29, 17, 35, 3, tzinfo=timezone.utc))

    with pytest.raises(ValueError, match="atraso minimo"):
        cliente.observations()


def test_without_the_header_the_guard_falls_back_to_the_clock():
    """Um proxy que retire o Last-Modified nao pode desligar a guarda."""
    cliente = _cliente(publicado=None,
                       relogio=lambda: MAIS_RECENTE + timedelta(minutes=5))

    with pytest.raises(ValueError, match="relogio local"):
        cliente.observations()


def test_the_minimum_delay_is_exactly_ten_minutes():
    """Fixa a constante pelos DOIS lados, com os dois numeros escritos a mao.

    Sem o par, a suite so prendia a margem a uma banda larga: com o "cinco
    minutos nao chegam" de um lado e os "35 minutos passam" do outro, qualquer
    valor entre 6 e 35 deixava tudo verde -- incluindo os 30 minutos que
    bloquearam esta tarefa na ronda 1. Um arranjo que nao esta protegido contra
    regressao nao esta feito.

    Nove minutos sao recusados, dez sao aceites. Mudar a politica obriga a
    mudar este teste, que e o que se quer de um teste de politica.
    """
    nove = _cliente(publicado=MAIS_RECENTE + timedelta(minutes=9))
    dez = _cliente(publicado=MAIS_RECENTE + timedelta(minutes=10))

    with pytest.raises(ValueError, match="atraso minimo"):
        nove.observations()
    assert dez.observations()


# --- o cabecalho e util, nao e de confianca cega --------------------------

def test_a_last_modified_in_the_future_does_not_decide():
    """Um cabecalho adiantado fazia passar um feed que tem de ser recusado.

    O instante mais recente esta a cinco minutos do nosso relogio -- recente de
    mais. O cabecalho, trinta minutos a frente do nosso relogio, faria a conta
    dar 35 minutos e o feed entrava em silencio. E tambem o caso do relogio da
    PROPRIA origem adiantado, em que os carimbos e o cabecalho deslizam juntos
    e a diferenca entre eles nao denuncia nada: o unico sinal que sobra e o
    cabecalho estar no futuro do nosso relogio.
    """
    recente = datetime(2026, 8, 20, 14, 45, tzinfo=timezone.utc)
    feed = {"2026-08-20T14:45": {ID_DOIS_PORTOS: _registo()}}
    cliente = _cliente(observacoes=feed,
                       publicado=recente + timedelta(minutes=35),
                       relogio=lambda: recente + timedelta(minutes=5))

    with pytest.raises(ValueError, match="Last-Modified no futuro"):
        cliente.observations()


def test_a_last_modified_stuck_in_the_past_does_not_refuse_for_ever():
    """Uma cache a servir um cabecalho velho com conteudo fresco dava recusa
    PERMANENTE, com a mensagem a acusar a origem de ter mudado de fuso.

    E a falha catastrofica do N1 outra vez, por uma via que nao controlamos:
    com o feed a ser uma janela deslizante de 24 h e ninguem a olhar para o
    estado dos jobs, uma recusa sustentada e perda definitiva. Contra o
    cabecalho, o atraso aqui seria de -28 horas.
    """
    cliente = _cliente(publicado=MAIS_RECENTE - timedelta(hours=28),
                       relogio=lambda: MAIS_RECENTE + timedelta(minutes=50))

    assert cliente.observations()


def test_an_unreadable_last_modified_falls_back_to_the_clock():
    """Nao e o cabecalho que manda: e o cabecalho quando se percebe."""
    cliente = _cliente(publicado="quinta-feira, talvez",
                       relogio=lambda: MAIS_RECENTE + timedelta(minutes=5))

    with pytest.raises(ValueError, match="Last-Modified ilegivel"):
        cliente.observations()


def test_a_last_modified_without_a_zone_is_read_as_utc():
    """`-0000` e sintaxe legal e quer dizer "sem fuso conhecido": o parser
    devolve um naive.

    Sem a normalizacao, a subtraccao rebentava; e se alguem a "arranjasse"
    assumindo o fuso local da maquina, o erro era de UMA HORA na propria
    grandeza que a guarda mede -- o erro que ela existe para detectar,
    produzido por ela.
    """
    cliente = _cliente(publicado=SEM_FUSO, relogio=lambda: MAIS_RECENTE + timedelta(minutes=50))

    assert cliente.observations()


def test_a_feed_published_with_the_usual_delay_passes():
    """Fronteira exacta: o atraso minimo passa, um minuto menos nao."""
    cliente = _cliente(publicado=NO_LIMITE)

    assert cliente.observations()


def test_the_timezone_guard_does_not_catch_a_shift_backwards():
    """O que a guarda NAO faz, fixado para nao parecer mais forte do que e.

    Uma origem que passasse a carimbar em UTC-1 daria instantes ainda MAIS
    antigos: o atraso aparente cresce, a guarda nao dispara, e a serie fica uma
    hora atrasada em silencio. Nao ha, do lado do consumidor, sinal barato que
    apanhe isso -- este teste existe para que ninguem leia a guarda como
    protecao contra qualquer mudanca de fuso.
    """
    atrasado = {"2026-08-20T11:00": {ID_DOIS_PORTOS: _registo()},
                "2026-08-20T12:00": {ID_DOIS_PORTOS: _registo()}}
    cliente = _cliente(observacoes=atrasado,
                       relogio=lambda: datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc))

    assert cliente.observations() == atrasado


# --- altura solar: o unico limite que depende do instante e do sitio ------

def test_the_solar_altitude_matches_the_geometry_at_the_winter_solstice():
    """Ao meio-dia solar do solsticio de inverno a altura e 90 - latitude -
    23,44 graus, sem astronomia nenhuma pelo meio. Lisboa a 38,7223 da 27,84."""
    lat, lon = 38.7223, -9.1393
    altura = altura_solar_graus(datetime(2026, 12, 21, 12, 37, tzinfo=timezone.utc), lat, lon)

    assert altura == pytest.approx(90 - lat - 23.44, abs=0.1)


def test_the_sun_is_where_it_should_be_over_dois_portos():
    de_noite = altura_solar_graus(datetime(2026, 8, 20, 2, tzinfo=timezone.utc), 39.04389444, -9.179)
    de_dia = altura_solar_graus(datetime(2026, 8, 20, 13, tzinfo=timezone.utc), 39.04389444, -9.179)

    assert de_noite < ALTURA_SOLAR_DE_NOITE_GRAUS
    assert de_dia > 60.0


def test_the_solar_altitude_refuses_a_naive_instant():
    with pytest.raises(ValueError, match="fuso"):
        altura_solar_graus(datetime(2026, 8, 20, 2, 0), 39.04389444, -9.179)


def test_night_radiation_is_deleted_from_the_feed():
    """680 kJ/m2 as duas da manha dao 188,89 W/m2 -- dentro do intervalo
    fisico, portanto a guarda de intervalo nao lhes toca. Sao 23 estacoes no
    feed real de 29/08/2026, quatro delas com centenas de kJ/m2."""
    feed = _observacoes_do_feed(**{NOITE: {ID_DOIS_PORTOS: _registo(radiacao=680.0)}})
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[NOITE][ID_DOIS_PORTOS]["radiacao"] == VALOR_EM_FALTA
    # so a radiacao: o resto do registo nocturno e medicao a valer
    assert limpo[NOITE][ID_DOIS_PORTOS]["temperatura"] == 24.6
    # e o dia nao e tocado
    assert limpo[INSTANTES[0]][ID_DOIS_PORTOS]["radiacao"] == 3600.0


def test_night_radiation_never_becomes_a_row():
    feed = _observacoes_do_feed(**{NOITE: {ID_DOIS_PORTOS: _registo(radiacao=680.0)}})
    linhas = linhas_da_estacao(_cliente(observacoes=feed).observations(), ID_DOIS_PORTOS)

    nocturnas = [linha for linha in linhas if linha["date"].hour == 2]
    assert nocturnas
    assert WeatherMetric.solar_radiation not in {linha["metric"] for linha in nocturnas}


def test_the_hour_that_straddles_sunset_is_kept():
    """`radiacao` e uma ACUMULACAO da hora e o carimbo e um instante.

    Olhar so para a altura solar no carimbo apagava a hora que atravessa o por
    do sol -- 44 estacoes no feed real de 29/08/2026, todas com uma medicao de
    crepusculo verdadeira. Foi assim que este defeito na guarda se descobriu:
    a correr contra a rede, a contar quantas leituras a guarda descartava.
    """
    feed = _observacoes_do_feed(**{CREPUSCULO: {ID_DOIS_PORTOS: _registo(radiacao=215.0)}})
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[CREPUSCULO][ID_DOIS_PORTOS]["radiacao"] == 215.0


def test_a_night_reading_of_practically_zero_is_kept():
    """0,1 kJ/m2 sao 0,03 W/m2: e o zero do instrumento, que e o que um sensor
    a funcionar diz de noite. Apagar isso era mexer na serie sem ganho nenhum
    -- a guarda existe para o que nao pode ter sido medido, nao para o ruido."""
    feed = _observacoes_do_feed(**{NOITE: {ID_DOIS_PORTOS: _registo(radiacao=0.1)}})
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[NOITE][ID_DOIS_PORTOS]["radiacao"] == 0.1


def test_a_station_absent_from_the_station_list_is_left_untouched():
    """Sem coordenadas nao ha altura solar. Inventar uma posicao para poder
    aplicar a guarda era pior do que nao a aplicar -- fica no log."""
    desconhecida = "9999999"
    feed = {NOITE: {desconhecida: _registo(radiacao=680.0)},
            INSTANTES[0]: {desconhecida: _registo()}}
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[NOITE][desconhecida]["radiacao"] == 680.0


# --- a POLITICA da guarda solar, com os numeros escritos a mao ------------
#
# Os testes acima usam a constante de producao para dizer "esta abaixo do
# limiar", o que os torna cegos ao limiar mudar de valor -- e o mesmo defeito
# do mutante `aa`, encontrado aqui pela re-revisao. Os quatro que se seguem
# nao importam constante nenhuma: escolhem instantes cuja altura solar nas duas
# pontas da hora foi calculada uma vez e escrita no cabecalho deste ficheiro, e
# afirmam o que tem de acontecer a cada um deles.

def test_the_threshold_is_civil_twilight_and_not_the_horizon():
    """Ponta de tras a -4,63 graus: acima do crepusculo civil, logo a hora
    ainda teve luz difusa e a leitura fica.

    Com o limiar a 0 graus esta hora era apagada, e com ela ~389 horas por ano
    so em Turcifal, todas com radiacao de crepusculo verdadeira. E o mesmo
    defeito das 44 estacoes, um passo mais para dentro da noite.
    """
    feed = _feed_de_um_instante(CREPUSCULO_DE_JANEIRO, radiacao=18.0)   # 5 W/m2
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[CREPUSCULO_DE_JANEIRO][ID_DOIS_PORTOS]["radiacao"] == 18.0


def test_the_threshold_is_civil_twilight_and_not_astronomical_night():
    """Pontas a -7,24 e -26,64 graus: o sol ja passou o crepusculo civil nas
    duas, portanto nao houve luz nenhuma nesta hora e 50 W/m2 e falso.

    Fixa duas coisas ao mesmo tempo. Com o limiar a -18 graus (noite
    astronomica) a ponta de tras passava por "dia" e a guarda perdia ~828 horas
    por ano. Com a janela a 3 horas em vez de 1, a ponta de tras ia parar as
    18:00, com o sol a +15 graus, e a guarda perdia ~1460 horas por ano.
    """
    feed = _feed_de_um_instante(DEPOIS_DO_CREPUSCULO, radiacao=180.0)   # 50 W/m2
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[DEPOIS_DO_CREPUSCULO][ID_DOIS_PORTOS]["radiacao"] == VALOR_EM_FALTA


def test_the_dawn_end_of_the_window_counts_as_much_as_the_dusk_one():
    """Pontas a -20,62 e +0,19 graus: a hora acaba com o sol a nascer.

    E o caso simetrico do balde do por do sol. Olhar so para a ponta de tras
    -- que e a leitura ingenua de "esta hora ja comecou de noite" -- apagava
    ~730 horas por ano, todas de madrugada, todas com radiacao verdadeira.
    """
    feed = _feed_de_um_instante(MADRUGADA, radiacao=100.0)              # 27,8 W/m2
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[MADRUGADA][ID_DOIS_PORTOS]["radiacao"] == 100.0


def test_fifty_watts_in_the_middle_of_the_night_is_deleted():
    """Fixa o tecto por CIMA, que e o lado que nenhum teste tinha.

    O teste que ja existia usa 680 kJ/m2 (188,9 W/m2) e por isso sobrevivia a
    um tecto de 100 ou de 185 W/m2 -- no feed de hoje, com 185, 29 das 32
    leituras nocturnas falsas passavam. 50 W/m2 as duas da manha e tao
    impossivel como 189, e so morre com um tecto baixo.
    """
    feed = _feed_de_um_instante(NOITE, radiacao=180.0)                  # 50 W/m2
    limpo = _cliente(observacoes=feed).observations()

    assert limpo[NOITE][ID_DOIS_PORTOS]["radiacao"] == VALOR_EM_FALTA


def test_the_solar_position_is_anchored_where_the_orbit_is_not_circular():
    """Segunda afericao, num ponto onde o maior termo periodico do algoritmo
    vale ~1,9 graus.

    A ancora do solsticio de Inverno nao chega: cai a duas semanas do perielio,
    onde a equacao do centro e quase nula (apaga-la mexe 0,002 graus no
    resultado, e a suite nem dava por isso). Esta usa uma identidade exacta: no
    equinocio a declinacao solar e zero, e no polo a altura do sol E a
    declinacao. Sem a equacao do centro, o mesmo instante da -0,74 graus.

    O instante e o equinocio de Marco de 2026 publicado, 20/03 as 14:46 UTC.
    """
    equinocio = datetime(2026, 3, 20, 14, 46, tzinfo=timezone.utc)

    assert altura_solar_graus(equinocio, 90.0, 0.0) == pytest.approx(0.0, abs=0.05)
    # e o sinal muda de um lado ao outro do equinocio, meio dia para cada lado
    assert altura_solar_graus(equinocio - timedelta(hours=12), 90.0, 0.0) < -0.15
    assert altura_solar_graus(equinocio + timedelta(hours=12), 90.0, 0.0) > 0.15


# --- a estacao que existe e nao mede nada ---------------------------------

def test_a_station_that_gives_no_usable_value_at_all_is_reported():
    """Presente no feed, zero valores utilizaveis em 24 horas: devolver [] dava
    um job succeeded com zero linhas, e nada no estado do job distinguia "a
    estacao esta avariada" de "correu bem"."""
    so_nulos = {instante: {ID_DOIS_PORTOS: None} for instante in INSTANTES}

    with pytest.raises(ValueError, match="valor utilizavel"):
        linhas_da_estacao(so_nulos, ID_DOIS_PORTOS)


def test_a_station_with_every_field_missing_is_reported_too():
    todos_em_falta = {
        instante: {ID_DOIS_PORTOS: {campo: VALOR_EM_FALTA for campo in
                                    ("temperatura", "humidade", "precAcumulada",
                                     "intensidadeVento", "radiacao")}}
        for instante in INSTANTES
    }

    with pytest.raises(ValueError, match="valor utilizavel"):
        linhas_da_estacao(todos_em_falta, ID_DOIS_PORTOS)


def test_an_hourly_rainfall_above_twice_the_national_record_is_refused():
    """O recorde horario no continente anda pelos 50 mm. Um tecto de 250 mm era
    cinco vezes isso: a guarda so disparava para um sentinela nas centenas."""
    feed = _observacoes_do_feed(**{
        INSTANTES[0]: {ID_DOIS_PORTOS: _registo(precAcumulada=150.0)}})

    with pytest.raises(ValueError, match="precAcumulada"):
        linhas_da_estacao(feed, ID_DOIS_PORTOS)


# --- a base de dados: sitio, AOI e a serie que fica gravada ----------------

def _quadrado(lon: float, lat: float, lado_graus: float = 0.025) -> dict:
    meio = lado_graus / 2
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - meio, lat - meio], [lon + meio, lat - meio],
            [lon + meio, lat + meio], [lon - meio, lat + meio], [lon - meio, lat - meio],
        ]],
    }


def _aoi(session, site_code, aoi_code, lon, lat, status=AoiStatus.approved,
         proveniencia=GeometryProvenance.surveyed):
    site = Site(code=site_code, name=f"Sitio {site_code}")
    aoi = Aoi(
        site=site, code=aoi_code, purpose="earth_observation",
        geometry=geojson_to_wkt_element(_quadrado(lon, lat)),
        geometry_provenance=proveniencia, status=status,
        approved_by="site-manager" if status == AoiStatus.approved else None,
    )
    session.add(aoi)
    session.commit()
    return aoi


@pytest.fixture
def sitio_turcifal(session):
    return _aoi(session, "EUC-TUR-IPMA", "EUC-TUR-IPMA-EO", TURCIFAL_LON, TURCIFAL_LAT)


@pytest.fixture
def sitio_porto(session):
    return _aoi(session, "EUC-PTO-IPMA", "EUC-PTO-IPMA-EO", PORTO_LON, PORTO_LAT)


@pytest.fixture
def sitio_sem_aoi_aprovada(session):
    return _aoi(session, "EUC-TUR-IPMA-DRAFT", "EUC-TUR-IPMA-DRAFT-EO",
                TURCIFAL_LON, TURCIFAL_LAT, status=AoiStatus.draft,
                proveniencia=GeometryProvenance.provisional_pending_kml)


class _ClienteEspiao:
    """So regista que foi chamado: a lista vazia e a prova de que nao houve rede."""

    def __init__(self):
        self.chamadas = []
        self.descartes_por_estacao = {}

    def nearest_station(self, *args, **kwargs):
        self.chamadas.append("nearest_station")
        # com `stations_considered`, como o cliente real: um duplo a que falte
        # uma peca do contrato transforma cada uso novo dela numa falha alheia,
        # e este ja estava nessa condicao
        return {"station_id": ID_DOIS_PORTOS, "station_name": "x", "lat": 39.0, "lon": -9.2,
                "distance_km": 1.0, "stations_considered": 1}

    def observations(self, *args, **kwargs):
        self.chamadas.append("observations")
        return {}


class _ClienteQueRebenta:
    def nearest_station(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao IPMA perdida")

    def observations(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao IPMA perdida")


class _ClienteQueEspreitaOJob:
    """Le a linha do job na base A MEIO da chamada a rede.

    Mesmo papel do homonimo da reanalise: quando o sync_ipma devolve, o job ja
    esta succeeded e a passagem por running seria indistinguivel de nunca ter
    acontecido.
    """

    def __init__(self, session, cliente=None):
        self._cliente = cliente or _cliente()
        self._session = session
        self._commits = 0
        self.commits_ate_a_rede = None
        self.estado_a_meio = None
        event.listen(session, "after_commit", self._contar)

    def _contar(self, _sessao):
        self._commits += 1

    @property
    def descartes_por_estacao(self):
        return self._cliente.descartes_por_estacao

    def nearest_station(self, *args, **kwargs):
        self.commits_ate_a_rede = self._commits
        with self._session.no_autoflush:
            self._session.expire_all()
            self.estado_a_meio = self._session.execute(
                select(IngestionJob.status, IngestionJob.rows_written, IngestionJob.finished_at)
            ).one()
        return self._cliente.nearest_station(*args, **kwargs)

    def observations(self, *args, **kwargs):
        return self._cliente.observations(*args, **kwargs)


def _observacoes_gravadas(session, aoi):
    return session.scalars(
        select(Observation).where(Observation.site_id == aoi.site_id)
        .order_by(Observation.observed_at, Observation.metric)
    ).all()


def _linha_de_estacao(site_id, **trocas):
    """Linha com a identidade de uma das linhas que a sincronizacao vai
    escrever, mudada em UMA coluna. O que se prova nao e o cenario, e que a
    consulta de desduplicacao repete a uq_observation_identity inteira."""
    campos = {
        "site_id": site_id,
        "plot_id": None,
        "observed_at": datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc),
        "metric": WeatherMetric.air_temperature,
        "source_type": SourceType.weather_observed,
        "processing_version": PROCESSING_VERSION_IPMA,
        "unit": "degC",
        "value_numeric": 99.0,
        "value_qualifier": ValueQualifier.exact,
        "quality_flag": QualityFlag.unchecked,
        "evidence": {"nota": "linha posta a mao pelo teste"},
    }
    campos.update(trocas)
    return Observation(**campos)


def test_unknown_site_is_refused_before_any_network_call(session):
    espiao = _ClienteEspiao()

    with pytest.raises(ValueError, match="EUC-NAO-EXISTE"):
        sync_ipma(session, espiao, "EUC-NAO-EXISTE")

    assert espiao.chamadas == []
    assert session.scalars(select(IngestionJob)).all() == []


def test_a_site_without_an_approved_aoi_is_refused(session, sitio_sem_aoi_aprovada):
    espiao = _ClienteEspiao()

    with pytest.raises(ValueError, match="approved"):
        sync_ipma(session, espiao, "EUC-TUR-IPMA-DRAFT")

    assert espiao.chamadas == []


def test_the_first_run_writes_one_row_per_hour_and_metric(session, sitio_turcifal):
    job = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    assert job.status == JobStatus.succeeded
    assert job.rows_written == METRICAS_POR_REGISTO * len(INSTANTES)
    assert job.job_type == "ipma_sync"
    assert job.aoi_id == sitio_turcifal.id
    assert job.processing_version == PROCESSING_VERSION_IPMA
    assert job.request_hash
    assert job.finished_at is not None
    assert job.error is None
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 10


def test_a_second_run_of_the_same_hours_writes_nothing(session, sitio_turcifal):
    """A idempotencia e o que permite correr isto de hora a hora.

    Nao ha arquivo: o feed so tem as ultimas 24 horas, e o historico
    constroi-se a repetir a mesma leitura muitas vezes com sobreposicao quase
    total. Se a segunda passagem escrevesse outra vez, a serie ficava com
    24 copias de cada hora ao fim de um dia.
    """
    primeiro = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")
    segundo = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    assert primeiro.rows_written == 10
    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 10


def test_the_hour_that_is_new_is_added_next_to_the_ones_already_there(session, sitio_turcifal):
    """Idempotencia nao e "nao escrever nada na segunda vez": e escrever
    exactamente a hora que falta, que e a hora nova de cada passagem."""
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    hora_nova = "2026-08-20T15:00"
    feed = _observacoes_do_feed(**{hora_nova: {ID_DOIS_PORTOS: _registo(temperatura=23.1)}})
    segundo = sync_ipma(session, _cliente(observacoes=feed), "EUC-TUR-IPMA")

    assert segundo.rows_written == METRICAS_POR_REGISTO
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 15


def test_every_row_carries_the_station_provenance(session, sitio_turcifal):
    """5,34 km em Turcifal nao e uma medicao no campo.

    A base ja recusa uma linha sem proveniencia, mas nao verifica se a
    proveniencia diz alguma coisa: um evidence com o codigo do sitio e nada
    mais passava na mesma. O que tem de estar em CADA linha e a estacao
    concreta e a distancia a que ela esta.
    """
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    assert linhas
    for linha in linhas:
        assert linha.evidence["station_id"] == ID_DOIS_PORTOS
        assert linha.evidence["station_name"] == "Torres Vedras, Dois Portos"
        assert linha.evidence["distance_km"] == pytest.approx(DISTANCIA_DOIS_PORTOS_KM, abs=0.001)
        assert linha.evidence["measured_at_site"] is False
        # as duas posicoes, para a distancia se poder refazer sem ir buscar a
        # geometria da AOI de hoje nem o stations.json de hoje
        assert linha.evidence["station_lat"] == pytest.approx(39.04389444)
        assert linha.evidence["station_lon"] == pytest.approx(-9.179)
        assert linha.evidence["site_lat"] == pytest.approx(TURCIFAL_LAT, abs=1e-6)
        assert linha.evidence["site_lon"] == pytest.approx(TURCIFAL_LON, abs=1e-6)
        assert linha.evidence["source_url"] == URL_OBSERVACOES
        assert linha.evidence["request_hash"]


def test_the_recorded_distance_is_the_real_distance_from_site_to_station(session, sitio_turcifal):
    """A distancia nao vem do cliente nem de um argumento: e calculada a
    partir das duas posicoes, e tem de bater certo com a real."""
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    distancias = {linha.evidence["distance_km"]
                  for linha in _observacoes_gravadas(session, sitio_turcifal)}
    assert len(distancias) == 1
    assert distancias.pop() == pytest.approx(5.3399, abs=0.001)


def test_the_rows_are_stored_as_a_measurement_not_as_a_model(session, sitio_turcifal):
    """weather_observed, nao reanalysis: isto e uma medicao, feita por um
    instrumento real, ao contrario da serie do AgERA5. Num sistema MRV o que
    se pode defender e o que se mediu."""
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    assert {linha.source_type for linha in linhas} == {SourceType.weather_observed}
    assert all(SourceType.is_measurement(linha.source_type) for linha in linhas)
    assert {linha.source_collection for linha in linhas} == {COLECCAO_IPMA}
    assert {linha.processing_version for linha in linhas} == {PROCESSING_VERSION_IPMA}


def test_the_rows_are_flagged_unchecked_because_the_feed_is_not_validated(session, sitio_turcifal):
    """O IPMA publica as observacoes em tempo real sem validacao. O -99 que
    filtramos e a guarda de intervalo nao fazem controlo de qualidade -- so
    impedem o absurdo -- e dizer `valid` seria afirmar uma verificacao que
    ninguem fez."""
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    assert {linha.quality_flag for linha in linhas} == {QualityFlag.unchecked}
    assert {linha.value_qualifier for linha in linhas} == {ValueQualifier.exact}
    assert {linha.plot_id for linha in linhas} == {None}


def test_missing_values_never_reach_the_database(session, sitio_turcifal):
    feed = _observacoes_do_feed(**{
        INSTANTES[0]: {ID_DOIS_PORTOS: _registo(temperatura=VALOR_EM_FALTA,
                                                radiacao=VALOR_EM_FALTA)},
        INSTANTES[1]: {ID_DOIS_PORTOS: _registo()},
    })
    job = sync_ipma(session, _cliente(observacoes=feed), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    assert job.rows_written == METRICAS_POR_REGISTO * 2 - 2
    assert all(linha.value_numeric > -90 for linha in linhas)
    primeira_hora = [linha for linha in linhas
                     if linha.observed_at.astimezone(timezone.utc).hour == 13]
    assert {linha.metric for linha in primeira_hora} == {
        WeatherMetric.relative_humidity, WeatherMetric.precipitation, WeatherMetric.wind_speed,
    }


def test_the_station_is_chosen_from_the_site_point_in_the_database(session, sitio_porto):
    """A posicao do sitio sai do centroide da AOI aprovada, e e ela que escolhe
    a estacao: o mesmo cliente, com o mesmo feed, da outra estacao para o Porto."""
    sync_ipma(session, _cliente(), "EUC-PTO-IPMA")

    linhas = _observacoes_gravadas(session, sitio_porto)
    assert {linha.evidence["station_id"] for linha in linhas} == {ID_S_GENS}
    temperaturas = [linha.value_numeric for linha in linhas
                    if linha.metric == WeatherMetric.air_temperature]
    assert temperaturas == [19.0, 19.0]


def test_the_job_window_declares_the_hours_actually_written(session, sitio_turcifal):
    """O job nasce com a janela nominal das ultimas 24 horas, porque tem de
    existir antes da rede; quando a resposta chega, passa a declarar o
    intervalo que foi mesmo gravado."""
    job = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    assert job.date_from == DIA_DOS_INSTANTES
    assert job.date_to == DIA_DOS_INSTANTES


def test_the_job_is_visible_as_running_during_the_network_call(session, sitio_turcifal):
    cliente = _ClienteQueEspreitaOJob(session)
    job = sync_ipma(session, cliente, "EUC-TUR-IPMA")

    estado, escritas, terminado = cliente.estado_a_meio
    assert estado == JobStatus.running
    assert escritas == 0
    assert terminado is None
    assert cliente.commits_ate_a_rede >= 2
    assert job.status == JobStatus.succeeded


def test_a_network_failure_marks_the_job_failed_and_writes_nothing(session, sitio_turcifal):
    job = sync_ipma(session, _ClienteQueRebenta(), "EUC-TUR-IPMA")

    assert job.status == JobStatus.failed
    # o prefixo com a classe da excepcao vem do `_texto_do_erro` de producao;
    # o texto a seguir e o literal do duplo e nao prova nada, por isso nao e
    # sobre ele que se afirma
    assert job.error and job.error.startswith("ConnectError:")
    assert job.rows_written == 0
    assert _observacoes_gravadas(session, sitio_turcifal) == []
    assert session.get(IngestionJob, job.id).status == JobStatus.failed


def test_an_absurd_value_marks_the_job_failed_instead_of_being_written(session, sitio_turcifal):
    feed = _observacoes_do_feed(**{INSTANTES[0]: {ID_DOIS_PORTOS: _registo(humidade=-990.0)}})
    job = sync_ipma(session, _cliente(observacoes=feed), "EUC-TUR-IPMA")

    assert job.status == JobStatus.failed
    assert "humidade" in job.error
    assert _observacoes_gravadas(session, sitio_turcifal) == []


def test_a_site_with_no_station_within_the_ceiling_fails_the_job(session, sitio_turcifal):
    job = sync_ipma(session, _cliente(estacoes=[_feature(*OLHAO)]), "EUC-TUR-IPMA")

    assert job.status == JobStatus.failed
    assert "km" in job.error
    assert _observacoes_gravadas(session, sitio_turcifal) == []


# --- a desduplicacao espelha a identidade, coluna a coluna -----------------

def test_dedup_query_mirrors_the_identity_on_processing_version(session, sitio_turcifal):
    """Uma linha igual em tudo menos na versao de processamento NAO e
    duplicado: e o que permite reprocessar sem colidir com o que ja la esta."""
    session.add(_linha_de_estacao(sitio_turcifal.site_id, processing_version="ipma-stations-v0"))
    session.commit()

    job = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    assert job.rows_written == 10
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 11


def test_dedup_query_mirrors_the_identity_on_source_type(session, sitio_turcifal):
    """A mesma hora e a mesma metrica ja existem como reanalise: a linha da
    estacao entra ao lado dela, porque sao duas proveniencias diferentes da
    mesma grandeza -- que e exactamente o que o source_type separa.

    A linha posta a mao muda o source_type e SO o source_type: fica com a
    processing_version do IPMA, que nenhuma linha de reanalise real teria.
    E de proposito. Trocar as duas colunas ao mesmo tempo era um cenario mais
    realista e um teste mais fraco -- passava na mesma com o source_type fora
    da consulta de desduplicacao, porque a versao sozinha ja separava as duas
    linhas.
    """
    session.add(_linha_de_estacao(sitio_turcifal.site_id, source_type=SourceType.reanalysis))
    session.commit()

    job = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    assert job.rows_written == 10
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 11


def test_dedup_query_mirrors_the_identity_on_metric(session, sitio_turcifal):
    session.add(_linha_de_estacao(sitio_turcifal.site_id,
                                  metric=WeatherMetric.relative_humidity, unit="percent"))
    session.commit()

    job = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    # a linha de humidade das 13:00 ja existia: das dez, escreve-se nove
    assert job.rows_written == 9
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 10


def test_dedup_query_mirrors_the_identity_on_observed_at(session, sitio_turcifal):
    session.add(_linha_de_estacao(
        sitio_turcifal.site_id, observed_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)))
    session.commit()

    job = sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    assert job.rows_written == 10
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 11


def test_dedup_query_mirrors_the_identity_on_site_id(session, sitio_turcifal, sitio_porto):
    """A serie de um sitio nao pode tapar a de outro."""
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")
    job = sync_ipma(session, _cliente(), "EUC-PTO-IPMA")

    assert job.rows_written == 10
    assert len(_observacoes_gravadas(session, sitio_turcifal)) == 10
    assert len(_observacoes_gravadas(session, sitio_porto)) == 10


def test_the_same_row_written_twice_would_violate_the_database_identity(session, sitio_turcifal):
    """A desduplicacao e a primeira linha de defesa; a segunda e a base.

    Se a consulta deixasse passar um duplicado, o INSERT rebentava contra a
    uq_observation_identity e o job ficava failed -- ruidoso, mas nunca com a
    serie duplicada em silencio.
    """
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")
    linhas = _observacoes_gravadas(session, sitio_turcifal)
    repetida = linhas[0]

    session.add(_linha_de_estacao(
        sitio_turcifal.site_id, observed_at=repetida.observed_at, metric=repetida.metric,
        unit=repetida.unit))
    # a excepcao tem de ser a violacao da identidade, e nomeada: com
    # `Exception` a seco, um NOT NULL ou um erro de tipo passavam por "a
    # identidade rejeitou o duplicado" e o teste dizia uma coisa que nao viu
    with pytest.raises(IntegrityError, match="uq_observation_identity"):
        session.flush()
    session.rollback()


def test_a_feed_that_is_too_recent_fails_the_job(session, sitio_turcifal):
    cliente = _cliente(publicado=RECENTE_DE_MAIS)
    job = sync_ipma(session, cliente, "EUC-TUR-IPMA")

    assert job.status == JobStatus.failed
    assert "atraso minimo" in job.error
    assert _observacoes_gravadas(session, sitio_turcifal) == []


def test_night_radiation_never_reaches_the_database(session, sitio_turcifal):
    feed = _observacoes_do_feed(**{NOITE: {ID_DOIS_PORTOS: _registo(radiacao=680.0)}})
    job = sync_ipma(session, _cliente(observacoes=feed), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    nocturnas = [linha for linha in linhas
                 if linha.observed_at.astimezone(timezone.utc).hour == 2]
    assert job.status == JobStatus.succeeded
    assert job.rows_written == METRICAS_POR_REGISTO * 2 + 4     # duas horas de dia, uma de noite
    assert len(nocturnas) == 4
    assert WeatherMetric.solar_radiation not in {linha.metric for linha in nocturnas}


def test_a_station_with_nothing_usable_fails_the_job(session, sitio_turcifal):
    so_nulos = {instante: {ID_DOIS_PORTOS: None} for instante in INSTANTES}
    job = sync_ipma(session, _cliente(observacoes=so_nulos), "EUC-TUR-IPMA")

    assert job.status == JobStatus.failed
    assert "valor utilizavel" in job.error
    assert _observacoes_gravadas(session, sitio_turcifal) == []
    # a janela nominal fica como estava: um job falhado nao declara cobertura
    assert job.date_from != DIA_DOS_INSTANTES or job.date_to != DIA_DOS_INSTANTES


def test_the_discarded_night_readings_are_counted_in_the_evidence(session, sitio_turcifal):
    """Quem auditar a tabela daqui a um ano nao tem o log: se a contagem nao
    ficar na linha, nao ha nenhuma forma de saber que houve leituras
    descartadas nesta estacao."""
    feed = _observacoes_do_feed(**{
        NOITE: {ID_DOIS_PORTOS: _registo(radiacao=680.0)},
        "2026-08-20T03:00": {ID_DOIS_PORTOS: _registo(radiacao=657.0)},
    })
    sync_ipma(session, _cliente(observacoes=feed), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    assert linhas
    assert {linha.evidence["night_radiation_dropped"] for linha in linhas} == {2}


def test_a_run_with_nothing_discarded_says_zero_and_not_nothing(session, sitio_turcifal):
    """Zero e uma afirmacao; a ausencia da chave nao e. Sem isto, uma linha
    antiga e uma linha limpa ficavam indistinguiveis."""
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    assert {linha.evidence["night_radiation_dropped"] for linha in linhas} == {0}


class _ClienteSemContagem:
    """Cliente que escolhe uma estacao e nao diz de quantas.

    E o duplo que faltava: enquanto todos os duplos traziam a contagem, o
    `.get()` no servico gravava `null` em silencio e nenhum teste dava por
    isso.
    """

    def __init__(self, cliente=None):
        self._cliente = cliente or _cliente()
        self.descartes_por_estacao = {}

    def nearest_station(self, *args, **kwargs):
        proxima = dict(self._cliente.nearest_station(*args, **kwargs))
        proxima.pop("stations_considered", None)
        return proxima

    def observations(self, *args, **kwargs):
        feed = self._cliente.observations(*args, **kwargs)
        self.descartes_por_estacao = self._cliente.descartes_por_estacao
        return feed


def test_a_client_that_cannot_say_how_many_stations_it_weighed_fails_the_job(
    session, sitio_turcifal
):
    """Zero linhas e um job falhado, e nao linhas com `null` no evidence.

    E o mesmo principio que ja vale para a contagem de descartes: quem nao sabe
    de quantas estacoes escolheu nao pode afirmar "a mais proxima" por omissao.
    Um `null` gravado em silencio nao se distingue depois de uma linha antiga.
    """
    job = sync_ipma(session, _ClienteSemContagem(), "EUC-TUR-IPMA")

    assert job.status == JobStatus.failed
    assert "stations_considered" in job.error
    assert _observacoes_gravadas(session, sitio_turcifal) == []


def test_the_number_of_stations_considered_is_in_the_evidence(session, sitio_turcifal):
    """"A mais proxima" e uma afirmacao sobre uma lista: 5,34 km entre quatro
    estacoes e outra coisa do que 5,34 km entre 222. O numero sai do
    `nearest_station`, que e quem ordenou a lista, e nao de uma segunda leitura
    do stations.json."""
    sync_ipma(session, _cliente(), "EUC-TUR-IPMA")

    linhas = _observacoes_gravadas(session, sitio_turcifal)
    assert {linha.evidence["stations_considered"] for linha in linhas} == {len(ESTACOES)}
