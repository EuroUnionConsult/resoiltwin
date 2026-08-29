import pytest

from resoiltwin.config import MissingDatabaseUrlError, Settings

SECRET_FIELDS = ("cdse_client_id", "cdse_client_secret")

# database_url passado explicitamente aos testes abaixo que nao sao sobre ele:
# desde que deixou de ter valor por omissao, instanciar Settings() sem o
# fornecer depende de DATABASE_URL estar exportada no processo -- o que nao e
# verdade so por existir um ficheiro .env (esse so e lido quando _env_file
# nao e None). Os testes de secrets nao querem depender disso.
_DB_URL = "postgresql+psycopg://test:test@localhost:5432/test"


def test_settings_class_declares_no_default_secrets():
    """Afirma sobre os defaults da CLASSE, nao sobre o ambiente da maquina.

    A versao anterior instanciava Settings() e afirmava que cdse_client_id era
    None -- o que so era verdade por nao existir .env. Numa maquina que siga o
    README (`cp .env.example .env`) ou que exporte CDSE_CLIENT_ID, o teste
    falhava sem que houvesse defeito nenhum no codigo.
    """
    for name in SECRET_FIELDS:
        assert Settings.model_fields[name].default is None


def test_settings_read_no_secret_from_a_dotenv_file(monkeypatch):
    """Com _env_file=None e sem variaveis exportadas, os campos de credencial
    ficam a None: nenhum segredo esta embutido no codigo."""
    for name in (*SECRET_FIELDS, "app_name"):
        monkeypatch.delenv(name.upper(), raising=False)
    settings = Settings(_env_file=None, database_url=_DB_URL)
    assert settings.app_name == "ReSoilTwin API"
    assert settings.cdse_client_id is None
    assert settings.cdse_client_secret is None


def test_settings_without_database_url_fails_loudly(monkeypatch):
    """Sem DATABASE_URL e sem .env, o arranque tem de falhar -- nao ligar-se em
    silencio a base de desenvolvimento local.

    E o defeito do incidente de 29/08/2026: uma variavel mal escrita
    (RESOILTWIN_DATABASE_URL em vez de DATABASE_URL) foi ignorada em silencio
    e o valor por omissao apontava para a base real, que um `alembic
    downgrade base` apagou. A mensagem tem de nomear a variavel, para que
    quem a apanhe pela primeira vez saiba logo o que falta.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(MissingDatabaseUrlError, match="DATABASE_URL"):
        Settings(_env_file=None)
