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

⚠️ **O que isto NAO limita, e como ficou tapado.** Quem alcanca esta camada le
os dados da API sem apresentar a chave DA API -- e tem de ser assim, porque o
navegador nao pode ter essa chave. Ate 31/08 a noite isso queria dizer que quem
alcancasse o endereco lia tudo, e era a preocupacao numero um das Tasks 1 e 2: a
decisao 2 fechou a leitura precisamente porque estes dados nao sao publicos, e
esta camada reabria-a.

O que tapa a lacuna e uma guarda **a frente desta**, e nao aqui dentro: uma
senha a porta da consola (`api/console_auth.py`), aplicada em `main.py` aos dois
routers da consola. Quem nao a tem nao chega a esta camada. A camada continua a
ser a mesma cerca de sempre -- so leituras, so rotas desta API, sem geometrias,
e a credencial a nao sair --, e continua a nao ser uma identidade: por uma
identidade a frente (Entra ID, proposta 3 da decisao 7) continua por decidir, e
o que a senha muda e que a consola ja pode ser publicada num endereco publico
sem expor os dados.

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

**As coordenadas tambem nao passam, e essa e a segunda metade da mesma regra.**
Um poligono tem forma de GeoJSON e cai pelo corte acima; um centroide nao tem
forma nenhuma -- e um `float` chamado `site_lat` dentro da evidencia de uma
linha, ou um par escrito no meio de uma frase na nota de uma area de interesse.
A partir de 31/08 a tarde ha rotas de leitura que devolvem `evidence`, e com
elas essas duas formas passaram a ter caminho para o navegador. Cortam-se por
tres regras, e cada uma tem o seu preco escrito:

- **pelo nome, para os numeros soltos.** `lat`, `lon`, `latitude`, `longitude`,
  e qualquer chave acabada em `_lat`/`_lon`/`_latitude`/`_longitude`. Um numero
  solto nao tem forma que o denuncie, portanto o nome e o unico sinal que ha --
  e isso quer dizer que renomear `site_lat` para `y` contorna o corte. E por
  isso que a consola nao mostra evidencia por lista de excepcoes nenhuma: o que
  ela desenha e o que sai daqui, e o que sai daqui ja passou por este filtro;
- **pela forma, para as caixas envolventes.** Uma chave que fale de area
  (`area_*`, `bbox`, `*_bounds`) cujo valor seja uma lista de numeros. Repare-se
  que `area_m2` (um numero) e `area_expanded` (um booleano) passam: e a lista
  que faz a caixa;
- **pelo texto, para as coordenadas escritas em prosa.** Um par de numeros
  decimais com quatro ou mais casas, ou um numero solto com seis ou mais. Custo:
  uma medida legitima escrita com essa precisao dentro de uma frase tambem cai.
  Nenhuma existe hoje -- as areas das notas estao em metros com tres casas --, e
  falhar fechado e o lado certo para se errar.

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
import re
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

# A mesma ideia para uma coordenada solta, com a razao mudada: quem le o painel
# de proveniencia tem de conseguir distinguir "o campo existe e nao e mostrado"
# de "o campo nao existe". Sao duas coisas diferentes, e um `null` dizia a
# segunda quando a verdade e a primeira.
MARCA_DE_COORDENADA = {"withheld": "coordinate"}

# ⚠️ **Em ingles, e sem lingua nenhuma.** Esta marca nao e um texto de pagina: e
# escrita DENTRO do dado, no lugar do que foi cortado, e o mesmo corpo em JSON e
# servido a quem le a camada directamente. Traduzi-la por pedido fazia a mesma
# nota de uma AOI ter dois conteudos conforme quem a leu, e um deles nunca
# corresponderia ao que esta gravado. Pela mesma razao por que `RECUSA_DE_ROTA`
# tambem esta em ingles.
#
# E **derivada da marca estruturada**, e nao escrita a mao ao lado dela: sao a
# mesma afirmacao em dois formatos, e duas copias de uma afirmacao divergem.
TEXTO_DE_COORDENADA_RETIDA = (
    f"({MARCA_DE_COORDENADA['withheld']} {next(iter(MARCA_DE_COORDENADA))})"
)

# Os nomes que denunciam um numero solto como coordenada. Um `float` nao tem
# forma nenhuma que o distinga de outro `float` -- o nome e o unico sinal.
SUFIXOS_DE_COORDENADA = ("lat", "lon", "latitude", "longitude")

# As chaves que falam de uma area. Combinadas com "o valor e uma lista de
# numeros", dao uma caixa envolvente; sozinhas nao dao nada, e por isso
# `area_m2` e `area_expanded` continuam a passar.
PREFIXOS_DE_CAIXA = ("area", "bbox", "bounds")

# Um par de decimais com quatro ou mais casas, separado por virgula: e como uma
# coordenada aparece escrita numa frase. E, a seguir, um decimal solto com seis
# ou mais casas -- precisao que nenhuma medida em prosa deste projecto usa.
PAR_DE_COORDENADAS = re.compile(r"-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}")
DECIMAL_DE_COORDENADA = re.compile(r"-?\d{1,3}\.\d{6,}")

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


def _e_nome_de_coordenada(chave: str) -> bool:
    baixa = chave.lower()
    return baixa in SUFIXOS_DE_COORDENADA or any(
        baixa.endswith("_" + sufixo) for sufixo in SUFIXOS_DE_COORDENADA
    )


def _e_caixa(chave: str, valor: Any) -> bool:
    baixa = chave.lower()
    fala_de_area = any(baixa == p or baixa.startswith(p + "_") or baixa.endswith("_" + p)
                       for p in PREFIXOS_DE_CAIXA)
    return fala_de_area and isinstance(valor, list) and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in valor
    ) and bool(valor)


