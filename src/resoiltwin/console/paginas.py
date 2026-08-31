"""As tres vistas, e nada mais nesta fase.

    Observacoes      tabela com filtros por sitio, metrica e origem, e o painel
                     de proveniencia da linha escolhida
    Sincronizacoes   o que correu, o que falhou, e o que precisa de atencao
    Sitios           os dois, com as areas de interesse e o que cada uma tem

⛔ **Nao ha graficos, e a ausencia e deliberada.** Um grafico consegue insinuar
o que um texto nao afirma: uma linha continua entre uma leitura de campo e uma
celula de reanalise diz "isto e a mesma serie", e nao e. Enquanto as tres
proveniencias nao se cruzarem num numero util de dias -- hoje cruzam-se num --,
qualquer serie desenhada faz uma afirmacao que os dados nao sustentam. O que ha
e uma barra por linha, e so onde o dominio existe sem ser inventado: uma barra
nao liga pontos nenhuns, e a de um intervalo desenha a banda inteira, que e a
unica forma honesta de a desenhar.
"""

from typing import Any
from urllib.parse import urlencode

from resoiltwin.console import formato, proveniencia
from resoiltwin.console.marcacao import dia, e, momento, pagina
from resoiltwin.console.paleta import ORDEM_DA_PROVENIENCIA

TAMANHOS = (50, 100, 250, 500)
TAMANHO_POR_OMISSAO = 100

TODAS = ""  # o valor da opcao "sem filtro", num sitio so


def _opcoes(valores, escolhido, rotulo_de_todas: str | None = None) -> str:
    """As opcoes de um filtro.

    ⚠️ Os valores vem sempre do inventario que a API devolveu, e nunca de uma
    lista escrita aqui. Uma lista escrita aqui envelhece em silencio: uma
    metrica nova fica invisivel para quem so tem a consola.
    """
    partes = []
    if rotulo_de_todas is not None:
        marca = " selected" if escolhido in (None, TODAS) else ""
        partes.append(f'<option value=""{marca}>{e(rotulo_de_todas)}</option>')
    for valor, rotulo in valores:
        marca = " selected" if str(valor) == str(escolhido) else ""
        partes.append(f'<option value="{e(valor)}"{marca}>{e(rotulo)}</option>')
    return "".join(partes)


def _marca(origem: str, medido: bool) -> str:
    """O quadrado da origem: cor 10YR, e trama quando nao foi medido aqui."""
    titulo = formato.NA_PARCELA if medido else formato.FORA_DA_PARCELA
    return (
        f'<span class="marca" style="--prov: var(--prov-{e(origem)})" '
        f'role="img" aria-label="{e(titulo)}"></span>'
    )


def _barra(linha: dict[str, Any], medido: bool) -> str:
    faixa = formato.faixa_do_valor(linha)
    if faixa is None:
        return ""
    # A cor sai do TOPO da banda, e nao do meio dela. Num intervalo, o meio e
    # precisamente o numero que nao existe -- usa-lo para escolher a cor era
    # repor pela cor a afirmacao que o texto tem proibida. O topo e um numero
    # que a base tem mesmo, e a geometria da banda ja diz onde ela comeca.
    indice = min(4, max(0, int(faixa.fim / 25)))
    largura = max(1.0, faixa.fim - faixa.inicio)
    aberta = ' data-aberta="sim"' if faixa.aberta_em_cima else ""
    no_sitio = "sim" if medido else "nao"
    return (
        f'<span class="barra"{aberta}>'
        f'<i data-parcela-barra="{no_sitio}" style="left: {faixa.inicio:.1f}%; '
        f"width: {largura:.1f}%; background-color: var(--{e(faixa.rampa)}-{indice})\"></i>"
        "</span>"
    )


def _linha_de_observacao(linha: dict[str, Any], seleccionada: bool, endereco: str) -> str:
    valor = formato.apresentar_valor(linha)
    medido = formato.medido_na_parcela(linha)
    parcela = "sim" if medido else "nao"
    escolha = ' data-seleccionada="sim"' if seleccionada else ""
    return (
        f'<tr class="linha" data-linha="{e(linha["id"])}" data-parcela="{parcela}"{escolha}>'
        f'<td class="quando">{momento(linha.get("observed_at"))}</td>'
        f'<td class="metrica">{e(linha.get("metric"))}</td>'
        f'<td class="valor" data-forma="{e(valor.forma)}">'
        f'<span class="numero">{e(valor.texto)}</span>'
        f'<span class="unidade">{e(linha.get("unit"))}</span>'
        f"{_barra(linha, medido)}</td>"
        f'<td class="origem">'
        f'<span class="par">{_marca(str(linha.get("source_type")), medido)}'
        f'<span class="nome">{e(linha.get("source_type"))}</span></span>'
        f'<span class="lugar">{e(formato.lugar_da_medicao(linha))}</span></td>'
        f'<td class="qualidade">{e(linha.get("quality_flag"))}</td>'
        f'<td class="versao">{e(linha.get("processing_version"))}</td>'
        f'<td class="abrir"><a href="{e(endereco)}#proveniencia">proveniência</a></td>'
        "</tr>"
    )


