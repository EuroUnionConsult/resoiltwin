"""A chave partilhada das rotas de escrita.

**Estes testes nao sao uma amostra, sao um inventario.** As rotas nao estao
escritas a mao aqui: sao lidas de `app.routes` no momento da recolha, e cada
uma que escreva gera o seu proprio caso. Uma rota de escrita acrescentada
amanha sem `dependencies=EXIGE_CHAVE_DE_ESCRITA` faz nascer um caso novo, e
esse caso cai -- sem que ninguem se lembre de vir aqui acrescentar nada. Era
esse o ponto: um teste que cobre uma rota e presume as outras nao defende
nada, e esta fase ja produziu cinco testes que nao podiam falhar.

A leitura tambem esta presa, e no sentido contrario: cada rota que le gera um
caso que exige que ela responda SEM chave. Uma guarda posta a mais -- em
`/health`, por exemplo -- cai aqui. A fronteira esta pinada dos dois lados,
porque so um dos lados nao e uma fronteira.

O que impede o inventario de ser vazio (uma lista vazia faz o `parametrize`
recolher zero casos e passar sem ter medido nada) e
`test_o_inventario_cobre_todas_as_rotas_da_aplicacao`, que conta e exige que
nenhuma rota fique por classificar.
"""

import hmac

import pytest

from resoiltwin.api import auth
from resoiltwin.main import app
from tests.conftest import CHAVE_DE_ESCRITA_DOS_TESTES

# A partir de quantos caracteres um pedaco da chave conta como fuga. Tres era
# demasiado estrito para servir de guarda: um prefixo de tres letras de
# qualquer cadeia aparece por acaso em texto normal (o "mar" desta suite
# aparece em "summary" no OpenAPI) e o teste passava a falhar por coincidencia
# em vez de por fuga. Seis nao aparece por acaso e continua a apanhar qualquer
# registo que decida escrever "os primeiros N caracteres da chave".
PREFIXO_QUE_JA_E_FUGA = 6

# As duas recusas da guarda, escritas aqui a mao e nao importadas de `auth`.
# Importa-las tornava o teste circular -- seguia a mensagem para onde ela fosse
# --, e sao elas que distinguem uma recusa da guarda de uma recusa da rota. A
# distincao nao e teorica: `POST /sites/{code}/eo/sync` responde 503 sozinha
# quando faltam as credenciais do Copernicus (que e o caso na CI), e um teste
# que so olhasse para o numero 503 passava por causa dela sem a guarda ter
# corrido. Foi assim que se descobriu: a corrida contra a versao anterior
# apanhou este caso a passar onde tinha de cair.
RECUSA_DA_GUARDA = "Missing or invalid API key"
RECUSA_POR_CHAVE_NAO_CONFIGURADA = "Write access is not configured on this server"

METODOS_QUE_ESCREVEM = frozenset({"POST", "PUT", "PATCH", "DELETE"})
METODOS_QUE_LEEM = frozenset({"GET", "HEAD", "OPTIONS"})


def _rotas_da_aplicacao() -> list[tuple[str, str]]:
    """Todo o par (caminho, metodo) que a aplicacao serve, lido da aplicacao.

    Inclui de proposito as rotas da documentacao (`/docs`, `/openapi.json`):
    sao leituras, e tem de continuar abertas. Nada aqui e uma lista escrita a
    mao -- e essa a unica razao por que uma rota nova aparece sozinha.
    """
    pares = set()
    for rota in app.routes:
        for metodo in getattr(rota, "methods", None) or ():
            pares.add((rota.path, metodo))
    return sorted(pares)


TODAS_AS_ROTAS = _rotas_da_aplicacao()
ROTAS_DE_ESCRITA = [(c, m) for c, m in TODAS_AS_ROTAS if m in METODOS_QUE_ESCREVEM]
ROTAS_DE_LEITURA = [(c, m) for c, m in TODAS_AS_ROTAS if m in METODOS_QUE_LEEM]


def _detalhe(resposta) -> str | None:
    """O `detail` da resposta, ou None se ela nao for um erro em JSON."""
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    return corpo.get("detail") if isinstance(corpo, dict) else None


def _identificador(caso: tuple[str, str]) -> str:
    caminho, metodo = caso
    return f"{metodo} {caminho}"


