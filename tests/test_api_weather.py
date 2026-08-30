"""A porta de fora da ingestao meteorologica: o que sai, e com que codigo.

Nenhum teste toca a rede. Os dois clientes entram por dependencia do FastAPI e
sao substituidos por duplos. Os dois unicos testes que constroem um CDSClient
real -- os que verificam a propria dependencia -- constroem-no e fecham-no sem
lhe pedir nada: o `httpx.Client` so abre ligacao no primeiro pedido, e nenhum e
feito.

A distincao que este ficheiro existe para fixar e a que se perde primeiro: uma
recusa ANTES de a execucao comecar e um erro HTTP (nao ha job), e uma falha
DEPOIS de o job existir e um 202 com o job em `failed`. Os dois lados sao
testados, e nunca ao mesmo tempo.
"""

import uuid

import httpx
import pytest
from sqlalchemy import func, select

from resoiltwin.api.weather import _fabrica_de_cliente, get_cds_client, get_ipma_client
from resoiltwin.config import Settings, get_settings
from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, JobStatus, SourceType,
)
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.main import app
from resoiltwin.models import Aoi, IngestionJob, Observation, Site
from resoiltwin.weather.cds import DATASET_AGERA5, CDSClient, expandir_area
from resoiltwin.weather.ingest import (
    JOB_TYPE, JOB_TYPE_IPMA, PROCESSING_VERSION, PROCESSING_VERSION_IPMA, VARIAVEIS,
)
from resoiltwin.weather.ipma import COLECCAO_IPMA, RAIO_MAXIMO_KM
from resoiltwin.weather.metrics import (
    AggregationOperator, WeatherMetric, proveniencia_de_agregacao,
)

TURCIFAL_LON, TURCIFAL_LAT = -9.240247, 39.037317
CELULA_TURCIFAL = (39.0, -9.2)

JANELA = {"date_from": "2026-07-01", "date_to": "2026-07-03"}
DATAS = ("2026-07-01", "2026-07-02", "2026-07-03")

# variavel do AgERA5 -> (metrica, unidade, valor), como em test_weather_ingest.
# Tem de cobrir TODAS as variaveis que `ingest.VARIAVEIS` pede por omissao: e a
# rota que escolhe, e o duplo tem de saber responder ao que ela pede.
POR_VARIAVEL = {
    "2m_temperature": (WeatherMetric.air_temperature, "degC", 21.68),
    "precipitation_flux": (WeatherMetric.precipitation, "mm", 0.0),
    "solar_radiation_flux": (WeatherMetric.solar_radiation, "W/m2", 313.71),
    "reference_evapotranspiration": (WeatherMetric.reference_evapotranspiration, "mm", 4.2),
}

# O que cada variavel RESUME, reconstruido A MAO como o resto deste duplo.
# Nao e importado de `cds._AGREGACAO_AGERA5` de proposito: um duplo que va
# buscar a tabela de producao nunca discorda dela, e e a discordancia que o
# teste de contrato existe para apanhar.
AGREGACAO_POR_VARIAVEL = {
    "2m_temperature": (AggregationOperator.mean, 24),
    "precipitation_flux": (AggregationOperator.total, 24),
    "solar_radiation_flux": (AggregationOperator.mean, 24),
    "reference_evapotranspiration": (AggregationOperator.total, 24),
}


def test_the_double_answers_every_variable_the_route_asks_for():
    """Guarda sobre o DUPLO, e nao sobre o codigo. Sem ela, acrescentar uma
    variavel a omissao do servico fazia este ficheiro rebentar com um KeyError
    a meio de um teste que fala de outra coisa -- ou, pior, o duplo passava a
    devolver menos variaveis do que a rota pede e a suite deixava de exercitar
    o caminho de varias."""
    assert set(POR_VARIAVEL) == set(VARIAVEIS)

# a estacao real mais proxima de Turcifal, com a distancia medida na Task 4
DOIS_PORTOS = {"station_id": "1210739", "station_name": "Torres Vedras, Dois Portos",
               "lat": 39.04389444, "lon": -9.179, "distance_km": 5.3399}
