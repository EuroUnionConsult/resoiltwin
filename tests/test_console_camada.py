"""A camada que guarda a chave: o que ela leva para a API e o que traz de volta.

**O que estes testes tentam fazer.** Ler a chave a partir do que o navegador
recebe, por todas as vias que ocorreram a quem os escreveu: o corpo, os nomes e
os valores dos cabecalhos, os cookies, uma mensagem de erro, e o registo do
servidor. E tentam-no contra uma API que **colabora com a fuga** -- uma
aplicacao de brincar que devolve a chave que recebeu no corpo, num cabecalho,
num cookie e no `detail`. Uma camada que se limite a copiar a resposta falha
aqui.

⭐ **Cada teste que planta a chave tem um controlo negativo:** primeiro chama-se
a aplicacao que colabora **directamente** e exige-se que a chave la esteja. Sem
esse controlo, o teste passava no dia em que a aplicacao de brincar deixasse de
a devolver -- que e a forma de teste que este projecto ja produziu cinco vezes,
plantar um valor que o filtro a jusante nunca chega a devolver.

**Os inventarios sao lidos da aplicacao**, como em `test_api_auth.py`: as rotas
de leitura e as de escrita saem de `app.routes`. Uma rota nova nao precisa de
ninguem se lembrar de vir aqui. E ha um piso a contar os casos, porque um
`parametrize` sobre uma lista vazia recolhe zero casos e fica verde sem ter
medido nada.
"""

import json

import pytest
from fastapi.testclient import TestClient

from resoiltwin.api import PREFIXO_DA_API, console
from resoiltwin.api.auth import NOME_DO_CABECALHO
from resoiltwin.main import app
from tests.conftest import CHAVE_DE_ESCRITA_DOS_TESTES

# A partir de quantos caracteres um pedaco da chave conta como fuga. O mesmo
# criterio e o mesmo numero de `test_api_auth.py`, e pela mesma razao: tres
# letras de qualquer cadeia aparecem por acaso em texto normal.
PREFIXO_QUE_JA_E_FUGA = 6

PREFIXOS_DA_CHAVE = [
    CHAVE_DE_ESCRITA_DOS_TESTES[:n]
    for n in range(PREFIXO_QUE_JA_E_FUGA, len(CHAVE_DE_ESCRITA_DOS_TESTES) + 1)
]

METODOS_QUE_ESCREVEM = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _url_da_consola(caminho_da_api: str) -> str:
    return console.PREFIXO_DA_CONSOLA + caminho_da_api


def _sem_parametros(caminho: str) -> str:
    """Preenche os parametros do caminho com valores que nao existem.

    Nao existirem e o ponto: o que se mede aqui e se a camada deixa passar o
    caminho, e nao o que a base tem la dentro. A resposta que vier da API --
    404, 422, 503 -- e assunto da API.
    """
    return (
        caminho
        .replace("{code}", "SITIO-QUE-NAO-EXISTE")
        .replace("{job_id}", "00000000-0000-0000-0000-000000000000")
    )


def _rotas_da_aplicacao() -> list[tuple[str, str]]:
    pares = set()
    for rota in app.routes:
        for metodo in getattr(rota, "methods", None) or ():
            pares.add((rota.path, metodo))
    return sorted(pares)


TODAS_AS_ROTAS = _rotas_da_aplicacao()

# As leituras da API: o que esta camada tem de deixar passar.
LEITURAS_DA_API = [
    (caminho, metodo)
    for caminho, metodo in TODAS_AS_ROTAS
    if metodo == "GET" and caminho.startswith(PREFIXO_DA_API + "/")
]

# As escritas: o que ela tem de recusar, e nao por acaso.
ESCRITAS_DA_API = [
    (caminho, metodo)
    for caminho, metodo in TODAS_AS_ROTAS
    if metodo in METODOS_QUE_ESCREVEM and caminho.startswith(PREFIXO_DA_API + "/")
]


def _identificador(caso: tuple[str, str]) -> str:
    caminho, metodo = caso
    return f"{metodo} {caminho}"


def _detalhe(resposta) -> str | None:
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    return corpo.get("detail") if isinstance(corpo, dict) else None


def _superficies(resposta) -> dict[str, str]:
    """Tudo o que o navegador consegue ler de uma resposta, em texto."""
    return {
        "corpo": resposta.text,
        "nomes dos cabecalhos": " ".join(resposta.headers.keys()),
        "valores dos cabecalhos": " ".join(resposta.headers.values()),
        "cookies": str(dict(resposta.cookies)),
    }


