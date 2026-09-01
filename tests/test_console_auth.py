"""A senha a porta da consola.

**Estes testes nao sao uma amostra, sao um inventario.** As rotas da consola nao
estao escritas a mao aqui: sao lidas de `app.routes` no momento da recolha,
filtradas pelo prefixo, e cada uma gera os seus proprios casos. Uma rota da
consola acrescentada amanha sem guarda -- porque nasceu num router novo
registado sem `dependencies=EXIGE_SENHA_DA_CONSOLA`, ou porque alguem lhe deu um
router proprio -- faz nascer casos novos, e esses casos caem, sem que ninguem se
lembre de vir aqui acrescentar nada. E o mesmo desenho de `test_api_auth.py`, e
existe pela mesma razao: um teste que cobre uma rota e presume as outras nao
defende nada.

⚠️ **O apanha-tudo e a razao numero um para o inventario ser derivado.**
`/console/{caminho:path}` apanha tudo o que esteja sob `/console`. Uma folha de
estilo sem guarda nao expoe dados; uma rota de dados que caia no apanha-tudo sem
passar pela guarda expoe. Nao ha aqui isencao nenhuma -- a lista de rotas da
consola e a lista de rotas guardadas, e `test_o_inventario_da_consola_nao_tem_isencoes`
exige que continuem a ser a mesma lista.

O que impede o inventario de ser vazio (uma lista vazia faz o `parametrize`
recolher zero casos e passar sem ter medido nada) e
`test_o_inventario_conta_as_rotas_da_consola_e_as_outras`.

**O que estes testes NAO medem, e fica dito:** nao medem tempo. A comparacao ser
em tempo constante mede-se pela chamada e pelo numero de chamadas
(`test_o_par_apresentado_passa_por_uma_unica_comparacao_em_tempo_constante`), e
nao por um cronometro -- a diferenca que interessa esta abaixo do ruido de
qualquer maquina partilhada, e uma medicao de tempo numa suite e uma fonte de
instabilidade.
"""

import base64
import hmac
import json

import pytest

from resoiltwin.api import console_auth
from resoiltwin.api.console import PREFIXO_DA_CONSOLA
from resoiltwin.main import app
from tests.conftest import (
    SENHA_DA_CONSOLA_DOS_TESTES,
    UTILIZADOR_DA_CONSOLA_DOS_TESTES,
    cabecalho_da_consola,
)
from tests.test_api_auth import ROTAS_SEM_GUARDA, _rotas_de

# As duas recusas da guarda, escritas aqui a mao e nao importadas de
# `console_auth`. Importa-las tornava o teste circular -- seguia a mensagem para
# onde ela fosse --, e sao elas que distinguem uma recusa da guarda de uma
# recusa da rota. A distincao nao e teorica: a camada da consola devolve 404
# sozinha para um caminho que nao seja leitura desta API, e um teste que so
# olhasse para o numero passava por causa dela sem a guarda ter corrido.
RECUSA_DA_PORTA = "Console access requires credentials"
RECUSA_POR_SENHA_NAO_CONFIGURADA = "Console access is not configured on this server"

# A partir de quantos caracteres um pedaco da senha conta como fuga. O mesmo
# criterio e o mesmo argumento de `test_api_auth.py`: tres aparece por acaso em
# texto normal, seis nao.
PREFIXO_QUE_JA_E_FUGA = 6


def _rotas_da_consola(aplicacao) -> list[tuple[str, str]]:
    """Todo o par (caminho, metodo) que a aplicacao serve sob `/console`.

    Derivado do encaminhador e nao escrito a mao -- e essa a unica razao por que
    uma rota nova aparece aqui sozinha. O filtro e o prefixo e mais nada: nao ha
    lista de nomes, nao ha lista de modulos, e uma rota da consola registada de
    qualquer maneira que ponha o caminho sob `/console` entra no inventario.
    """
    return [
        (caminho, metodo)
        for caminho, metodo in _rotas_de(aplicacao)
        if caminho == PREFIXO_DA_CONSOLA or caminho.startswith(PREFIXO_DA_CONSOLA + "/")
    ]


TODAS_AS_ROTAS = _rotas_de(app)
ROTAS_DA_CONSOLA = _rotas_da_consola(app)
ROTAS_FORA_DA_CONSOLA = [par for par in TODAS_AS_ROTAS if par not in ROTAS_DA_CONSOLA]


