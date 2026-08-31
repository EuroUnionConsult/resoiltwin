"""A chave partilhada que TODAS as rotas exigem, menos o `/health`.

Decidido a 31/08/2026, decisoes 2 e 7 de `docs/fase-e-decisoes-pendentes.md`.
A 31/08 de manha a chave cobria as oito rotas que escrevem; a decisao 2 alargou
o ambito a leitura. O mecanismo e o mesmo -- o mesmo cabecalho, a mesma
comparacao, as mesmas duas recusas indistinguiveis --, muda **onde** e
aplicado.

**Porque e que ler tambem passou a pedir credencial.** As geometrias das
parcelas e as leituras de campo nao sao publicas, e isso ja tinha sido decidido
duas vezes noutro sitio:

- as geometrias aprovadas foram postas num repositorio **privado**
  (`EuroUnionConsult/resoiltwin-internal`) precisamente porque nao podem sair;
- as notas de evidencia publicadas seguem a mesma regra desde que existem:
  publicam distancias e o tamanho da celula, **nunca os poligonos**.

Uma API que devolvia essas mesmas geometrias e essas mesmas leituras a quem
pedisse contradizia as duas decisoes. Nao ha aqui nada de novo sobre o que e
publico: ha o codigo a passar a dizer o que o resto do projecto ja dizia.

**O `/health` e a unica excepcao, e nao e uma folga.** A sonda de saude dos
Container Apps chama-o sem credencial nenhuma: exigir chave ali fazia a revisao
nunca ficar saudavel e o *deployment* nao arrancar. O que ele devolve foi
conferido antes de ficar aberto -- `status`, o nome da aplicacao e a etiqueta
do ambiente, e mais nada: nao toca na base, nao diz a versao, nao diz para onde
aponta a `DATABASE_URL`. Esta preso em `tests/test_api_auth.py`, que exige que
as chaves da resposta sejam exactamente essas tres.

**As quatro rotas de documentacao (`/openapi.json`, `/docs`,
`/docs/oauth2-redirect`, `/redoc`) ficaram fechadas como as outras**, e o
argumento esta em `resoiltwin/api/docs.py`, ao lado do codigo que as regista.

**O que isto continua a NAO fazer, e fica escrito porque foi aceite e nao
esquecido:** nao identifica ninguem. Todos os pedidos validos sao iguais entre
si, e `approved_by` continua a ser um campo de texto que o cliente preenche --
uma aprovacao continua a poder dizer que foi feita por qualquer nome. Nao ha
revogacao por pessoa: retirar o acesso a alguem e gerar outra chave e
redistribui-la a todos os outros. Identidade a serio (Entra ID a frente do
Container App, com um utilizador real por detras de cada `approved_by`) e a
proposta 3 da decisao 7, e nao e este passo.

Tres escolhas que valem a pena estarem explicadas aqui e nao so no relatorio:

- **a comparacao e em tempo constante** (`hmac.compare_digest`). Um `==` entre
  cadeias para no primeiro byte diferente, e a diferenca de tempo entre parar
  ao primeiro byte e parar ao quinto e mensuravel atraves da rede com
  repeticoes suficientes. Quem mede isso reconstroi a chave prefixo a prefixo,
  em tempo linear no comprimento em vez de exponencial;
- **sem cabecalho e com cabecalho errado dao exactamente a mesma resposta** --
  o mesmo codigo, o mesmo corpo, os mesmos cabecalhos. Sao coisas diferentes
  para quem depura, e por isso a diferenca vai para o registo do servidor, que
  quem ataca nao ve. Se fossem duas respostas distintas, um pedido bastava para
  confirmar que uma chave adivinhada tem o formato certo;
- **nada do que sai daqui contem a chave** -- nem inteira, nem um prefixo, nem
  o comprimento. Nem na resposta, nem no registo, nem no OpenAPI.

**Sobre o nome `WRITE_API_KEY`, que passou a dizer menos do que a chave faz.**
Ficou. Nao e distraccao: e o nome do segredo `write-api-key` que ja esta no
cofre do guia de instalacao e a variavel que `infra/modules/app.bicep` leva
para dentro do contentor. Renomear e mudar o contrato com o *deployment* --
segredo novo, parametros novos, guia novo -- e isso e uma alteracao com uma
reposicao atras, nao um alargamento de ambito. Fica registado aqui como divida
de nome, para nao passar por descuido.
"""