ESTACAO_NOVA = {"station_id": "1210999", "station_name": "Turcifal (estacao nova)",
                "lat": 39.0373, "lon": -9.2402, "distance_km": 0.4}
INSTANTE_IPMA = "2026-08-20T13:00"
# temperatura e humidade: duas metricas por instante, portanto duas linhas
METRICAS_POR_INSTANTE = 2


def _quadrado(lon: float, lat: float, lado_graus: float = 0.025) -> dict:
    meio = lado_graus / 2
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - meio, lat - meio], [lon + meio, lat - meio],
            [lon + meio, lat + meio], [lon - meio, lat + meio], [lon - meio, lat - meio],
        ]],
    }


def _aoi(session, site_code, aoi_code, status=AoiStatus.approved,
         proveniencia=GeometryProvenance.surveyed):
    site = Site(code=site_code, name=f"Sitio {site_code}")
    aoi = Aoi(
        site=site, code=aoi_code, purpose="earth_observation",
        geometry=geojson_to_wkt_element(_quadrado(TURCIFAL_LON, TURCIFAL_LAT)),
        geometry_provenance=proveniencia, status=status,
        approved_by="site-manager" if status == AoiStatus.approved else None,
    )
    session.add(aoi)
    session.commit()
    return aoi


@pytest.fixture
def sitio(session):
    return _aoi(session, "EUC-TUR-MET-API", "EUC-TUR-MET-API-EO")


@pytest.fixture
def sitio_sem_aoi_aprovada(session):
    return _aoi(session, "EUC-TUR-MET-API-DRAFT", "EUC-TUR-MET-API-DRAFT-EO",
                status=AoiStatus.draft,
                proveniencia=GeometryProvenance.provisional_pending_kml)


# --- duplos dos dois clientes -----------------------------------------------

class _CDSFalso:
    """Devolve a serie ja normalizada, como o `agera5_diario` do cliente real.

    **Honra `variaveis`, e isso nao e detalhe.** Ate 30/08/2026 este duplo
    ignorava o argumento e devolvia sempre so temperatura, enquanto a rota
    pede as variaveis todas por omissao. Era o unico sitio da suite onde o
    caminho de producao passava com mais do que uma variavel, e por isso a
    suite inteira ficava cega a tudo o que dependesse de haver varias -- um
    `break` depois da primeira deixava os 530 testes verdes. E a armadilha da
    "coleccao de um": um duplo que devolve sempre um elemento faz o ciclo que
    o consome correr sempre uma vez.
    """

    def __init__(self, datas=DATAS, datas_por_variavel=None):
        self.datas = tuple(datas)
        # janelas DIFERENTES por variavel, que e o que a origem faz quando o
        # atraso de publicacao nao e igual para todas
        self.datas_por_variavel = dict(datas_por_variavel or {})

    def agera5_diario(self, area, lat_sitio, lon_sitio, date_from, date_to,
                      variaveis=None, timeout_s=900.0):
        variaveis = list(variaveis) if variaveis else ["2m_temperature"]
        caixa, alargada = expandir_area(area)
        cell_lat, cell_lon = CELULA_TURCIFAL
        return [
            {"date": dia, "metric": POR_VARIAVEL[variavel][0],
             "value": POR_VARIAVEL[variavel][2], "unit": POR_VARIAVEL[variavel][1],
             "variable": variavel, "dataset": DATASET_AGERA5,
             "cell_lat": cell_lat, "cell_lon": cell_lon, "cell_size_deg": 0.1,
             "area_original": [float(x) for x in area],
             "area_requested": caixa, "area_expanded": alargada,
             "masked_days_dropped": 0,
             "aggregation": proveniencia_de_agregacao(*AGREGACAO_POR_VARIAVEL[variavel]),
             "source_file": f"{variavel}_AgERA5_{dia.replace('-', '')}_final-v2.0.0.nc"}
            for variavel in variaveis
            for dia in self.datas_por_variavel.get(variavel, self.datas)
        ]


