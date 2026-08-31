from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingDatabaseUrlError(RuntimeError):
    """DATABASE_URL nao definida, e sem um valor por omissao para a substituir.

    Ate 28/08/2026 o campo tinha um valor por omissao que apontava para a base
    de desenvolvimento local. Uma variavel de ambiente mal escrita
    (RESOILTWIN_DATABASE_URL em vez de DATABASE_URL, por exemplo -- `Settings`
    nao tem env_prefix) era entao ignorada em silencio, e um `alembic
    downgrade base` corrido nessa condicao apagou a base real em vez de
    falhar. Sem valor por omissao, o mesmo erro de configuracao para o
    arranque em vez de se ligar ao sitio errado.
    """


class Settings(BaseSettings):
    app_name: str = "ReSoilTwin API"
    environment: str = "local"
    # sem valor por omissao de proposito -- ver MissingDatabaseUrlError.
    database_url: str | None = None
    cdse_client_id: str | None = None
    cdse_client_secret: str | None = None
    # credenciais do Climate Data Store (reanalise meteorologica), mesmo padrao
    # das do CDSE: sem valor por omissao, lidas do .env ou do ambiente.
    cds_api_url: str | None = None
    cds_api_key: str | None = None
    # chave partilhada exigida pelas rotas que ESCREVEM (ver api/auth.py).
    #
    # Sem valor por omissao, pela mesma razao que `database_url`: um valor por
    # omissao num repositorio publico e a mesma chave em todas as instalacoes,
    # ou seja uma fechadura pintada. Mas, ao contrario de `database_url`, a
    # falta desta NAO impede o arranque: `database_url` e precisa nas dezasseis
    # rotas e sem ela nao ha nada a servir, enquanto esta e precisa em oito.
    # Recusar arrancar por causa dela partia quem so quer ler -- e, pior,
    # empurrava quem tem pressa para inventar um valor so para arrancar, que e
    # o valor por omissao outra vez, agora por outra via.
    #
    # O que a ausencia faz e fechar: sem chave configurada, as rotas de escrita
    # respondem 503 e nao escrevem nada. A falha perigosa seria a simetrica --
    # "nao ha chave configurada, portanto deixa passar" -- e e precisamente
    # essa que a guarda de `exigir_chave_de_escrita` existe para impedir.
    write_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _require_database_url(self) -> "Settings":
        if not self.database_url:
            raise MissingDatabaseUrlError(
                "DATABASE_URL is not set. In development it comes from .env "
                "(copy .env.example: `cp .env.example .env`). In CI or production, "
                "export DATABASE_URL explicitly before starting the app."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
