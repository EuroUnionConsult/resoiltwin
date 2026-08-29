"""Ingestao das estacoes do IPMA: o que se grava, o que se recusa a gravar.

Nenhum teste toca a rede. O cliente e o IPMAClient REAL, ligado a um
httpx.MockTransport que devolve o formato exacto dos dois ficheiros do feed
aberto -- lidos a 29/08/2026 -- em vez de um duplo que devolve linhas ja
normalizadas. E de proposito: a ordem [lon, lat] do GeoJSON e o -99 do IPMA
so existem no formato de origem, e um duplo que devolvesse dicionarios ja
limpos nunca chegaria a exercer nenhuma das duas.
"""

from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import event, select

from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, JobStatus, QualityFlag, SourceType, ValueQualifier,
)
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.models import Aoi, IngestionJob, Observation, Site
from resoiltwin.weather.ingest import PROCESSING_VERSION_IPMA, sync_ipma
from resoiltwin.weather.ipma import (
    COLECCAO_IPMA,
    RAIO_MAXIMO_KM,
    URL_OBSERVACOES,
    VALOR_EM_FALTA,
    IPMAClient,
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
        "pressao": -99.0,
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


def _transport(estacoes=None, observacoes=None):
    def handler(request):
        caminho = request.url.path
        if caminho.endswith("stations.json"):
            return httpx.Response(200, json=ESTACOES if estacoes is None else estacoes)
        if caminho.endswith("observations.json"):
            return httpx.Response(
                200, json=_observacoes_do_feed() if observacoes is None else observacoes)
        return httpx.Response(404, text=f"caminho nao servido pelo duplo: {caminho}")

    return httpx.MockTransport(handler)


def _cliente(estacoes=None, observacoes=None) -> IPMAClient:
    return IPMAClient(transport=_transport(estacoes, observacoes))


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
    with pytest.raises(ValueError, match="9999999"):
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

    def nearest_station(self, *args, **kwargs):
        self.chamadas.append("nearest_station")
        return {"station_id": ID_DOIS_PORTOS, "station_name": "x", "lat": 39.0, "lon": -9.2,
                "distance_km": 1.0}

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
    assert job.error and "IPMA" in job.error
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
    with pytest.raises(Exception):
        session.flush()
    session.rollback()