def _identificador(caso: tuple[str, str]) -> str:
    caminho, metodo = caso
    return f"{metodo} {caminho}"


def _url(caminho: str) -> str:
    """O apanha-tudo com o parametro preenchido por um caminho que nao existe.

    Nao existir e o ponto: a guarda corre antes do corpo da rota, portanto a
    recusa tem de acontecer na mesma sobre um caminho inventado. Se um destes
    pedidos chegasse a tocar na base, o teste estaria a medir outra coisa.
    """
    return caminho.replace("{caminho:path}", "caminho-que-nao-existe")


def _detalhe(resposta) -> str | None:
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    return corpo.get("detail") if isinstance(corpo, dict) else None


class _SemSenhaConfigurada:
    """Definicoes de uma instalacao a que falta metade do par, ou o par todo.

    O nome fala da senha porque foi o caso que veio primeiro, mas o utilizador
    conta tanto como ela: uma instalacao que defina a senha e esqueca o
    utilizador nao esta meio protegida, esta aberta a quem apresente utilizador
    vazio e a senha -- e a senha, num par que so tem metade, e um segredo unico
    partilhado que ninguem tratou como tal.
    """

    def __init__(self, senha, utilizador=UTILIZADOR_DA_CONSOLA_DOS_TESTES):
        self.console_user = utilizador
        self.console_password = senha


# ---------------------------------------------------------------------------
# Os pisos: sem eles, um inventario vazio passava tudo o que esta abaixo.
# ---------------------------------------------------------------------------


def test_o_inventario_conta_as_rotas_da_consola_e_as_outras():
    """Sem isto, um inventario vazio deixava esta suite verde sem medir nada.

    Um `parametrize` sobre uma lista vazia recolhe zero casos e a suite fica
    verde por nao ter olhado para nada -- que e uma das formas de teste que nao
    pode falhar. Aqui conta-se, e exige-se que haja rotas dos dois lados.
    """
    assert len(ROTAS_DA_CONSOLA) + len(ROTAS_FORA_DA_CONSOLA) == len(TODAS_AS_ROTAS)
    # Sete: o apanha-tudo, a folha de estilo, e as cinco das tres vistas
    # (`/console` e `/console/` sao dois caminhos e nao um, e a vista das
    # observacoes serve os tres). O numero e um piso e nao uma igualdade -- uma
    # rota da consola nova deve fazer cair o SEU caso, e nao este.
    assert len(ROTAS_DA_CONSOLA) >= 7
    # E tem de haver rotas fora da consola, ou o filtro esta a apanhar tudo e o
    # inventario deixou de significar o que diz.
    assert len(ROTAS_FORA_DA_CONSOLA) >= 20


def test_o_inventario_e_lido_da_aplicacao_e_nao_escrito_a_mao():
    """O leitor tem de ver uma rota de consola que ninguem lhe foi dizer que existia.

    Um leitor que devolvesse uma lista fixa passava todos os casos deste ficheiro
    -- estariam todos certos sobre as rotas de hoje -- e deixava de gerar caso
    nenhum para a rota de amanha, que e a unica coisa que este inventario existe
    para fazer.

    **O que isto ainda nao apanha**, e fica dito para nao passar por mais do que
    e: uma lista escrita a mao que por acaso seja exactamente a de hoje passa por
    aqui e passa por tudo o resto, e so mente amanha. Quem o apanha e a
    verificacao feita fora da suite -- acrescentar uma rota de consola numa copia
    da arvore e confirmar que nascem casos novos e que eles caem.
    """
    from fastapi import FastAPI

    de_brincar = FastAPI()

    @de_brincar.get(PREFIXO_DA_CONSOLA + "/rota-de-consola-que-a-real-nao-tem")
    def _rota_de_brincar():
        return {}

    @de_brincar.get("/fora-da-consola")
    def _outra_rota_de_brincar():
        return {}

    lido = _rotas_da_consola(de_brincar)
    assert (PREFIXO_DA_CONSOLA + "/rota-de-consola-que-a-real-nao-tem", "GET") in lido
    # E o filtro tem de ser um filtro: uma rota fora do prefixo nao entra.
    assert ("/fora-da-consola", "GET") not in lido
    # E o inventario deste ficheiro e o que sai do leitor sobre a aplicacao
    # real, sem nada pelo meio.
    assert ROTAS_DA_CONSOLA == _rotas_da_consola(app)