def _url(caminho: str) -> str:
    """Preenche os parametros do caminho com valores que nao existem.

    Nao existirem e o ponto: a guarda corre antes do corpo da rota, portanto a
    recusa por falta de chave tem de acontecer na mesma sobre um sitio
    inventado. Se um destes pedidos chegasse a tocar na base, o teste estaria a
    medir outra coisa.
    """
    return (
        caminho
        .replace("{code}", "SITIO-QUE-NAO-EXISTE")
        .replace("{job_id}", "00000000-0000-0000-0000-000000000000")
    )


def test_o_inventario_cobre_todas_as_rotas_da_aplicacao():
    """Sem isto, um inventario vazio passava todos os testes deste ficheiro.

    Um `parametrize` sobre uma lista vazia recolhe zero casos e a suite fica
    verde por nao ter medido nada -- que e uma das formas de teste que nao pode
    falhar. Aqui conta-se: as duas listas juntas tem de dar todas as rotas, e
    tem de haver rotas dos dois lados.
    """
    assert len(ROTAS_DE_ESCRITA) + len(ROTAS_DE_LEITURA) == len(TODAS_AS_ROTAS), (
        "ha rotas com um metodo que nao esta em METODOS_QUE_ESCREVEM nem em "
        "METODOS_QUE_LEEM, e portanto ficaram por testar: "
        f"{sorted(set(TODAS_AS_ROTAS) - set(ROTAS_DE_ESCRITA) - set(ROTAS_DE_LEITURA))}"
    )
    assert len(ROTAS_DE_ESCRITA) >= 8
    assert len(ROTAS_DE_LEITURA) >= 8


@pytest.mark.parametrize("caso", ROTAS_DE_ESCRITA, ids=_identificador)
def test_rota_de_escrita_recusa_sem_chave_e_com_chave_errada(cliente_sem_chave, caso):
    """Um caso por rota que escreve. Uma rota nova sem guarda cai aqui."""
    caminho, metodo = caso
    url = _url(caminho)

    sem = cliente_sem_chave.request(metodo, url)
    errada = cliente_sem_chave.request(
        metodo, url, headers={auth.NOME_DO_CABECALHO: "nao-e-a-chave"}
    )

    assert sem.status_code == 401, f"{metodo} {caminho} escreveria sem credencial nenhuma"
    assert errada.status_code == 401, f"{metodo} {caminho} aceitou uma chave errada"
    assert _detalhe(sem) == RECUSA_DA_GUARDA
    assert _detalhe(errada) == RECUSA_DA_GUARDA
    # As duas recusas tem de ser indistinguiveis para quem esta a adivinhar:
    # se o corpo ou os cabecalhos diferissem, um pedido bastava para saber se
    # uma chave adivinhada chegou a ser comparada.
    assert sem.json() == errada.json()
    assert dict(sem.headers) == dict(errada.headers)


@pytest.mark.parametrize("caso", ROTAS_DE_ESCRITA, ids=_identificador)
def test_rota_de_escrita_deixa_passar_a_chave_certa(client, caso):
    """A guarda tem de recusar quem nao tem chave, e so esses.

    Sem este lado, uma guarda que recusasse toda a gente passava os testes
    acima -- e uma porta soldada nao e uma fechadura. O que se exige aqui e so
    que a resposta ja nao seja a da guarda; qual e ela (404 pelo sitio que nao
    existe, 422 pelo corpo em falta, 503 do Copernicus por credenciais que esta
    rota precisa e a guarda nao) e assunto da rota e nao deste teste -- e por
    isso olha-se para a mensagem e nao so para o numero.
    """
    caminho, metodo = caso
    resposta = client.request(metodo, _url(caminho))
    assert resposta.status_code != 401, f"{metodo} {caminho} recusou uma chave certa"
    assert _detalhe(resposta) not in (RECUSA_DA_GUARDA, RECUSA_POR_CHAVE_NAO_CONFIGURADA), (
        f"{metodo} {caminho} respondeu com a recusa da guarda a um pedido com a chave certa"
    )