import hmac
import logging

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from resoiltwin.config import get_settings

logger = logging.getLogger(__name__)

NOME_DO_CABECALHO = "X-API-Key"

# `auto_error=False` de proposito. Com `auto_error=True` o FastAPI responde
# sozinho, e com um codigo diferente (403), quando o cabecalho falta -- e
# passariam a existir duas respostas distintas, uma para "sem cabecalho" e
# outra para "cabecalho errado", que e exactamente a distincao que nao pode
# ficar visivel. Com False, o cabecalho em falta chega aqui como None e e
# recusado no mesmo sitio e da mesma maneira que o errado.
#
# A instancia existe (em vez de se ler o cabecalho a mao do `Request`) porque e
# ela que poe o cadeado no esquema: o FastAPI recolhe os requisitos de
# seguranca percorrendo as sub-dependencias, e uma leitura manual nao aparecia
# em lado nenhum. A documentacao gerada tem de dizer que a rota precisa de
# chave.
_cabecalho_da_chave = APIKeyHeader(
    name=NOME_DO_CABECALHO,
    auto_error=False,
    scheme_name="ApiKey",
    description=(
        "Shared key required by every route except /api/v1/health, which the "
        "platform health probe calls with no credential. The key does not "
        "identify the caller: all valid requests are equivalent."
    ),
)

# Um unico texto para os dois casos. Ver o cabecalho do modulo.
_RECUSADO = "Missing or invalid API key"


def exigir_chave(apresentada: str | None = Security(_cabecalho_da_chave)) -> None:
    """Recusa o pedido se o `X-API-Key` faltar ou nao for o configurado."""
    esperada = get_settings().write_api_key
    if not esperada:
        # Fecha, nunca abre. Um `if esperada:` a volta da conferencia -- que e
        # a forma "natural" de escrever isto -- deixaria passar TUDO na
        # instalacao que se esqueceu do segredo, que e precisamente a
        # instalacao onde ninguem esta a olhar. Tambem apanha `WRITE_API_KEY=`
        # vazio no ambiente, que nao e o mesmo que nao definida mas vale o
        # mesmo: nao ha chave nenhuma para conferir contra.
        #
        # 503 e nao 401 porque isto nao e um pedido mal feito: nao ha cabecalho
        # nenhum que o cliente pudesse enviar para o corrigir. E o servidor que
        # nao esta em condicoes de aceitar pedidos. Quem ataca so fica a saber
        # que a API esta fechada; quem opera fica a saber a diferenca entre
        # "esqueci-me do segredo" e "a minha chave esta errada" -- e essa
        # diferenca e o passo 9 do guia de instalacao.
        logger.error(
            "request refused: WRITE_API_KEY is not configured, so no request can be accepted"
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API access is not configured on this server",
        )
    if apresentada is None:
        logger.warning("request refused: no %s header", NOME_DO_CABECALHO)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _RECUSADO)
    # `.encode()` porque `compare_digest` sobre `str` rebenta com TypeError
    # assim que um dos lados tiver um caractere fora do ASCII -- e o lado de la
    # e escolhido por quem faz o pedido.
    if not hmac.compare_digest(apresentada.encode("utf-8"), esperada.encode("utf-8")):
        logger.warning("request refused: %s did not match", NOME_DO_CABECALHO)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _RECUSADO)


# O que se poe no `dependencies=` de cada `include_router`. Ate 31/08 de manha
# isto ia rota a rota, nas oito que escreviam; agora que a regra e "todas menos
# uma", repetir a mesma linha em quinze rotas era esconder a excepcao no meio
# do ruido. Ao nivel do router, a politica inteira le-se num ecra em
# `main.py`: oito routers com a guarda, o `health` sem ela.
#
# Isto NAO garante por si que um router novo a leve -- garantir isso numa
# chamada e impossivel, porque escrever `include_router` sem ela e uma linha
# valida de Python. Quem garante e `tests/test_api_auth.py`, que enumera as
# rotas da aplicacao e gera um caso por cada uma que nao esteja na lista de
# excepcoes; uma rota que fique aberta faz cair o seu proprio caso.
EXIGE_CHAVE = [Depends(exigir_chave)]
