"""A chave partilhada que as rotas de escrita exigem.

Decidido a 31/08/2026, decisao 7 de `docs/fase-e-decisoes-pendentes.md`,
proposta 2 das tres que la estavam. As oito rotas que escrevem exigem um
cabecalho `X-API-Key` conferido contra um segredo; as oito que leem, incluindo
`/health`, ficam abertas.

**O que isto NAO faz, e fica escrito porque foi aceite e nao esquecido:** nao
identifica quem escreveu. Todos os pedidos validos sao iguais entre si, e
`approved_by` continua a ser um campo de texto que o cliente preenche -- uma
aprovacao continua a poder dizer que foi feita por qualquer nome. O que muda e
que deixa de a poder fazer quem nao tem a chave. Identidade a serio (Entra ID
a frente do Container App, com um utilizador real por detras de cada
`approved_by`) e a proposta 3 da mesma decisao, e nao e este passo.

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
# ela que poe o cadeado no `/docs`: o FastAPI recolhe os requisitos de seguranca
# percorrendo as sub-dependencias, e uma leitura manual nao aparecia em lado
# nenhum. A documentacao gerada tem de dizer que a rota precisa de chave.
_cabecalho_da_chave = APIKeyHeader(
    name=NOME_DO_CABECALHO,
    auto_error=False,
    scheme_name="WriteApiKey",
    description=(
        "Shared key required by every route that writes. Read routes, including "
        "/health, need no credential. The key does not identify who is writing: "
        "all valid requests are equivalent."
    ),
)

# Um unico texto para os dois casos. Ver o cabecalho do modulo.
_RECUSADO = "Missing or invalid API key"


def exigir_chave_de_escrita(apresentada: str | None = Security(_cabecalho_da_chave)) -> None:
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
        # nao esta em condicoes de aceitar escritas. Quem ataca so fica a saber
        # que as escritas estao fechadas; quem opera fica a saber a diferenca
        # entre "esqueci-me do segredo" e "a minha chave esta errada".
        logger.error(
            "write request refused: WRITE_API_KEY is not configured, so no write can be accepted"
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Write access is not configured on this server",
        )
    if apresentada is None:
        logger.warning("write request refused: no %s header", NOME_DO_CABECALHO)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _RECUSADO)
    # `.encode()` porque `compare_digest` sobre `str` rebenta com TypeError
    # assim que um dos lados tiver um caractere fora do ASCII -- e o lado de la
    # e escolhido por quem faz o pedido.
    if not hmac.compare_digest(apresentada.encode("utf-8"), esperada.encode("utf-8")):
        logger.warning("write request refused: %s did not match", NOME_DO_CABECALHO)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _RECUSADO)


# O que se poe no `dependencies=` de cada rota que escreve. Uma lista partilhada
# e nao um `Depends(...)` repetido oito vezes: o FastAPI copia-a para o grafo de
# dependencias da rota no momento do registo, e assim as oito rotas dizem
# literalmente a mesma coisa em vez de dizerem a mesma coisa oito vezes.
#
# Isto NAO garante por si que uma rota de escrita nova a leve -- garantir isso
# num decorador e impossivel, porque escrever o decorador sem ela e uma linha
# valida de Python. Quem garante e `tests/test_api_auth.py`, que enumera as
# rotas da aplicacao e gera um caso por cada uma que escreva; uma rota nova sem
# guarda faz nascer um caso novo, e esse caso cai.
EXIGE_CHAVE_DE_ESCRITA = [Depends(exigir_chave_de_escrita)]
