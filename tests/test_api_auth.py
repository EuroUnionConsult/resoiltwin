"""A chave partilhada, agora em todas as rotas menos uma.

**Estes testes nao sao uma amostra, sao um inventario.** As rotas nao estao
escritas a mao aqui: sao lidas de `app.routes` no momento da recolha, e cada
uma gera o seu proprio caso. Uma rota acrescentada amanha sem guarda -- porque
o `include_router` foi escrito sem `dependencies=EXIGE_CHAVE`, ou porque nasceu
num router novo -- faz nascer um caso novo, e esse caso cai, sem que ninguem se
lembre de vir aqui acrescentar nada. Era esse o ponto: um teste que cobre uma
rota e presume as outras nao defende nada, e esta fase ja produziu cinco testes
que nao podiam falhar.

**O que mudou a 31/08 a tarde foi o sentido de metade dos casos.** De manha, a
regra era «escrever pede chave, ler nao», e cada leitura gerava um caso que
exigia que ela respondesse SEM chave. A decisao 2 inverteu isso: pede-se chave
em tudo, e a lista de excepcoes tem um nome (`ROTAS_SEM_GUARDA`) e, desde a
tarde de 31/08, dois elementos por duas razoes diferentes -- a sonda de saude,
que nao tem onde por um cabecalho, e a camada da consola, que existe
precisamente porque o navegador nao pode ter a chave. A fronteira continua
pinada dos dois lados -- uma rota
que fique aberta cai, e a excepcao que deixe de responder sem chave tambem --,
porque so um dos lados nao e uma fronteira.

O que impede o inventario de ser vazio (uma lista vazia faz o `parametrize`
recolher zero casos e passar sem ter medido nada) e
`test_o_inventario_cobre_todas_as_rotas_da_aplicacao`, que conta e exige que
nenhuma rota fique por classificar.
"""

import hmac
import json

import pytest

from resoiltwin.api import auth, docs
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
RECUSA_POR_CHAVE_NAO_CONFIGURADA = "API access is not configured on this server"

# A lista de excepcoes, e e so isto. Nao ha regra nenhuma que a derive -- nem
# por metodo, nem por prefixo --, de proposito: uma regra faz nascer excepcoes
# sozinha, e uma lista obriga a escrever a linha e a justifica-la.
#
# `GET /api/v1/health` esta aqui porque a sonda de saude da plataforma o chama
# sem credencial nenhuma. Exigir chave ali fazia a revisao nunca ficar saudavel
# e o deployment nao arrancar -- ou seja, a guarda mais apertada dava o sistema
# desligado, que nao e uma escolha entre seguranca e conveniencia mas entre ter
# sistema e nao ter. O que a rota devolve esta preso mais abaixo, em
# `test_a_rota_aberta_nao_devolve_mais_do_que_estado_nome_e_ambiente`.
#
# `GET /console/{caminho:path}` entrou a 31/08 a tarde, e a razao e outra: e a
# camada que guarda a chave para o navegador (`api/console.py`), e um navegador
# nao pode ter credencial nenhuma -- e essa a razao de a camada existir. Uma
# guarda ali fechava a consola a toda a gente e nao protegia nada, porque o que
# ela protege nao e o acesso: e a credencial e o que com ela se pode fazer.
#
# ⚠️ O que esta isencao custa esta escrito no cabecalho de `api/console.py` e
# nao se disfarca: quem alcanca este caminho le os dados da API sem apresentar
# credencial. O que a camada garante e o resto -- so `GET`, so rotas de leitura
# desta API, sem geometrias, e a chave a nunca voltar para tras --, e isso esta
# preso em `tests/test_console_camada.py`, que e o sitio onde uma folga nesse
# estreitamento faz cair um teste.
ROTAS_SEM_GUARDA = frozenset({
    ("/api/v1/health", "GET"),
    ("/console/{caminho:path}", "GET"),
})

METODOS_QUE_ESCREVEM = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _rotas_de(aplicacao) -> list[tuple[str, str]]:
    """Todo o par (caminho, metodo) que uma aplicacao serve, lido dela.

    Inclui de proposito as rotas da documentacao (`/docs`, `/openapi.json`,
    `/docs/oauth2-redirect`, `/redoc`): a decisao de 31/08 fechou-as como as
    outras, e e aqui que isso se mede -- elas estao fora do esquema, portanto
    nenhum teste do OpenAPI lhes toca. Nada aqui e uma lista escrita a mao -- e
    essa a unica razao por que uma rota nova aparece sozinha.
    """
    pares = set()
    for rota in aplicacao.routes:
        for metodo in getattr(rota, "methods", None) or ():
            pares.add((rota.path, metodo))
    return sorted(pares)