def _exigir_que_nao_ha_chave(resposta, onde: str) -> None:
    for superficie, texto in _superficies(resposta).items():
        for prefixo in PREFIXOS_DA_CHAVE:
            assert prefixo not in texto, f"{onde}: {superficie} deixa sair um pedaco da chave"


class _ApiEspiada:
    """A aplicacao real, com um caderno do que lhe chega.

    Embrulha em vez de substituir: o que corre por baixo continua a ser a API,
    com a guarda da chave e tudo. `routes` e delegado porque e por ai que a
    camada decide o que reencaminha -- se o embrulho escondesse as rotas, o
    teste media outra coisa.
    """

    def __init__(self, aplicacao):
        self._aplicacao = aplicacao
        self.pedidos: list[dict] = []

    @property
    def routes(self):
        return self._aplicacao.routes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            self.pedidos.append({
                "caminho": scope["path"],
                "metodo": scope["method"],
                "query": scope["query_string"].decode("utf-8"),
                "cabecalhos": {
                    nome.decode("utf-8").lower(): valor.decode("utf-8")
                    for nome, valor in scope["headers"]
                },
            })
        await self._aplicacao(scope, receive, send)


class _ApiQueColaboraComAFuga:
    """Uma API que devolve a chave que recebeu, por todos os caminhos que tem.

    Nao e um espantalho: e a unica maneira de exercer o que a camada faz com
    uma resposta que traz a credencial. Hoje nenhuma rota da API real
    devolveria isto -- e "hoje nenhuma" nao e uma garantia.
    """

    def __init__(self, aplicacao):
        self._aplicacao = aplicacao

    @property
    def routes(self):
        return self._aplicacao.routes

    async def __call__(self, scope, receive, send):
        cabecalhos = {
            nome.decode("utf-8").lower(): valor.decode("utf-8") for nome, valor in scope["headers"]
        }
        chave = cabecalhos.get(NOME_DO_CABECALHO.lower(), "")
        corpo = json.dumps({
            "detail": f"the key you sent was {chave}",
            "eco": {"x-api-key": chave},
            "aninhado": [{"credencial": chave}],
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-api-key", chave.encode("utf-8")),
                (b"x-leak", chave.encode("utf-8")),
                (b"set-cookie", f"credencial={chave}; Path=/".encode("utf-8")),
            ],
        })
        await send({"type": "http.response.body", "body": corpo})


class _ApiQueFugaSoNoCabecalho:
    """Uma API cujo corpo esta limpo e cujos cabecalhos trazem a chave.

    Existe separada da anterior por uma razao que so se ve ao medir: com a
    fuga tambem no corpo, a recusa do corpo dispara primeiro e o codigo que
    monta o envelope da resposta **nao chega a correr**. Um teste que so
    usasse a outra aplicacao deixava o envelope sem medicao nenhuma -- e o
    envelope e precisamente onde uma copia de cabecalhos deixaria a chave sair.
    """

    def __init__(self, aplicacao):
        self._aplicacao = aplicacao

    @property
    def routes(self):
        return self._aplicacao.routes

    async def __call__(self, scope, receive, send):
        cabecalhos = {
            nome.decode("utf-8").lower(): valor.decode("utf-8") for nome, valor in scope["headers"]
        }
        chave = cabecalhos.get(NOME_DO_CABECALHO.lower(), "")
        corpo = json.dumps([{"code": "EUC-TUR-01", "area_m2": 251.4}]).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-api-key", chave.encode("utf-8")),
                (b"x-leak", chave.encode("utf-8")),
                (b"set-cookie", f"credencial={chave}; Path=/".encode("utf-8")),
            ],
        })
        await send({"type": "http.response.body", "body": corpo})


class _ApiQueNaoDevolveJson:
    def __init__(self, aplicacao):
        self._aplicacao = aplicacao

    @property
    def routes(self):
        return self._aplicacao.routes

    async def __call__(self, scope, receive, send):
        cabecalhos = {
            nome.decode("utf-8").lower(): valor.decode("utf-8") for nome, valor in scope["headers"]
        }
        chave = cabecalhos.get(NOME_DO_CABECALHO.lower(), "")
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": f"a chave e {chave}".encode("utf-8")})


