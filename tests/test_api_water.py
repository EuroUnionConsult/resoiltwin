"""A porta de fora do balanco hidrico: o que sai, e com que codigo.

Nenhum teste toca a rede, e nenhum precisa de duplo nenhum. Ao contrario da
meteorologia, esta camada nao tem cliente: le as entradas **da base**, e o que
aqui se monta sao linhas de observacao reais, escritas pela suite.

Tres coisas ficam presas aqui, e nenhuma se ve olhando so para o codigo HTTP:

1. **A recusa ANTES da execucao e um erro HTTP e nao deixa job nenhum**, e as
   tres formas dela nao se confundem: o corpo que nao se aguenta e 422, o sitio
   que nao existe e 404, o sitio sem AOI aprovada e 409.
2. **A falha DEPOIS do job existir e um 202 com o `status` no corpo.** Um
   cliente que receba 202 e assuma sucesso perde uma falha de ingestao -- e este
   ficheiro tem o teste que o prova, com o job em `failed`, zero linhas escritas
   e a serie que faltava nomeada no `error`.
3. **A capacidade utilizavel chega pelo CORPO do pedido** e vai ate a identidade
   e ao `evidence` da linha. Ninguem a mediu nestes solos e e ela que domina o
   resultado: uma rota que a ignorasse e usasse um numero seu decidia em
   silencio o que sai de todas as corridas.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, QualityFlag, SourceType, ValueQualifier,
)
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.models import Aoi, IngestionJob, Observation, Site

TURCIFAL_LON, TURCIFAL_LAT = -9.240247, 39.037317

# escritos POR EXTENSO e nao importados do codigo de producao: um teste que
# compare a constante consigo propria continua verde no dia em que ela mudar de
# valor por engano.
PRECIPITACAO = "precipitation"
ET0 = "reference_evapotranspiration"
AGUA_NO_SOLO = "soil_available_water"
TIPO_DE_JOB = "water_balance_sync"
VERSAO_REANALISE = "agera5-v2_0"

# a capacidade que a maioria destes testes envia no corpo. Nao e uma omissao do
# codigo -- nao ha nenhuma -- e cada teste que precise de outra escreve-a.
CAPACIDADE = 100.0

INICIO, FIM = "2026-07-01", "2026-07-05"
DIAS = 5


def _quadrado(lon: float, lat: float, lado_graus: float = 0.025) -> dict:
    meio = lado_graus / 2
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - meio, lat - meio], [lon + meio, lat - meio],
            [lon + meio, lat + meio], [lon - meio, lat + meio], [lon - meio, lat - meio],
        ]],
    }


def _sitio(session, site_code, aoi_code, status=AoiStatus.approved):
    site = Site(code=site_code, name=f"Sitio {site_code}")
    aoi = Aoi(
        site=site, code=aoi_code, purpose="earth_observation",
        geometry=geojson_to_wkt_element(_quadrado(TURCIFAL_LON, TURCIFAL_LAT)),
        geometry_provenance=(
            GeometryProvenance.surveyed if status == AoiStatus.approved
            else GeometryProvenance.provisional_pending_kml
        ),
        status=status,
        approved_by="site-manager" if status == AoiStatus.approved else None,
    )
    session.add(aoi)
    session.commit()
    return site


@pytest.fixture
def sitio(session):
    return _sitio(session, "EUC-TUR-BAL-API", "EUC-TUR-BAL-API-EO")


@pytest.fixture
def sitio_sem_aoi_aprovada(session):
    return _sitio(session, "EUC-TUR-BAL-API-DRAFT", "EUC-TUR-BAL-API-DRAFT-EO",
                  status=AoiStatus.draft)


def _entrada(session, sitio, dia, metrica, valor):
    """Uma linha de entrada tal como a Fase C a grava."""
    session.add(Observation(
        site_id=sitio.id, plot_id=None,
        observed_at=datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc),
        metric=metrica, unit="mm", value_numeric=valor,
        value_qualifier=ValueQualifier.exact, source_type=SourceType.reanalysis,
        quality_flag=QualityFlag.valid, source_collection="agera5-daily",
        processing_version=VERSAO_REANALISE,
        evidence={"escrito_por": "tests/test_api_water.py"},
    ))
    session.commit()


def _serie(session, sitio, inicio=date(2026, 7, 1), dias=DIAS, precipitacao=0.0, et0=30.0,
           metricas=(PRECIPITACAO, ET0)):
    """`dias` dias contiguos das metricas pedidas, todas de reanalise.

    `metricas` existe para poder montar uma janela **incompleta** -- so chuva,
    ou so ET0 -- que e o caminho que faz o job falhar depois de existir.
    """
    valores = {PRECIPITACAO: precipitacao, ET0: et0}
    for i in range(dias):
        dia = inicio + timedelta(days=i)
        for metrica in metricas:
            _entrada(session, sitio, dia, metrica, valores[metrica])


def _url(code: str) -> str:
    return f"/api/v1/sites/{code}/water/sync"


def _corpo(capacidade=CAPACIDADE, inicio=INICIO, fim=FIM) -> dict:
    return {"date_from": inicio, "date_to": fim,
            "available_water_capacity_mm": capacidade}


def _jobs(session) -> int:
    return session.scalar(select(func.count()).select_from(IngestionJob))


def _linhas_de_agua(session, sitio):
    return list(session.scalars(
        select(Observation)
        .where(Observation.site_id == sitio.id, Observation.metric == AGUA_NO_SOLO)
        .order_by(Observation.observed_at, Observation.processing_version)
    ))


# --- o caminho normal: 202 com o job ----------------------------------------

def test_the_route_returns_202_with_a_succeeded_job_and_the_simulated_series(
    client, sitio, session
):
    _serie(session, sitio)

    r = client.post(_url(sitio.code), json=_corpo())

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "succeeded"
    assert corpo["job_type"] == TIPO_DE_JOB
    assert corpo["rows_written"] == DIAS
    assert corpo["error"] is None
    linhas = _linhas_de_agua(session, sitio)
    assert len(linhas) == DIAS
    # um balanco nunca passa por medicao, e e o `source_type` que o diz
    assert {linha.source_type for linha in linhas} == {SourceType.simulated}


def test_the_job_declares_the_window_it_balanced_and_not_a_wider_one(client, sitio, session):
    """As entradas cobrem tres dos cinco dias pedidos. O job tem de declarar os
    tres: declarar cinco era afirmar uma cobertura que a serie desmente, com
    `succeeded` e `error: null` a dar-lhe ar de verdade."""
    _serie(session, sitio, dias=3)

    corpo = client.post(_url(sitio.code), json=_corpo()).json()

    assert corpo["status"] == "succeeded"
    assert corpo["rows_written"] == 3
    assert corpo["date_from"] == "2026-07-01"
    assert corpo["date_to"] == "2026-07-03"


def test_the_days_the_reservoir_is_still_undetermined_come_out_as_a_range(
    client, sitio, session
):
    """O estado inicial do reservatorio nao e conhecido, e a rota nao o inventa
    pelo caminho: enquanto as duas trajectorias extremas nao se encontram, a
    linha e um intervalo. Com 100 mm de capacidade e 30 mm/dia de procura, elas
    encontram-se ao quarto dia -- portanto a serie tem das duas formas, e uma
    rota que colapsasse tudo para um escalar ficava aqui."""
    _serie(session, sitio)

    client.post(_url(sitio.code), json=_corpo())

    linhas = _linhas_de_agua(session, sitio)
    qualificadores = [linha.value_qualifier for linha in linhas]
    assert qualificadores[0] == ValueQualifier.range
    assert linhas[0].value_numeric is None
    assert linhas[0].value_min is not None and linhas[0].value_max is not None
    assert ValueQualifier.exact in qualificadores
    assert linhas[-1].value_qualifier == ValueQualifier.exact


# --- a capacidade chega pelo CORPO do pedido --------------------------------

def test_the_capacity_travels_from_the_request_body_into_the_row(client, sitio, session):
    """Um numero que nao esta em constante nenhuma do codigo: se a rota usasse
    uma capacidade sua e ignorasse o corpo, ele nao aparecia aqui."""
    _serie(session, sitio)

    corpo = client.post(_url(sitio.code), json=_corpo(capacidade=137.5)).json()

    assert corpo["processing_version"].endswith("+awc137.5mm")
    linhas = _linhas_de_agua(session, sitio)
    assert {linha.evidence["available_water_capacity_mm"] for linha in linhas} == {137.5}
    # e continua a dizer, ao lado do numero, que ninguem o mediu
    assert {linha.evidence["capacity_is_measured"] for linha in linhas} == {False}


def test_two_capacities_asked_through_the_route_are_two_series_side_by_side(
    client, sitio, session
):
    """A capacidade domina o resultado e entra na identidade da linha. Se so
    viajasse no `evidence`, a segunda corrida batia na identidade da primeira,
    escrevia zero linhas e respondia `succeeded` -- e a serie da segunda
    capacidade nunca tinha existido."""
    _serie(session, sitio)

    primeiro = client.post(_url(sitio.code), json=_corpo(capacidade=100)).json()
    segundo = client.post(_url(sitio.code), json=_corpo(capacidade=250)).json()

    assert primeiro["rows_written"] == DIAS
    assert segundo["status"] == "succeeded"
    assert segundo["rows_written"] == DIAS
    assert primeiro["processing_version"] != segundo["processing_version"]
    assert len(_linhas_de_agua(session, sitio)) == 2 * DIAS


def test_a_second_identical_request_writes_nothing_and_still_succeeds(client, sitio, session):
    """A desduplicacao vista pela porta de fora: repetir o mesmo pedido nao
    duplica linhas e continua a ser sucesso."""
    _serie(session, sitio)

    primeiro = client.post(_url(sitio.code), json=_corpo()).json()
    segundo = client.post(_url(sitio.code), json=_corpo()).json()

    assert primeiro["rows_written"] == DIAS
    assert segundo["status"] == "succeeded"
    assert segundo["rows_written"] == 0
    assert len(_linhas_de_agua(session, sitio)) == DIAS


# --- recusa ANTES do job: erro HTTP, e nenhum job na base -------------------

def test_an_unknown_site_returns_404_and_leaves_no_job(client, session):
    r = client.post(_url("NAO-EXISTE"), json=_corpo())

    assert r.status_code == 404
    assert _jobs(session) == 0


def test_a_site_without_an_approved_aoi_returns_409_and_leaves_no_job(
    client, sitio_sem_aoi_aprovada, session
):
    """O sitio existe -- por isso nao e 404 -- mas nao esta em condicoes de ser
    balancado: a AOI e de onde sai a geometria e nao ha nenhuma aprovada."""
    _serie(session, sitio_sem_aoi_aprovada)

    r = client.post(_url(sitio_sem_aoi_aprovada.code), json=_corpo())

    assert r.status_code == 409
    assert "approved" in r.json()["detail"]
    assert _jobs(session) == 0


def test_an_inverted_window_is_refused_before_the_job_exists(client, sitio, session):
    _serie(session, sitio)

    r = client.post(_url(sitio.code), json=_corpo(inicio="2026-07-05", fim="2026-07-01"))

    assert r.status_code == 422
    assert _jobs(session) == 0
    assert _linhas_de_agua(session, sitio) == []


def test_a_request_without_a_capacity_is_refused(client, sitio, session):
    """**A capacidade nao pode ganhar um valor por omissao.** Ninguem a mediu
    nestes solos e e ela que domina o resultado: uma omissao aqui era um numero
    inventado a decidir em silencio o que sai de todas as corridas de quem nao a
    escrever, com o `evidence` a dar-lhe ar de escolha deliberada."""
    _serie(session, sitio)

    r = client.post(_url(sitio.code), json={"date_from": INICIO, "date_to": FIM})

    assert r.status_code == 422
    assert "available_water_capacity_mm" in r.text
    assert _jobs(session) == 0
    assert _linhas_de_agua(session, sitio) == []


@pytest.mark.parametrize("capacidade", [0, -50.0])
def test_a_capacity_that_is_not_a_reservoir_is_refused_before_the_job_exists(
    client, sitio, session, capacidade
):
    """Um reservatorio de zero mm nao e um reservatorio, e um de -50 mm e
    aritmetica sem sentido. A regra e a do modelo, chamada no corpo do pedido:
    e uma propriedade do pedido, decidivel sem tocar na base, e por isso sai
    como 422 e nao como um 409 que diria que o problema estava no sitio."""
    _serie(session, sitio)

    r = client.post(_url(sitio.code), json=_corpo(capacidade=capacidade))

    assert r.status_code == 422
    assert _jobs(session) == 0
    assert _linhas_de_agua(session, sitio) == []


# --- falha DEPOIS do job: 202 com o status no corpo -------------------------

def test_no_input_series_at_all_returns_202_with_the_job_failed(client, sitio, session):
    """⭐ O teste que a distincao inteira existe para servir.

    O sitio existe, a AOI esta aprovada, o corpo do pedido esta bem formado --
    portanto o pedido foi aceite e processado, e isso e 202. Mas nao ha uma
    unica linha de entrada na janela, e o balanco **nao pode acontecer**. O que
    nao pode acontecer e um job `succeeded` com zero linhas escritas: quem
    lesse so o codigo HTTP concluia que a serie ficou gravada.
    """
    r = client.post(_url(sitio.code), json=_corpo())

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "failed"
    assert corpo["rows_written"] == 0
    assert corpo["error"]
    # o erro nomeia a serie que faltou, senao quem opera tem de adivinhar qual
    assert PRECIPITACAO in corpo["error"]
    assert "Traceback" not in corpo["error"]
    assert _jobs(session) == 1
    assert _linhas_de_agua(session, sitio) == []


def test_a_window_with_rain_but_without_et0_also_fails_instead_of_being_balanced(
    client, sitio, session
):
    """Metade das entradas nao e meia serie: tratar a ET0 em falta como zero era
    afirmar que nao houve procura de agua nenhuma em dias que ninguem observou.
    E a ET0 e a entrada que **domina** o resultado."""
    _serie(session, sitio, metricas=(PRECIPITACAO,))

    r = client.post(_url(sitio.code), json=_corpo())

    assert r.status_code == 202
    corpo = r.json()
    assert corpo["status"] == "failed"
    assert corpo["rows_written"] == 0
    assert ET0 in corpo["error"]
    assert _linhas_de_agua(session, sitio) == []


def test_a_failed_job_still_declares_the_capacity_it_tried_to_use(client, sitio):
    """Um job que falha nao escreve linha nenhuma, portanto nao ha observacoes de
    onde deduzir com que capacidade a corrida foi tentada. E ainda assim tem de
    o dizer -- senao duas tentativas falhadas com capacidades diferentes sao
    indistinguiveis depois do facto."""
    corpo = client.post(_url(sitio.code), json=_corpo(capacidade=250)).json()

    assert corpo["status"] == "failed"
    assert corpo["processing_version"].endswith("+awc250mm")


def test_the_job_the_route_created_is_readable_by_the_existing_jobs_route(client, sitio, session):
    """Esta rota nao duplica a leitura do job: escreve na mesma tabela que a
    Fase B ja publica."""
    _serie(session, sitio)

    criado = client.post(_url(sitio.code), json=_corpo()).json()
    lido = client.get(f"/api/v1/jobs/{criado['id']}")

    assert lido.status_code == 200
    assert lido.json()["id"] == criado["id"]
    assert lido.json()["job_type"] == TIPO_DE_JOB
    assert lido.json()["status"] == "succeeded"


def test_a_failed_water_job_is_readable_by_id_with_its_error(client, sitio):
    """Um 202 com o job falhado tambem fica na base: quem so guardou o id ainda
    consegue descobrir o que correu mal."""
    criado = client.post(_url(sitio.code), json=_corpo()).json()

    lido = client.get(f"/api/v1/jobs/{criado['id']}").json()

    assert lido["status"] == "failed"
    assert lido["error"]
