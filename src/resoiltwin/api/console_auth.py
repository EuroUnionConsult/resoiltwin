"""A senha a entrada da consola, e so a entrada da consola.

Decidido a 31/08/2026, decisao 2 de `docs/fase-e-decisoes-pendentes.md`.

**O problema que isto fecha.** A decisao 2 fechou a leitura da API porque estes
dados nao sao publicos. A camada da consola (`api/console.py`) guarda a chave
para o navegador -- que e o desenho certo, porque um frontend nao pode ter
credencial nenhuma -- e ao faze-lo reabriu a leitura a quem alcance o endereco.
A Task 1 escreveu isso como preocupacao numero um e recomendou nao publicar sem
identidade a frente. Isto nao e identidade a frente: e uma porta com senha.

**Porque uma porta e nao identidade.** ⛔ A consola partilha o contentor com a
API, por decisao da Task 1, e o ambiente foi criado com `internal: false`.
Tornar a consola privada tornava a API privada tambem, e recriar o ambiente nao
esta em cima da mesa. O que sobra e por uma identidade a frente do Container App
(Entra ID, proposta 3 da decisao 7) ou por uma senha a porta. Esta e a segunda,
e o que ela NAO faz fica dito abaixo.

**O ambito e a consola, e mais nada.** ⛔ A autenticacao da API nao e tocada:
`GET /api/v1/health` continua aberta e todas as outras rotas continuam a exigir
`X-API-Key` (`api/auth.py`). Sao duas guardas com duas razoes: a da API protege
a escrita e os dados de quem nao tem a chave; esta protege o endereco publico da
consola de quem simplesmente o alcancou.

**Cobre TODAS as rotas da consola, incluindo o apanha-tudo.** A guarda e posta
ao nivel dos dois routers, em `main.py`, e nao rota a rota: `/console/{caminho:path}`
apanha tudo o que esteja sob `/console`, e uma rota de dados que caisse la sem
passar por aqui expunha exactamente aquilo que esta guarda existe para tapar. A
folha de estilo tambem leva a guarda -- nao porque uma folha de estilo exponha
dados, mas porque uma excepcao e uma linha a justificar e esta nao tem
justificacao nenhuma para existir.


As quatro escolhas, com o argumento de cada uma
------------------------------------------------

**1. Uma comparacao, e nao duas.** O utilizador e a senha nao sao comparados
separadamente. Duas comparacoes ligadas por `and` param na primeira que falhe --
e entao um pedido com o utilizador errado responde mais depressa do que um com o
utilizador certo e a senha errada. Quem mede isso fica a saber quando acertou no
utilizador, e a partir dai tem meio problema em vez de um problema inteiro.
Ligadas por `&` ja nao param, mas continuam a ser duas passagens sobre dois
comprimentos diferentes. O que se faz e reduzir o par a uma impressao de tamanho
fixo (`_impressao`) e comparar as duas impressoes de uma vez: ha um unico
`compare_digest`, sobre 64 bytes sempre, e nada no tempo de resposta diz qual dos
dois campos estava errado -- nem sequer quantos caracteres tinha o que foi
apresentado.

**2. `hmac.compare_digest`, nunca `==`.** O mesmo argumento de `api/auth.py`: um
`==` entre cadeias para no primeiro byte diferente, e a diferenca entre parar ao
primeiro e parar ao quinto e mensuravel atraves da rede com repeticoes
suficientes. Quem mede isso reconstroi a senha prefixo a prefixo, em tempo linear
no comprimento em vez de exponencial. Preso por
`test_o_par_apresentado_passa_por_uma_unica_comparacao_em_tempo_constante`.

**3. O `sha256` e sobre os dois campos separados, e nao sobre o par colado.**
Colar com um separador (`utilizador:senha`) faz colidir pares diferentes: o
utilizador `a:b` com a senha `c` daria a mesma cadeia que o utilizador `a` com a
senha `b:c`. Duas impressoes concatenadas nao colidem, e continuam a dar um
comprimento fixo.

**4. O cabecalho e lido a mao, e nao pelo `HTTPBasic` do FastAPI.** O
`HTTPBasic(auto_error=False)` devolve `None` quando o cabecalho falta, mas
levanta um 401 com OUTRO texto (`Invalid authentication credentials`) quando o
base64 esta partido -- e passariam a existir duas respostas distintas para quem
esta a experimentar. Aqui um cabecalho ausente, um cabecalho com o esquema
errado, um base64 partido e um par errado dao exactamente a mesma resposta. O
que se perde e o cadeado no esquema OpenAPI, e nao se perde nada: as rotas da
consola estao fora do esquema (`include_in_schema=False`), portanto nao ha
pagina de documentacao nenhuma onde o cadeado pudesse aparecer.


O que nao sai daqui
--------------------

⛔ Nem a senha, nem um prefixo dela, nem o comprimento -- nao na pagina, nao num
cabecalho de resposta, nao no registo, nao numa mensagem de erro, nao no
OpenAPI. O registo distingue os casos que a resposta nao distingue (falta de
cabecalho, par errado, senha por configurar), pela mesma razao que em
`api/auth.py`: quem depura precisa da diferenca, e quem ataca nao ve o registo do
servidor.


O que isto NAO faz, e fica escrito porque foi aceite e nao esquecido
---------------------------------------------------------------------

- **nao identifica ninguem.** Ha um par e e o mesmo para toda a gente. Dois
  visitantes validos sao indistinguiveis um do outro, tal como na chave da API;
- **nao tem revogacao por pessoa.** Tirar o acesso a alguem e gerar outra senha e
  redistribui-la a todos os outros;
- **nao substitui a identidade a frente.** A proposta 3 da decisao 7 continua a
  ser a resposta certa as duas alineas acima. O que muda com esta porta e que o
  endereco deixa de servir dados a quem apenas o conheca -- que era a razao pela
  qual a consola nao podia ser publicada.
"""

