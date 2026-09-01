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

**Nenhum texto visivel esta escrito neste ficheiro.** Todos vem de `textos.py`,
pela chave, na lingua que o pedido pediu -- ingles quando nao pediu nada. Uma
cadeia escrita aqui existiria numa lingua so, e desaparecia na outra sem que
nada caisse.
"""

from typing import Any

from resoiltwin.console import formato, proveniencia
from resoiltwin.console.marcacao import dia, e, endereco, momento, pagina
from resoiltwin.console.paleta import ORDEM_DA_PROVENIENCIA
from resoiltwin.console.textos import LINGUA_POR_OMISSAO, PARAMETRO_DA_LINGUA, Textos

TAMANHOS = (50, 100, 250, 500)
TAMANHO_POR_OMISSAO = 100

TODAS = ""  # o valor da opcao "sem filtro", num sitio so

VISTA_DAS_OBSERVACOES = "/console/observacoes"


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


def _marca(origem: str, medido: bool, textos: Textos) -> str:
    """O quadrado da origem: cor 10YR, e trama quando nao foi medido aqui."""
    chave = "valor.na_parcela" if medido else "valor.fora_da_parcela"
    return (
        f'<span class="marca" style="--prov: var(--prov-{e(origem)})" '
        f'role="img" aria-label="{e(textos[chave])}"></span>'
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


def _linha_de_observacao(
    linha: dict[str, Any], seleccionada: bool, destino: str, textos: Textos
) -> str:
    valor = formato.apresentar_valor(linha, textos)
    medido = formato.medido_na_parcela(linha)
    parcela = "sim" if medido else "nao"
    escolha = ' data-seleccionada="sim"' if seleccionada else ""
    return (
        f'<tr class="linha" data-linha="{e(linha["id"])}" data-parcela="{parcela}"{escolha}>'
        f'<td class="quando">{momento(linha.get("observed_at"), textos)}</td>'
        f'<td class="metrica">{e(linha.get("metric"))}</td>'
        f'<td class="valor" data-forma="{e(valor.forma)}">'
        f'<span class="numero">{e(valor.texto)}</span>'
        f'<span class="unidade">{e(linha.get("unit"))}</span>'
        f"{_barra(linha, medido)}</td>"
        f'<td class="origem">'
        f'<span class="par">{_marca(str(linha.get("source_type")), medido, textos)}'
        f'<span class="nome">{e(linha.get("source_type"))}</span></span>'
        f'<span class="lugar">{e(formato.lugar_da_medicao(linha, textos))}</span></td>'
        f'<td class="qualidade">{e(linha.get("quality_flag"))}</td>'
        f'<td class="versao">{e(linha.get("processing_version"))}</td>'
        f'<td class="abrir"><a href="{e(destino)}#proveniencia">'
        f'{e(textos["coluna.abrir"])}</a></td>'
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


def _painel(linha: dict[str, Any] | None, textos: Textos) -> str:
    titulo = f"<h3>{e(textos['painel.titulo'])}</h3>"
    if linha is None:
        return (
            '<aside class="proveniencia" id="proveniencia"><div class="interior">'
            f'{titulo}<p class="em-falta">{e(textos["painel.escolha"])}</p>'
            "</div></aside>"
        )
    conteudo = proveniencia.painel_de(linha, textos)
    valor = formato.apresentar_valor(linha, textos)
    cabeca = (
        f"{titulo}"
        f'<p class="contagem">{e(linha.get("metric"))} · '
        f'{e(valor.texto)} {e(linha.get("unit"))}</p>'
        f'<p class="lugar">{e(formato.lugar_da_medicao(linha, textos))} · '
        f'{momento(linha.get("observed_at"), textos)}</p>'
    )
    if conteudo.estruturada:
        corpo = _campos(conteudo.da_evidencia)
    else:
        corpo = (
            f'<p class="em-falta"><strong>{e(textos["prov.sem_proveniencia"])}</strong>'
            f'{e(textos["prov.porque_falta"])}</p>'
        )
    return (
        '<aside class="proveniencia" id="proveniencia"><div class="interior">'
        f"{cabeca}{corpo}"
        f"<h3>{e(textos['painel.na_linha'])}</h3>"
        f"{_campos(conteudo.da_linha)}"
        "</div></aside>"
    )


def _legenda(textos: Textos) -> str:
    escala = "".join(
        f'<li><span class="marca" style="--prov: var(--prov-{origem.value})"></span>'
        f"{e(origem.value)}</li>"
        for origem in ORDEM_DA_PROVENIENCIA
    )
    solido = textos.formatar("legenda.solido", lugar=textos["valor.na_parcela"])
    tramado = textos.formatar("legenda.tramado", lugar=textos["valor.fora_da_parcela"])
    return (
        '<ul class="legenda">'
        f'<li><span class="marca" style="--prov: var(--prov-observed_screening)"></span>'
        f"{e(solido)}</li>"
        f'<li data-parcela="nao"><span class="marca" '
        f'style="--prov: var(--prov-observed_screening)"></span>'
        f"{e(tramado)}</li>"
        "</ul>"
        '<ul class="legenda">'
        f'<li>{e(textos["legenda.escala"])}</li>'
        f"{escala}</ul>"
    )


def _endereco(base: dict[str, Any], textos: Textos, **mudancas) -> str:
    return endereco(VISTA_DAS_OBSERVACOES, textos.lingua, {**base, **mudancas})


def observacoes(contexto: dict[str, Any]) -> str:
    """A tabela, os filtros, e o painel da linha escolhida."""
    textos: Textos = contexto["textos"]
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
            _endereco(filtros, textos, linha=linha["id"]),
            textos,
        )
        for linha in linhas
    )
    if not corpo_da_tabela:
        corpo_da_tabela = f'<tr><td class="vazio" colspan="7">{e(textos["obs.vazio"])}</td></tr>'

    total, devolvidas = inventario.get("total", 0), inventario.get("returned", 0)
    chave = "obs.resumo.uma" if total == 1 else "obs.resumo.varias"
    resumo = '<p class="subtitulo">' + textos.formatar(
        chave,
        total=f'<span class="contagem">{e(total)}</span>',
        devolvidas=f'<span class="contagem">{e(devolvidas)}</span>',
    ) + "</p>"

    codigo_do_sitio = filtros.get("sitio")
    opcoes_de_sitio = _opcoes(
        [(s["code"], f'{s["code"]} — {s["name"]}') for s in contexto["sitios"]], codigo_do_sitio
    )
    opcoes_de_metrica = _opcoes(
        metricas, filtros.get("metrica"), textos["filtro.todas_as_metricas"]
    )
    opcoes_de_origem = _opcoes(
        [(o, o) for o in origens], filtros.get("origem"), textos["filtro.todas_as_origens"]
    )
    opcoes_de_tamanho = _opcoes([(n, n) for n in TAMANHOS], filtros.get("n"))
    limpar = _endereco({"sitio": codigo_do_sitio}, textos)

    # ⚠️ O formulario e um `GET` sem campo de lingua nenhum, e por isso filtrar
    # em portugues levaria de volta ao ingles. A lingua viaja num campo
    # escondido, pelo mesmo caminho que os filtros -- e nao numa segunda
    # ligacao, que se perderia no dia em que alguem carregasse no botao.
    escondido = (
        f'<input type="hidden" name="{e(PARAMETRO_DA_LINGUA)}" value="{e(textos.lingua)}">'
        if textos.lingua != LINGUA_POR_OMISSAO
        else ""
    )
    formulario = (
        f'<form class="filtros" method="get" action="{VISTA_DAS_OBSERVACOES}">'
        f'<label><span>{e(textos["filtro.sitio"])}</span>'
        f'<select name="sitio">{opcoes_de_sitio}</select></label>'
        f'<label><span>{e(textos["filtro.metrica"])}</span>'
        f'<select name="metrica">{opcoes_de_metrica}</select></label>'
        f'<label><span>{e(textos["filtro.origem"])}</span>'
        f'<select name="origem">{opcoes_de_origem}</select></label>'
        f'<label><span>{e(textos["filtro.linhas"])}</span>'
        f'<select name="n">{opcoes_de_tamanho}</select></label>'
        f'{escondido}'
        f'<button type="submit">{e(textos["filtro.botao"])}</button>'
        f'<a class="limpar" href="{e(limpar)}">{e(textos["filtro.limpar"])}</a>'
        "</form>"
    )

    cabecalhos = "".join(
        f"<th>{e(textos[chave])}</th>"
        for chave in (
            "coluna.quando", "coluna.metrica", "coluna.valor", "coluna.origem",
            "coluna.qualidade", "coluna.versao",
        )
    )
    tabela = (
        '<div class="tabela"><table>'
        f"<thead><tr>{cabecalhos}<th></th></tr></thead>"
        f"<tbody>{corpo_da_tabela}</tbody>"
        "</table></div>"
    )

    corpo = (
        f"<h1>{e(textos['obs.titulo'])}</h1>"
        f"{resumo}{formulario}{_legenda(textos)}"
        f'<div class="duas-colunas">{tabela}{_painel(seleccionada, textos)}</div>'
    )
    return pagina(
        textos["obs.titulo"], VISTA_DAS_OBSERVACOES, corpo,
        contexto["ambiente"], textos, filtros, contexto.get("avisos", ()),
    )


# ---------------------------------------------------------------------------
# Sincronizacoes
# ---------------------------------------------------------------------------

# ⭐ Os tres veredictos. A chave e o que a API devolve em `attention`; o texto
# esta em `textos.py`, e nas duas linguas ele ACUSA a execucao em vez de
# descrever um estado. As tres formas de perder dados em silencio que este
# projecto ja apanhou foram execucoes que declararam sucesso.
CHAVES_DOS_VEREDICTOS = {
    "failed": "veredicto.failed",
    "never_finished": "veredicto.never_finished",
    "succeeded_without_writing": "veredicto.succeeded_without_writing",
}


def _veredicto(atencao, textos: Textos) -> str:
    chave = CHAVES_DOS_VEREDICTOS.get(atencao)
    return textos[chave] if chave else str(atencao)


def _linha_de_execucao(execucao: dict[str, Any], textos: Textos) -> str:
    atencao = execucao.get("attention")
    dias = execucao.get("uncovered_days")
    ate = execucao.get("requested_date_to")
    return (
        f'<tr class="linha" data-execucao="{e(execucao.get("job_type"))}" '
        f'data-atencao="{"sim" if atencao else "nao"}">'
        f'<td class="quando">{momento(execucao.get("started_at"), textos)}</td>'
        f'<td class="metrica">{e(execucao.get("job_type"))}</td>'
        f'<td class="estado">{e(execucao.get("status"))}'
        + (
            f'<span class="lugar veredicto">{e(_veredicto(atencao, textos))}</span>'
            if atencao
            else ""
        )
        + "</td>"
        f'<td class="janelas">'
        f'<span class="janela"><b>{e(textos["sinc.janela.pedida"])}</b> '
        f'{dia(execucao.get("requested_date_from"), textos) or e(textos["sinc.nao_registada"])}'
        f'{textos["sinc.janela.ate"] + dia(ate, textos) if ate else ""}'
        "</span>"
        f'<span class="janela"><b>{e(textos["sinc.janela.coberta"])}</b> '
        f'{dia(execucao.get("date_from"), textos)}{textos["sinc.janela.ate"]}'
        f'{dia(execucao.get("date_to"), textos)}</span></td>'
        f'<td class="valor"><span class="numero">'
        f'{e(textos["sinc.sem_janela_pedida"]) if dias is None else e(dias)}</span></td>'
        f'<td class="valor"><span class="numero">{e(execucao.get("rows_written"))}</span></td>'
        f'<td class="versao">'
        f'{e(execucao.get("processing_version") or textos["sinc.nao_registada"])}</td>'
        f'<td class="erro">{e(execucao.get("error") or "")}</td>'
        "</tr>"
    )


def sincronizacoes(contexto: dict[str, Any]) -> str:
    textos: Textos = contexto["textos"]
    execucoes = contexto["execucoes"]
    precisam = [linha for linha in execucoes if linha.get("attention")]

    cabecalhos = "".join(
        f"<th>{e(textos[chave])}</th>"
        for chave in (
            "sinc.coluna.comecou", "sinc.coluna.tipo", "sinc.coluna.estado",
            "sinc.coluna.janelas", "sinc.coluna.dias", "sinc.coluna.linhas",
            "sinc.coluna.versao", "sinc.coluna.erro",
        )
    )

    def tabela(linhas: list[dict[str, Any]], vazio: str) -> str:
        corpo = "".join(_linha_de_execucao(linha, textos) for linha in linhas)
        if not corpo:
            corpo = f'<tr><td class="vazio" colspan="8">{e(vazio)}</td></tr>'
        return (
            '<div class="tabela"><table><thead><tr>'
            f"{cabecalhos}"
            f"</tr></thead><tbody>{corpo}</tbody></table></div>"
        )

    corpo = (
        f"<h1>{e(textos['sinc.titulo'])}</h1>"
        f'<p class="subtitulo">{e(textos["sinc.subtitulo"])}</p>'
        f"<h2>{e(textos.formatar('sinc.atencao.titulo', quantas=len(precisam)))}</h2>"
        f'<p class="subtitulo">{e(textos["sinc.atencao.subtitulo"])}</p>'
        + tabela(precisam, textos["sinc.atencao.vazio"])
        + f"<h2>{e(textos.formatar('sinc.todas.titulo', quantas=len(execucoes)))}</h2>"
        f'<p class="subtitulo">{e(textos["sinc.todas.subtitulo"])}</p>'
        + tabela(execucoes, textos["sinc.todas.vazio"])
    )
    return pagina(
        textos["sinc.titulo"], "/console/sincronizacoes", corpo,
        contexto["ambiente"], textos, None, contexto.get("avisos", ()),
    )


# ---------------------------------------------------------------------------
# Sitios
# ---------------------------------------------------------------------------

def _pares(*campos) -> str:
    itens = "".join(f"<li><b>{e(rotulo)}</b> {e(valor)}</li>" for rotulo, valor in campos if valor)
    return f'<ul class="pares">{itens}</ul>'


def _ficha_de_sitio(ficha: dict[str, Any], textos: Textos) -> str:
    sitio = ficha["sitio"]
    areas = "".join(
        "<h3>" + e(area["code"]) + "</h3>"
        + _pares(
            (textos["sitios.par.finalidade"], area.get("purpose")),
            (textos["sitios.par.area"], f'{formato.numero(area.get("area_m2"), 0, textos)} m²'),
            (textos["sitios.par.proveniencia"], area.get("geometry_provenance")),
            (textos["sitios.par.estado"], area.get("status")),
            (textos["sitios.par.aprovada_por"], area.get("approved_by")),
        )
        + (f'<p class="nota">{e(area.get("geometry_source_note"))}</p>'
           if area.get("geometry_source_note") else "")
        for area in ficha["areas"]
    ) or f'<p class="nota">{e(textos["sitios.sem_areas"])}</p>'

    parcelas = "".join(
        f"<li><b>{e(parcela['code'])}</b> {e(parcela.get('name'))} · {e(parcela.get('purpose'))}</li>"
        for parcela in ficha["parcelas"]
    )
    parcelas = (
        f'<ul class="pares">{parcelas}</ul>' if parcelas
        else f'<p class="nota">{e(textos["sitios.sem_parcelas"])}</p>'
    )

    inventario = "".join(
        f"<li><b>{e(facet['metric'])}</b> {facet['count']} · {e(facet.get('unit'))} · "
        f"{e(', '.join(facet.get('source_types', [])))} · "
        + e(textos.formatar(
            "sitios.periodo",
            inicio=dia((facet.get("first_observed_at") or "")[:10], textos),
            fim=dia((facet.get("last_observed_at") or "")[:10], textos),
        ))
        + "</li>"
        for facet in ficha["metricas"]
    )
    inventario = (
        f'<ul class="pares">{inventario}</ul>' if inventario
        else f'<p class="nota">{e(textos["sitios.sem_observacoes"])}</p>'
    )

    return (
        '<div class="ficha"><div class="interior">'
        f"<h2>{e(sitio['code'])} — {e(sitio.get('name'))}</h2>"
        + _pares(
            (textos["sitios.par.cultura"], sitio.get("crop_type")),
            (textos["sitios.par.fuso"], sitio.get("timezone")),
        )
        + (f'<p class="nota">{e(sitio.get("notes"))}</p>' if sitio.get("notes") else "")
        + f"<h3>{e(textos['sitios.areas'])}</h3>"
        f'<p class="nota">{e(textos["sitios.aviso_contorno"])}</p>'
        f"{areas}"
        f"<h3>{e(textos['sitios.parcelas'])}</h3>"
        f"{parcelas}"
        f"<h3>{e(textos['sitios.inventario'])}</h3>"
        f"{inventario}"
        "</div></div>"
    )


def sitios(contexto: dict[str, Any]) -> str:
    textos: Textos = contexto["textos"]
    corpo = (
        f"<h1>{e(textos['sitios.titulo'])}</h1>"
        f'<p class="subtitulo">{e(textos["sitios.subtitulo"])}</p>'
        + "".join(_ficha_de_sitio(ficha, textos) for ficha in contexto["fichas"])
    )
    return pagina(
        textos["sitios.titulo"], "/console/sitios", corpo,
        contexto["ambiente"], textos, None, contexto.get("avisos", ()),
    )


__all__ = ["observacoes", "sincronizacoes", "sitios"]
