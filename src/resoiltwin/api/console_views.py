"""As rotas das tres vistas da consola.

⚠️ **Estas rotas tem de ser registadas ANTES de `api/console.py`.** O router da
camada serve `/console/{caminho:path}`, que apanha tudo o que esteja sob
`/console` -- estas paginas incluidas. Registado primeiro, ele responde-lhes o
404 em JSON dele, e a consola deixa de existir sem nada rebentar. E a
preocupacao 4 do relatorio da Task 1, e esta preso por
`test_a_pagina_da_consola_ganha_ao_apanha_tudo`.

**Estas rotas nao tocam na base de dados.** Toda a leitura passa por
`console.ler`, que e a camada que guarda a chave: e ela que apresenta a
credencial a API, que corta as geometrias e as coordenadas, e que se recusa a
deixar sair um corpo com a chave dentro. Uma pagina com a sua propria sessao de
base de dados perdia as tres garantias de uma vez, e nao ganhava nada -- a
consola nao escreve.

**Nao tem `dependencies=EXIGE_CHAVE`, pela mesma razao que a camada nao tem:** o
navegador nao tem chave nenhuma para apresentar, e nao pode ter.

**Tem `dependencies=EXIGE_SENHA_DA_CONSOLA`**, posto em `main.py` como o
anterior, e e outra guarda por outra razao: a chave da API protege os dados de
quem nao a tem; a senha protege o endereco publico de quem apenas o alcancou.
Estas rotas nao a repetem uma a uma -- ela esta no router -- e por isso uma
rota nova neste modulo nasce guardada. O que garante que um router NOVO tambem
a leva e `tests/test_console_auth.py`, que gera um caso por cada rota sob
`/console` lida de `app.routes`.
"""

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse

from resoiltwin.api import PREFIXO_DA_API
from resoiltwin.api.console import PREFIXO_DA_CONSOLA, RecusaDaCamada, ler
from resoiltwin.config import get_settings
from resoiltwin.console import paginas
from resoiltwin.console.estilo import FOLHA_DE_ESTILO

router = APIRouter(prefix=PREFIXO_DA_CONSOLA, include_in_schema=False)

# Uma hora. A folha nao muda entre pedidos dentro da mesma versao da imagem, e
# nao ha aqui nada de privado -- e uma folha de estilo. Curto na mesma: uma
# entrega nova tem de chegar a quem ja tinha a pagina aberta.
CACHE_DA_FOLHA = "public, max-age=3600"


def _ambiente() -> str:
    return f"ambiente: {get_settings().environment}"


async def _le(pedido: Request, caminho: str, **parametros) -> tuple[Any | None, str | None]:
    """Uma leitura pela camada: `(corpo, falha)`, e nunca uma excepcao.

    ⚠️ **A falha volta ao lado do corpo, e nao no lugar dele.** Uma vista que
    engolisse o erro desenhava "nenhuma observacao corresponde a este filtro"
    sobre uma API que respondeu 503 -- ou seja, dizia que a base esta vazia
    quando o que se passa e que ninguem conseguiu ler. E a forma de defeito que
    este projecto ja apanhou mais vezes: um sistema que diz "sim" a uma
    mentira. Quem chama tem de decidir o que fazer com a falha, e as tres
    vistas mostram-na.

    Nao levanta: um codigo de sitio escrito a mao na linha de endereco nao pode
    dar um 500, que nao explica nada a ninguem.
    """
    query = urlencode({c: v for c, v in parametros.items() if v not in (None, "")})
    try:
        estado, corpo = await ler(pedido.app, PREFIXO_DA_API + caminho, query)
    except RecusaDaCamada as recusa:
        return None, f"{caminho}: a camada recusou esta leitura ({recusa.detalhe})."
    if estado != 200:
        return None, f"{caminho}: a API respondeu {estado}."
    return corpo, None