def _campos(campos) -> str:
    partes = ["<dl>"]
    for campo in campos:
        partes.append(f"<dt>{e(campo.rotulo)}</dt>")
        classe = ' class="retido"' if campo.retido else ""
        if campo.filhos:
            partes.append(f"<dd{classe}>{_campos(campo.filhos)}</dd>")
        else:
            partes.append(f"<dd{classe}>{e(campo.valor)}</dd>")
    partes.append("</dl>")
    return "".join(partes)


def _painel(linha: dict[str, Any] | None) -> str:
    if linha is None:
        return (
            '<aside class="proveniencia" id="proveniencia"><div class="interior">'
            "<h3>Proveniência</h3>"
            "<p class=\"em-falta\">Escolha uma linha da tabela para ver de onde veio o "
            "valor dela: o que foi medido, a que distância, com que instrumento e sobre "
            "que entradas.</p>"
            "</div></aside>"
        )
    conteudo = proveniencia.painel_de(linha)
    valor = formato.apresentar_valor(linha)
    cabeca = (
        "<h3>Proveniência</h3>"
        f'<p class="contagem">{e(linha.get("metric"))} · '
        f'{e(valor.texto)} {e(linha.get("unit"))}</p>'
        f'<p class="lugar">{e(formato.lugar_da_medicao(linha))} · '
        f'{momento(linha.get("observed_at"))}</p>'
    )
    if conteudo.estruturada:
        corpo = _campos(conteudo.da_evidencia)
    else:
        corpo = (
            f'<p class="em-falta"><strong>{e(proveniencia.SEM_PROVENIENCIA)}</strong>'
            f"{e(proveniencia.PORQUE_FALTA)}</p>"
        )
    return (
        '<aside class="proveniencia" id="proveniencia"><div class="interior">'
        f"{cabeca}{corpo}"
        "<h3>Na própria linha</h3>"
        f"{_campos(conteudo.da_linha)}"
        "</div></aside>"
    )


def _legenda() -> str:
    escala = "".join(
        f'<li><span class="marca" style="--prov: var(--prov-{origem.value})"></span>'
        f"{e(origem.value)}</li>"
        for origem in ORDEM_DA_PROVENIENCIA
    )
    return (
        '<ul class="legenda">'
        f'<li><span class="marca" style="--prov: var(--prov-observed_screening)"></span>'
        f"sólido: {e(formato.NA_PARCELA)}</li>"
        f'<li data-parcela="nao"><span class="marca" '
        f'style="--prov: var(--prov-observed_screening)"></span>'
        f"tramado: {e(formato.FORA_DA_PARCELA)}</li>"
        "</ul>"
        '<ul class="legenda">'
        "<li>escala de proveniência, do mais directo ao mais distante:</li>"
        f"{escala}</ul>"
    )


def _endereco(base: dict[str, Any], **mudancas) -> str:
    campos = {chave: valor for chave, valor in {**base, **mudancas}.items() if valor}
    return "/console/observacoes" + ("?" + urlencode(campos) if campos else "")