@pytest.mark.parametrize("caso", ROTAS_DE_LEITURA, ids=_identificador)
def test_rota_de_leitura_responde_sem_chave(cliente_sem_chave, caso):
    """O outro sentido da fronteira: ler nao pede credencial.

    Cai se alguem puser a guarda numa leitura -- incluindo em `/health`, que e
    a que uma sonda de disponibilidade chama sem cabecalho nenhum.
    """
    caminho, metodo = caso
    resposta = cliente_sem_chave.request(metodo, _url(caminho))
    assert resposta.status_code != 401, f"{metodo} {caminho} passou a pedir chave, e e uma leitura"
    assert _detalhe(resposta) not in (RECUSA_DA_GUARDA, RECUSA_POR_CHAVE_NAO_CONFIGURADA), (
        f"{metodo} {caminho} respondeu com a recusa da guarda, e e uma leitura"
    )


def test_a_comparacao_e_em_tempo_constante(cliente_sem_chave, monkeypatch):
    """Prova que a chave passa por `hmac.compare_digest` e nao por `==`.

    Nao se mede tempo: uma medicao de tempo numa suite de testes e uma fonte de
    instabilidade, e a diferenca que interessa esta abaixo do ruido de qualquer
    maquina partilhada. Mede-se a chamada. Um `==` no lugar da comparacao
    passaria por aqui sem tocar em `compare_digest`, e a lista fica vazia.
    """
    chamadas = []
    verdadeira = hmac.compare_digest

    def espia(a, b):
        chamadas.append((a, b))
        return verdadeira(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", espia)
    cliente_sem_chave.post(
        "/api/v1/observations", headers={auth.NOME_DO_CABECALHO: "nao-e-a-chave"}
    )

    assert chamadas, "a chave apresentada nao passou por hmac.compare_digest"
    apresentada, esperada = chamadas[0]
    assert apresentada == b"nao-e-a-chave"
    assert esperada == CHAVE_DE_ESCRITA_DOS_TESTES.encode("utf-8")


class _SemChaveConfigurada:
    """Definicoes de uma instalacao que se esqueceu do segredo."""

    def __init__(self, valor):
        self.write_api_key = valor


@pytest.mark.parametrize("valor_da_definicao", [None, ""], ids=["nao-definida", "vazia"])
@pytest.mark.parametrize("caso", ROTAS_DE_ESCRITA, ids=_identificador)
def test_sem_chave_configurada_a_escrita_fecha_em_vez_de_abrir(
    cliente_sem_chave, monkeypatch, caso, valor_da_definicao
):
    """Uma chave por configurar fecha as escritas; nunca as abre.

    E a falha que uma guarda escrita de forma natural comete: `if esperada:` a
    volta da conferencia deixa passar tudo precisamente na instalacao que se
    esqueceu do segredo. Aqui exige-se 503 -- e exige-se tambem que nem sequer
    a chave certa sirva, porque nao ha chave certa quando nao ha chave.
    """
    caminho, metodo = caso
    monkeypatch.setattr(auth, "get_settings", lambda: _SemChaveConfigurada(valor_da_definicao))
    url = _url(caminho)

    sem = cliente_sem_chave.request(metodo, url)
    com = cliente_sem_chave.request(
        metodo, url, headers={auth.NOME_DO_CABECALHO: CHAVE_DE_ESCRITA_DOS_TESTES}
    )

    for resposta, o_que in ((sem, "sem cabecalho"), (com, "com a chave dos testes")):
        assert resposta.status_code == 503, (
            f"{metodo} {caminho} ({o_que}) nao fechou sem chave configurada"
        )
        # A mensagem tem de ser a da guarda. Sem esta linha, o 503 que a rota
        # do Copernicus da por falta das SUAS credenciais passava por este
        # teste sem a guarda ter corrido.
        assert _detalhe(resposta) == RECUSA_POR_CHAVE_NAO_CONFIGURADA, (
            f"{metodo} {caminho} ({o_que}) deu 503, mas nao foi a guarda a recusar"
        )


@pytest.mark.parametrize("valor_da_definicao", [None, ""], ids=["nao-definida", "vazia"])
def test_uma_chave_vazia_apresentada_nao_casa_com_uma_chave_vazia_configurada(
    cliente_sem_chave, monkeypatch, valor_da_definicao
):
    """O caso que uma comparacao ingenua deixaria passar.

    `compare_digest(b"", b"")` e True. Se a guarda so comparasse, um servidor
    com `WRITE_API_KEY=` vazia aceitaria um `X-API-Key:` vazio -- credencial
    nenhuma a casar com credencial nenhuma.
    """
    monkeypatch.setattr(auth, "get_settings", lambda: _SemChaveConfigurada(valor_da_definicao))
    resposta = cliente_sem_chave.post(
        "/api/v1/observations", headers={auth.NOME_DO_CABECALHO: ""}
    )
    assert resposta.status_code == 503
    assert _detalhe(resposta) == RECUSA_POR_CHAVE_NAO_CONFIGURADA


def test_a_recusa_nao_deixa_sair_a_chave_por_lado_nenhum(cliente_sem_chave, caplog):
    """Nem a chave, nem um prefixo dela, nem o comprimento.

    O comprimento conta como fuga: dizer que a chave tem 51 caracteres corta o
    espaco de procura, e um registo que o diga escreve-o em todas as recusas.
    """
    chave = CHAVE_DE_ESCRITA_DOS_TESTES
    with caplog.at_level("DEBUG"):
        sem = cliente_sem_chave.post("/api/v1/observations")
        errada = cliente_sem_chave.post(
            "/api/v1/observations", headers={auth.NOME_DO_CABECALHO: "nao-e-a-chave"}
        )

    prefixos = [chave[:n] for n in range(PREFIXO_QUE_JA_E_FUGA, len(chave) + 1)]
    superficies = {
        "corpo (sem cabecalho)": sem.text,
        "corpo (chave errada)": errada.text,
        "cabecalhos (sem cabecalho)": str(dict(sem.headers)),
        "cabecalhos (chave errada)": str(dict(errada.headers)),
        "registo": caplog.text,
    }
    for onde, texto in superficies.items():
        for prefixo in prefixos:
            assert prefixo not in texto, f"{onde} deixa sair um prefixo da chave"
        assert str(len(chave)) not in texto, f"{onde} deixa sair o comprimento da chave"


def test_o_openapi_nao_contem_a_chave():
    """A documentacao gerada e publica, e serve-se do mesmo processo."""
    import json

    texto = json.dumps(app.openapi())
    assert CHAVE_DE_ESCRITA_DOS_TESTES not in texto
    assert CHAVE_DE_ESCRITA_DOS_TESTES[:PREFIXO_QUE_JA_E_FUGA] not in texto


def test_o_registo_distingue_o_que_a_resposta_nao_distingue(cliente_sem_chave, caplog):
    """Para quem depura sao dois casos; para quem ataca sao um so.

    A distincao vai para o registo do servidor -- que quem faz o pedido nao ve
    -- e nao para a resposta. As respostas serem iguais esta preso, rota a
    rota, em `test_rota_de_escrita_recusa_sem_chave_e_com_chave_errada`.
    """
    with caplog.at_level("WARNING", logger=auth.logger.name):
        cliente_sem_chave.post("/api/v1/observations")
        sem_cabecalho = caplog.text
        caplog.clear()
        cliente_sem_chave.post(
            "/api/v1/observations", headers={auth.NOME_DO_CABECALHO: "nao-e-a-chave"}
        )
        chave_errada = caplog.text

    assert "no X-API-Key header" in sem_cabecalho
    assert "did not match" in chave_errada
    assert sem_cabecalho != chave_errada


@pytest.mark.parametrize("caso", ROTAS_DE_ESCRITA, ids=_identificador)
def test_o_openapi_declara_a_chave_em_cada_rota_de_escrita(caso):
    """Requisito 5: o `/docs` nao pode mentir sobre o que a rota precisa.

    Tambem por rota, e pela mesma razao: uma rota nova que leve a guarda no
    codigo mas nao apareca na documentacao e uma pagina que engana quem a le.
    """
    caminho, metodo = caso
    operacao = app.openapi()["paths"][caminho][metodo.lower()]
    assert operacao.get("security") == [{"WriteApiKey": []}], (
        f"{metodo} {caminho} escreve mas o /docs nao diz que precisa de chave"
    )


@pytest.mark.parametrize("caso", ROTAS_DE_LEITURA, ids=_identificador)
def test_o_openapi_nao_declara_chave_nas_leituras(caso):
    caminho, metodo = caso
    documentadas = app.openapi()["paths"]
    if caminho not in documentadas or metodo.lower() not in documentadas[caminho]:
        pytest.skip("rota fora do esquema (documentacao gerada pelo proprio FastAPI)")
    assert documentadas[caminho][metodo.lower()].get("security") is None, (
        f"{metodo} {caminho} aparece no /docs a pedir chave, e e uma leitura"
    )