def test_a_superficie_da_consola_nao_cresce_em_silencio():
    """Duas coisas de uma vez, e as duas sao deliberadas.

    **Nao ha lista de excepcoes, e essa ausencia e uma decisao.** A guarda da API
    tem uma (`ROTAS_SEM_GUARDA`), porque a sonda de saude nao tem onde por um
    cabecalho. Aqui nao ha razao equivalente: um navegador poe sempre o cabecalho
    depois de a caixa de credenciais aparecer, a folha de estilo incluida. Uma
    isencao futura tem de ser escrita como codigo, e nao pode nascer de um filtro
    que se alargou.

    **E uma rota da consola nova tem de vir aqui.** A igualdade e exacta de
    proposito: os casos gerados abaixo ja fazem cair uma rota nova que fique sem
    guarda, e este exige que mesmo uma rota nova COM guarda passe pelos olhos de
    alguem. Numa consola publicada, o que ela serve e uma decisao e nao um
    detalhe de encaminhamento.
    """
    caminhos = {caminho for caminho, _ in ROTAS_DA_CONSOLA}
    assert caminhos == {
        PREFIXO_DA_CONSOLA,
        PREFIXO_DA_CONSOLA + "/",
        PREFIXO_DA_CONSOLA + "/estilo.css",
        PREFIXO_DA_CONSOLA + "/observacoes",
        PREFIXO_DA_CONSOLA + "/sincronizacoes",
        PREFIXO_DA_CONSOLA + "/sitios",
        PREFIXO_DA_CONSOLA + "/{caminho:path}",
    }


def test_toda_a_rota_isenta_da_chave_da_api_ou_e_o_health_ou_pede_senha():
    """A invariante que liga as duas guardas, e que nenhuma delas ve sozinha.

    `test_api_auth.py` mede que uma rota isenta da chave da API responde sem ela.
    Este ficheiro mede que uma rota da consola pede senha. O que faltava era a
    juncao: **uma rota isenta da chave da API que nao seja o `/health` tem de ser
    uma rota da consola** -- e portanto, pelos casos gerados abaixo, tem de pedir
    senha. Sem esta linha, uma isencao nova acrescentada a `ROTAS_SEM_GUARDA`
    para uma rota fora de `/console` nascia sem guarda nenhuma, e nenhum dos dois
    ficheiros dava por isso.
    """
    da_consola = set(ROTAS_DA_CONSOLA)
    for par in ROTAS_SEM_GUARDA:
        assert par == ("/api/v1/health", "GET") or par in da_consola, (
            f"{_identificador(par)} nao pede a chave da API e nao e uma rota da consola"
        )


# ---------------------------------------------------------------------------
# Um caso por rota da consola. Uma rota nova sem guarda cai aqui.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("caso", ROTAS_DA_CONSOLA, ids=_identificador)
def test_rota_da_consola_recusa_sem_credencial(cliente_a_porta, caso):
    """Quem so conhece o endereco nao passa da porta."""
    caminho, metodo = caso
    resposta = cliente_a_porta.request(metodo, _url(caminho))
    assert resposta.status_code == 401, (
        f"{metodo} {caminho} responde sem credencial nenhuma"
    )
    assert _detalhe(resposta) == RECUSA_DA_PORTA, (
        f"{metodo} {caminho} deu 401, mas nao foi a porta a recusar"
    )


@pytest.mark.parametrize("caso", ROTAS_DA_CONSOLA, ids=_identificador)
def test_rota_da_consola_pede_credenciais_ao_navegador(cliente_a_porta, caso):
    """Sem o `WWW-Authenticate`, o 401 e uma parede e nao uma porta.

    E o cabecalho que faz o navegador abrir a caixa que pede o par. Sem ele,
    quem tem a senha nao tem onde a escrever -- e a consola fica fechada a toda
    a gente, que nao e o que se decidiu.
    """
    caminho, metodo = caso
    resposta = cliente_a_porta.request(metodo, _url(caminho))
    desafio = resposta.headers.get("www-authenticate")
    assert desafio is not None, f"{metodo} {caminho} recusa e nao pede credenciais"
    assert desafio.lower().startswith("basic "), desafio
    assert console_auth.REINO in desafio


