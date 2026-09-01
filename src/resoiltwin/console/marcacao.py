"""As pecas de HTML de que as tres vistas sao feitas.

Nao ha aqui motor de modelos, e a razao e a mesma que decidiu a folha de estilo:
um motor e uma dependencia nova para instalar, empacotar e actualizar, e o que
esta consola desenha sao tres vistas de leitura. O que um motor traria de
valioso -- escapar tudo por omissao -- traz-se com uma funcao de tres linhas e
uma regra: **nada entra numa pagina sem passar por `e()`**.

O escape e com `quote=True` de proposito. Sem ele, um valor com aspas dentro de
um atributo fecha o atributo e o que vier a seguir passa a ser marcacao. Os
valores que aqui chegam vem da base de dados e da linha de endereco, e nenhum
dos dois e de confiar por vir de onde vem.
"""

import html
from datetime import datetime
from urllib.parse import urlencode

from resoiltwin.console.textos import (
    LINGUA_POR_OMISSAO,
    LINGUAS,
    NOME_DA_LINGUA,
    PARAMETRO_DA_LINGUA,
    FORMATO_DO_DIA,
    FORMATO_DO_MOMENTO,
    Textos,
)


def e(valor) -> str:
    """Texto pronto a entrar numa pagina, atributos incluidos."""
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def momento(instante: str | None, textos: Textos) -> str:
    """Uma data e hora, no formato da lingua da pagina, a partir do ISO da API."""
    if not instante:
        return ""
    try:
        lido = datetime.fromisoformat(instante.replace("Z", "+00:00"))
    except ValueError:
        return e(instante)
    return lido.strftime(FORMATO_DO_MOMENTO[textos.lingua])


def dia(data: str | None, textos: Textos) -> str:
    if not data:
        return ""
    try:
        lido = datetime.fromisoformat(data)
    except ValueError:
        return e(data)
    return lido.strftime(FORMATO_DO_DIA[textos.lingua])


def endereco(vista: str, lingua: str, parametros=None) -> str:
    """Um endereco desta consola que **leva a lingua consigo**.

    ⚠️ Toda a ligacao dentro da consola passa por aqui. Uma ligacao escrita a
    mao perdia a lingua ao ser seguida, e quem escolheu portugues voltava ao
    ingles a meio da navegacao sem perceber porque.

    A lingua por omissao NAO se escreve no endereco. Nao e economia de
    caracteres: e o que torna visivel que sem escolha nenhuma sai o ingles --
    `/console/observacoes` sem mais nada e a pagina inglesa.
    """
    campos = {chave: valor for chave, valor in (parametros or {}).items() if valor}
    if lingua != LINGUA_POR_OMISSAO:
        campos[PARAMETRO_DA_LINGUA] = lingua
    return vista + ("?" + urlencode(campos) if campos else "")


def _ligacao(rotulo: str, destino: str, actual: bool) -> str:
    marca = ' aria-current="page"' if actual else ""
    return f'<a href="{e(destino)}"{marca}>{e(rotulo)}</a>'


# As tres vistas: o caminho, e a chave do nome delas. ⚠️ Os CAMINHOS nao se
# traduzem. Um endereco e uma identidade -- e o que alguem guarda nos favoritos,
# o que aparece num registo e o que se cola numa mensagem --, e uma consola com
# dois enderecos para a mesma pagina tem duas paginas para quem le um registo.
# O que muda com a lingua e o nome que se le, e nao o sitio onde se esta.
VISTAS = (
    ("nav.observacoes", "/console/observacoes"),
    ("nav.sincronizacoes", "/console/sincronizacoes"),
    ("nav.sitios", "/console/sitios"),
)


def _navegacao(vista: str, textos: Textos) -> str:
    return "".join(
        _ligacao(textos[chave], endereco(destino, textos.lingua), destino == vista)
        for chave, destino in VISTAS
    )


def _troca_de_lingua(vista: str, textos: Textos, parametros) -> str:
    """As outras linguas, a partir da pagina onde se esta.

    ⭐ Leva os `parametros` da pagina actual consigo. Uma troca de lingua que
    deitasse fora o filtro obrigava quem quisesse ler a mesma tabela na outra
    lingua a refazer a escolha toda -- e a comparar duas tabelas diferentes.
    """
    ligacoes = "".join(
        _ligacao(
            NOME_DA_LINGUA[lingua],
            endereco(vista, lingua, parametros),
            lingua == textos.lingua,
        )
        for lingua in LINGUAS
    )
    return f'<nav class="lingua" aria-label="{e(textos["nav.lingua"])}">{ligacoes}</nav>'


def _falhas(avisos, textos: Textos) -> str:
    """⚠️ O que uma pagina diz quando nao conseguiu ler tudo.

    Sem isto, uma API que responde 503 produzia uma tabela vazia com a legenda
    "nenhuma observacao corresponde a este filtro" -- ou seja, a pagina afirmava
    que a base esta vazia quando o que se passa e que ninguem conseguiu ler.
    Vazio e ilegivel sao duas coisas, e confundi-las e a forma de defeito que
    este projecto mais apanhou.
    """
    if not avisos:
        return ""
    itens = "".join(f"<li>{e(aviso)}</li>" for aviso in avisos)
    return (
        f'<div class="falha" role="alert"><b>{e(textos["falha.titulo"])}</b>'
        f'<p>{e(textos["falha.explicacao"])}</p>'
        f"<ul>{itens}</ul></div>"
    )


def pagina(
    titulo: str,
    vista: str,
    corpo: str,
    ambiente: str,
    textos: Textos,
    parametros=None,
    avisos=(),
) -> str:
    """O involucro das tres vistas.

    O `lang` do `<html>` sai da lingua servida e nao de uma constante: e ele que
    diz ao navegador como separar silabas e que aspas usar, e uma pagina inglesa
    declarada como portuguesa e-lhe uma instrucao errada.
    """
    corpo = _falhas(avisos, textos) + corpo
    # ⚠️ A ressalva nao e um rodape decorativo: e a unica coisa nesta consola
    # que impede tres leituras erradas que a propria tabela sugere. Fica em
    # todas as paginas porque qualquer uma delas pode ser a primeira que alguem
    # abre. Leva marcacao, e por isso e o unico texto que nao passa por `e()`.
    return (
        f'<!doctype html>\n<html lang="{e(textos.etiqueta_html)}">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(titulo)} · ReSoilTwin</title>\n"
        '<link rel="stylesheet" href="/console/estilo.css">\n'
        "</head>\n<body>\n"
        '<header class="cimo">'
        '<p class="produto">ReSoilTwin</p>'
        f"<nav>{_navegacao(vista, textos)}</nav>"
        f'<p class="ambiente">{e(ambiente)}</p>'
        f"{_troca_de_lingua(vista, textos, parametros)}"
        "</header>\n"
        f"<main>\n{corpo}\n</main>\n"
        f'<footer class="rodape"><p>{textos["ressalva"]}</p></footer>\n'
        "</body>\n</html>\n"
    )
