"""Ronda dos achados F1, F2 e F3 da caca a falhas silenciosas, mais o R15.

Os tres achados sao da mesma familia: o sistema perde dados ou grava um numero
errado e diz que correu bem. Dois deles a suite NAO PODIA apanhar antes deste
lote, e isso foi medido e nao deduzido -- a ronda `antes` (HEAD cd2f4ef)
confirmou que `serie.append(parcial[0])` e um `break` depois da primeira
variavel sobreviviam aos 530 testes.

Cada mutante aqui repoe exactamente o comportamento anterior de uma guarda. Se
sobreviver, a guarda nao esta a ser defendida por teste nenhum. E nao basta
morrer: a lista de apanhados de cada um tem de nomear o teste da SUA propria
guarda, senao a guarda morreu por dano colateral e continua sem medicao.
"""

MUTANTES = [
    # --- F1: um no sem dado nao e uma medicao -----------------------------
    ("f1-guarda",
     "src/resoiltwin/weather/cds.py",
     "            if _e_sem_dado(bruto):",
     "            if False:",
     "_ler_netcdf_solto",
     "o dia sem dado volta a ser gravado (NaN como medicao exacta)"),

    ("f1-mascara",
     "src/resoiltwin/weather/cds.py",
     "    if numpy.ma.is_masked(valor):",
     "    if False:",
     "_e_sem_dado",
     "a mascara deixa de ser perguntada e o float() do numpy e que decide"),

    ("f1-contagem",
     "src/resoiltwin/weather/cds.py",
     '                linha["masked_days_dropped"] = len(sem_dado)',
     '                linha["masked_days_dropped"] = 0',
     "agera5_diario",
     "a linha afirma que nao houve dias saltados quando houve"),

    ("f1-base",
     "migrations/versions/0009_observation_values_are_finite.py",
     "    \"(value_numeric IS NULL OR (value_numeric > '-Infinity'::double precision\"",
     "    \"(TRUE OR (value_numeric > '-Infinity'::double precision\"",
     "(modulo)",
     "a base volta a aceitar NaN em value_numeric"),

    # --- F2: a janela do job e verdadeira para todas as variaveis ---------
    ("f2-break",
     "src/resoiltwin/weather/cds.py",
     "        for variavel in variaveis:",
     "        for variavel in variaveis[:1]:",
     "agera5_diario",
     "so a primeira variavel pedida e transferida"),

    ("f2-fim",
     "src/resoiltwin/weather/ingest.py",
     "    fim = min(max(momentos) for momentos in por_variavel.values()).date()",
     "    fim = max(max(momentos) for momentos in por_variavel.values()).date()",
     "_janela_coberta_por_todas",
     "o fim do job volta a ser o ultimo dia de QUALQUER variavel"),

    ("f2-inicio",
     "src/resoiltwin/weather/ingest.py",
     "    inicio = max(min(momentos) for momentos in por_variavel.values()).date()",
     "    inicio = min(min(momentos) for momentos in por_variavel.values()).date()",
     "_janela_coberta_por_todas",
     "o inicio do job volta a ser o primeiro dia de QUALQUER variavel"),

    ("f2-vazia",
     "src/resoiltwin/weather/ingest.py",
     "    if vazias:",
     "    if False:",
     "_janela_coberta_por_todas",
     "uma variavel pedida que nao trouxe uma unica linha passa em silencio"),

    # --- F3: o zip e lido ate ao fim de cada membro -----------------------
    ("f3-membro",
     "src/resoiltwin/weather/cds.py",
     "            serie.extend(parcial)",
     "            serie.append(parcial[0])",
     "ler_serie_netcdf",
     "de cada membro do zip so sai o primeiro dia"),

    # --- R15: a ET0 e pedida por omissao ----------------------------------
    ("r15-et0",
     "src/resoiltwin/weather/ingest.py",
     '             "reference_evapotranspiration")',
     "             )",
     "(modulo)",
     "a evapotranspiracao de referencia deixa de ser pedida por omissao"),
]