import base64
import binascii
import hashlib
import hmac
import logging

from fastapi import Depends, HTTPException, Request, status

from resoiltwin.config import get_settings

logger = logging.getLogger(__name__)

# O que o navegador poe na caixa que pede as credenciais. Nao pode dizer nada
# util a quem ataca -- nem o nome do utilizador, nem que servidor e este por
# dentro -- e tem de ser reconhecivel por quem tem a senha.
REINO = "ReSoilTwin console"

# `charset="UTF-8"` diz ao navegador em que codificacao mandar o par. Sem ele,
# uma senha com um caractere fora do ASCII e enviada de maneiras diferentes por
# navegadores diferentes, e a mesma senha passa num e falha noutro.
DESAFIO = f'Basic realm="{REINO}", charset="UTF-8"'

# Um unico texto para os quatro casos: sem cabecalho, esquema errado, base64
# partido, par errado. Ver a escolha 4 no cabecalho do modulo.
_RECUSADO = "Console access requires credentials"

_POR_CONFIGURAR = "Console access is not configured on this server"

ESQUEMA = "basic"


def _impressao(utilizador: str, senha: str) -> bytes:
    """O par reduzido a 64 bytes, sempre 64, seja qual for o que la entrou.

    Duas impressoes separadas e concatenadas, e nao um `sha256` sobre
    `utilizador:senha`: colar com um separador faz colidir pares diferentes (ver
    a escolha 3 no cabecalho do modulo).

    O comprimento fixo e metade do ponto. Comparar o que foi apresentado
    directamente contra o esperado deixava o tempo da comparacao depender do
    comprimento do que foi apresentado -- que e escolhido por quem faz o pedido.
    """
    return (
        hashlib.sha256(utilizador.encode("utf-8")).digest()
        + hashlib.sha256(senha.encode("utf-8")).digest()
    )


