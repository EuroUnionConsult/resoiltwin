from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from resoiltwin.config import get_settings
from resoiltwin.db import get_session
from resoiltwin.enums import AoiStatus, GeometryProvenance
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.main import app
from resoiltwin.models import Aoi, Site  # importa tambem os restantes modelos, registados no __init__

# nota: nao usar .replace("/resoiltwin", ...) aqui - a url tem "//resoiltwin"
# no protocolo+utilizador, e um replace ingenuo tambem troca o username.
# substituir apenas o ultimo segmento do path (o nome da base de dados).
TEST_DB_URL = get_settings().database_url.rsplit("/", 1)[0] + "/resoiltwin_test"

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def engine():
    admin = create_engine(get_settings().database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS resoiltwin_test"))
        conn.execute(text("CREATE DATABASE resoiltwin_test"))
    admin.dispose()

    # o schema e construido pelas MIGRACOES, nao por Base.metadata.create_all.
    # create_all constroi a partir dos modelos, que e o unico caminho que a
    # producao nunca usa: uma migracao partida deixava a suite toda verde e so
    # rebentava na primeira base criada por `alembic upgrade head`. Assim, a
    # suite inteira e tambem um teste das quatro migracoes.
    # (a extensao postgis ja nao e criada aqui: a migracao 0001 fa-lo.)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["sqlalchemy_url"] = TEST_DB_URL
    command.upgrade(cfg, "head")

    eng = create_engine(TEST_DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    # ligacao dedicada com transaccao externa: mesmo que o codigo de producao
    # (rotas da api) chame session.commit(), isso so liberta um savepoint
    # interno - a transaccao externa e sempre revertida no fim do teste.
    # sem isto, um commit real feito por uma rota partilha estado entre
    # testes de ficheiros diferentes (visto na colisao do codigo EUC-TUR-01
    # entre test_api_sites.py e test_models_site.py).
    connection = engine.connect()
    outer = connection.begin()
    Session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    s = Session()
    yield s
    s.close()
    outer.rollback()
    connection.close()


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def prod_client(session):
    """Cliente que se comporta como a producao: uma excepcao nao tratada sai
    como 500 em vez de subir para dentro do teste.

    Com o TestClient por omissao, um erro do servidor rebenta como excepcao
    Python e o teste falha com um traceback -- o que esconde a distincao entre
    "recusado com 422" e "explodiu com 500", que e precisamente a distincao que
    os achados desta ronda sao sobre.
    """
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


_AOI_APROVADA_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [-9.24034, 39.03725], [-9.24016, 39.03725],
        [-9.24016, 39.03739], [-9.24034, 39.03739], [-9.24034, 39.03725],
    ]],
}


@pytest.fixture
def aoi_aprovada(session):
    """AOI approved, com proveniencia surveyed: a que um job de ingestao pode
    usar sem violar ck_aoi_provisional_never_approved."""
    site = Site(code="EUC-TUR-JOB", name="Turcifal job de ingestao")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO-JOB", purpose="earth_observation",
        geometry=geojson_to_wkt_element(_AOI_APROVADA_SQUARE),
        geometry_provenance=GeometryProvenance.surveyed,
        status=AoiStatus.approved, approved_by="site-manager",
    )
    session.add(aoi)
    session.commit()
    return aoi
