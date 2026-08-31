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

# A pagina declara-se em portugues de Portugal: e nessa lingua que ela esta
# escrita, e e ela que diz ao navegador como separar silabas e que aspas usar.
IDIOMA = "pt-PT"


def e(valor) -> str:
    """Texto pronto a entrar numa pagina, atributos incluidos."""
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def momento(instante: str | None) -> str:
    """Uma data e hora em portugues de Portugal, a partir do ISO da API."""
    if not instante:
        return ""
    try:
        lido = datetime.fromisoformat(instante.replace("Z", "+00:00"))
    except ValueError:
        return e(instante)
    return lido.strftime("%d/%m/%Y %H:%M")


def dia(data: str | None) -> str:
    if not data:
        return ""
    try:
        lido = datetime.fromisoformat(data)
    except ValueError:
        return e(data)
    return lido.strftime("%d/%m/%Y")


def _ligacao(rotulo: str, destino: str, actual: bool) -> str:
    marca = ' aria-current="page"' if actual else ""
    return f'<a href="{e(destino)}"{marca}>{e(rotulo)}</a>'


VISTAS = (
    ("Observações", "/console/observacoes"),
    ("Sincronizações", "/console/sincronizacoes"),
    ("Sítios", "/console/sitios"),
)

# ⚠️ A ressalva nao e um rodape decorativo: e a unica coisa nesta consola que
# impede tres leituras erradas que a propria tabela sugere. Fica em todas as
# paginas porque qualquer uma delas pode ser a primeira que alguem abre.
RESSALVA = (
    "Esta consola mostra o que está gravado, e nada mais. "
    "<b>Nada aqui foi validado agronomicamente.</b> "
    "O balanço hídrico é um modelo corrido sobre séries já guardadas: não mede a água "
    "do solo destes terrenos, e por isso devolve um intervalo enquanto não sabe. "
    "E três proveniências da mesma métrica aparecem na mesma tabela por serem a mesma "
    "métrica, não por se compararem entre si."
)


# ⚠️ O que uma pagina diz quando nao conseguiu ler tudo. Sem isto, uma API que
# responde 503 produzia uma tabela vazia com a legenda "nenhuma observacao
# corresponde a este filtro" -- ou seja, a pagina afirmava que a base esta vazia
# quando o que se passa e que ninguem conseguiu ler. Vazio e ilegivel sao duas
# coisas, e confundi-las e a forma de defeito que este projecto mais apanhou.
FALHA_DE_LEITURA = "Nem tudo foi lido, e o que está em baixo está incompleto."


def _falhas(avisos) -> str:
    if not avisos:
        return ""
    itens = "".join(f"<li>{e(aviso)}</li>" for aviso in avisos)
    return (
        f'<div class="falha" role="alert"><b>{e(FALHA_DE_LEITURA)}</b>'
        "<p>Isto não é o mesmo que estar vazio: houve leituras que não chegaram a "
        "responder, e o que falta abaixo pode existir na base.</p>"
        f"<ul>{itens}</ul></div>"
    )


def pagina(titulo: str, vista: str, corpo: str, ambiente: str, avisos=()) -> str:
    """O invólucro das tres vistas."""
    navegacao = "".join(_ligacao(rotulo, destino, destino == vista) for rotulo, destino in VISTAS)
    corpo = _falhas(avisos) + corpo
    return (
        f'<!doctype html>\n<html lang="{IDIOMA}">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(titulo)} · ReSoilTwin</title>\n"
        '<link rel="stylesheet" href="/console/estilo.css">\n'
        "</head>\n<body>\n"
        '<header class="cimo">'
        '<p class="produto">ReSoilTwin</p>'
        f"<nav>{navegacao}</nav>"
        f'<p class="ambiente">{e(ambiente)}</p>'
        "</header>\n"
        f"<main>\n{corpo}\n</main>\n"
        f'<footer class="rodape"><p>{RESSALVA}</p></footer>\n'
        "</body>\n</html>\n"
    )
