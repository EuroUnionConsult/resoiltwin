"""Ronda do lote que repoe a janela PEDIDA ao lado da janela COBERTA.

O buraco que este lote fecha e o ultimo da familia de 29/08/2026: dois jobs de
reanalise responderam `succeeded` com `error: null` tendo gravado 6 linhas onde
havia 159. O defeito de leitura ja estava corrigido (96717e8), mas o caso
continuava indetectavel -- e a razao e que fomos nos que apagamos a informacao
que o permitia ver. O commit 68d09d7 fez o job passar a declarar a janela que
COBRIU em vez da que PEDIU, e a partir dai os dois lados de qualquer comparacao
vinham da mesma execucao.

Cada mutante aqui repoe exactamente uma parte desse estado anterior, ou
transforma a contagem nova num alarme. Nao basta morrer: a lista de apanhados
de cada um tem de nomear o teste da SUA propria guarda, senao a guarda morreu
por dano colateral e continua sem medicao.

Nota sobre os dois mutantes de migracao (`guarda-metade` e `guarda-contencao`):
mexem no texto congelado dentro da migracao 0011, que e o que constroi a base
da suite. `tests/test_schema_parity.py` cai neles tambem, e por bom motivo --
e a divergencia modelo/migracao que ele existe para apanhar. O que se verifica
nesses dois e que o teste da propria guarda esta na lista, e nao so o da
paridade.
"""

MUTANTES = [
    # --- a janela pedida deixa de ser gravada -----------------------------
    ("pedida-reanalise",
     "src/resoiltwin/weather/ingest.py",
     "        requested_date_from=inicio, requested_date_to=fim,",
     None,
     "sync_reanalysis",
     "a reanalise volta a nao registar a janela que pediu"),

    ("pedida-satelite",
     "src/resoiltwin/eo/ingest.py",
     "        requested_date_from=inicio, requested_date_to=fim,",
     None,
     "sync_aoi",
     "o satelite volta a nao registar a janela que pediu"),

    ("pedida-balanco",
     "src/resoiltwin/water/ingest.py",
     "        requested_date_from=inicio, requested_date_to=fim,",
     None,
     "sync_water_balance",
     "o balanco hidrico volta a nao registar a janela que pediu"),

    ("pedida-ipma",
     "src/resoiltwin/weather/ingest.py",
     "        date_from=janela[0], date_to=janela[1], request_hash=pedido,",
     ("        date_from=janela[0], date_to=janela[1], request_hash=pedido,"
      " requested_date_from=janela[0], requested_date_to=janela[1],"),
     "sync_ipma",
     "o IPMA passa a gravar como PEDIDA uma janela nominal que nunca pediu"),

    # --- as duas janelas passam a ser a mesma ------------------------------
    ("mesma-reanalise",
     "src/resoiltwin/weather/ingest.py",
     "        job.date_from, job.date_to = _janela_coberta_por_todas(linhas, variaveis)",
     ("        job.date_from, job.date_to = job.requested_date_from, job.requested_date_to"
      " = _janela_coberta_por_todas(linhas, variaveis)"),
     "sync_reanalysis",
     "a janela coberta e escrita por cima da pedida: o job volta a ter razao sempre"),

    ("mesma-satelite",
     "src/resoiltwin/eo/ingest.py",
     "        job.date_from, job.date_to = _janela_coberta(linhas, inicio, fim)",
     ("        job.date_from, job.date_to = job.requested_date_from, job.requested_date_to"
      " = _janela_coberta(linhas, inicio, fim)"),
     "sync_aoi",
     "a janela coberta e escrita por cima da pedida no satelite"),

    ("mesma-balanco",
     "src/resoiltwin/water/ingest.py",
     "        job.date_from, job.date_to = dias[0], dias[-1]",
     ("        job.date_from, job.date_to = job.requested_date_from, job.requested_date_to"
      " = dias[0], dias[-1]"),
     "sync_water_balance",
     "a janela coberta e escrita por cima da pedida no balanco hidrico"),

    # --- a contagem deixa de ver o caso de 29/08 ---------------------------
    ("contagem-fim",
     "src/resoiltwin/attention.py",
     ") + (IngestionJob.requested_date_to - IngestionJob.date_to)",
     ") + (IngestionJob.date_to - IngestionJob.date_to)",
     "(modulo)",
     "os dias que faltam ao FIM da janela deixam de ser contados: 29/08 da zero"),

    ("contagem-inicio",
     "src/resoiltwin/attention.py",
     "    IngestionJob.date_from - IngestionJob.requested_date_from",
     "    IngestionJob.date_from - IngestionJob.date_from",
     "(modulo)",
     "os dias que faltam ao INICIO da janela deixam de ser contados"),

    ("contagem-perdida",
     "src/resoiltwin/schemas/job.py",
     "            uncovered_days=uncovered_days,",
     "            uncovered_days=None,",
     "a_partir_de",
     "a contagem e calculada pela base e nunca chega a resposta"),

    # --- a contagem passa a disparar no caso legitimo ----------------------
    ("limiar-ignorado",
     "src/resoiltwin/api/jobs.py",
     "    if min_uncovered_days is not None:",
     "    if False:",
     "list_jobs",
     "o limiar de quem pergunta e ignorado e o atraso do arquivo volta em todas as listagens"),

    ("limiar-inventado",
     "src/resoiltwin/api/jobs.py",
     "        consulta = consulta.where(DIAS_FORA_DA_COBERTURA >= min_uncovered_days)",
     "        consulta = consulta.where(DIAS_FORA_DA_COBERTURA >= 0)",
     "list_jobs",
     "o servico troca o limiar do chamador pelo seu: o atraso do arquivo dispara sempre"),

    # --- as guardas da base ------------------------------------------------
    ("guarda-metade",
     "migrations/versions/0011_ingestion_job_requested_window.py",
     '    " OR (requested_date_from IS NOT NULL AND requested_date_to IS NOT NULL"',
     '    " OR (TRUE"',
     "(modulo)",
     "meia janela pedida passa a ser aceite, e a contencao avalia a NULL (que PASSA)"),

    ("guarda-contencao",
     "migrations/versions/0011_ingestion_job_requested_window.py",
     '    " AND date_from >= requested_date_from AND date_to <= requested_date_to)"',
     '    " AND TRUE)"',
     "(modulo)",
     "a janela coberta passa a poder sair de dentro da pedida"),
]
