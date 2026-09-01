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
    # chave partilhada exigida por TODAS as rotas menos o /health (api/auth.py).
    # O nome ficou com "write" por ser o do segredo que ja esta no cofre e na
    # variavel que o `infra/modules/app.bicep` leva para o contentor; a divida
    # de nome esta registada no cabecalho de `api/auth.py`.
    #
    # Sem valor por omissao, pela mesma razao que `database_url`: um valor por
    # omissao num repositorio publico e a mesma chave em todas as instalacoes,
    # ou seja uma fechadura pintada.
    #
    # Ao contrario de `database_url`, a falta desta continua a NAO impedir o
    # arranque -- e agora por outra razao. Ate 31/08 de manha o argumento era
    # que sem ela ainda se podia ler; a decisao 2 acabou com isso. O que resta,
    # e chega, e poder diagnosticar: uma aplicacao que arranca responde no
    # `/health`, escreve no registo qual e a variavel que falta, e devolve 503
    # em todas as outras rotas -- que e exactamente o que o passo 9 do guia de
    # instalacao manda distinguir de um 401. Uma que se recusasse a arrancar
    # nao diria nada a ninguem, e empurrava quem tem pressa para inventar um
    # valor so para arrancar, que e o valor por omissao outra vez por outra via.
    #
    # O que a ausencia faz e fechar: sem chave configurada, tudo menos o
    # `/health` responde 503. A falha perigosa seria a simetrica -- "nao ha
    # chave configurada, portanto deixa passar" -- e e precisamente essa que a
    # guarda de `exigir_chave` existe para impedir.
    write_api_key: str | None = None
    # A porta da consola (api/console_auth.py). Sao duas definicoes e nao uma:
    # a autenticacao HTTP basica pede um par, e o par e conferido de uma so vez.
    #
    # O utilizador TEM valor por omissao e a senha NAO tem, e a assimetria e
    # deliberada. O utilizador nao e segredo -- o navegador mostra-o na caixa
    # que pede as credenciais, quem o escreve ve-o, e ele viaja em claro dentro
    # do mesmo cabecalho que a senha. Um valor por omissao ali nao e uma
    # fechadura pintada: e a etiqueta da fechadura. A forca esta toda na senha,
    # e por isso a senha segue a regra do `write_api_key` -- sem valor por
    # omissao, porque um valor por omissao num repositorio publico e a mesma
    # senha em todas as instalacoes.
    #
    # Sem senha configurada, a consola FECHA: todas as rotas sob `/console`
    # respondem 503, e nenhuma delas serve uma linha de dados. Nao ha excepcao
    # por ambiente -- nem `environment == "local"`, nem nada que se pareca. Uma
    # guarda que se desliga sozinha quando uma variavel de ambiente diz uma
    # certa palavra e uma guarda que se desliga sozinha no dia em que essa
    # variavel nao chegar ao contentor, que e precisamente a instalacao onde
    # ninguem esta a olhar.
    #
    # O custo, que e real e nao se disfarca: quem corre isto localmente para
    # desenvolver tem de por uma senha no `.env` antes de a consola abrir. E
    # uma linha, e e a mesma linha que a `WRITE_API_KEY` ja exige desde 31/08
    # -- sem ela, a API ja hoje responde 503 em tudo menos o `/health`, e
    # portanto a consola local ja hoje nao mostrava dado nenhum. O atrito novo
    # e uma linha num ficheiro que ja tem de ser editado.
    #
    # Porque 503 e nao "nao arrancar": a consola partilha o contentor com a
    # API. Uma aplicacao que se recusasse a arrancar por falta da senha da
    # consola derrubava a API inteira e a sonda de saude com ela -- uma
    # configuracao em falta na parte menos critica do sistema desligava a mais
    # critica. E 503 e nao 401 porque nao ha credencial nenhuma que o navegador
    # pudesse apresentar para o corrigir: o servidor e que nao esta em
    # condicoes. Quem opera distingue assim "o segredo nao chegou ao contentor"
    # de "enganei-me na senha", que e a mesma distincao que o passo 9 do guia
    # de instalacao ja manda fazer para a chave da API.
    console_user: str = "console"
    console_password: str | None = None

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