TODAS_AS_ROTAS = _rotas_de(app)
ROTAS_GUARDADAS = [par for par in TODAS_AS_ROTAS if par not in ROTAS_SEM_GUARDA]
ROTAS_ABERTAS = [par for par in TODAS_AS_ROTAS if par in ROTAS_SEM_GUARDA]


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
    assert len(ROTAS_GUARDADAS) + len(ROTAS_ABERTAS) == len(TODAS_AS_ROTAS)
    # As dezasseis rotas da aplicacao, mais as quatro da documentacao com GET e
    # HEAD, menos a excepcao. O numero e um piso e nao uma igualdade: uma rota
    # nova deve fazer cair o SEU caso, e nao este.
    assert len(ROTAS_GUARDADAS) >= 20
    assert len(ROTAS_ABERTAS) == 2
    # E tem de haver escritas la dentro: um inventario que so apanhasse
    # leituras deixava as oito rotas que escrevem sem caso nenhum.
    assert sum(1 for _, metodo in ROTAS_GUARDADAS if metodo in METODOS_QUE_ESCREVEM) >= 8


def test_o_inventario_e_lido_da_aplicacao_e_nao_escrito_a_mao():
    """O leitor tem de ver rotas que ninguem lhe foi dizer que existiam.

    Um leitor que devolvesse uma lista fixa passava todos os casos deste
    ficheiro -- estariam todos certos sobre as rotas de hoje -- e deixava de
    gerar caso nenhum para a rota de amanha, que e a unica coisa que este
    inventario existe para fazer. Aqui monta-se uma aplicacao de brincar, com
    uma rota que a real nao tem, e exige-se que ela apareca.

    **O que isto ainda nao apanha**, e fica dito para nao passar por mais do
    que e: uma lista escrita a mao que por acaso seja exactamente a de hoje
    passa por aqui e passa por tudo o resto, e so mente amanha. Nenhum teste
    consegue apanhar isso hoje. Quem o apanha e a verificacao feita fora da
    suite -- acrescentar uma rota numa copia da arvore e confirmar que nascem
    casos novos e que eles caem.
    """
    from fastapi import FastAPI

    de_brincar = FastAPI()

    @de_brincar.get("/rota-que-a-aplicacao-real-nao-tem")
    def _rota_de_brincar():
        return {}

    lido = _rotas_de(de_brincar)
    assert ("/rota-que-a-aplicacao-real-nao-tem", "GET") in lido
    # E o inventario deste ficheiro e o que sai do leitor sobre a aplicacao
    # real, sem nada pelo meio.
    assert TODAS_AS_ROTAS == _rotas_de(app)


def test_a_lista_de_excepcoes_nao_apodrece():
    """Uma excepcao a uma rota que ja nao existe e uma linha que ninguem apaga.

    Pior do que inutil: no dia em que alguem registar outra vez um caminho com
    esse nome, ele nasce aberto por causa de uma linha escrita para outra coisa.
    """
    for par in ROTAS_SEM_GUARDA:
        assert par in TODAS_AS_ROTAS, f"{_identificador(par)} esta isento e nao existe"
    # Uma excepcao nova pode vir a fazer sentido, mas nao pode entrar em
    # silencio: quem a acrescentar tem de vir aqui, e ao vir aqui le as razoes
    # por que as duas que ja existem existem -- que sao razoes diferentes uma
    # da outra.
    assert ROTAS_SEM_GUARDA == frozenset({
        ("/api/v1/health", "GET"),
        ("/console/{caminho:path}", "GET"),
    })


def test_as_quatro_rotas_de_documentacao_continuam_registadas():
    """A decisao foi fecha-las, e nao apaga-las -- sao coisas diferentes.

    Se um dia desaparecerem do `main.py`, nenhum dos casos gerados cai: elas
    deixam simplesmente de estar no inventario, e a suite fica verde sobre uma
    documentacao que ja nao existe. Fechada, quem tem a chave continua a poder
    pedir o esquema; apagada, ninguem.

    Cai tambem no sentido contrario, e esse e o perigoso: se alguem devolver as
    rotas ao FastAPI (`docs_url=` outra vez), elas voltam a ser rotas do
    Starlette registadas no `__init__` -- antes destas, portanto a ganhar o
    encaminhamento -- e respondem 200 a quem nao tem chave. O caminho continua
    no inventario, e e o caso de `test_rota_guardada_recusa_...` que cai.
    """
    caminhos = {caminho for caminho, _ in TODAS_AS_ROTAS}
    for caminho in (
        docs.CAMINHO_DO_ESQUEMA,
        docs.CAMINHO_DO_SWAGGER,
        docs.CAMINHO_DO_REDIRECT_OAUTH2,
        docs.CAMINHO_DO_REDOC,
    ):
        assert caminho in caminhos, f"{caminho} deixou de ser servido"
        assert (caminho, "GET") not in ROTAS_SEM_GUARDA


