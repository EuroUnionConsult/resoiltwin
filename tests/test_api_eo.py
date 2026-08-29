import uuid

import httpx
import pytest
from sqlalchemy import select

from resoiltwin.api.eo import get_cdse_client
from resoiltwin.config import Settings, get_settings
from resoiltwin.enums import AoiStatus, GeometryProvenance, JobStatus
from resoiltwin.eo.cdse import CDSEClient
from resoiltwin.eo.evalscripts import (
    EVALSCRIPT_VERSION,
    EVALSCRIPT_VERSION_SCL,
    NDVI_NDMI_NDRE,
    NDVI_NDMI_NDRE_SCL,
    evalscript_hash,
)
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.main import app
from resoiltwin.models import Aoi, IngestionJob, Observation, Site

_QUADRADO = {
    "type": "Polygon",
    "coordinates": [[
        [-9.2547, 39.0261], [-9.2258, 39.0261],
        [-9.2258, 39.0485], [-9.2547, 39.0485], [-9.2547, 39.0261],
    ]],
}


def _corpo_estatisticas():
    """Resposta minima da Statistical API, uma unica aquisicao valida."""
    bloco = {"stats": {"mean": 0.4, "sampleCount": 100, "noDataCount": 0}}
    return {"data": [
        {"interval": {"from": "2026-08-11T00:00:00Z"},
         "outputs": {"ndvi": {"bands": {"B0": bloco}}, "ndmi": {"bands": {"B0": bloco}},
                     "ndre": {"bands": {"B0": bloco}}}},
    ]}


def _cliente_ok():
    """CDSEClient real sobre MockTransport: nenhum teste toca a rede."""
    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        return httpx.Response(200, json=_corpo_estatisticas())
    return CDSEClient("id", "segredo", transport=httpx.MockTransport(handler))


class _ClienteQueRebenta:
    """Falha de rede a meio da execucao: o job tem de ficar failed, nao 500."""

    def statistics(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao CDSE perdida a meio da serie")


@pytest.fixture
def outro_site(session):
    """Um segundo site, sem nenhuma AOI propria: serve para provar que uma
    AOI de outro site nao pode ser sincronizada por aqui."""
    site = Site(code="EUC-TUR-OUTRO", name="Turcifal outro site")
    session.add(site)
    session.commit()
    return site


@pytest.fixture
def aoi_rascunho(session):
    site = Site(code="EUC-TUR-API-DRAFT", name="Turcifal por confirmar (api)")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO-API-DRAFT", purpose="earth_observation",
        geometry=geojson_to_wkt_element(_QUADRADO),
        geometry_provenance=GeometryProvenance.provisional_pending_kml,
        status=AoiStatus.draft,
    )
    session.add(aoi)
    session.commit()
    return aoi


@pytest.fixture
def client_com_cdse_ok(client):
    """O cliente `client` do conftest, com o CDSEClient trocado por um
    duplo sobre MockTransport -- nenhum teste desta suite toca a rede."""
    app.dependency_overrides[get_cdse_client] = _cliente_ok
    yield client
    del app.dependency_overrides[get_cdse_client]


@pytest.fixture
def client_com_cdse_que_rebenta(client):
    app.dependency_overrides[get_cdse_client] = _ClienteQueRebenta
    yield client
    del app.dependency_overrides[get_cdse_client]


@pytest.fixture
def client_sem_credenciais(client):
    """Nao mexe em get_cdse_client: e a propria dependencia que tem de
    recusar quando as settings nao trazem credenciais."""
    sem_credenciais = Settings(
        database_url=get_settings().database_url,
        cdse_client_id=None, cdse_client_secret=None,
    )
    app.dependency_overrides[get_settings] = lambda: sem_credenciais
    yield client
    del app.dependency_overrides[get_settings]


def _corpo_sync(aoi_code, date_from="2026-08-01", date_to="2026-08-28", **extra):
    """O corpo minimo. `extra` serve para os campos opcionais -- o scl_mask e
    opcional de proposito, e ausencia tem de significar "com mascara"."""
    return {"aoi_code": aoi_code, "date_from": date_from, "date_to": date_to, **extra}


def _versoes_gravadas(session, aoi):
    """As processing_version que a rota deixou na base para este sitio.

    O job passou a declarar a sua versao, mas isso e o que o servico AFIRMA;
    isto e o que a base tem. Os dois numeros continuam a valer separadamente,
    e ha um teste abaixo a exigir que coincidam.
    """
    return {
        linha.processing_version
        for linha in session.scalars(
            select(Observation).where(Observation.site_id == aoi.site_id)
        ).all()
    }


