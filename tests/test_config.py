from resoiltwin.config import Settings

SECRET_FIELDS = ("cdse_client_id", "cdse_client_secret")


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
    settings = Settings(_env_file=None)
    assert settings.app_name == "ReSoilTwin API"
    assert settings.cdse_client_id is None
    assert settings.cdse_client_secret is None
