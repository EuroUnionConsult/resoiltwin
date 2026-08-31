"""Ronda da consola (Fase F, Task 2).

Cada mutante diz uma coisa falsa sobre o dominio, e a coluna da direita e a
guarda que ela quebra. Os tres obrigatorios do plano sao o `i1` (o intervalo
passa a mostrar-se como um numero), o `c1` (a saturacao perde o `>=`) e o `t1`
(a trama desaparece e a origem passa a distinguir-se so pela cor).

⚠️ Ler a lista de APANHADOS de cada mutante, e nao so a contagem. Um mutante
pode morrer por dano colateral enquanto o teste da sua propria guarda fica de
pe -- e isso e uma guarda sem medicao, ainda que a tabela diga "morto". Foi
assim que a primeira ronda da Task 1 escondeu dois testes vazios.
"""

MUTANTES = [
    # -------------------------------------------------- o intervalo
    ("i1",
     "src/resoiltwin/console/formato.py",
     '            f"{numero(minimo, casas)}{SEPARADOR_DE_INTERVALO}{numero(maximo, casas)}",',
     "            numero((minimo + maximo) / 2, casas),",
     "apresentar_valor",
     "o intervalo passa a mostrar-se como um numero: o meio dele"),

    ("i2",
     "src/resoiltwin/console/formato.py",
     '        return Faixa(rampa, posicao(linha["value_min"]), posicao(linha["value_max"]))',
     '        return Faixa(rampa, 0.0, posicao((linha["value_min"] + linha["value_max"]) / 2))',
     "faixa_do_valor",
     "a banda de um intervalo passa a ir do zero ao meio dele"),

    # -------------------------------------------------- a saturacao
    ("c1",
     "src/resoiltwin/console/formato.py",
     "            f\"{MAIOR_OU_IGUAL}{ESPACO_DE_MILHARES}{numero(linha.get('value_numeric'), casas)}\",",
     '            numero(linha.get("value_numeric"), casas),',
     "apresentar_valor",
     "a leitura saturada perde o >= e passa a ler-se como uma medida"),

    # -------------------------------------------------- a trama
    ("t1",
     "src/resoiltwin/console/estilo.py",
     "TRAMA = (",
     'TRAMA = "none" or (',
     "(modulo)",
     "a trama desaparece e a origem passa a distinguir-se so pela cor"),

    ("t2",
     "src/resoiltwin/console/paginas.py",
     "        f'<span class=\"lugar\">{e(formato.lugar_da_medicao(linha))}</span></td>'",
     '        "</td>"',
     "_linha_de_observacao",
     "a origem deixa de dizer por escrito onde foi medida"),

    ("t3",
     "src/resoiltwin/console/paginas.py",
     '    parcela = "sim" if medido else "nao"',
     '    parcela = "sim"',
     "_linha_de_observacao",
     "todas as linhas se marcam como medidas na parcela"),

    # -------------------------------------------------- a proveniencia
    ("p1",
     "src/resoiltwin/console/paginas.py",
     "    if conteudo.estruturada:",
     "    if True:",
     "_painel",
     "uma linha sem proveniencia estruturada mostra um painel vazio"),

    ("q1",
     "src/resoiltwin/console/proveniencia.py",
     "        if isinstance(razao, str) and len(bruto) == 1:",
     "        if False:",
     "_valor",
     "o que a camada reteve deixa de se ler como retido"),

    # -------------------------------------------------- as coordenadas
    ("g1",
     "src/resoiltwin/api/console.py",
     "            if _e_nome_de_coordenada(chave) or _e_caixa(chave, interior):",
     "            if False:",
     "_sem_coordenadas",
     "as coordenadas de dentro da evidencia chegam ao navegador"),

    ("g2",
     "src/resoiltwin/api/console.py",
     "    return DECIMAL_DE_COORDENADA.sub(TEXTO_DE_COORDENADA_RETIDA, sem_par)",
     "    return texto",
     "_texto_sem_coordenadas",
     "uma coordenada escrita numa frase deixa de ser cortada"),

    ("g3",
     "src/resoiltwin/api/console.py",
     "    sem_par = PAR_DE_COORDENADAS.sub(TEXTO_DE_COORDENADA_RETIDA, texto)",
     "    sem_par = texto",
     "_texto_sem_coordenadas",
     "so o decimal solto e cortado: um par com poucas casas passa"),

    # -------------------------------------------------- o encaminhamento
    ("o1",
     "src/resoiltwin/main.py",
     "    app.include_router(console_views.router)",
     "    app.include_router(console.router); app.include_router(console_views.router)",
     "create_app",
     "a ordem de registo troca e o apanha-tudo ganha as paginas"),

    ("k1",
     "src/resoiltwin/main.py",
     "    app.include_router(console.router)",
     "    app.include_router(console.router, dependencies=EXIGE_CHAVE)",
     "create_app",
     "a camada passa a exigir a chave que o navegador nao tem"),

    # -------------------------------------------------- o que sai para fora
    ("e1",
     "src/resoiltwin/console/marcacao.py",
     "        '<link rel=\"stylesheet\" href=\"/console/estilo.css\">\\n'",
     "        '<link rel=\"stylesheet\" href=\"https://exemplo.invalido/consola.css\">\\n'",
     "pagina",
     "a consola passa a ir buscar a folha de estilo a um servidor de fora"),

    ("j1",
     "src/resoiltwin/console/marcacao.py",
     '        "</head>\\n<body>\\n"',
     '        "<script>const x = 1;</script></head>\\n<body>\\n"',
     "pagina",
     "a consola passa a servir codigo ao navegador"),

    # -------------------------------------------------- o tema e o movimento
    ("d1",
     "src/resoiltwin/console/estilo.py",
     "@media (prefers-color-scheme: dark) {{",
     "@media (min-width: 0px) {{",
     "(modulo)",
     "o tema escuro deixa de ser um tema: a consola so existe em claro"),

    ("m1",
     "src/resoiltwin/console/estilo.py",
     "@media (prefers-reduced-motion: no-preference) {{",
     "@media (min-width: 0px) {{",
     "(modulo)",
     "a animacao deixa de respeitar quem pediu menos movimento"),

    # -------------------------------------------------- a cor
    ("v1",
     "src/resoiltwin/console/paleta.py",
     '    "realce": "#E8EEF2",',
     '    "realce": "#DCE8FF",',
     "(modulo)",
     "a moldura ganha saturacao e deixa de ser so a cor dos dados"),

    ("w1",
     "src/resoiltwin/console/paleta.py",
     '    SourceType.reanalysis: "#B69C76",',
     '    SourceType.reanalysis: "#7695B6",',
     "(modulo)",
     "a escala de proveniencia sai da matiz 10YR"),

    ("r1",
     "src/resoiltwin/console/paleta.py",
     'AGUA = ("#C4622A", "#D9A05C", "#D8CBB0", "#7FA8B8", "#2E6E8E")',
     'AGUA = ("#C4622A", "#D8C42A", "#2AC44A", "#2A6EC4", "#8A2AC4")',
     "(modulo)",
     "a rampa da agua passa a ser um arco-iris"),

    # -------------------------------------------------- os numeros e a origem
    ("f1",
     "src/resoiltwin/console/formato.py",
     '    return texto.replace(",", "\\x00").replace(".", ",").replace("\\x00", ESPACO_DE_MILHARES)',
     "    return texto",
     "numero",
     "os numeros passam a escrever-se com ponto decimal"),

    ("x1",
     "src/resoiltwin/console/formato.py",
     '        return evidencia["measured_at_site"]',
     "        pass",
     "medido_na_parcela",
     "a linha deixa de dizer de si propria e deduz-se sempre pela origem"),

    # -------------------------------------------------- as sincronizacoes
    ("s1",
     "src/resoiltwin/console/paginas.py",
     '        f\'{" a " + dia(execucao.get("requested_date_to")) if execucao.get("requested_date_to") else ""}\'',
     '        f\'{" a " + dia(execucao.get("date_to"))}\'',
     "_linha_de_execucao",
     "a janela pedida passa a mostrar a data da coberta: as duas viram uma"),

    ("u1",
     "src/resoiltwin/console/paginas.py",
     '        f\'{"não medível" if dias is None else dias}</span></td>\'',
     '        "</span></td>"',
     "_linha_de_execucao",
     "os dias por cobrir deixam de aparecer"),

    # -------------------------------------------------- o inventario
    ("n1",
     "src/resoiltwin/api/observations.py",
     "        metrics=_inventario(session, site),",
     "        metrics=[f for f in _inventario(session, site) if metric in (None, f.metric)],",
     "list_observations",
     "o inventario passa a sair do filtro e encolhe com ele"),
]

