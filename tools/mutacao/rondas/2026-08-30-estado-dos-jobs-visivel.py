"""Ronda sobre o veredicto de atencao dos jobs e sobre a rota que o mostra.

A divida numero 4 da Fase C. Ninguem olhava para `ingestion_jobs.status`, e o
desenho inteiro da camada meteorologica apoia-se em "a falha e visivel". A
peca que faltava e a definicao do que precisa de atencao mais a rota que a
responde sem se saber o identificador de antemao.

Cada mutante afirma uma coisa falsa: ou sobre a regra (o que conta como
atencao), ou sobre a rota (o que a listagem devolve). Um mutante que sobreviva
e um pedaco que nenhum teste esta a defender.

Nota sobre o que NAO esta aqui: a condicao `_OUTRA.id != IngestionJob.id` do
`exists` e hoje redundante -- o ramo so corre sobre linhas com zero linhas
escritas -- e um mutante que a apague seria equivalente, sobreviveria sempre e
nao diria nada. A razao de ela existir esta escrita ao lado dela.
"""

REGRA = "src/resoiltwin/attention.py"
ROTA = "src/resoiltwin/api/jobs.py"

MUTANTES = [
    # -- a regra: o que conta como atencao -----------------------------------
    ("a1",
     REGRA,
     "    (IngestionJob.status == JobStatus.failed, AttentionReason.failed.value),",
     "    (IngestionJob.status == JobStatus.running, AttentionReason.failed.value),",
     "(modulo)",
     "o ramo de 'failed' olha para o estado errado"),

    ("a2",
     REGRA,
     "            IngestionJob.finished_at.is_(None),",
     "            IngestionJob.finished_at.is_not(None),",
     "(modulo)",
     "quem nunca registou o fim deixa de contar, e quem o registou passa a contar"),

    ("a3",
     REGRA,
     "            IngestionJob.status.in_((JobStatus.pending, JobStatus.running)),",
     "            IngestionJob.status.in_((JobStatus.running,)),",
     "(modulo)",
     "um job que ficou em pending e nunca arrancou nao precisa de atencao"),

    ("a4",
     REGRA,
     "            IngestionJob.rows_written == 0,",
     None,
     "(modulo)",
     "um job que escreveu linhas e marcado como se nao tivesse escrito nenhuma"),

    ("a5",
     REGRA,
     "            IngestionJob.status == JobStatus.succeeded,",
     "            IngestionJob.status == JobStatus.pending,",
     "(modulo)",
     "um job vazio que disse que correu bem nao precisa de atencao"),

    ("a6",
     REGRA,
     "            ~_OUTRA_EXECUCAO_DO_MESMO_PEDIDO_ESCREVEU,",
     "            _OUTRA_EXECUCAO_DO_MESMO_PEDIDO_ESCREVEU,",
     "(modulo)",
     "a regra inverte-se: so as repeticoes legitimas sao marcadas"),

    ("a7",
     REGRA,
     "        _OUTRA.request_hash == IngestionJob.request_hash,",
     None,
     "(modulo)",
     "qualquer job que tenha escrito desculpa um vazio, mesmo de outro pedido"),

    ("a8",
     REGRA,
     "        _OUTRA.rows_written > 0,",
     "        _OUTRA.rows_written >= 0,",
     "(modulo)",
     "basta existir outra execucao do mesmo pedido, tenha ela escrito ou nao"),

    # -- a rota: o que a listagem devolve ------------------------------------
    ("j1",
     ROTA,
     "        consulta = consulta.where(ATTENTION_REASON.is_not(None))",
     "        consulta = consulta.where(ATTENTION_REASON.is_(None))",
     "list_jobs",
     "o filtro de atencao devolve exactamente o contrario do que promete"),

    ("j2",
     ROTA,
     "    if needs_attention:",
     "    if False:",
     "list_jobs",
     "o filtro de atencao e ignorado e a listagem vem inteira"),

    ("j3",
     ROTA,
     "        .order_by(IngestionJob.started_at.desc(), IngestionJob.id)",
     "        .order_by(IngestionJob.started_at, IngestionJob.id)",
     "list_jobs",
     "a listagem vem do mais antigo para o mais recente"),

    ("j4",
     ROTA,
     "        .limit(limit)",
     None,
     "list_jobs",
     "o limite pedido e ignorado e a listagem vem toda"),

    ("j5",
     ROTA,
     "    if job_status is not None:",
     "    if False:",
     "list_jobs",
     "o filtro de estado e ignorado em silencio"),

    ("j6",
     ROTA,
     "    if job_type is not None:",
     "    if False:",
     "list_jobs",
     "o filtro de tipo de job e ignorado em silencio"),

    ("j7",
     ROTA,
     '    limit: int = Query(50, ge=1, le=500, description="Most recent first."),',
     '    limit: int = Query(50, description="Most recent first."),',
     "list_jobs",
     "um limite fora da gama e aceite em vez de recusado"),

    ("j8",
     ROTA,
     "    if linha is None:",
     "    if False:",
     "read_job",
     "um identificador que nao existe rebenta em vez de dar 404"),
]