def observacoes(contexto: dict[str, Any]) -> str:
    """A tabela, os filtros, e o painel da linha escolhida."""
    inventario = contexto["inventario"]
    filtros = contexto["filtros"]
    linhas = inventario.get("rows", [])
    seleccionada = contexto.get("seleccionada")

    metricas = [(m["metric"], f'{m["metric"]} ({m["count"]})') for m in inventario.get("metrics", [])]
    origens = sorted({
        origem for facet in inventario.get("metrics", []) for origem in facet.get("source_types", [])
    })

    corpo_da_tabela = "".join(
        _linha_de_observacao(
            linha,
            seleccionada is not None and str(linha["id"]) == str(seleccionada["id"]),
            _endereco(filtros, linha=linha["id"]),
        )
        for linha in linhas
    )
    if not corpo_da_tabela:
        corpo_da_tabela = (
            '<tr><td class="vazio" colspan="7">Nenhuma observação corresponde a este '
            "filtro. Este sítio pode não ter esta métrica, ou não a ter desta origem.</td></tr>"
        )

    total, devolvidas = inventario.get("total", 0), inventario.get("returned", 0)
    resumo = (
        f'<p class="subtitulo"><span class="contagem">{total}</span> '
        f"{'observação corresponde' if total == 1 else 'observações correspondem'} a este filtro; "
        f'a mostrar as <span class="contagem">{devolvidas}</span> mais recentes.</p>'
    )

    codigo_do_sitio = filtros.get("sitio")
    opcoes_de_sitio = _opcoes(
        [(s["code"], f'{s["code"]} — {s["name"]}') for s in contexto["sitios"]], codigo_do_sitio
    )
    opcoes_de_metrica = _opcoes(metricas, filtros.get("metrica"), "todas as métricas")
    opcoes_de_origem = _opcoes([(o, o) for o in origens], filtros.get("origem"), "todas as origens")
    opcoes_de_tamanho = _opcoes([(n, n) for n in TAMANHOS], filtros.get("n"))
    limpar = _endereco({"sitio": codigo_do_sitio})

    formulario = (
        '<form class="filtros" method="get" action="/console/observacoes">'
        f'<label><span>Sítio</span><select name="sitio">{opcoes_de_sitio}</select></label>'
        f'<label><span>Métrica</span><select name="metrica">{opcoes_de_metrica}</select></label>'
        f'<label><span>Origem</span><select name="origem">{opcoes_de_origem}</select></label>'
        f'<label><span>Linhas</span><select name="n">{opcoes_de_tamanho}</select></label>'
        '<button type="submit">Filtrar</button>'
        f'<a class="limpar" href="{e(limpar)}">limpar</a>'
        "</form>"
    )

    tabela = (
        '<div class="tabela"><table>'
        "<thead><tr>"
        "<th>Quando</th><th>Métrica</th><th>Valor</th><th>Origem</th>"
        "<th>Qualidade</th><th>Versão</th><th></th>"
        "</tr></thead>"
        f"<tbody>{corpo_da_tabela}</tbody>"
        "</table></div>"
    )

    corpo = (
        "<h1>Observações</h1>"
        f"{resumo}{formulario}{_legenda()}"
        f'<div class="duas-colunas">{tabela}{_painel(seleccionada)}</div>'
    )
    return pagina(
        "Observações", "/console/observacoes", corpo,
        contexto["ambiente"], contexto.get("avisos", ()),
    )


# ---------------------------------------------------------------------------
# Sincronizacoes
# ---------------------------------------------------------------------------

VEREDICTOS = {
    "failed": "declarou que correu mal",
    "never_finished": "ficou a correr e nunca acabou",
    "succeeded_without_writing": "disse que sim e não escreveu nada",
}


def _linha_de_execucao(execucao: dict[str, Any]) -> str:
    atencao = execucao.get("attention")
    dias = execucao.get("uncovered_days")
    return (
        f'<tr class="linha" data-execucao="{e(execucao.get("job_type"))}" '
        f'data-atencao="{"sim" if atencao else "nao"}">'
        f'<td class="quando">{momento(execucao.get("started_at"))}</td>'
        f'<td class="metrica">{e(execucao.get("job_type"))}</td>'
        f'<td class="estado">{e(execucao.get("status"))}'
        + (
            f'<span class="lugar veredicto">{e(VEREDICTOS.get(atencao, atencao))}</span>'
            if atencao
            else ""
        )
        + "</td>"
        f'<td class="janelas">'
        f'<span class="janela"><b>pedida</b> '
        f'{dia(execucao.get("requested_date_from")) or "não registada"}'
        f'{" a " + dia(execucao.get("requested_date_to")) if execucao.get("requested_date_to") else ""}'
        "</span>"
        f'<span class="janela"><b>coberta</b> {dia(execucao.get("date_from"))} a '
        f'{dia(execucao.get("date_to"))}</span></td>'
        f'<td class="valor"><span class="numero">'
        f'{"não medível" if dias is None else dias}</span></td>'
        f'<td class="valor"><span class="numero">{e(execucao.get("rows_written"))}</span></td>'
        f'<td class="versao">{e(execucao.get("processing_version") or "não registada")}</td>'
        f'<td class="erro">{e(execucao.get("error") or "")}</td>'
        "</tr>"
    )