@pytest.mark.parametrize("caso", ROTAS_DA_CONSOLA, ids=_identificador)
def test_rota_da_consola_nao_distingue_utilizador_errado_de_senha_errada(
    cliente_a_porta, caso
):
    """As duas recusas tem de ser identicas, byte a byte.

    Se diferissem -- no codigo, no corpo ou nos cabecalhos --, um pedido bastava
    para saber que o utilizador estava certo, e quem esta a adivinhar ficava com
    meio problema em vez de um problema inteiro.
    """
    caminho, metodo = caso
    url = _url(caminho)

    utilizador_errado = cliente_a_porta.request(
        metodo, url,
        headers=cabecalho_da_consola(utilizador="nao-e-o-utilizador"),
    )
    senha_errada = cliente_a_porta.request(
        metodo, url, headers=cabecalho_da_consola(senha="nao-e-a-senha"),
    )

    assert utilizador_errado.status_code == 401, f"{metodo} {caminho} aceitou outro utilizador"
    assert senha_errada.status_code == 401, f"{metodo} {caminho} aceitou outra senha"
    assert utilizador_errado.content == senha_errada.content
    assert dict(utilizador_errado.headers) == dict(senha_errada.headers)


@pytest.mark.parametrize("caso", ROTAS_DA_CONSOLA, ids=_identificador)
def test_rota_da_consola_deixa_passar_o_par_certo(client, caso):
    """A guarda tem de recusar quem nao tem o par, e so esses.

    Sem este lado, uma guarda que recusasse toda a gente passava os testes acima
    -- e uma porta soldada nao e uma fechadura. O que se exige e so que a
    resposta ja nao seja a da porta; qual e ela (404 do apanha-tudo por um
    caminho que nao existe, 200 de uma pagina) e assunto da rota.
    """
    caminho, metodo = caso
    resposta = client.request(metodo, _url(caminho))
    assert resposta.status_code != 401, f"{metodo} {caminho} recusou o par certo"
    assert _detalhe(resposta) not in (RECUSA_DA_PORTA, RECUSA_POR_SENHA_NAO_CONFIGURADA), (
        f"{metodo} {caminho} respondeu com a recusa da porta a um pedido com o par certo"
    )


@pytest.mark.parametrize("valor_da_definicao", [None, ""], ids=["nao-definida", "vazia"])
@pytest.mark.parametrize("caso", ROTAS_DA_CONSOLA, ids=_identificador)
def test_sem_senha_configurada_a_consola_fecha_em_vez_de_abrir(
    cliente_a_porta, monkeypatch, caso, valor_da_definicao
):
    """Uma senha por configurar fecha a consola; nunca a abre.

    E a falha que uma guarda escrita de forma natural comete: sem a recusa
    explicita, o par apresentado por quem nao manda cabecalho nenhum e `("", "")`
    e o par esperado tambem -- credencial nenhuma a casar com credencial nenhuma,
    e a consola aberta precisamente na instalacao que se esqueceu do segredo.

    Exige-se tambem que nem sequer o par certo sirva, porque nao ha par certo
    quando nao ha senha.
    """
    caminho, metodo = caso
    monkeypatch.setattr(
        console_auth, "get_settings", lambda: _SemSenhaConfigurada(valor_da_definicao)
    )
    url = _url(caminho)

    sem = cliente_a_porta.request(metodo, url)
    com = cliente_a_porta.request(metodo, url, headers=cabecalho_da_consola())

    for resposta, o_que in ((sem, "sem cabecalho"), (com, "com o par dos testes")):
        assert resposta.status_code == 503, (
            f"{metodo} {caminho} ({o_que}) nao fechou sem senha configurada"
        )
        assert _detalhe(resposta) == RECUSA_POR_SENHA_NAO_CONFIGURADA, (
            f"{metodo} {caminho} ({o_que}) deu 503, mas nao foi a porta a recusar"
        )


