"""A camada que guarda a chave, entre o navegador e a API.

    navegador  ->  esta camada  ->  API do ReSoilTwin
                        ^
                  guarda a chave

Desde 31/08/2026 todas as rotas da API exigem `X-API-Key`, menos o
`GET /api/v1/health`. Um frontend que corre no navegador nao pode guardar essa
chave: o que esta no codigo, na configuracao ou numa resposta, qualquer pessoa
que abra as ferramentas do navegador ve -- e a partir dai escreve na base de
producao. A consola tem por isso uma camada de servidor propria, que tem a
chave e fala com a API; o navegador nunca a ve.


A stack: Python/FastAPI, a mesma aplicacao e a mesma imagem
-----------------------------------------------------------

Nao ha aqui tempo de execucao novo, e a escolha nao foi de gosto.

A API e Python/FastAPI, ja esta empacotada (`Dockerfile`) e publicada. Um
segundo tempo de execucao -- Node, por exemplo -- traz consigo uma segunda
imagem para construir, uma segunda cadeia de dependencias para actualizar, uma
segunda superficie para proteger e uma segunda coisa para publicar em cada
entrega. Do outro lado da balanca, o que se ganharia era o ecossistema de
frontend; e a consola desta fase mostra tres vistas de leitura, que qualquer
lado serve. O ganho nao paga a duplicacao.

Fica na mesma aplicacao (um router, como os outros) e portanto no mesmo
contentor. Consequencia assumida: **a consola nao pode ser publicada sem a
API**, e separa-las mais tarde e um transporte novo e um endereco novo, nao um
`docker run` a parte.


O transporte: em processo, e isso e uma guarda e nao um atalho
---------------------------------------------------------------

O pedido a API e um pedido HTTP a serio -- com o `X-API-Key` nos cabecalhos,
passando por `exigir_chave` como o de qualquer outro cliente --, mas viaja por
um transporte ASGI ligado a **esta** aplicacao em vez de sair para a rede.

Nao e uma optimizacao. E o que torna estrutural a regra "a camada fala so com a
API": o cliente desta camada esta preso a aplicacao que recebeu o pedido, e
nao tem para onde mais ir. Nao ha endereco configuravel que alguem possa
apontar a base de dados, ao Copernicus ou a um servidor de terceiros; nao ha
porta a adivinhar; e o que corre nos testes e exactamente o que corre em
producao. Custo: publicar a consola noutro sitio que nao o contentor da API
exige aqui um transporte de rede e um endereco -- uma alteracao deliberada, com
a decisao escrita, que e como deve ser.


O que e reencaminhado, e o que custa
-------------------------------------

Nao ha saida gratuita, e esta e a escolha com o preco a vista.

**So leituras (`GET`).** A rota esta registada com um unico metodo, portanto um
`POST` ao `/console/...` e recusado pelo encaminhador antes de existir codigo
nosso a correr. A consola desta fase mostra dados: nao dispara sincronizacoes
nem aprova areas de interesse. Enquanto assim for, quem alcancar a camada nao
consegue escrever na base, mesmo tendo a camada inteira a sua frente. Custo: no
dia em que a consola precisar de disparar uma sincronizacao, isto tem de ser
mexido -- de proposito, e com a decisao escrita. Era esse o ponto.

**So caminhos que esta aplicacao serve como `GET` sob o `PREFIXO_DA_API`, e a
lista e lida da aplicacao.** Nao ha aqui nenhuma lista de rotas escrita a mao:
`_e_leitura_da_api` pergunta ao encaminhador da propria aplicacao se o caminho
casa com alguma rota e se essa rota serve `GET`. Uma leitura acrescentada
amanha fica alcancavel sem ninguem vir aqui; uma escrita nunca fica. A
alternativa -- uma lista fechada -- envelhece em silencio, que e um padrao que
este projecto ja apanhou tres vezes.

Custo, e e real: uma rota de leitura nova passa a ser legivel por quem alcance
a consola **sem que ninguem tenha tomado essa decisao**. E o preco de nao ter
uma lista que apodrece. Fica limitado por tres coisas: e sempre uma leitura;
tem de estar sob o prefixo da API, o que deixa de fora as quatro rotas de
documentacao (que a decisao de 31/08 fechou de proposito) e a propria consola;
e as geometrias nao passam (ver a seguir).

⚠️ **O que isto NAO limita, e tem de ficar dito:** quem alcanca esta camada le
os dados da API sem apresentar credencial nenhuma. A decisao 2 de 31/08 fechou
a leitura precisamente porque estes dados nao sao publicos, e esta camada
reabre-a a quem chegar ao endereco. O plano da Fase F assume a lacuna ("a
camada e uma cerca, nao uma identidade"), e o que a cerca protege e o que
sobra: a credencial nao sai, e nada do que passa por aqui escreve. Por uma
identidade a frente (proposta 3 da decisao 7) continua por decidir, e ate la a
consola nao devia ser publicada num endereco publico.

**Nenhum cabecalho do navegador chega a API.** Os cabecalhos do pedido de saida
sao construidos de raiz, com o `X-API-Key` e um `accept`. Um navegador que
mande o seu proprio `X-API-Key` nao substitui nada nem confunde nada.

**Nenhum cabecalho da API chega ao navegador.** A resposta e construida de raiz
a partir do estado e do corpo. Nao ha caminho por onde um cabecalho de resposta
possa trazer a credencial para fora, nem hoje nem no dia em que alguem
acrescentar um cabecalho a uma rota.

**As geometrias nao passam.** ⛔ Os poligonos das parcelas estao num
repositorio privado desde 31/08 e nao podem sair. `GET /sites/{code}/aois`
devolve o poligono da area de interesse ao lado da area em m2; a area pode ser
mostrada, o poligono nao. O corte e feito pela **forma** do valor e nao pelo
nome do campo -- um objecto com `coordinates`, com `geometries`, ou com um
`type` da lista do GeoJSON e substituido por uma marca -- de maneira a que
renomear `geometry` para outra coisa nao o contorne. Custo: um campo futuro que
seja legitimamente GeoJSON e queiramos mostrar tambem cai, e ha que vir aqui.
Falhar fechado e o lado certo para se errar.

**Um corpo que nao seja JSON nao passa**, e um corpo que contenha a chave
tambem nao. O segundo e uma rede por baixo do primeiro: hoje nenhuma rota
devolve o que recebeu nos cabecalhos, mas "hoje nenhuma" nao e uma garantia, e
a garantia custa uma linha.

O estado da resposta da API vai tal e qual, incluindo um 401 ou um 503 -- que
ali significam "a chave desta camada esta errada" e "esta camada nao tem chave
configurada". Quem opera precisa de os distinguir; quem ataca nao fica a saber
nada sobre o valor da chave.
"""

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.routing import Match