def _resposta_directa(aplicacao, caminho: str):
    """Chama a aplicacao de brincar sem a camada pelo meio: o controlo negativo.

    Sem `with`: o gestor de contexto do `TestClient` corre o ciclo de vida
    ASGI, e estas aplicacoes de brincar so sabem responder a pedidos HTTP --
    que e tudo o que a camada lhes faz.
    """
    cliente = TestClient(aplicacao)
    return cliente.get(caminho, headers={NOME_DO_CABECALHO: CHAVE_DE_ESCRITA_DOS_TESTES})


@pytest.fixture
def api_espiada(monkeypatch):
    espia = _ApiEspiada(app)
    monkeypatch.setattr(console, "_aplicacao_alvo", lambda pedido: espia)
    return espia


# --------------------------------------------------------------------------
# 1. o pedido do navegador chega a API COM a chave
# --------------------------------------------------------------------------


def test_o_pedido_do_navegador_chega_a_api_com_a_chave(cliente_sem_chave, api_espiada):
    """O navegador nao manda credencial nenhuma, e a API recebe uma."""
    resposta = cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/sites"))

    assert resposta.status_code == 200, resposta.text
    assert len(api_espiada.pedidos) == 1, "a camada nao fez exactamente um pedido a API"
    pedido = api_espiada.pedidos[0]
    assert pedido["caminho"] == f"{PREFIXO_DA_API}/sites"
    assert pedido["metodo"] == console.METODO_UNICO
    assert pedido["cabecalhos"][NOME_DO_CABECALHO.lower()] == CHAVE_DE_ESCRITA_DOS_TESTES


def test_a_chave_que_o_navegador_inventa_nao_substitui_a_da_camada(cliente_sem_chave, api_espiada):
    """Quem faz o pedido nao escolhe a credencial com que ele e feito.

    Sem isto, bastava um navegador mandar `X-API-Key:` para os cabecalhos dele
    passarem para o pedido de saida -- e entao a camada deixava de guardar
    coisa nenhuma, so reencaminhava o que lhe davam.
    """
    resposta = cliente_sem_chave.get(
        _url_da_consola(f"{PREFIXO_DA_API}/sites"),
        headers={NOME_DO_CABECALHO: "a-chave-que-o-navegador-inventou"},
    )

    assert resposta.status_code == 200, resposta.text
    chegou = api_espiada.pedidos[0]["cabecalhos"][NOME_DO_CABECALHO.lower()]
    assert chegou == CHAVE_DE_ESCRITA_DOS_TESTES
    assert "a-chave-que-o-navegador-inventou" not in json.dumps(api_espiada.pedidos[0])


def test_a_query_do_navegador_e_reencaminhada(cliente_sem_chave, api_espiada):
    """Os filtros da consola sao query string, e tem de chegar la.

    Sem este lado, uma camada que deitasse fora a query passava todos os
    testes de fuga -- e a consola mostrava sempre tudo.
    """
    cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/jobs") + "?limit=3")
    assert api_espiada.pedidos[0]["query"] == "limit=3"


# --------------------------------------------------------------------------
# 2. a resposta ao navegador NAO contem a chave
# --------------------------------------------------------------------------


def test_controlo_a_api_que_colabora_devolve_mesmo_a_chave():
    """O controlo negativo dos dois testes seguintes.

    Se um dia esta aplicacao de brincar deixar de devolver a chave, os testes
    da fuga passam a estar a medir nada -- e sao eles a coisa mais importante
    deste ficheiro. Aqui exige-se que a fuga exista antes de se exigir que a
    camada a corte.
    """
    resposta = _resposta_directa(_ApiQueColaboraComAFuga(app), f"{PREFIXO_DA_API}/sites")
    assert CHAVE_DE_ESCRITA_DOS_TESTES in resposta.text
    assert resposta.headers["x-api-key"] == CHAVE_DE_ESCRITA_DOS_TESTES
    assert CHAVE_DE_ESCRITA_DOS_TESTES in resposta.headers["set-cookie"]


def test_a_chave_nao_sai_mesmo_com_a_api_a_devolve_la(cliente_sem_chave, monkeypatch):
    """Corpo, cabecalhos, cookies e mensagem de erro: por nenhum deles."""
    monkeypatch.setattr(
        console, "_aplicacao_alvo", lambda pedido: _ApiQueColaboraComAFuga(app)
    )
    resposta = cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/sites"))

    _exigir_que_nao_ha_chave(resposta, "api que colabora com a fuga")
    assert resposta.status_code == 502
    assert _detalhe(resposta) == console.RECUSA_DE_CORPO