@pytest.mark.parametrize("valor_da_definicao", [None, ""], ids=["nao-definido", "vazio"])
@pytest.mark.parametrize("caso", ROTAS_DA_CONSOLA, ids=_identificador)
def test_sem_utilizador_configurado_a_consola_fecha_tambem(
    cliente_a_porta, monkeypatch, caso, valor_da_definicao
):
    """Metade do par em falta fecha, tal como o par inteiro.

    O caso simetrico do teste acima, e o que faltava ate 01/09/2026: la a senha
    e que estava por definir e o utilizador estava posto. Aqui e ao contrario --
    e a guarda tem de recusar na mesma.

    Sem isto, uma guarda escrita como `if not senha_esperada:` passa a suite
    inteira, e numa instalacao que defina a senha e esqueca o utilizador o par
    esperado passa a ser `("", senha)`: quem apresentar utilizador vazio e a
    senha entra. Nao e uma instalacao meio protegida, e uma instalacao aberta a
    quem souber metade -- e a senha, sozinha, deixou de ser um par para ser um
    segredo unico que ninguem decidiu partilhar assim.

    Exige-se tambem que nem o par dos testes sirva: nao ha par certo quando o
    par nao esta inteiro.
    """
    caminho, metodo = caso
    monkeypatch.setattr(
        console_auth,
        "get_settings",
        lambda: _SemSenhaConfigurada(SENHA_DA_CONSOLA_DOS_TESTES, valor_da_definicao),
    )
    url = _url(caminho)

    sem = cliente_a_porta.request(metodo, url)
    com = cliente_a_porta.request(metodo, url, headers=cabecalho_da_consola())
    vazio = cliente_a_porta.request(
        metodo, url, headers=cabecalho_da_consola(utilizador="")
    )

    for resposta, o_que in (
        (sem, "sem cabecalho"),
        (com, "com o par dos testes"),
        (vazio, "com utilizador vazio e a senha certa"),
    ):
        assert resposta.status_code == 503, (
            f"{metodo} {caminho} ({o_que}) nao fechou sem utilizador configurado"
        )
        assert _detalhe(resposta) == RECUSA_POR_SENHA_NAO_CONFIGURADA, (
            f"{metodo} {caminho} ({o_que}) deu 503, mas nao foi a porta a recusar"
        )


@pytest.mark.parametrize("caso", ROTAS_FORA_DA_CONSOLA, ids=_identificador)
def test_a_senha_da_consola_nao_toca_no_resto_da_api(client, caso):
    """O outro sentido da fronteira: a porta e da consola e de mais nada.

    Cai se alguem puser a guarda da consola num router da API -- que passaria a
    responder 401 a quem apresenta a chave certa, ou 503 numa instalacao sem
    senha da consola. O `/health` esta ca dentro, e e o caso que mais importa:
    uma guarda a mais ali nao aperta o sistema, desliga-o.
    """
    caminho, metodo = caso
    url = (
        caminho
        .replace("{code}", "SITIO-QUE-NAO-EXISTE")
        .replace("{job_id}", "00000000-0000-0000-0000-000000000000")
    )
    resposta = client.request(metodo, url)
    if metodo == "HEAD":
        # Sem corpo, por protocolo. O caso GET do mesmo caminho le o detalhe --
        # as unicas rotas que servem HEAD sao as quatro da documentacao, e todas
        # servem GET tambem.
        assert resposta.status_code != 503
        return
    assert _detalhe(resposta) not in (RECUSA_DA_PORTA, RECUSA_POR_SENHA_NAO_CONFIGURADA), (
        f"{metodo} {caminho} passou pela guarda da consola, e nao e da consola"
    )


def test_sem_senha_configurada_o_resto_da_api_continua_a_responder(client, monkeypatch):
    """Uma instalacao sem senha da consola tem de continuar a servir a API.

    E metade da razao por que a falta da senha nao impede o arranque: a sonda
    continua a receber 200, a API continua a responder a quem tem a chave, e o
    que fecha e a consola. Se a aplicacao se recusasse a arrancar, uma variavel
    em falta na parte menos critica desligava a mais critica.
    """
    monkeypatch.setattr(console_auth, "get_settings", lambda: _SemSenhaConfigurada(None))
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/sites").status_code == 200


# ---------------------------------------------------------------------------
# A comparacao
# ---------------------------------------------------------------------------