# --- POST /sites/{code}/eo/sync ---------------------------------------------

def test_sync_over_approved_aoi_returns_202_with_job(client_com_cdse_ok, aoi_aprovada):
    r = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["aoi_id"] == str(aoi_aprovada.id)
    assert body["rows_written"] == 3
    assert body["error"] is None
    assert "id" in body and "request_hash" in body


def test_sync_over_draft_aoi_returns_409_mentioning_approval(client_com_cdse_ok, aoi_rascunho):
    r = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_rascunho.site.code}/eo/sync", json=_corpo_sync(aoi_rascunho.code)
    )
    assert r.status_code == 409
    assert "approved" in r.json()["detail"]


def test_sync_over_unknown_aoi_returns_404(client_com_cdse_ok, aoi_aprovada):
    r = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync("NAO-EXISTE")
    )
    assert r.status_code == 404


def test_sync_over_unknown_site_returns_404(client_com_cdse_ok, aoi_aprovada):
    r = client_com_cdse_ok.post(
        "/api/v1/sites/NAO-EXISTE/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    )
    assert r.status_code == 404


def test_sync_with_aoi_belonging_to_another_site_returns_404(
    client_com_cdse_ok, aoi_aprovada, outro_site
):
    """A AOI existe, so que noutro site: a rota tem de se comportar como se
    nao existisse aqui, sem confirmar a um cliente que o codigo existe algures."""
    r = client_com_cdse_ok.post(
        f"/api/v1/sites/{outro_site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    )
    assert r.status_code == 404


def test_network_failure_returns_202_with_failed_status_not_a_traceback(
    client_com_cdse_que_rebenta, aoi_aprovada
):
    r = client_com_cdse_que_rebenta.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]
    assert "Traceback" not in body["error"]
    assert body["rows_written"] == 0


def test_missing_credentials_does_not_return_500(client_sem_credenciais, aoi_aprovada):
    r = client_sem_credenciais.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    )
    assert r.status_code != 500
    detalhe = r.json()["detail"]
    assert "cdse_client_id" in detalhe
    assert "cdse_client_secret" in detalhe


# --- GET /jobs/{id} ----------------------------------------------------------

def test_get_existing_job_returns_200_with_state(client_com_cdse_ok, aoi_aprovada):
    criado = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    ).json()

    r = client_com_cdse_ok.get(f"/api/v1/jobs/{criado['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["rows_written"] == 3
    assert body["error"] is None


def test_get_unknown_job_uuid_returns_404(client_com_cdse_ok):
    r = client_com_cdse_ok.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert r.status_code == 404


def test_get_job_with_non_uuid_id_returns_422(client_com_cdse_ok):
    r = client_com_cdse_ok.get("/api/v1/jobs/nao-e-um-uuid")
    assert r.status_code == 422


# --- persistencia: o job devolvido pela rota e o mesmo que fica gravado ------

def test_job_created_by_the_route_is_persisted(client_com_cdse_ok, aoi_aprovada, session):
    body = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    ).json()
    gravado = session.get(IngestionJob, uuid.UUID(body["id"]))
    assert gravado is not None
    assert gravado.status == JobStatus.succeeded


# --- escolha do evalscript pela rota ----------------------------------------

def test_sync_without_scl_mask_field_uses_the_mask(client_com_cdse_ok, aoi_aprovada, session):
    """Ausencia do campo e o caminho normal: quem nao escolher tem de ficar
    com o comportamento correcto, nao com o antigo."""
    r = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    )

    assert r.status_code == 202
    assert r.json()["status"] == "succeeded"
    assert _versoes_gravadas(session, aoi_aprovada) == {
        f"{EVALSCRIPT_VERSION_SCL}+{evalscript_hash(NDVI_NDMI_NDRE_SCL)}"
    }


def test_sync_with_scl_mask_false_produces_a_v1_job(client_com_cdse_ok, aoi_aprovada, session):
    """O v1 fica acessivel pela rota para reproduzir o que ja esta gravado."""
    r = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync",
        json=_corpo_sync(aoi_aprovada.code, scl_mask=False),
    )

    assert r.status_code == 202
    assert r.json()["status"] == "succeeded"
    assert _versoes_gravadas(session, aoi_aprovada) == {
        f"{EVALSCRIPT_VERSION}+{evalscript_hash(NDVI_NDMI_NDRE)}"
    }