class _CDSSemValor(_CDSFalso):
    """Serie valida com um dia sem valor nenhum: a base recusa a linha.

    E o caminho que substitui um `except IntegrityError` na rota -- a violacao
    de restricao acontece dentro do sincronizador e tem de chegar ao cliente
    como um job `failed`, nao como um 409 de duplicado nem como um 500.
    """

    def agera5_diario(self, *args, **kwargs):
        linhas = super().agera5_diario(*args, **kwargs)
        linhas[-1]["value"] = None
        return linhas


class _CDSQueRebenta:
    def agera5_diario(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao CDS perdida a meio da serie")


class _IPMAFalso:
    """Duplo do IPMAClient, com o tecto do raio aplicado como no cliente real."""

    def __init__(self, instantes=(INSTANTE_IPMA,), estacao=None, descartes=0):
        self.instantes = tuple(instantes)
        self.estacao = dict(estacao or DOIS_PORTOS)
        self.raios_recebidos = []
        # parte do contrato do cliente: `sync_ipma` le daqui quantas leituras
        # de radiacao nocturna foram descartadas, para as gravar no evidence
        self.descartes_por_estacao = {self.estacao["station_id"]: descartes}

    def stations(self):
        return [dict(self.estacao)]

    def nearest_station(self, lat, lon, raio_maximo_km=RAIO_MAXIMO_KM):
        self.raios_recebidos.append(raio_maximo_km)
        if self.estacao["distance_km"] > raio_maximo_km:
            raise ValueError("estacao acima do tecto")
        return dict(self.estacao, stations_considered=len(self.stations()),
                    stations_unreadable=0)

    def observations(self):
        return {instante: {self.estacao["station_id"]:
                           {"temperatura": 24.6, "humidade": 77.0}}
                for instante in self.instantes}


class _IPMAQueRebenta:
    def stations(self):
        raise httpx.ConnectError("ligacao ao IPMA perdida")

    def nearest_station(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao IPMA perdida")

    def observations(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao IPMA perdida")


@pytest.fixture
def api(client):
    """O cliente HTTP com os dois clientes meteorologicos substituidos.

    Devolve `(client, duplos)` para os testes poderem trocar um dos duplos e
    inspeccionar o que ele recebeu.
    """
    duplos = {"cds": _CDSFalso(), "ipma": _IPMAFalso(), "construidos": []}

    def fabrica(qual):
        def construir():
            duplos["construidos"].append(qual)
            return duplos[qual]
        return construir

    # o que a dependencia cede e uma FABRICA, nao um cliente: e o contrato que
    # permite que so nasca o cliente da fonte escolhida. `construidos` regista
    # quais foram mesmo pedidos, e e por ai que se prova que o outro nao nasceu.
    app.dependency_overrides[get_cds_client] = lambda: fabrica("cds")
    app.dependency_overrides[get_ipma_client] = lambda: fabrica("ipma")
    yield client, duplos
    del app.dependency_overrides[get_cds_client]
    del app.dependency_overrides[get_ipma_client]


@pytest.fixture
def api_sem_credenciais_do_cds(client):
    """Nao mexe em `get_cds_client`: e a propria dependencia que tem de decidir
    o que fazer quando as settings nao trazem credenciais do CDS.

    O cliente do IPMA continua substituido, porque a pergunta destes testes e
    "o que acontece ao ramo que NAO precisa da credencial" e nao "consegue-se
    chegar ao IPMA".
    """
    sem = Settings(database_url=get_settings().database_url,
                   cds_api_url=None, cds_api_key=None)
    duplo = _IPMAFalso()
    app.dependency_overrides[get_settings] = lambda: sem
    app.dependency_overrides[get_ipma_client] = lambda: (lambda: duplo)
    yield client
    del app.dependency_overrides[get_settings]
    del app.dependency_overrides[get_ipma_client]


def _url(code: str) -> str:
    return f"/api/v1/sites/{code}/weather/sync"


def _jobs(session) -> int:
    return session.scalar(select(func.count()).select_from(IngestionJob))


def _linhas(session, aoi):
    return session.scalars(
        select(Observation).where(Observation.site_id == aoi.site_id)
        .order_by(Observation.observed_at, Observation.metric)
    ).all()


# --- o caminho normal: 202 com o job, uma fonte de cada vez ------------------

def test_reanalysis_sync_returns_202_with_a_succeeded_job(api, sitio, session):
    cliente, _ = api

    r = cliente.post(_url(sitio.site.code), json={"source": "reanalysis", **JANELA})

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "succeeded"
    assert corpo["job_type"] == JOB_TYPE
    assert corpo["processing_version"] == PROCESSING_VERSION
    # uma linha por variavel e por dia: a rota nao pede uma variavel, pede as
    # de `ingest.VARIAVEIS`. O numero sai da constante e nao de um literal --
    # acrescentar uma variavel ao pedido tem de mexer aqui, e nao passar
    # despercebido.
    assert corpo["rows_written"] == len(DATAS) * len(VARIAVEIS)
    assert corpo["error"] is None
    assert corpo["aoi_id"] == str(sitio.id)
    assert len(_linhas(session, sitio)) == len(DATAS) * len(VARIAVEIS)


def test_ipma_sync_returns_202_with_a_succeeded_job(api, sitio, session):
    cliente, _ = api

    r = cliente.post(_url(sitio.site.code), json={"source": "ipma"})

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "succeeded"
    assert corpo["job_type"] == JOB_TYPE_IPMA
    assert corpo["processing_version"] == PROCESSING_VERSION_IPMA
    assert corpo["rows_written"] == METRICAS_POR_INSTANTE
    assert corpo["error"] is None
    assert len(_linhas(session, sitio)) == METRICAS_POR_INSTANTE


def test_the_source_field_chooses_which_ingestion_runs(api, sitio, session):
    """O campo tem de escolher mesmo. Se a rota ignorasse o `source`, os dois
    pedidos davam o mesmo job e uma das fontes nunca corria -- e as duas series
    coexistem na base precisamente por terem source_type diferentes."""
    cliente, _ = api

    reanalise = cliente.post(_url(sitio.site.code),
                             json={"source": "reanalysis", **JANELA}).json()
    ipma = cliente.post(_url(sitio.site.code), json={"source": "ipma"}).json()

    assert reanalise["job_type"] != ipma["job_type"]
    assert reanalise["request_hash"] != ipma["request_hash"]
    proveniencias = {linha.source_type for linha in _linhas(session, sitio)}
    assert proveniencias == {SourceType.reanalysis, SourceType.weather_observed}


def test_the_ipma_rows_written_through_the_route_carry_the_station_provenance(
    api, sitio, session
):
    """A rota nao pode ser uma porta por onde entram linhas sem proveniencia:
    um valor de estacao a 5 km nao e uma medicao no sitio, e cada linha tem de
    o dizer por si."""
    cliente, _ = api

    cliente.post(_url(sitio.site.code), json={"source": "ipma"})

    linhas = _linhas(session, sitio)
    assert linhas
    for linha in linhas:
        assert linha.source_collection == COLECCAO_IPMA
        assert linha.evidence["station_id"] == DOIS_PORTOS["station_id"]
        assert linha.evidence["measured_at_site"] is False
        assert linha.evidence["distance_km"] > 0
        assert linha.evidence["station_search_radius_km"] == RAIO_MAXIMO_KM
        # os dois campos que o cliente passou a publicar na ronda 2 da Task 4.
        # Estao aqui porque um duplo dessincronizado do cliente real deixa a
        # suite verde e rebenta com KeyError no primeiro sync a serio: o que
        # esta linha exige e que o percurso cliente -> ingest -> evidence esteja
        # inteiro pela rota, e nao so no teste do modulo.
        assert linha.evidence["stations_considered"] == 1
        assert linha.evidence["night_radiation_dropped"] == 0


def test_the_night_radiation_count_reaches_the_row_through_the_route(api, sitio, session):
    """Zero e uma afirmacao; um numero diferente de zero tem de chegar tambem.

    Com o duplo a devolver sempre zero, a assercao acima passava na mesma se o
    servico plantasse um zero de sua lavra em vez de ler o do cliente.
    """
    cliente, duplos = api
    duplos["ipma"] = _IPMAFalso(descartes=7)

    cliente.post(_url(sitio.site.code), json={"source": "ipma"})

    linhas = _linhas(session, sitio)
    assert linhas
    for linha in linhas:
        assert linha.evidence["night_radiation_dropped"] == 7


def test_a_station_change_between_two_requests_fails_instead_of_reporting_success(
    api, sitio, session
):
    """O cenario que so precisa da rota: o mesmo pedido, byte a byte, duas vezes.

    Entre eles o IPMA publica uma estacao mais proxima. As leituras dela caem
    nos mesmos instantes e batem todas na identidade das que ja estao gravadas
    -- a estacao nao entra na identidade nem no `request_hash`. Sem guarda, a
    segunda resposta e `202 succeeded rows_written: 0`, indistinguivel de uma
    reexecucao legitima, e a serie da estacao nova desaparece.
    """
    cliente, duplos = api

    primeiro = cliente.post(_url(sitio.site.code), json={"source": "ipma"}).json()
    assert primeiro["status"] == "succeeded"

    duplos["ipma"] = _IPMAFalso(estacao=ESTACAO_NOVA)
    r = cliente.post(_url(sitio.site.code), json={"source": "ipma"})

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "failed"
    assert DOIS_PORTOS["station_id"] in corpo["error"]
    assert ESTACAO_NOVA["station_id"] in corpo["error"]
    assert {linha.evidence["station_id"] for linha in _linhas(session, sitio)} == {
        DOIS_PORTOS["station_id"]}


# --- recusa ANTES do job: erro HTTP, e nenhum job na base -------------------

@pytest.mark.parametrize("corpo", [{"source": "reanalysis", **JANELA}, {"source": "ipma"}])
def test_an_unknown_site_returns_404_and_leaves_no_job(api, session, corpo):
    cliente, _ = api

    r = cliente.post(_url("NAO-EXISTE"), json=corpo)

    assert r.status_code == 404
    assert _jobs(session) == 0


@pytest.mark.parametrize("corpo", [{"source": "reanalysis", **JANELA}, {"source": "ipma"}])
def test_a_site_without_an_approved_aoi_returns_409_and_leaves_no_job(
    api, sitio_sem_aoi_aprovada, session, corpo
):
    """O sitio existe -- por isso nao e 404 -- mas nao esta em condicoes de ser
    sincronizado: o ponto sai do centroide da AOI aprovada e nao ha nenhuma."""
    cliente, _ = api

    r = cliente.post(_url(sitio_sem_aoi_aprovada.site.code), json=corpo)

    assert r.status_code == 409
    assert "approved" in r.json()["detail"]
    assert _jobs(session) == 0


def test_an_unknown_site_never_builds_a_client(api, session):
    """A guarda corre antes de haver cliente nenhum.

    Um duplo que rebentasse nao provava isto: `sync_ipma` recusa o sitio
    desconhecido em `_sitio_e_aoi_aprovada`, antes de tocar no cliente, portanto
    o teste ficava verde com a guarda da rota apagada. O que se pode medir e
    outra coisa -- a fabrica nunca ser chamada. Com a guarda apagada, a rota
    chega ao ramo e constroi o cliente antes de o sincronizador recusar.
    """
    cliente, duplos = api

    r = cliente.post(_url("NAO-EXISTE"), json={"source": "ipma"})

    assert r.status_code == 404
    assert duplos["construidos"] == []
    assert _jobs(session) == 0


def test_a_request_for_one_source_never_builds_the_other_client(api, sitio):
    """As dependencias do FastAPI resolvem-se todas antes do corpo da rota.

    Com elas a construir os clientes, um pedido `ipma` construia na mesma um
    `CDSClient` que nunca servia para nada -- e fechava-o a seguir, fechando uma
    ligacao que nunca existiu. Cedendo uma fabrica, so nasce o da fonte pedida.
    """
    cliente, duplos = api

    cliente.post(_url(sitio.site.code), json={"source": "ipma"})
    assert duplos["construidos"] == ["ipma"]

    cliente.post(_url(sitio.site.code), json={"source": "reanalysis", **JANELA})
    assert duplos["construidos"] == ["ipma", "cds"]


# --- falha DEPOIS do job: 202 com o status no corpo -------------------------

def test_a_network_failure_returns_202_with_the_job_failed(api, sitio, session):
    """O caso que a distincao inteira existe para servir: o pedido foi aceite e
    processado, portanto 202 -- e o resultado esta no `status`, nao no codigo
    HTTP."""
    cliente, duplos = api
    duplos["cds"] = _CDSQueRebenta()

    r = cliente.post(_url(sitio.site.code), json={"source": "reanalysis", **JANELA})

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "failed"
    assert corpo["rows_written"] == 0
    assert corpo["error"]
    assert "Traceback" not in corpo["error"]
    assert _jobs(session) == 1
    assert _linhas(session, sitio) == []


def test_an_ipma_network_failure_also_returns_202_with_the_job_failed(api, sitio, session):
    cliente, duplos = api
    duplos["ipma"] = _IPMAQueRebenta()

    r = cliente.post(_url(sitio.site.code), json={"source": "ipma"})

    assert r.status_code == 202
    assert r.json()["status"] == "failed"
    assert _jobs(session) == 1
    assert _linhas(session, sitio) == []


def test_a_failed_job_still_declares_the_processing_version_it_tried(api, sitio):
    """Um job que falha nao escreve linha nenhuma, portanto nao ha observacoes
    de onde deduzir a versao. E ainda assim tem de dizer o que tentou correr."""
    cliente, duplos = api
    duplos["cds"] = _CDSQueRebenta()

    corpo = cliente.post(_url(sitio.site.code),
                         json={"source": "reanalysis", **JANELA}).json()

    assert corpo["status"] == "failed"
    assert corpo["processing_version"] == PROCESSING_VERSION


def test_a_row_the_database_refuses_becomes_a_failed_job(prod_client, sitio, session):
    """Uma violacao de restricao nao pode sair como 500 nem como um 409 de
    duplicado. Nao ha `except IntegrityError` nesta rota porque ela nao escreve
    nada por sua mao: a escrita acontece dentro do sincronizador, que faz
    rollback e marca o job. Este teste e o que prova que esse caminho existe --
    sem ele, a ausencia do bloco seria uma suposicao."""
    app.dependency_overrides[get_cds_client] = lambda: (lambda: _CDSSemValor())
    app.dependency_overrides[get_ipma_client] = lambda: (lambda: _IPMAFalso())
    try:
        r = prod_client.post(_url(sitio.site.code),
                             json={"source": "reanalysis", **JANELA})
    finally:
        del app.dependency_overrides[get_cds_client]
        del app.dependency_overrides[get_ipma_client]

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "failed"
    assert "ck_observation_has_a_value" in corpo["error"]
    assert corpo["rows_written"] == 0
    # tudo-ou-nada: as linhas boas que vinham antes da ma tambem nao entram
    assert _linhas(session, sitio) == []


def test_a_second_identical_sync_reports_succeeded_with_nothing_written(
    api, sitio, session
):
    """A desduplicacao vista pela porta de fora: repetir o pedido nao duplica
    linhas e continua a ser sucesso. E o que permite correr isto de hora a hora."""
    cliente, _ = api

    primeiro = cliente.post(_url(sitio.site.code), json={"source": "ipma"}).json()
    segundo = cliente.post(_url(sitio.site.code), json={"source": "ipma"}).json()

    assert primeiro["rows_written"] == METRICAS_POR_INSTANTE
    assert segundo["status"] == "succeeded"
    assert segundo["rows_written"] == 0
    assert len(_linhas(session, sitio)) == METRICAS_POR_INSTANTE


# --- o corpo do pedido: a janela tem de servir a fonte ----------------------

@pytest.mark.parametrize("janela", [
    {"date_from": "2026-07-01", "date_to": "2026-07-03"},
    {"date_from": "2026-07-01"},
    {"date_to": "2026-07-03"},
])
def test_a_window_with_the_ipma_source_is_refused_not_ignored(api, sitio, session, janela):
    """Ignorar a janela em silencio seria mentir ao cliente: ele receberia 202
    com um job cuja janela nao e a que pediu, e ficaria a julgar que tem
    arquivado um periodo que a origem nunca publicou."""
    cliente, _ = api

    r = cliente.post(_url(sitio.site.code), json={"source": "ipma", **janela})

    assert r.status_code == 422
    assert "24 hours" in r.text
    assert _jobs(session) == 0


@pytest.mark.parametrize("janela", [{}, {"date_from": "2026-07-01"}, {"date_to": "2026-07-03"}])
def test_reanalysis_without_a_complete_window_is_refused(api, sitio, session, janela):
    cliente, _ = api

    r = cliente.post(_url(sitio.site.code), json={"source": "reanalysis", **janela})

    assert r.status_code == 422
    assert _jobs(session) == 0


def test_an_inverted_window_is_refused_before_the_job_exists(api, sitio, session):
    """422 e nao um job `failed`: o sincronizador tambem a recusa, mas so
    depois de o job existir, e ficava um rasto de uma execucao que nunca devia
    ter comecado."""
    cliente, _ = api

    r = cliente.post(_url(sitio.site.code),
                     json={"source": "reanalysis", "date_from": "2026-07-03",
                           "date_to": "2026-07-01"})

    assert r.status_code == 422
    assert _jobs(session) == 0


@pytest.mark.parametrize("source", ["era5", "IPMA", "", "weather_observed"])
def test_an_unknown_source_is_refused(api, sitio, session, source):
    """O vocabulario e fechado. `weather_observed` esta na lista de proposito:
    e o `SourceType` da base, e aceita-lo aqui era colar dois vocabularios que
    classificam coisas diferentes."""
    cliente, _ = api

    r = cliente.post(_url(sitio.site.code), json={"source": source, **JANELA})

    assert r.status_code == 422
    assert _jobs(session) == 0


def test_a_request_without_a_source_is_refused(api, sitio, session):
    cliente, _ = api

    r = cliente.post(_url(sitio.site.code), json=JANELA)

    assert r.status_code == 422
    assert _jobs(session) == 0


# --- credenciais: so o ramo que precisa delas e que se recusa ---------------

def test_reanalysis_without_cds_credentials_returns_503_naming_them(
    api_sem_credenciais_do_cds, sitio, session
):
    r = api_sem_credenciais_do_cds.post(_url(sitio.site.code),
                                        json={"source": "reanalysis", **JANELA})

    assert r.status_code == 503
    detalhe = r.json()["detail"]
    assert "cds_api_url" in detalhe
    assert "cds_api_key" in detalhe
    assert _jobs(session) == 0


def test_the_ipma_source_does_not_need_the_cds_credentials(
    api_sem_credenciais_do_cds, sitio, session
):
    """O caso que obriga a dependencia do CDS a nao recusar por si: as
    dependencias resolvem-se todas antes do corpo da rota, e um 503 dentro do
    `get_cds_client` fazia o IPMA -- que nao toca no CDS -- responder 503 por
    falta de uma credencial que nao ia usar."""
    r = api_sem_credenciais_do_cds.post(_url(sitio.site.code), json={"source": "ipma"})

    assert r.status_code == 202
    assert r.json()["status"] == "succeeded"
    assert len(_linhas(session, sitio)) == METRICAS_POR_INSTANTE


def test_the_dependency_builds_a_real_client_when_the_credentials_are_there(client):
    """A dependencia nao pode devolver None sempre: se devolvesse, o ramo da
    reanalise respondia 503 para toda a gente e o teste do 503 acima continuava
    verde. O cliente e construido e fechado sem lhe ser pedido nada: nenhuma
    ligacao chega a ser aberta."""
    com = Settings(database_url=get_settings().database_url,
                   cds_api_url="https://cds.example/api", cds_api_key="segredo")

    fabricas = list(get_cds_client(settings=com))

    assert len(fabricas) == 1
    cliente = fabricas[0]()
    assert isinstance(cliente, CDSClient)
    # a fabrica memoriza: duas chamadas no mesmo pedido nao podem dar dois
    # clientes, senao o segundo ficava por fechar
    assert fabricas[0]() is cliente


def test_the_factory_builds_at_most_one_client_per_request():
    """A fabrica memoriza, e a prova tem de CONTAR construcoes.

    Sem a contagem, uma fabrica que construisse um cliente novo em cada chamada
    e devolvesse sempre o primeiro passava o teste da identidade: os clientes a
    mais nascem, sao fechados no fim, e nada os distingue de fora. O desperdicio
    que este ficheiro existe para eliminar era exactamente esse.
    """
    class _Cliente:
        def __init__(self):
            self.fechado = False

        def close(self):
            self.fechado = True

    construidos = []

    def construir():
        construidos.append(_Cliente())
        return construidos[-1]

    gerador = _fabrica_de_cliente(construir)
    fabrica = next(gerador)
    primeiro, segundo = fabrica(), fabrica()

    assert primeiro is segundo
    assert len(construidos) == 1
    with pytest.raises(StopIteration):
        next(gerador)
    assert primeiro.fechado is True


def test_a_factory_never_called_leaves_nothing_to_close():
    """Adiar a construcao so vale se ninguem a fizer por baixo: uma dependencia
    que construisse na mesma e so escondesse o cliente nao poupava nada."""
    construcoes = []

    gerador = _fabrica_de_cliente(lambda: construcoes.append(1))
    next(gerador)
    with pytest.raises(StopIteration):
        next(gerador)

    assert construcoes == []


def test_a_client_built_by_the_dependency_closes_its_connection():
    """A rota constroi um cliente por pedido HTTP. Sem fechar, cada
    sincronizacao deixava um pool de ligacoes para tras."""
    com = Settings(database_url=get_settings().database_url,
                   cds_api_url="https://cds.example/api", cds_api_key="segredo")
    gerador = get_cds_client(settings=com)
    cliente = next(gerador)()
    assert cliente._client.is_closed is False
    with pytest.raises(StopIteration):
        next(gerador)
    assert cliente._client.is_closed is True


def test_the_ipma_dependency_also_closes_its_connection():
    """O mesmo para o IPMA, e nao por simetria: e o cliente que a Task 4 ja
    teve de ensinar a fechar-se, e uma rota que o constroi por pedido e
    exactamente o consumidor que faz a diferenca notar-se. Sem este teste, a
    dependencia podia deixar de fechar e nada caia."""
    gerador = get_ipma_client()
    cliente = next(gerador)()
    assert cliente._client.is_closed is False
    with pytest.raises(StopIteration):
        next(gerador)
    assert cliente._client.is_closed is True


# --- o job continua a ser lido pela rota que ja existe ----------------------

def test_the_job_created_here_is_readable_by_the_existing_jobs_route(api, sitio):
    """Esta rota nao duplica a leitura: o `GET /jobs/{id}` da Fase B serve os
    jobs meteorologicos tal como serve os de satelite, e tem de dar a mesma
    resposta que o POST devolveu."""
    cliente, _ = api

    criado = cliente.post(_url(sitio.site.code), json={"source": "ipma"}).json()
    lido = cliente.get(f"/api/v1/jobs/{criado['id']}")

    assert lido.status_code == 200
    corpo = lido.json()
    assert corpo["id"] == criado["id"]
    assert corpo["status"] == criado["status"]
    assert corpo["job_type"] == JOB_TYPE_IPMA
    assert corpo["processing_version"] == criado["processing_version"]


def test_a_failed_weather_job_is_readable_by_id_with_its_error(api, sitio):
    cliente, duplos = api
    duplos["cds"] = _CDSQueRebenta()

    criado = cliente.post(_url(sitio.site.code),
                          json={"source": "reanalysis", **JANELA}).json()
    corpo = cliente.get(f"/api/v1/jobs/{criado['id']}").json()

    assert corpo["status"] == JobStatus.failed.value
    # o `assert` do erro vem primeiro: `corpo["error"] == criado["error"]`
    # sozinho passa com `None` dos dois lados, e um job failed sem erro nem
    # sequer cabe na base (ck_failed_job_needs_an_error)
    assert corpo["error"]
    assert corpo["error"] == criado["error"]


def test_the_job_created_by_the_route_is_persisted(api, sitio, session):
    cliente, _ = api

    corpo = cliente.post(_url(sitio.site.code), json={"source": "ipma"}).json()

    gravado = session.get(IngestionJob, uuid.UUID(corpo["id"]))
    assert gravado is not None
    assert gravado.status == JobStatus.succeeded
    assert gravado.job_type == JOB_TYPE_IPMA