def test_controlo_a_api_que_fuga_no_cabecalho_devolve_mesmo_a_chave():
    """O controlo negativo do teste seguinte, e o corpo tem de estar limpo.

    As duas metades contam: se o corpo levasse a chave, o teste seguinte
    passava pela recusa do corpo e o envelope continuava sem medicao.
    """
    resposta = _resposta_directa(_ApiQueFugaSoNoCabecalho(app), f"{PREFIXO_DA_API}/sites")
    assert resposta.headers["x-leak"] == CHAVE_DE_ESCRITA_DOS_TESTES
    assert CHAVE_DE_ESCRITA_DOS_TESTES in resposta.headers["set-cookie"]
    assert CHAVE_DE_ESCRITA_DOS_TESTES not in resposta.text


def test_nenhum_cabecalho_da_api_chega_ao_navegador(cliente_sem_chave, monkeypatch):
    """Nao e so a chave: e o envelope todo.

    A resposta e construida de raiz. Um cabecalho acrescentado amanha a uma
    rota da API -- de diagnostico, de rastreio, o que for -- nao passa por aqui
    sem alguem decidir que passa.
    """
    monkeypatch.setattr(
        console, "_aplicacao_alvo", lambda pedido: _ApiQueFugaSoNoCabecalho(app)
    )
    resposta = cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/sites"))

    assert resposta.status_code == 200, "o corpo estava limpo e mesmo assim nao passou"
    assert "x-leak" not in resposta.headers
    assert "set-cookie" not in resposta.headers
    assert resposta.cookies == {}
    _exigir_que_nao_ha_chave(resposta, "api com fuga so no cabecalho")


def test_um_corpo_que_nao_e_json_nao_passa(cliente_sem_chave, monkeypatch):
    """A rede por baixo da rede: o que nao se sabe ler nao se copia."""
    monkeypatch.setattr(
        console, "_aplicacao_alvo", lambda pedido: _ApiQueNaoDevolveJson(app)
    )
    resposta = cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/sites"))

    assert resposta.status_code == 502
    assert _detalhe(resposta) == console.RECUSA_DE_CORPO
    _exigir_que_nao_ha_chave(resposta, "api que nao devolve json")


def test_o_piso_das_leituras_nao_deixa_o_inventario_ficar_vazio():
    """Sem isto, os dois `parametrize` a seguir recolhiam zero casos."""
    assert len(LEITURAS_DA_API) >= 6
    assert len(ESCRITAS_DA_API) >= 8


@pytest.mark.parametrize("caso", LEITURAS_DA_API, ids=_identificador)
def test_nenhuma_leitura_normal_deixa_sair_a_chave(cliente_sem_chave, caso):
    """Um caso por rota de leitura. Uma rota nova entra sozinha neste teste."""
    caminho, _ = caso
    resposta = cliente_sem_chave.get(_url_da_consola(_sem_parametros(caminho)))
    _exigir_que_nao_ha_chave(resposta, caminho)


# --------------------------------------------------------------------------
# 3. um pedido a uma rota que nao existe nao passa
# --------------------------------------------------------------------------


CAMINHOS_QUE_NAO_PASSAM = [
    f"{PREFIXO_DA_API}/rota-que-nao-existe",
    f"{PREFIXO_DA_API}/sites/UM/dois/tres",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/etc/passwd",
    # ⚠️ `/` saiu desta lista a 31/08 a noite, e a saida e uma decisao e nao uma
    # cedencia. `/console/` deixou de chegar ao apanha-tudo porque passou a ser
    # uma rota propria -- a pagina de entrada da consola --, registada antes
    # dele. O apanha-tudo continua a recusar tudo o que nao seja uma leitura da
    # API, e e isso que os restantes casos medem; o que mudou foi que este
    # caminho ja nao lhe chega.
    f"{PREFIXO_DA_API}/../../openapi.json",
    f"{PREFIXO_DA_API}/sites/../../../openapi.json",
    "/api/v2/sites",
    f"{console.PREFIXO_DA_CONSOLA}{PREFIXO_DA_API}/sites",
]


@pytest.mark.parametrize("caminho", CAMINHOS_QUE_NAO_PASSAM)
def test_um_caminho_que_nao_e_leitura_da_api_nao_passa(cliente_sem_chave, api_espiada, caminho):
    """404 da camada, e -- o que interessa mais -- a API nem chega a ser chamada.

    Sem a segunda metade, uma camada que reencaminhasse tudo e devolvesse o 404
    da API passava por aqui: o numero era o mesmo e a porta estava aberta.
    """
    resposta = cliente_sem_chave.get(console.PREFIXO_DA_CONSOLA + caminho)

    assert resposta.status_code == 404, f"{caminho} passou pela camada"
    assert _detalhe(resposta) == console.RECUSA_DE_ROTA
    assert api_espiada.pedidos == [], f"{caminho} chegou a API"