from resoiltwin.api import PREFIXO_DA_API
from resoiltwin.api.auth import NOME_DO_CABECALHO
from resoiltwin.config import get_settings

logger = logging.getLogger(__name__)

PREFIXO_DA_CONSOLA = "/console"

# O unico metodo, num sitio so: e o que a rota aceita e e o que a camada pede a
# API. Dois literais separados podiam divergir -- aceitar um POST aqui e
# transforma-lo num GET la e uma forma silenciosa de o encaminhamento passar a
# aceitar coisas que ninguem quis.
METODO_UNICO = "GET"

# Endereco de fachada. O transporte e em processo (ver o cabecalho do modulo):
# nada e resolvido, nada sai para a rede, e este nome nunca chega a um DNS.
BASE_INTERNA = "http://api.interna"

# Os tipos do GeoJSON (RFC 7946), mais o `Feature`/`FeatureCollection` que os
# embrulham. Vem da norma e nao dos nomes de campo desta API, de proposito.
TIPOS_GEOJSON = frozenset({
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
    "Feature", "FeatureCollection",
})

# O que fica no lugar de uma geometria. Uma marca e nao um `null`: a consola
# tem de conseguir dizer "existe e nao e mostrado", que nao e o mesmo que "nao
# existe" -- a mesma regra de proveniencia que vale no resto da interface.
MARCA_DE_RETIDO = {"withheld": "geometry"}

RECUSA_DE_ROTA = "Not a read route of this API"
RECUSA_DE_CORPO = "The API answered with something this layer will not pass on"

# Sem `dependencies=EXIGE_CHAVE`, e essa e a unica razao de este router
# existir: o navegador nao tem chave nenhuma para apresentar. O que o substitui
# nao e credencial -- e o estreitamento do que daqui se pode fazer, escrito no
# cabecalho do modulo.
#
# Fora do esquema: isto nao e uma rota da API, e uma calha para a consola. O
# esquema descreve a API, e quem o le tem a chave.
router = APIRouter(prefix=PREFIXO_DA_CONSOLA, include_in_schema=False)