# Acrescentados depois de a propria consola ter sido apanhada a mentir: uma
# leitura que falhava desenhava-se como uma tabela vazia com a legenda "nenhuma
# observacao corresponde a este filtro". Vazio e ilegivel sao duas coisas.
MUTANTES += [
    ("y1",
     "src/resoiltwin/console/marcacao.py",
     "    corpo = _falhas(avisos) + corpo",
     "    corpo = corpo + ''",
     "pagina",
     "a falha de leitura deixa de ser mostrada e a pagina parece so vazia"),

    ("y2",
     "src/resoiltwin/api/console_views.py",
     "            self.avisos.append(falha)",
     "            pass",
     "__call__",
     "a falha de leitura e engolida antes de chegar a pagina"),
]

# Acrescentados depois de ler a lista de apanhados e nao a contagem. Duas
# guardas estavam de pe sem nenhum mutante a medi-las:
#   - "as paginas nao pedem credencial" so caia por dano colateral do `o1`, que
#     as torna inalcancaveis -- e inalcancavel nao e o mesmo que fechada;
#   - "a escala de proveniencia ordena-se por contraste" sobreviveu ao `w1`,
#     porque a cor que ele troca tem quase a mesma claridade da original.
MUTANTES += [
    ("k2",
     "src/resoiltwin/main.py",
     "    app.include_router(console_views.router)",
     "    app.include_router(console_views.router, dependencies=EXIGE_CHAVE)",
     "create_app",
     "as paginas passam a exigir a chave que o navegador nao tem"),

    ("w2",
     "src/resoiltwin/console/paleta.py",
     '    SourceType.observed_lab: "#33281E",',
     '    SourceType.observed_lab: "#EDE4D4",',
     "(modulo)",
     "a medicao mais directa passa a ser a de menos contraste: a ordem inverte-se"),
]