def test_o_par_apresentado_passa_por_uma_unica_comparacao_em_tempo_constante(
    cliente_a_porta, monkeypatch
):
    """Prova duas coisas de uma vez, e as duas sao a mesma decisao.

    **Que passa por `hmac.compare_digest`**: um `==` no lugar da comparacao
    passaria por aqui sem tocar em `compare_digest`, e a lista ficava vazia.

    **Que ha UMA chamada e nao duas**: comparar o utilizador e a senha
    separadamente -- mesmo em tempo constante cada uma -- diz, pelo tempo total,
    qual dos dois campos estava errado. Duas chamadas fazem este teste cair.

    E exige-se o comprimento fixo: 64 bytes dos dois lados, sejam quais forem os
    comprimentos do que foi apresentado. Sem isso, o tempo da comparacao passava
    a depender de um comprimento escolhido por quem faz o pedido.
    """
    chamadas = []
    verdadeira = hmac.compare_digest

    def espia(a, b):
        chamadas.append((a, b))
        return verdadeira(a, b)

    monkeypatch.setattr(console_auth.hmac, "compare_digest", espia)
    cliente_a_porta.get(
        "/console/observacoes",
        headers=cabecalho_da_consola(utilizador="qualquer", senha="nao-e-a-senha"),
    )

    assert chamadas, "o par apresentado nao passou por hmac.compare_digest"
    assert len(chamadas) == 1, (
        "o par foi comparado em mais do que uma passagem: o tempo total diz "
        "qual dos dois campos estava errado"
    )
    apresentado, esperado = chamadas[0]
    assert len(apresentado) == 64 and len(esperado) == 64
    assert apresentado != esperado


def test_o_par_certo_e_o_que_a_configuracao_diz():
    """A impressao esperada e a do par configurado, e nao uma constante do modulo.

    Sem isto, uma guarda que comparasse contra um par escrito no codigo passava
    todos os testes acima -- e a senha deixava de vir da configuracao sem que
    nada caisse.
    """
    esperada = console_auth._impressao(
        UTILIZADOR_DA_CONSOLA_DOS_TESTES, SENHA_DA_CONSOLA_DOS_TESTES
    )
    assert console_auth._impressao("outro", SENHA_DA_CONSOLA_DOS_TESTES) != esperada
    assert console_auth._impressao(UTILIZADOR_DA_CONSOLA_DOS_TESTES, "outra") != esperada


def test_a_impressao_nao_confunde_o_utilizador_com_a_senha():
    """`a:b` + `c` e `a` + `b:c` sao pares diferentes, e tem de o continuar a ser.

    Um `sha256` sobre `utilizador:senha` colado dava a mesma impressao aos dois,
    e entao um par que ninguem configurou abria a consola.
    """
    assert console_auth._impressao("a:b", "c") != console_auth._impressao("a", "b:c")


@pytest.mark.parametrize(
    "cabecalho",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Basic"},
        {"Authorization": "Bearer " + base64.b64encode(b"u:p").decode()},
        {"Authorization": "Basic nao-e-base64!!"},
        {"Authorization": "Basic " + base64.b64encode(b"sem-dois-pontos").decode()},
        {"Authorization": "Basic " + base64.b64encode(b"\xff\xfe").decode()},
    ],
    ids=["ausente", "vazio", "sem-parametro", "esquema-errado", "base64-partido",
         "sem-dois-pontos", "bytes-que-nao-sao-utf8"],
)
def test_um_cabecalho_torcido_da_a_mesma_recusa_que_um_par_errado(cliente_a_porta, cabecalho):
    """Quatro maneiras de mandar lixo, uma unica resposta.

    O `HTTPBasic` do FastAPI responde a algumas destas com outro texto, e entao
    passariam a existir duas respostas distintas para quem esta a experimentar.
    E por isso que o cabecalho e lido a mao (escolha 4 do cabecalho do modulo).
    """
    normal = cliente_a_porta.get(
        "/console/observacoes", headers=cabecalho_da_consola(senha="nao-e-a-senha")
    )
    torcido = cliente_a_porta.get("/console/observacoes", headers=cabecalho)

    assert torcido.status_code == normal.status_code == 401
    assert torcido.content == normal.content
    assert dict(torcido.headers) == dict(normal.headers)


