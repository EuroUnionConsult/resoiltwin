"""Ronda dos achados F5 e F6 da caca a falhas silenciosas.

Os dois sao da mesma familia: a linha afirma menos do que sabe, e quem a le nao
consegue aprender a diferenca dela. O F6 e o periodo de agregacao que nunca
chegava ao `evidence` -- tres series de `air_temperature` em `degC` no mesmo
sitio, e duas de `solar_radiation` em `W/m2` com uma ordem de grandeza de
diferenca ao meio-dia. O F5 e a identidade do ficheiro de origem, que so servia
para nomear um ficheiro temporario e nunca chegava a base.

Cada mutante repoe exactamente o comportamento anterior de uma guarda, ou
apaga a chave que a fecha. Nao basta morrer: a lista de apanhados de cada um
tem de nomear o teste da SUA propria guarda, senao a guarda morreu por dano
colateral e continua sem medicao.
"""

MUTANTES = [
    # --- F6: a chave cai do `evidence` -------------------------------------
    ("f6-evidencia-reanalise",
     "src/resoiltwin/weather/ingest.py",
     '            **linha["aggregation"],',
     None,
     "_observacao",
     "a linha de reanalise volta a nao dizer o que o numero resume"),

    ("f6-evidencia-estacao",
     "src/resoiltwin/weather/ingest.py",
     "            **agregacao_da_estacao,",
     None,
     "_observacao_de_estacao",
     "so a reanalise fica etiquetada, que e pior do que nenhuma estar"),

    # --- F6: o caso "esta variavel nao tem estatistica" deixa de estar
    #     distinguido do caso "ninguem preencheu" -----------------------------
    ("f6-undeclared-com-periodo",
     "src/resoiltwin/weather/metrics.py",
     "        if periodo_horas is not None:",
     "        if False:",
     "proveniencia_de_agregacao",
     "o `undeclared` passa a aceitar um periodo: o null deixa de estar preso a ele"),

    ("f6-operador-sem-periodo",
     "src/resoiltwin/weather/metrics.py",
     "        if periodo_horas is None:",
     "        if False:",
     "proveniencia_de_agregacao",
     "uma media passa a poder vir sem periodo: o null passa a ser ambiguo"),

    ("f6-palpite-na-estacao",
     "src/resoiltwin/weather/ipma.py",
     '    "temperatura": proveniencia_de_agregacao(AggregationOperator.undeclared, None),',
     '    "temperatura": proveniencia_de_agregacao(AggregationOperator.mean, 1),',
     "(modulo)",
     "o campo que a origem nao declara passa a afirmar uma media horaria"),

    ("f6-periodo-da-radiacao",
     "src/resoiltwin/weather/ipma.py",
     '    "radiacao": proveniencia_de_agregacao(AggregationOperator.mean, 1),',
     '    "radiacao": proveniencia_de_agregacao(AggregationOperator.mean, 24),',
     "(modulo)",
     "a media horaria da estacao passa a declarar as 24 h da reanalise"),

    # --- F6: o dicionario e partilhado entre linhas -------------------------
    ("f6-alias-reanalise",
     "src/resoiltwin/weather/cds.py",
     '                        "aggregation": dict(_AGREGACAO_AGERA5[variavel]),',
     '                        "aggregation": _AGREGACAO_AGERA5[variavel],',
     "agera5_diario",
     "as linhas todas passam a partilhar o dicionario da tabela"),

    ("f6-alias-estacao",
     "src/resoiltwin/weather/ipma.py",
     '                "aggregation": dict(_AGREGACAO_POR_CAMPO[campo]),',
     '                "aggregation": _AGREGACAO_POR_CAMPO[campo],',
     "linhas_da_estacao",
     "24 horas de linhas passam a partilhar o dicionario da tabela"),

    # --- F5: a identidade do ficheiro cai do `evidence` ---------------------
    ("f5-evidencia",
     "src/resoiltwin/weather/ingest.py",
     '            "source_file": linha["source_file"],',
     None,
     "_observacao",
     "nenhuma linha volta a saber dizer de que ficheiro veio"),

    # --- F5: a identidade deixa de ser POR DIA ------------------------------
    ("f5-por-chamada",
     "src/resoiltwin/weather/cds.py",
     "            serie.extend((dia, valor, membro) for dia, valor in parcial)",
     "            serie.extend((dia, valor, membros[0]) for dia, valor in parcial)",
     "ler_serie_netcdf",
     "os dias todos do zip passam a nomear o primeiro membro"),

    ("f5-nome-extraido",
     "src/resoiltwin/weather/cds.py",
     "            serie.extend((dia, valor, membro) for dia, valor in parcial)",
     "            serie.extend((dia, valor, destino.name) for dia, valor in parcial)",
     "ler_serie_netcdf",
     "a linha grava o nome com que NOS extraimos o membro, nao o da origem"),

    ("f5-nome-inventado",
     "src/resoiltwin/weather/cds.py",
     "                    ficheiro = self.download(job_id, Path(pasta))",
     '                    ficheiro = self.download(job_id, Path(pasta) / f"{job_id}.nc")',
     "agera5_diario",
     "o .nc solto volta a chamar-se pelo nosso nome e nao pelo da origem"),
]