@pytest.mark.parametrize("caso", ROTAS_GUARDADAS, ids=_identificador)
def test_rota_guardada_recusa_sem_chave_e_com_chave_errada(cliente_sem_chave, caso):
    """Um caso por rota. Uma rota nova sem guarda cai aqui."""
    caminho, metodo = caso
    url = _url(caminho)

    sem = cliente_sem_chave.request(metodo, url)
    errada = cliente_sem_chave.request(
        metodo, url, headers={auth.NOME_DO_CABECALHO: "nao-e-a-chave"}
    )

    assert sem.status_code == 401, f"{metodo} {caminho} responde sem credencial nenhuma"
    assert errada.status_code == 401, f"{metodo} {caminho} aceitou uma chave errada"
    if metodo != "HEAD":
        assert _detalhe(sem) == RECUSA_DA_GUARDA
        assert _detalhe(errada) == RECUSA_DA_GUARDA
    # Um HEAD nao traz corpo, por protocolo, e portanto nao ha `detail` para
    # ler: o que distingue a recusa da guarda da recusa da rota fica preso pelo
    # caso GET do mesmo caminho, que existe sempre -- as unicas rotas que
    # servem HEAD sao as quatro da documentacao, e todas servem GET tambem.
    #
    # As duas recusas tem de ser indistinguiveis para quem esta a adivinhar:
    # se o corpo ou os cabecalhos diferissem, um pedido bastava para saber se
    # uma chave adivinhada chegou a ser comparada.
    assert sem.content == errada.content
    assert dict(sem.headers) == dict(errada.headers)


@pytest.mark.parametrize("caso", ROTAS_GUARDADAS, ids=_identificador)
def test_rota_guardada_deixa_passar_a_chave_certa(client, caso):
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


@pytest.mark.parametrize("caso", ROTAS_ABERTAS, ids=_identificador)
def test_rota_aberta_responde_sem_chave(cliente_sem_chave, caso):
    """O outro sentido da fronteira: a excepcao tem de continuar a ser uma.

    Cai se alguem puser a guarda no `/health` -- que e a rota que a sonda de
    disponibilidade chama sem cabecalho nenhum, e portanto a unica em que uma
    guarda a mais desliga o sistema em vez de o proteger.
    """
    caminho, metodo = caso
    resposta = cliente_sem_chave.request(metodo, _url(caminho))
    assert resposta.status_code != 401, f"{metodo} {caminho} passou a pedir chave, e esta isenta"
    assert _detalhe(resposta) not in (RECUSA_DA_GUARDA, RECUSA_POR_CHAVE_NAO_CONFIGURADA), (
        f"{metodo} {caminho} respondeu com a recusa da guarda, e esta isenta"
    )


