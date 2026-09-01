import base64
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resoiltwin.api.auth import NOME_DO_CABECALHO
from resoiltwin.config import get_settings
from resoiltwin.db import get_session
from resoiltwin.enums import AoiStatus, GeometryProvenance
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.main import app
from resoiltwin.models import Aoi, Site  # importa tambem os restantes modelos, registados no __init__
from tests.base_de_testes import base_para_esta_corrida

ROOT = Path(__file__).resolve().parent.parent

# Marcador de posicao, nao um segredo: e o valor que esta suite mete no
# ambiente para que as rotas de escrita tenham chave contra que conferir. Nao
# vale nada em lado nenhum, e o nome di-lo para que ninguem o copie para um
# `.env` a pensar que e uma chave.
CHAVE_DE_ESCRITA_DOS_TESTES = "marcador-de-posicao-so-desta-suite-nao-e-um-segredo"

# O par que abre a porta da consola durante a corrida. Marcadores de posicao
# pela mesma razao, e com o nome a diz-lo para que ninguem os copie para um
# `.env` a pensar que sao credenciais.
UTILIZADOR_DA_CONSOLA_DOS_TESTES = "utilizador-de-posicao-so-desta-suite"
SENHA_DA_CONSOLA_DOS_TESTES = "marcador-de-posicao-da-senha-da-consola-nao-e-um-segredo"


def cabecalho_da_consola(
    utilizador: str = UTILIZADOR_DA_CONSOLA_DOS_TESTES,
    senha: str = SENHA_DA_CONSOLA_DOS_TESTES,
) -> dict[str, str]:
    """O `Authorization` de um par, montado a mao.

    A mao e nao pelo `auth=` do `httpx`: os testes da guarda precisam de mandar
    pares que nenhum cliente montaria -- um esquema errado, um base64 partido,
    um par sem `:` --, e um so caminho para construir o cabecalho e o que faz
    com que o caso normal e os casos torcidos passem pelo mesmo sitio.
    """
    par = f"{utilizador}:{senha}".encode()
    return {"Authorization": "Basic " + base64.b64encode(par).decode("ascii")}


@pytest.fixture(scope="session", autouse=True)
def chave_de_escrita_configurada():
    """Poe uma chave de escrita no ambiente durante toda a corrida.

    Sem isto, as oito rotas que escrevem responderiam 503 -- a recusa de quem
    nao tem chave configurada -- e nenhum dos testes de escrita que ja existiam
    passaria. Nao e um atalho a volta da guarda: os testes correm com a guarda
    ligada e a passar-lhe a chave, e `test_api_auth.py` tem os casos que a
    apanham desligada, sem chave, e com a chave errada.

    A definicao vive numa variavel de ambiente e nao num `dependency_overrides`
    de proposito. Um override substituiria a propria guarda, e entao a suite
    inteira deixaria de a exercer -- que e exactamente a forma de teste que nao
    pode falhar.
    """
    anterior = os.environ.get("WRITE_API_KEY")
    os.environ["WRITE_API_KEY"] = CHAVE_DE_ESCRITA_DOS_TESTES
    get_settings.cache_clear()
    yield CHAVE_DE_ESCRITA_DOS_TESTES
    if anterior is None:
        os.environ.pop("WRITE_API_KEY", None)
    else:
        os.environ["WRITE_API_KEY"] = anterior
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def senha_da_consola_configurada(chave_de_escrita_configurada):
    """Poe o par da consola no ambiente durante toda a corrida.

    Sem isto, as oito rotas sob `/console` responderiam 503 -- a recusa de quem
    nao tem senha configurada -- e nenhum dos testes da consola que ja existiam
    passaria. Nao e um atalho a volta da guarda: os testes correm com a guarda
    ligada e a apresentar-lhe o par, e `test_console_auth.py` tem os casos que a
    apanham sem guarda, sem senha configurada, e com o par errado.

    Depende do fixture da chave de escrita apenas para fixar a ordem: os dois
    escrevem no ambiente e os dois limpam a cache das definicoes, e a cache tem
    de ser limpa DEPOIS da ultima escrita. Sem a dependencia, a ordem e a de
    declaracao -- que e a mesma hoje e nao tem de o ser amanha.
    """
    anteriores = {
        "CONSOLE_USER": os.environ.get("CONSOLE_USER"),
        "CONSOLE_PASSWORD": os.environ.get("CONSOLE_PASSWORD"),
    }
    os.environ["CONSOLE_USER"] = UTILIZADOR_DA_CONSOLA_DOS_TESTES
    os.environ["CONSOLE_PASSWORD"] = SENHA_DA_CONSOLA_DOS_TESTES
    get_settings.cache_clear()
    yield SENHA_DA_CONSOLA_DOS_TESTES
    for nome, valor in anteriores.items():
        if valor is None:
            os.environ.pop(nome, None)
        else:
            os.environ[nome] = valor
    get_settings.cache_clear()


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
    # a listagem das sobras e o aviso vivem dentro de `base_para_esta_corrida`
    # e nao aqui: uma linha no conftest fica fora do alcance das rondas de
    # mutacao, e apaga-la deixava a suite verde.
    base = base_para_esta_corrida(get_settings().database_url)
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
    """O cliente de sempre: a chave de escrita e o par da consola em todos os
    pedidos.

    As duas credenciais vao nos cabecalhos por omissao do cliente e nao em cada
    chamada, para que os testes que ja existiam continuem a ler-se como se leem.
    Sao duas guardas diferentes e nao se estorvam: a API olha para o
    `X-API-Key` e ignora o `Authorization`, a consola faz o contrario.

    Quem precisa de um cliente SEM chave da API usa `cliente_sem_chave`; quem
    precisa de um cliente SEM credencial nenhuma -- os testes da guarda da
    consola -- usa `cliente_a_porta`.
    """
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        c.headers[NOME_DO_CABECALHO] = CHAVE_DE_ESCRITA_DOS_TESTES
        c.headers.update(cabecalho_da_consola())
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_chave(session):
    """Como `client`, mas sem a chave da API: e assim que chega quem nao a tem.

    ⚠️ **Leva o par da consola.** Ate 31/08 a tarde nao levava cabecalho
    nenhum, porque nao havia nenhuma outra guarda. Com a senha a porta da
    consola, um cliente sem credencial nenhuma passava a bater na porta antes de
    chegar a camada -- e os testes da consola que usam este cliente deixavam de
    medir o que medem (que a consola nao pede a chave DA API) para passarem a
    medir a porta. As duas guardas sao independentes, e este cliente exercita a
    da API por lhe faltar exactamente a credencial da API. Quem quer bater a
    porta usa `cliente_a_porta`.

    Tambem nao levanta as excepcoes do servidor (`raise_server_exceptions=False`),
    para que um mutante que faca a guarda rebentar em vez de recusar apareca
    como 500 e nao como um traceback dentro do teste -- a distincao entre
    "recusado" e "explodiu" e das que estes testes tem de conseguir fazer.
    """
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers.update(cabecalho_da_consola())
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def cliente_a_porta(session):
    """Sem credencial nenhuma: nem a chave da API, nem o par da consola.

    E assim que chega quem so conhece o endereco, que e a pessoa que a senha da
    consola existe para deter. Usado pelos testes de `test_console_auth.py`.
    """
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app, raise_server_exceptions=False) as c:
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
        c.headers[NOME_DO_CABECALHO] = CHAVE_DE_ESCRITA_DOS_TESTES
        c.headers.update(cabecalho_da_consola())
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
