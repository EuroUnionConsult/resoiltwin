from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resoiltwin.config import get_settings
from resoiltwin.db import get_session
from resoiltwin.enums import AoiStatus, GeometryProvenance
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.main import app
from resoiltwin.models import Aoi, Site  # importa tambem os restantes modelos, registados no __init__
from tests.base_de_testes import BaseDeTestes, avisar_das_sobras, bases_de_outras_corridas

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def engine():
    """Uma base de dados so desta corrida, criada aqui e largada no fim.

    O nome sai de `tests/base_de_testes.py` e leva o pid: duas corridas em
    paralelo -- uma ronda de mutacao e um `pytest` local, que e a combinacao
    que ja estragou medicoes neste projecto -- deixaram de partilhar base. Nao
    e preciso exportar variavel nenhuma para isso acontecer.

    O `with` larga a base no `finally`, portanto tambem quando a suite falha:
    uma base por corrida a acumular no servidor era trocar um problema por
    outro.
    """
    origem = get_settings().database_url
    # listadas antes de criarmos a nossa, e por isso todas alheias por
    # construcao. Ficam avisadas, nunca largadas: uma delas pode ser de uma
    # corrida a decorrer agora. Ver bases_de_outras_corridas().
    avisar_das_sobras(bases_de_outras_corridas(origem))
    base = BaseDeTestes(origem)
    with base:
        # o schema e construido pelas MIGRACOES, nao por Base.metadata.create_all.
        # create_all constroi a partir dos modelos, que e o unico caminho que a
        # producao nunca usa: uma migracao partida deixava a suite toda verde e so
        # rebentava na primeira base criada por `alembic upgrade head`. Assim, a
        # suite inteira e tambem um teste das migracoes.
        # (a extensao postgis ja nao e criada aqui: a migracao 0001 fa-lo.)
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.attributes["sqlalchemy_url"] = base.url
        command.upgrade(cfg, "head")

        eng = create_engine(base.url)
        try:
            yield eng
        finally:
            # sem isto, o pool desta engine fica com ligacoes abertas e o DROP
            # tem de as terminar a forca; dispor primeiro e o caminho limpo.
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