def test_a_documentacao_continua_fechada_por_esta_via(cliente_sem_chave, api_espiada):
    """O `/openapi.json` e uma rota GET desta aplicacao, e mesmo assim nao passa.

    E o caso que separa "so leituras" de "so leituras **da API**": as quatro
    rotas de documentacao foram fechadas de proposito a 31/08, e uma camada
    que deixasse passar qualquer GET reabria-as a quem nao tem chave -- com o
    mapa das dezasseis rotas la dentro.
    """
    assert ("/openapi.json", "GET") in TODAS_AS_ROTAS
    resposta = cliente_sem_chave.get(_url_da_consola("/openapi.json"))
    assert resposta.status_code == 404
    assert api_espiada.pedidos == []


@pytest.mark.parametrize("caso", ESCRITAS_DA_API, ids=_identificador)
def test_nenhuma_escrita_da_api_e_alcancavel_pela_camada(cliente_sem_chave, api_espiada, caso):
    """Um caso por rota de escrita. Uma escrita nova entra sozinha neste teste.

    O metodo e recusado pelo encaminhador (405), antes de existir codigo nosso
    a correr, porque a rota da camada esta registada com um unico metodo. A
    linha que interessa e a ultima: a API nao chega a ser chamada.
    """
    caminho, metodo = caso
    url = _url_da_consola(_sem_parametros(caminho))

    resposta = cliente_sem_chave.request(metodo, url)

    assert resposta.status_code == 405, f"{metodo} {caminho} passou pela camada"
    assert api_espiada.pedidos == [], f"{metodo} {caminho} chegou a API"


# Os caminhos que SO existem para escrever. Um `GET` a um destes nao e uma
# leitura desta API, e tem de morrer na camada e nao na API -- e a diferenca
# entre "a camada nao deixa" e "a API respondeu 404" e o que separa um
# reencaminhamento estreito de um que reencaminha tudo e devolve o que vier.
CAMINHOS_SO_DE_ESCRITA = sorted(
    {caminho for caminho, _ in ESCRITAS_DA_API}
    - {caminho for caminho, _ in LEITURAS_DA_API}
)


def test_ha_caminhos_que_so_existem_para_escrever():
    """Piso do `parametrize` a seguir."""
    assert len(CAMINHOS_SO_DE_ESCRITA) >= 4


@pytest.mark.parametrize("caminho", CAMINHOS_SO_DE_ESCRITA)
def test_um_caminho_so_de_escrita_nao_e_legivel_pela_camada(
    cliente_sem_chave, api_espiada, caminho
):
    resposta = cliente_sem_chave.get(_url_da_consola(_sem_parametros(caminho)))

    assert resposta.status_code == 404, f"GET {caminho} passou pela camada"
    assert _detalhe(resposta) == console.RECUSA_DE_ROTA
    assert api_espiada.pedidos == [], f"GET {caminho} chegou a API"


@pytest.mark.parametrize("caso", LEITURAS_DA_API, ids=_identificador)
def test_cada_leitura_da_api_e_alcancavel_pela_camada(cliente_sem_chave, caso):
    """O outro lado da fronteira: uma camada que recusasse tudo nao serve.

    Nao se exige um estado: exige-se que a recusa **nao seja a da camada**. O
    que vier da API -- 404 por um sitio inventado, 422 por um parametro em
    falta, 503 do Copernicus -- e assunto da API.
    """
    caminho, _ = caso
    resposta = cliente_sem_chave.get(_url_da_consola(_sem_parametros(caminho)))
    assert resposta.status_code != 405, f"{caminho} foi recusado pelo metodo"
    assert _detalhe(resposta) != console.RECUSA_DE_ROTA, f"{caminho} foi recusado pela camada"


# --------------------------------------------------------------------------
# 4. a chave nao aparece em registo nenhum
# --------------------------------------------------------------------------