def sincronizacoes(contexto: dict[str, Any]) -> str:
    execucoes = contexto["execucoes"]
    precisam = [linha for linha in execucoes if linha.get("attention")]

    def tabela(linhas: list[dict[str, Any]], vazio: str) -> str:
        corpo = "".join(_linha_de_execucao(linha) for linha in linhas)
        if not corpo:
            corpo = f'<tr><td class="vazio" colspan="8">{e(vazio)}</td></tr>'
        return (
            '<div class="tabela"><table><thead><tr>'
            "<th>Começou</th><th>Tipo</th><th>Estado</th><th>Janelas</th>"
            "<th>Dias por cobrir</th><th>Linhas</th><th>Versão</th><th>Erro</th>"
            f"</tr></thead><tbody>{corpo}</tbody></table></div>"
        )

    corpo = (
        "<h1>Sincronizações</h1>"
        '<p class="subtitulo">Cada ingestão deixa uma linha. Várias decisões deste sistema '
        "assentam em falhar alto em vez de perder em silêncio, e falhar alto só é melhor do "
        "que perder em silêncio se alguém olhar.</p>"
        f"<h2>Precisam de atenção ({len(precisam)})</h2>"
        '<p class="subtitulo">Uma execução entra aqui por ter declarado que correu mal, por '
        "ter ficado a correr sem nunca acabar, ou por ter dito que sim sem escrever nada "
        "quando nenhuma outra execução do mesmo pedido escreveu.</p>"
        + tabela(precisam, "Nenhuma execução está assinalada. Isto não quer dizer que esteja "
                           "tudo bem: quer dizer que não há nada que estas três regras vejam.")
        + f"<h2>Todas as execuções ({len(execucoes)})</h2>"
        '<p class="subtitulo">Os dias por cobrir são a contagem dos dias da janela pedida que '
        "ficaram fora da janela coberta. É uma contagem e não um veredicto: um arquivo que "
        "publica com atraso e uma série genuinamente perdida têm a mesma forma e só diferem "
        "em magnitude, e o limiar é de quem lê.</p>"
        + tabela(execucoes, "Não há execuções registadas.")
    )
    return pagina(
        "Sincronizações", "/console/sincronizacoes", corpo,
        contexto["ambiente"], contexto.get("avisos", ()),
    )


# ---------------------------------------------------------------------------
# Sitios
# ---------------------------------------------------------------------------

def _pares(*campos) -> str:
    itens = "".join(f"<li><b>{e(rotulo)}</b> {e(valor)}</li>" for rotulo, valor in campos if valor)
    return f'<ul class="pares">{itens}</ul>'


def _ficha_de_sitio(ficha: dict[str, Any]) -> str:
    sitio = ficha["sitio"]
    areas = "".join(
        "<h3>" + e(area["code"]) + "</h3>"
        + _pares(
            ("finalidade", area.get("purpose")),
            ("área", f'{formato.numero(area.get("area_m2"), 0)} m²'),
            ("proveniência da geometria", area.get("geometry_provenance")),
            ("estado", area.get("status")),
            ("aprovada por", area.get("approved_by")),
        )
        + (f'<p class="nota">{e(area.get("geometry_source_note"))}</p>'
           if area.get("geometry_source_note") else "")
        for area in ficha["areas"]
    ) or "<p class=\"nota\">Este sítio não tem áreas de interesse registadas.</p>"

    parcelas = "".join(
        f"<li><b>{e(parcela['code'])}</b> {e(parcela.get('name'))} · {e(parcela.get('purpose'))}</li>"
        for parcela in ficha["parcelas"]
    )
    parcelas = (
        f'<ul class="pares">{parcelas}</ul>' if parcelas
        else '<p class="nota">Sem parcelas registadas.</p>'
    )

    inventario = "".join(
        f"<li><b>{e(facet['metric'])}</b> {facet['count']} · {e(facet.get('unit'))} · "
        f"{e(', '.join(facet.get('source_types', [])))} · "
        f"{dia((facet.get('first_observed_at') or '')[:10])} a "
        f"{dia((facet.get('last_observed_at') or '')[:10])}</li>"
        for facet in ficha["metricas"]
    )
    inventario = (
        f'<ul class="pares">{inventario}</ul>' if inventario
        else '<p class="nota">Este sítio ainda não tem observações.</p>'
    )

    return (
        '<div class="ficha"><div class="interior">'
        f"<h2>{e(sitio['code'])} — {e(sitio.get('name'))}</h2>"
        + _pares(("cultura", sitio.get("crop_type")), ("fuso", sitio.get("timezone")))
        + (f'<p class="nota">{e(sitio.get("notes"))}</p>' if sitio.get("notes") else "")
        + "<h3>Áreas de interesse</h3>"
        '<p class="nota">O contorno de cada área não é servido por esta consola: os '
        "polígonos estão num repositório privado. A área em metros quadrados e a "
        "proveniência do traçado são o que há para ver aqui.</p>"
        f"{areas}"
        "<h3>Parcelas</h3>"
        f"{parcelas}"
        "<h3>O que este sítio tem</h3>"
        f"{inventario}"
        "</div></div>"
    )


def sitios(contexto: dict[str, Any]) -> str:
    corpo = (
        "<h1>Sítios</h1>"
        '<p class="subtitulo">Os dois sítios, as áreas de interesse de cada um, e o que '
        "cada um tem gravado.</p>"
        + "".join(_ficha_de_sitio(ficha) for ficha in contexto["fichas"])
    )
    return pagina(
        "Sítios", "/console/sitios", corpo,
        contexto["ambiente"], contexto.get("avisos", ()),
    )


__all__ = ["observacoes", "sincronizacoes", "sitios"]
