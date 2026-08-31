"""As quatro rotas de documentacao, registadas por nos para levarem a guarda.

**Porque e que isto existe.** O FastAPI serve `/openapi.json`, `/docs`,
`/docs/oauth2-redirect` e `/redoc` sozinho, mas serve-as como rotas do
Starlette acrescentadas no `setup()` -- nao sao `APIRoute`, e por isso **nao
recebem** nem o `dependencies=` da aplicacao nem o de nenhum router. Foi
verificado, e nao deduzido: uma aplicacao com `FastAPI(dependencies=[...])`
responde 200 no `/docs` enquanto a dependencia recusa tudo o resto. Deixa-las
ao FastAPI era deixar quatro portas abertas por distraccao.

O caminho e portanto: desligar as do FastAPI (`openapi_url=None`,
`docs_url=None`, `redoc_url=None` em `main.py`) e voltar a registar as mesmas
quatro aqui, agora como rotas normais, que e o que as faz passar pela guarda
como todas as outras.

---

**A decisao: as quatro ficam fechadas.** O argumento, com o custo assumido.

O esquema nao contem dados -- nao ha ali uma geometria nem uma leitura. Contem
o **mapa**: os nomes das dezasseis rotas, os campos de cada corpo, que
`approved_by` e texto livre, onde se pedem poligonos e em que formato. Publicar
o mapa das portas que se acabou de fechar e uma assimetria auto-infligida: nao
ajuda ninguem que tenha a chave (quem a tem le o esquema na mesma) e poupa o
trabalho de reconhecimento a quem nao a tem.

O criterio que se aplicou foi o mesmo do `/health`, e e por isso que deu
resultado diferente: **uma rota so fica aberta se alguma coisa que nao pode
levar credencial precisar dela.** A sonda de saude precisa do `/health` e nao
tem onde por um cabecalho. Nada de automatico precisa do `/docs`.

**O custo, que e real e nao se disfarca:** quem tem a chave deixa de poder
abrir o `/docs` no navegador. Um navegador nao poe cabecalhos numa barra de
enderecos, portanto a pagina passa a responder 401 e a interface do Swagger nao
chega a carregar. Nao ha meia solucao: deixar o `/docs` aberto e fechar o
`/openapi.json` dava uma pagina que carrega e nao consegue ler o esquema --
zero informacao a mais para quem tem a chave, uma porta aberta a mais para quem
nao tem.

O que fica em troca do custo: o esquema continua a ser servido, so que a quem
apresentar a chave.

    curl -H "X-API-Key: <a chave>" "$URL/openapi.json"

Dai sai um documento OpenAPI valido, que se le num Swagger UI local, num Redoc
local, ou num gerador de clientes. A documentacao nao desaparece; deixa de ser
de leitura anonima, como tudo o resto.
"""

from fastapi import APIRouter, Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse, JSONResponse

# Os mesmos caminhos por omissao do FastAPI, escritos aqui porque a aplicacao
# deixou de lhos dizer. Mudar um destes sem mudar o de la e o unico erro que
# esta separacao introduz, e as tres primeiras apontam para a quarta.
CAMINHO_DO_ESQUEMA = "/openapi.json"
CAMINHO_DO_SWAGGER = "/docs"
CAMINHO_DO_REDIRECT_OAUTH2 = "/docs/oauth2-redirect"
CAMINHO_DO_REDOC = "/redoc"

# `include_in_schema=False` como no FastAPI: a documentacao nao se documenta a
# si propria. Tem uma consequencia nos testes que vale a pena saber -- estas
# quatro nao aparecem nos `paths` do OpenAPI, portanto sao verificadas pelo
# comportamento (respondem 401 sem chave) e nao pelo esquema.
router = APIRouter(include_in_schema=False)


def _prefixo(request: Request) -> str:
    """O `root_path`, para que os caminhos funcionem atras de um proxy.

    E o que o FastAPI faz nas rotas que estas substituem. Sem isto, uma
    aplicacao servida em `/api` mandava o navegador buscar o esquema a raiz do
    dominio.
    """
    return request.scope.get("root_path", "").rstrip("/")


@router.api_route(CAMINHO_DO_ESQUEMA, methods=["GET", "HEAD"])
def esquema_openapi(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi())


@router.api_route(CAMINHO_DO_SWAGGER, methods=["GET", "HEAD"])
def swagger_ui(request: Request) -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=_prefixo(request) + CAMINHO_DO_ESQUEMA,
        title=f"{request.app.title} - Swagger UI",
        oauth2_redirect_url=_prefixo(request) + CAMINHO_DO_REDIRECT_OAUTH2,
    )


@router.api_route(CAMINHO_DO_REDIRECT_OAUTH2, methods=["GET", "HEAD"])
def redirect_oauth2_do_swagger() -> HTMLResponse:
    return get_swagger_ui_oauth2_redirect_html()


@router.api_route(CAMINHO_DO_REDOC, methods=["GET", "HEAD"])
def redoc(request: Request) -> HTMLResponse:
    return get_redoc_html(
        openapi_url=_prefixo(request) + CAMINHO_DO_ESQUEMA,
        title=f"{request.app.title} - ReDoc",
    )