class _Leitor:
    """Le pela camada e guarda as falhas para a pagina as poder mostrar.

    Existe para que nenhuma vista tenha de se lembrar de tratar a falha: pede-se
    e le-se, e o que correu mal fica na lista que a pagina recebe. Uma vista que
    se esquecesse produzia a mentira que `_le` descreve.
    """

    def __init__(self, pedido: Request):
        self.pedido = pedido
        self.avisos: list[str] = []

    async def __call__(self, caminho: str, **parametros):
        corpo, falha = await _le(self.pedido, caminho, **parametros)
        if falha is not None:
            self.avisos.append(falha)
        return corpo


@router.get("/estilo.css")
def folha_de_estilo() -> Response:
    return Response(
        content=FOLHA_DE_ESTILO,
        media_type="text/css; charset=utf-8",
        headers={"cache-control": CACHE_DA_FOLHA},
    )


@router.get("")
@router.get("/")
@router.get("/observacoes")
async def observacoes(
    pedido: Request,
    sitio: str | None = Query(None),
    metrica: str | None = Query(None),
    origem: str | None = Query(None),
    linha: str | None = Query(None),
    n: int = Query(paginas.TAMANHO_POR_OMISSAO),
) -> HTMLResponse:
    """A tabela, os filtros e o painel de proveniencia da linha escolhida."""
    le = _Leitor(pedido)
    sitios = await le("/sites") or []
    codigos = [s["code"] for s in sitios]
    # ⚠️ O codigo do sitio vem da linha de endereco e vai entrar num caminho.
    # Confere-se contra a lista que a API devolveu em vez de se confiar nele: o
    # que nao esta na lista nao e um sitio, seja o que for que pareca.
    escolhido = sitio if sitio in codigos else (codigos[0] if codigos else None)
    if n not in paginas.TAMANHOS:
        n = paginas.TAMANHO_POR_OMISSAO

    inventario = {"metrics": [], "rows": [], "total": 0, "returned": 0}
    if escolhido:
        inventario = await le(
            f"/sites/{escolhido}/observations",
            metric=metrica, source_type=origem, limit=n,
        ) or inventario

    seleccionada = next(
        (candidata for candidata in inventario["rows"] if str(candidata["id"]) == str(linha)), None
    )
    return HTMLResponse(paginas.observacoes({
        "sitios": sitios,
        "inventario": inventario,
        "filtros": {"sitio": escolhido, "metrica": metrica, "origem": origem, "n": n},
        "seleccionada": seleccionada,
        "ambiente": _ambiente(),
        "avisos": le.avisos,
    }))


@router.get("/sincronizacoes")
async def sincronizacoes(pedido: Request) -> HTMLResponse:
    """O que correu, o que falhou, e o que precisa de atencao."""
    le = _Leitor(pedido)
    execucoes = await le("/jobs", limit=500) or []
    return HTMLResponse(paginas.sincronizacoes({
        "execucoes": execucoes, "ambiente": _ambiente(), "avisos": le.avisos,
    }))


@router.get("/sitios")
async def sitios(pedido: Request) -> HTMLResponse:
    """Os dois sitios, as areas de interesse, e o que cada um tem."""
    le = _Leitor(pedido)
    fichas = []
    for sitio in await le("/sites") or []:
        codigo = sitio["code"]
        # `limit=0` traz o inventario sem uma unica linha: esta vista precisa do
        # catalogo e nao das observacoes, e pedir cem para deitar cem fora era
        # trabalho a mais no sitio errado.
        inventario = await le(f"/sites/{codigo}/observations", limit=0) or {}
        fichas.append({
            "sitio": sitio,
            "areas": await le(f"/sites/{codigo}/aois") or [],
            "parcelas": await le(f"/sites/{codigo}/plots") or [],
            "metricas": inventario.get("metrics", []),
        })
    return HTMLResponse(paginas.sitios({
        "fichas": fichas, "ambiente": _ambiente(), "avisos": le.avisos,
    }))