def test_a_rota_aberta_nao_devolve_mais_do_que_estado_nome_e_ambiente(cliente_sem_chave):
    """A unica rota que qualquer pessoa le, e portanto a que tem de ser contada.

    A isencao do `/health` foi dada porque a sonda precisa dela, e nao porque o
    que ela devolve seja inofensivo por natureza. Esta preso aqui: as chaves da
    resposta sao exactamente tres. Um campo acrescentado por conveniencia --
    a versao a correr, a contagem de linhas, a maquina da base -- passa a sair
    para a internet sem credencial, e o sitio onde isso se descobre e este.
    """
    resposta = cliente_sem_chave.get("/api/v1/health")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert set(corpo) == {"status", "service", "environment"}
    # Nada la dentro pode ser a chave nem parte da ligacao a base.
    texto = json.dumps(corpo)
    assert CHAVE_DE_ESCRITA_DOS_TESTES[:PREFIXO_QUE_JA_E_FUGA] not in texto
    for palavra in ("postgres", "password", "@", "://"):
        assert palavra not in texto, f"o /health deixa sair {palavra!r}"


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
@pytest.mark.parametrize("caso", ROTAS_GUARDADAS, ids=_identificador)
def test_sem_chave_configurada_a_api_fecha_em_vez_de_abrir(
    cliente_sem_chave, monkeypatch, caso, valor_da_definicao
):
    """Uma chave por configurar fecha a API; nunca a abre.

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
        # teste sem a guarda ter corrido. (Num HEAD nao ha corpo para ler; o
        # caso GET do mesmo caminho ja o le.)
        if metodo != "HEAD":
            assert _detalhe(resposta) == RECUSA_POR_CHAVE_NAO_CONFIGURADA, (
                f"{metodo} {caminho} ({o_que}) deu 503, mas nao foi a guarda a recusar"
            )


@pytest.mark.parametrize("caso", ROTAS_ABERTAS, ids=_identificador)
def test_sem_chave_configurada_a_rota_isenta_continua_a_responder(
    cliente_sem_chave, monkeypatch, caso
):
    """Uma instalacao sem segredo tem de continuar diagnosticavel.

    E metade da razao por que a falta da chave nao impede o arranque: a sonda
    continua a receber 200 e quem opera consegue distinguir «o segredo nao
    chegou ao contentor» (503 em tudo o resto) de «a minha chave esta errada»
    (401). Se o `/health` fechasse tambem, as duas ficavam iguais vistas de
    fora.
    """
    caminho, metodo = caso
    monkeypatch.setattr(auth, "get_settings", lambda: _SemChaveConfigurada(None))
    resposta = cliente_sem_chave.request(metodo, _url(caminho))
    assert resposta.status_code != 503
    assert _detalhe(resposta) != RECUSA_POR_CHAVE_NAO_CONFIGURADA


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
    """O esquema so sai a quem tem a chave, mas isso nao autoriza a leva-la la."""
    texto = json.dumps(app.openapi())
    assert CHAVE_DE_ESCRITA_DOS_TESTES not in texto
    assert CHAVE_DE_ESCRITA_DOS_TESTES[:PREFIXO_QUE_JA_E_FUGA] not in texto


def test_o_registo_distingue_o_que_a_resposta_nao_distingue(cliente_sem_chave, caplog):
    """Para quem depura sao dois casos; para quem ataca sao um so.

    A distincao vai para o registo do servidor -- que quem faz o pedido nao ve
    -- e nao para a resposta. As respostas serem iguais esta preso, rota a
    rota, em `test_rota_guardada_recusa_sem_chave_e_com_chave_errada`.
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


def _no_esquema(caso: tuple[str, str]) -> bool:
    """Se a operacao aparece nos `paths` do OpenAPI.

    As quatro rotas da documentacao nao aparecem (`include_in_schema=False`,
    como no FastAPI), e portanto os dois testes seguintes nao lhes tocam. Elas
    sao medidas pelo comportamento, em `test_rota_guardada_recusa_...`.
    """
    caminho, metodo = caso
    paths = app.openapi()["paths"]
    return caminho in paths and metodo.lower() in paths[caminho]


ROTAS_GUARDADAS_EM_ESQUEMA = [caso for caso in ROTAS_GUARDADAS if _no_esquema(caso)]


def test_o_esquema_documenta_as_dezasseis_rotas_da_aplicacao():
    """Piso para o `parametrize` a seguir: se `_no_esquema` passar a dar sempre
    False, ele recolhe zero casos e fica verde sem ter olhado para nada."""
    assert len(ROTAS_GUARDADAS_EM_ESQUEMA) >= 15


@pytest.mark.parametrize("caso", ROTAS_GUARDADAS_EM_ESQUEMA, ids=_identificador)
def test_o_openapi_declara_a_chave_em_cada_rota_guardada(caso):
    """O `/docs` nao pode mentir sobre o que a rota precisa.

    Tambem por rota, e pela mesma razao: uma rota nova que leve a guarda no
    codigo mas nao apareca na documentacao e uma pagina que engana quem a le.
    """
    caminho, metodo = caso
    operacao = app.openapi()["paths"][caminho][metodo.lower()]
    assert operacao.get("security") == [{"ApiKey": []}], (
        f"{metodo} {caminho} pede chave, e o esquema nao o diz"
    )


@pytest.mark.parametrize("caso", ROTAS_ABERTAS, ids=_identificador)
def test_o_openapi_nao_declara_chave_na_rota_isenta(caso):
    caminho, metodo = caso
    documentadas = app.openapi()["paths"]
    if caminho not in documentadas or metodo.lower() not in documentadas[caminho]:
        pytest.skip("rota fora do esquema")
    assert documentadas[caminho][metodo.lower()].get("security") is None, (
        f"{metodo} {caminho} aparece no esquema a pedir chave, e esta isenta"
    )