def _par_apresentado(pedido: Request) -> tuple[str, str]:
    """O par que veio no `Authorization`, ou `("", "")` se nao veio nenhum.

    Um par vazio nao e um caso especial mais abaixo: segue pelo mesmo caminho e
    e recusado pela mesma comparacao. E o que faz com que um cabecalho ausente,
    um esquema errado, um base64 partido e um par errado sejam indistinguiveis
    vistos de fora.

    Nao pode casar por acidente: a guarda ja recusou antes disto qualquer
    instalacao sem utilizador ou sem senha configurados, portanto o lado
    esperado nunca e o par vazio.
    """
    bruto = pedido.headers.get("authorization", "")
    esquema, _, parametro = bruto.partition(" ")
    if esquema.lower() != ESQUEMA:
        return "", ""
    try:
        decodificado = base64.b64decode(parametro, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return "", ""
    utilizador, separador, senha = decodificado.partition(":")
    if not separador:
        # Sem `:` nao ha par nenhum -- e um so campo, e nao se sabe qual.
        return "", ""
    return utilizador, senha


def exigir_senha_da_consola(pedido: Request) -> None:
    """Recusa quem chega a consola sem o par configurado."""
    definicoes = get_settings()
    utilizador_esperado = definicoes.console_user
    senha_esperada = definicoes.console_password
    if not utilizador_esperado or not senha_esperada:
        # Fecha, nunca abre -- e apanha tambem `CONSOLE_PASSWORD=` vazia no
        # ambiente, que nao e o mesmo que nao definida e vale o mesmo: nao ha
        # senha nenhuma para conferir contra. Sem esta linha, uma instalacao
        # sem senha aceitaria um cabecalho ausente, porque o par vazio casaria
        # com o par vazio -- credencial nenhuma a casar com credencial nenhuma.
        #
        # 503 e nao 401 pela razao escrita em `config.py`: nao ha credencial que
        # o navegador pudesse apresentar para corrigir isto, e um 401 punha o
        # navegador a pedir credenciais que nunca serviriam.
        # Nomeia a metade que falta, e nao a senha por reflexo: uma instalacao
        # que gere a senha e esqueca o utilizador ficava com um registo a
        # culpar a senha que ali esta -- e quem o lesse ia procurar no sitio
        # errado. O registo do servidor e o unico sitio onde a distincao pode
        # ser feita, porque a resposta ao cliente recusa faze-la de proposito.
        em_falta = " and ".join(
            nome
            for nome, valor in (("CONSOLE_USER", utilizador_esperado),
                                ("CONSOLE_PASSWORD", senha_esperada))
            if not valor
        )
        logger.error(
            "console refused: %s is not configured, so the console cannot be served", em_falta
        )
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _POR_CONFIGURAR)

    utilizador, senha = _par_apresentado(pedido)
    # Uma comparacao e nao duas. Ver a escolha 1 no cabecalho do modulo: duas
    # comparacoes -- mesmo em tempo constante cada uma -- dizem, pelo tempo
    # total, qual dos dois campos estava errado.
    apresentado = _impressao(utilizador, senha)
    esperado = _impressao(utilizador_esperado, senha_esperada)
    if not hmac.compare_digest(apresentado, esperado):
        # O registo distingue o que a resposta nao distingue, e nunca escreve o
        # que foi apresentado: um utilizador apresentado e muitas vezes metade
        # de um par que alguem escreveu a pressa, e o registo do servidor nao e
        # sitio para o guardar.
        logger.warning(
            "console refused: %s credentials",
            "wrong" if pedido.headers.get("authorization") else "missing",
        )
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            _RECUSADO,
            headers={"WWW-Authenticate": DESAFIO},
        )


# O que se poe no `dependencies=` de cada router da consola, em `main.py`. Ao
# nivel do router e nao rota a rota: as rotas da consola nascem em dois modulos
# e um deles serve um apanha-tudo, e repetir a linha em cada uma era deixar a
# proxima por escrever.
#
# Isto NAO garante por si que um router novo a leve -- escrever `include_router`
# sem ela e uma linha valida de Python. Quem garante e
# `tests/test_console_auth.py`, que enumera as rotas da aplicacao, escolhe as
# que estao sob `/console` e gera um caso por cada uma; uma rota da consola que
# fique sem guarda faz cair o seu proprio caso.
EXIGE_SENHA_DA_CONSOLA = [Depends(exigir_senha_da_consola)]