def test_a_chave_nao_aparece_em_registo_nenhum(cliente_sem_chave, caplog, monkeypatch):
    """Os tres caminhos que escrevem no registo, com o nivel todo aberto.

    O comprimento conta como fuga, pela mesma razao de `test_api_auth.py`:
    dizer que a chave tem N caracteres corta o espaco de procura.
    """
    with caplog.at_level("DEBUG"):
        cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/sites"))
        cliente_sem_chave.get(_url_da_consola("/openapi.json"))
        monkeypatch.setattr(
            console, "_aplicacao_alvo", lambda pedido: _ApiQueColaboraComAFuga(app)
        )
        cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/sites"))
        monkeypatch.setattr(
            console, "_aplicacao_alvo", lambda pedido: _ApiQueNaoDevolveJson(app)
        )
        cliente_sem_chave.get(_url_da_consola(f"{PREFIXO_DA_API}/sites"))

    assert caplog.text, "o registo ficou vazio, e entao este teste nao mediu nada"
    for prefixo in PREFIXOS_DA_CHAVE:
        assert prefixo not in caplog.text, "o registo deixa sair um pedaco da chave"
    assert str(len(CHAVE_DE_ESCRITA_DOS_TESTES)) not in caplog.text


# --------------------------------------------------------------------------
# as geometrias, que tambem nao podem chegar ao navegador
# --------------------------------------------------------------------------


def test_controlo_a_api_devolve_mesmo_a_geometria_da_area_de_interesse(client, aoi_aprovada):
    """O controlo negativo do teste seguinte: ha um poligono para cortar."""
    resposta = client.get(f"{PREFIXO_DA_API}/sites/EUC-TUR-JOB/aois")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo[0]["geometry"]["type"] == "Polygon"
    assert corpo[0]["geometry"]["coordinates"], "a API deixou de devolver coordenadas"


def test_a_geometria_da_area_de_interesse_nao_chega_ao_navegador(
    cliente_sem_chave, client, aoi_aprovada
):
    """A area em m2 passa; o poligono nao.

    Os poligonos estao num repositorio privado desde 31/08 e nao podem sair.
    O que a consola precisa de mostrar -- o tamanho, a finalidade, o estado, a
    proveniencia -- passa tudo.
    """
    da_api = client.get(f"{PREFIXO_DA_API}/sites/EUC-TUR-JOB/aois").json()
    uma_coordenada = str(da_api[0]["geometry"]["coordinates"][0][0][0])

    resposta = cliente_sem_chave.get(
        _url_da_consola(f"{PREFIXO_DA_API}/sites/EUC-TUR-JOB/aois")
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo[0]["geometry"] == console.MARCA_DE_RETIDO
    assert corpo[0]["area_m2"] == da_api[0]["area_m2"]
    assert corpo[0]["geometry_provenance"] == da_api[0]["geometry_provenance"]
    assert uma_coordenada not in resposta.text, "uma coordenada chegou ao navegador"


def test_o_corte_e_pela_forma_e_nao_pelo_nome_do_campo():
    """Renomear `geometry` nao contorna o corte, e um dicionario normal sobrevive.

    Os dois lados sao precisos: um corte que apagasse tudo passava a metade de
    cima deste teste e deixava a consola sem dados nenhuns.
    """
    poligono = {"type": "Polygon", "coordinates": [[[-9.24, 39.03], [-9.24, 39.04]]]}

    for nome in ("geometry", "boundary", "qualquer_outro_nome"):
        cortado = console._sem_geometria({nome: poligono, "area_m2": 251.4})
        assert cortado[nome] == console.MARCA_DE_RETIDO, f"{nome} passou"
        assert cortado["area_m2"] == 251.4

    # Uma geometria sem `type`, que e a forma que uma resposta mais magra
    # teria. Nao ha aqui nome de campo nem etiqueta de tipo a ajudar: o que a
    # denuncia sao as coordenadas.
    so_coordenadas = {"contorno": {"coordinates": [[[-9.24, 39.03]]]}}
    assert console._sem_geometria(so_coordenadas) == {"contorno": console.MARCA_DE_RETIDO}

    intacto = {"code": "EUC-TUR-01", "type": "vine", "leituras": [1, 2, 3], "nulo": None}
    assert console._sem_geometria(intacto) == intacto

    # Uma lista de registos, que e a forma que as rotas de listagem devolvem.
    lista = console._sem_geometria([{"geometry": poligono}, {"geometry": None}])
    assert lista == [{"geometry": console.MARCA_DE_RETIDO}, {"geometry": None}]

    # E o embrulho do GeoJSON, que traz a geometria mais um nivel abaixo.
    feature = {"type": "Feature", "geometry": poligono, "properties": {}}
    assert console._sem_geometria({"aoi": feature}) == {"aoi": console.MARCA_DE_RETIDO}