# ---------------------------------------------------------------------------
# A senha nao sai
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cabecalho",
    [None, "errado"],
    ids=["sem-cabecalho", "par-errado"],
)
def test_a_recusa_nao_deixa_sair_a_senha_por_lado_nenhum(cliente_a_porta, caplog, cabecalho):
    """Nem a senha, nem um prefixo dela, nem o comprimento.

    O comprimento conta como fuga: dizer que a senha tem 52 caracteres corta o
    espaco de procura, e um registo que o diga escreve-o em todas as recusas.
    """
    senha = SENHA_DA_CONSOLA_DOS_TESTES
    cabecalhos = cabecalho_da_consola(senha="nao-e-a-senha") if cabecalho else {}
    with caplog.at_level("DEBUG"):
        resposta = cliente_a_porta.get("/console/observacoes", headers=cabecalhos)

    prefixos = [senha[:n] for n in range(PREFIXO_QUE_JA_E_FUGA, len(senha) + 1)]
    superficies = {
        "corpo": resposta.text,
        "cabecalhos": str(dict(resposta.headers)),
        "registo": caplog.text,
    }
    for onde, texto in superficies.items():
        for prefixo in prefixos:
            assert prefixo not in texto, f"{onde} deixa sair um prefixo da senha"
        assert str(len(senha)) not in texto, f"{onde} deixa sair o comprimento da senha"


def test_a_senha_nao_aparece_em_pagina_nenhuma_da_consola(client):
    """A porta abriu, e a senha nao entrou com quem passou.

    Um cabecalho de resposta, um comentario no HTML, um campo escondido num
    formulario: qualquer um deles punha a senha no navegador de quem ja entrou,
    e a partir dai em qualquer sitio onde essa pagina fosse guardada.
    """
    senha = SENHA_DA_CONSOLA_DOS_TESTES
    for caminho in ("/console/observacoes", "/console/sincronizacoes", "/console/sitios",
                    "/console/estilo.css"):
        resposta = client.get(caminho)
        assert resposta.status_code == 200, caminho
        for superficie in (resposta.text, str(dict(resposta.headers))):
            assert senha[:PREFIXO_QUE_JA_E_FUGA] not in superficie, caminho
            assert UTILIZADOR_DA_CONSOLA_DOS_TESTES not in superficie, caminho


def test_o_openapi_nao_contem_a_senha():
    """As rotas da consola estao fora do esquema, e isso nao autoriza a levar la a senha."""
    texto = json.dumps(app.openapi())
    assert SENHA_DA_CONSOLA_DOS_TESTES not in texto
    assert SENHA_DA_CONSOLA_DOS_TESTES[:PREFIXO_QUE_JA_E_FUGA] not in texto
    assert UTILIZADOR_DA_CONSOLA_DOS_TESTES not in texto


def test_o_registo_distingue_o_que_a_resposta_nao_distingue(cliente_a_porta, caplog):
    """Para quem depura sao dois casos; para quem ataca sao um so.

    A distincao vai para o registo do servidor -- que quem faz o pedido nao ve
    -- e nao para a resposta. As respostas serem iguais esta preso, rota a rota,
    em `test_rota_da_consola_nao_distingue_utilizador_errado_de_senha_errada`.
    """
    with caplog.at_level("WARNING", logger=console_auth.logger.name):
        cliente_a_porta.get("/console/observacoes")
        sem_cabecalho = caplog.text
        caplog.clear()
        cliente_a_porta.get(
            "/console/observacoes", headers=cabecalho_da_consola(senha="nao-e-a-senha")
        )
        par_errado = caplog.text

    assert "missing credentials" in sem_cabecalho
    assert "wrong credentials" in par_errado
    assert sem_cabecalho != par_errado


def test_o_registo_nao_escreve_o_que_foi_apresentado(cliente_a_porta, caplog):
    """Um utilizador apresentado e muitas vezes metade de um par escrito a pressa.

    Um registo que o guarde guarda tambem, mais cedo ou mais tarde, uma senha
    escrita no campo errado.
    """
    with caplog.at_level("DEBUG"):
        cliente_a_porta.get(
            "/console/observacoes",
            headers=cabecalho_da_consola(
                utilizador="utilizador-inventado-por-quem-tenta",
                senha="senha-inventada-por-quem-tenta",
            ),
        )
    assert "utilizador-inventado-por-quem-tenta" not in caplog.text
    assert "senha-inventada-por-quem-tenta" not in caplog.text