def test_the_two_choices_produce_different_jobs_over_the_same_window(
    client_com_cdse_ok, aoi_aprovada, session
):
    """Mesma AOI, mesma janela, escolhas diferentes: dois jobs distintos e as
    duas series a coexistirem. Se a rota ignorasse o campo, os dois pedidos
    davam o mesmo request_hash e o segundo nao escrevia nada."""
    url = f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync"
    com = client_com_cdse_ok.post(url, json=_corpo_sync(aoi_aprovada.code)).json()
    sem = client_com_cdse_ok.post(
        url, json=_corpo_sync(aoi_aprovada.code, scl_mask=False)
    ).json()

    assert com["request_hash"] != sem["request_hash"]
    assert com["rows_written"] == 3
    assert sem["rows_written"] == 3
    assert _versoes_gravadas(session, aoi_aprovada) == {
        f"{EVALSCRIPT_VERSION_SCL}+{evalscript_hash(NDVI_NDMI_NDRE_SCL)}",
        f"{EVALSCRIPT_VERSION}+{evalscript_hash(NDVI_NDMI_NDRE)}",
    }


# --- a versao de processamento e legivel pela rota -------------------------

def test_job_declares_the_processing_version_it_ran_with(
    client_com_cdse_ok, aoi_aprovada, session
):
    """Pela rota, sem ir a tabela de observacoes, tem de ser possivel dizer se
    um job aplicou a mascara ao pixel. E a versao que o job declara tem de ser
    a mesma que ficou nas linhas que ele escreveu -- se divergissem, uma das
    duas estaria a mentir sobre como os numeros foram produzidos."""
    esperada = f"{EVALSCRIPT_VERSION_SCL}+{evalscript_hash(NDVI_NDMI_NDRE_SCL)}"

    body = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    ).json()

    assert body["processing_version"] == esperada
    assert _versoes_gravadas(session, aoi_aprovada) == {esperada}


def test_the_two_choices_are_distinguishable_by_the_route_alone(
    client_com_cdse_ok, aoi_aprovada
):
    """O ponto do campo: mascarado e nao mascarado tem de ser distinguiveis
    sem consultar mais nada. O request_hash difere nos dois casos, mas e um
    digest -- nao se le, so se compara."""
    url = f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync"
    com = client_com_cdse_ok.post(url, json=_corpo_sync(aoi_aprovada.code)).json()
    sem = client_com_cdse_ok.post(
        url, json=_corpo_sync(aoi_aprovada.code, scl_mask=False)
    ).json()

    assert com["processing_version"] == (
        f"{EVALSCRIPT_VERSION_SCL}+{evalscript_hash(NDVI_NDMI_NDRE_SCL)}"
    )
    assert sem["processing_version"] == f"{EVALSCRIPT_VERSION}+{evalscript_hash(NDVI_NDMI_NDRE)}"


def test_failed_job_still_declares_its_processing_version(
    client_com_cdse_que_rebenta, aoi_aprovada
):
    """O caso que justifica gravar a versao no job e nao a deduzir das
    observacoes: um job que falha nao escreve linha nenhuma, portanto nao ha
    observacoes de onde a ler. E ainda assim tem de dizer o que tentou correr."""
    body = client_com_cdse_que_rebenta.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    ).json()

    assert body["status"] == "failed"
    assert body["rows_written"] == 0
    assert body["processing_version"] == (
        f"{EVALSCRIPT_VERSION_SCL}+{evalscript_hash(NDVI_NDMI_NDRE_SCL)}"
    )


def test_job_read_by_id_carries_the_same_processing_version(client_com_cdse_ok, aoi_aprovada):
    """O GET /jobs/{id} le da base, o POST devolve o objecto em memoria: os
    dois caminhos tem de dar a mesma resposta."""
    criado = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync", json=_corpo_sync(aoi_aprovada.code)
    ).json()

    lido = client_com_cdse_ok.get(f"/api/v1/jobs/{criado['id']}").json()
    assert lido["processing_version"] == criado["processing_version"]


def test_scl_mask_with_a_non_boolean_value_is_refused(client_com_cdse_ok, aoi_aprovada):
    """Recusar com 422 e melhor do que aceitar uma string e trata-la como
    verdadeira: um "false" a passar por True escolhia o script errado sem
    ninguem dar por isso."""
    r = client_com_cdse_ok.post(
        f"/api/v1/sites/{aoi_aprovada.site.code}/eo/sync",
        json=_corpo_sync(aoi_aprovada.code, scl_mask="talvez"),
    )
    assert r.status_code == 422