def _texto_sem_coordenadas(texto: str) -> str:
    """Uma frase com o centroide escrito la dentro, sem o centroide.

    A nota que explica de onde veio o contorno de uma area vale a pena mostrar
    -- e ela que diz se o traco foi levantado no terreno ou desenhado sobre um
    mapa. O que nao pode sair e o par de coordenadas que ela traz no meio.
    """
    sem_par = PAR_DE_COORDENADAS.sub(TEXTO_DE_COORDENADA_RETIDA, texto)
    return DECIMAL_DE_COORDENADA.sub(TEXTO_DE_COORDENADA_RETIDA, sem_par)


def _sem_coordenadas(valor: Any) -> Any:
    """A segunda passagem: o que nao tem forma de GeoJSON mas e na mesma um sitio."""
    if isinstance(valor, dict):
        limpo = {}
        for chave, interior in valor.items():
            if _e_nome_de_coordenada(chave) or _e_caixa(chave, interior):
                limpo[chave] = dict(MARCA_DE_COORDENADA)
            else:
                limpo[chave] = _sem_coordenadas(interior)
        return limpo
    if isinstance(valor, list):
        return [_sem_coordenadas(interior) for interior in valor]
    if isinstance(valor, str):
        return _texto_sem_coordenadas(valor)
    return valor


def _sem_localizacao(valor: Any) -> Any:
    """As duas passagens, sempre juntas e sempre nesta ordem.

    A geometria primeiro: um poligono e substituido inteiro pela marca dele, e
    assim a segunda passagem nao tem de percorrer milhares de coordenadas para
    concluir o que a primeira ja concluiu.
    """
    return _sem_coordenadas(_sem_geometria(valor))


def _cabecalhos_para_a_api() -> dict[str, str]:
    """Os cabecalhos do pedido de saida, construidos de raiz.

    Nada do que o navegador mandou entra aqui. `or ""` porque uma instalacao
    sem segredo tem de continuar a fazer o pedido e a levar com o 503 da
    guarda: e assim que quem opera descobre que o segredo nao chegou ao
    contentor, em vez de ver um erro desta camada sobre outra coisa.
    """
    return {NOME_DO_CABECALHO: get_settings().write_api_key or "", "accept": "application/json"}


class RecusaDaCamada(Exception):
    """A camada recusou-se a passar isto, e diz com que estado.

    E uma excepcao e nao um valor de retorno porque `ler` tem dois chamadores
    com envelopes diferentes -- o apanha-tudo devolve JSON, as paginas devolvem
    HTML -- e um valor de retorno obrigava os dois a lembrarem-se de o
    verificar. Quem se esquece de um `if` fica com a recusa a passar por
    resposta valida; quem se esquece de um `except` fica com um 500, que e
    barulhento e portanto visivel.
    """

    def __init__(self, estado: int, detalhe: str):
        super().__init__(detalhe)
        self.estado = estado
        self.detalhe = detalhe


def _corpo_seguro(resposta: httpx.Response) -> Any:
    """O corpo da API sem geometrias, sem coordenadas e sem a chave."""
    try:
        corpo = resposta.json()
    except ValueError:
        # Sem o corpo no registo: e precisamente o corpo que nao se sabe o que
        # tem que esta a ser recusado.
        logger.error("console refused a non-JSON answer from the API")
        raise RecusaDaCamada(502, RECUSA_DE_CORPO) from None
    limpo = _sem_localizacao(corpo)
    chave = get_settings().write_api_key
    if chave and chave in json.dumps(limpo):
        logger.error("console refused an answer that carried the credential back")
        raise RecusaDaCamada(502, RECUSA_DE_CORPO)
    return limpo


async def ler(aplicacao, caminho: str, query: str = "") -> tuple[int, Any]:
    """A unica porta por onde se le a API a partir do lado do navegador.

    O apanha-tudo (`reencaminhar`) e as paginas da consola passam os dois por
    aqui, e essa e a razao de esta funcao existir em vez de a pagina ter o seu
    proprio cliente: as garantias -- so leituras, so rotas desta API, sem
    geometrias, sem coordenadas, sem a chave a voltar para tras -- valem para
    as duas por construcao, e nao por alguem se lembrar de as repetir.

    Levanta `RecusaDaCamada` quando a camada se recusa a passar; o estado da
    API vai tal e qual quando ela responde, um 404 ou um 503 incluidos.
    """
    alvo = caminho if caminho.startswith("/") else "/" + caminho
    if not _e_leitura_da_api(aplicacao, alvo):
        logger.warning("console refused %s: not a read route of this API", alvo)
        raise RecusaDaCamada(404, RECUSA_DE_ROTA)
    transporte = httpx.ASGITransport(app=aplicacao)
    async with httpx.AsyncClient(transport=transporte, base_url=BASE_INTERNA) as cliente:
        resposta = await cliente.request(
            METODO_UNICO, alvo, params=query, headers=_cabecalhos_para_a_api()
        )
    return resposta.status_code, _corpo_seguro(resposta)


@router.api_route("/{caminho:path}", methods=[METODO_UNICO])
async def reencaminhar(caminho: str, pedido: Request) -> Response:
    """Leva o pedido do navegador a API com a chave, e traz a resposta sem ela.

    O envelope e novo de proposito: nenhum cabecalho da API e copiado, portanto
    nao ha caminho por onde um cabecalho de resposta possa trazer a credencial
    para fora.
    """
    try:
        estado, corpo = await ler(_aplicacao_alvo(pedido), "/" + caminho, pedido.url.query)
    except RecusaDaCamada as recusa:
        return JSONResponse({"detail": recusa.detalhe}, status_code=recusa.estado)
    return Response(content=json.dumps(corpo), status_code=estado, media_type="application/json")