def _aplicacao_alvo(pedido: Request):
    """A aplicacao a que esta camada fala: a que recebeu o pedido, e so essa.

    Le-se do pedido em vez de se importar o `main`, e nao e por causa do ciclo
    de importacao (esse resolvia-se). E porque assim nao ha nenhuma variavel a
    dizer com quem a camada fala: fala com a aplicacao onde esta montada.
    """
    return pedido.app


def _e_leitura_da_api(aplicacao, caminho: str) -> bool:
    """Se `caminho` e uma rota que esta aplicacao serve com `GET`, sob o prefixo.

    O encaminhador da propria aplicacao e que responde. Nao ha lista de rotas
    aqui, e e essa a intencao: uma rota de leitura nova entra sozinha, uma rota
    de escrita nunca entra, e as quatro rotas de documentacao ficam de fora por
    estarem fora do prefixo.

    `Match.FULL` exige caminho **e** metodo; um caminho que so exista em POST
    da `Match.PARTIAL` e nao serve. Um caminho com `..` la dentro nao casa com
    o regex de rota nenhuma, e por isso e recusado antes de chegar ao cliente
    HTTP -- que o normalizaria.
    """
    if not caminho.startswith(PREFIXO_DA_API + "/"):
        return False
    ambito = {
        "type": "http",
        "method": METODO_UNICO,
        "path": caminho,
        "root_path": "",
        "headers": [],
    }
    for rota in aplicacao.routes:
        correspondencia, _ = rota.matches(ambito)
        if correspondencia == Match.FULL:
            return True
    return False


def _sem_geometria(valor: Any) -> Any:
    """Substitui por uma marca tudo o que tenha forma de GeoJSON.

    Pela forma e nao pelo nome do campo: `{"boundary": {...}}` cai tal como
    `{"geometry": {...}}`. Ver o cabecalho do modulo.
    """
    if isinstance(valor, dict):
        if "coordinates" in valor or "geometries" in valor or valor.get("type") in TIPOS_GEOJSON:
            return dict(MARCA_DE_RETIDO)
        return {chave: _sem_geometria(interior) for chave, interior in valor.items()}
    if isinstance(valor, list):
        return [_sem_geometria(interior) for interior in valor]
    return valor


def _cabecalhos_para_a_api() -> dict[str, str]:
    """Os cabecalhos do pedido de saida, construidos de raiz.

    Nada do que o navegador mandou entra aqui. `or ""` porque uma instalacao
    sem segredo tem de continuar a fazer o pedido e a levar com o 503 da
    guarda: e assim que quem opera descobre que o segredo nao chegou ao
    contentor, em vez de ver um erro desta camada sobre outra coisa.
    """
    return {NOME_DO_CABECALHO: get_settings().write_api_key or "", "accept": "application/json"}


def _resposta_para_o_navegador(resposta: httpx.Response) -> Response:
    """O corpo da API, sem geometrias e sem a chave, num envelope novo.

    O envelope e novo de proposito: nenhum cabecalho da API e copiado, portanto
    nao ha caminho por onde um cabecalho de resposta possa trazer a credencial
    para fora.
    """
    try:
        corpo = resposta.json()
    except ValueError:
        # Sem o corpo no registo: e precisamente o corpo que nao se sabe o que
        # tem que esta a ser recusado.
        logger.error("console refused a non-JSON answer from the API")
        return JSONResponse({"detail": RECUSA_DE_CORPO}, status_code=502)
    texto = json.dumps(_sem_geometria(corpo))
    chave = get_settings().write_api_key
    if chave and chave in texto:
        logger.error("console refused an answer that carried the credential back")
        return JSONResponse({"detail": RECUSA_DE_CORPO}, status_code=502)
    return Response(content=texto, status_code=resposta.status_code, media_type="application/json")


@router.api_route("/{caminho:path}", methods=[METODO_UNICO])
async def reencaminhar(caminho: str, pedido: Request) -> Response:
    """Leva o pedido do navegador a API com a chave, e traz a resposta sem ela."""
    aplicacao = _aplicacao_alvo(pedido)
    alvo = "/" + caminho
    if not _e_leitura_da_api(aplicacao, alvo):
        logger.warning("console refused %s: not a read route of this API", alvo)
        return JSONResponse({"detail": RECUSA_DE_ROTA}, status_code=404)
    transporte = httpx.ASGITransport(app=aplicacao)
    async with httpx.AsyncClient(transport=transporte, base_url=BASE_INTERNA) as cliente:
        resposta = await cliente.request(
            METODO_UNICO, alvo, params=pedido.url.query, headers=_cabecalhos_para_a_api()
        )
    return _resposta_para_o_navegador(resposta)
