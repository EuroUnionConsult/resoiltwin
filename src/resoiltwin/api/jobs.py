"""Rotas HTTP do registo de execucoes de ingestao.

As duas rotas que respondem sobre `ingestion_jobs` vivem aqui, e nao em
`api/eo.py`, pela mesma razao que `schemas/job.py` deixou de viver em
`schemas/eo.py`: a tabela deixou de ser so do satelite. A sincronizacao
meteorologica escreve as mesmas linhas, e o `GET /jobs/{id}` sempre as leu --
o modulo do satelite era ja so o sitio onde a rota calhou de nascer.

**Porque e que a listagem faltava.** O desenho inteiro da camada meteorologica
apoia-se em "a falha e visivel": varias decisoes -- derrubar o job por um valor
absurdo, por uma mudanca de estacao, por um fuso errado -- foram tomadas com o
argumento de que falhar alto e melhor do que perder em silencio. Mas so havia
maneira de ler um job de que ja se soubesse o identificador. Sem uma pergunta
do genero "o que e que correu mal?", falhar alto era tao silencioso como o
`succeeded` enganador que substituiu.

**Uma rota e nao um comando**, e a escolha tem argumento:

- reutiliza o que ja ha. O `IngestionJobRead` e a dependencia da sessao servem
  as duas rotas sem uma linha nova; um script em `scripts/` precisava do seu
  proprio acesso a base e da sua propria serializacao da mesma linha, e ficava
  a ser o unico leitor de estado de jobs que fala com a base directamente --
  todos os outros (o `restore_dev_data.py`, as respostas das rotas de sync)
  passam por HTTP;
- e a outra metade de uma rota que ja existe. Quem faz um `POST .../sync`
  recebe um job e e mandado ao `GET /jobs/{id}`; o que faltava era a pergunta
  sem identificador;
- um codigo de saida diferente de zero, que e o que tornaria um comando util,
  so serve um agendador -- e ainda nao ha nenhum. A fase que agendar a ingestao
  e a que deve trazer o comando, e ele pode chamar esta rota.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from resoiltwin.attention import ATTENTION_REASON, DIAS_FORA_DA_COBERTURA, UNCOVERED_DAYS
from resoiltwin.db import get_session
from resoiltwin.enums import JobStatus
from resoiltwin.models import IngestionJob
from resoiltwin.schemas.job import IngestionJobStatusRead

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[IngestionJobStatusRead])
def list_jobs(
    session: Session = Depends(get_session),
    job_status: JobStatus | None = Query(
        None, alias="status", description="Only jobs in this state."
    ),
    job_type: str | None = Query(
        None, description="Only jobs of this kind: eo_sync, reanalysis_sync, ipma_sync."
    ),
    needs_attention: bool = Query(
        False,
        description=(
            "Only jobs that need a human to look. What counts as such, and what "
            "deliberately does not, is documented in resoiltwin/attention.py."
        ),
    ),
    min_uncovered_days: int | None = Query(
        None,
        ge=0,
        description=(
            "Only jobs that left at least this many days of the window they asked "
            "for outside the window they covered. The number is yours: this service "
            "has no threshold of its own, and no default that judges. Jobs with no "
            "recorded requested window are never returned -- they cannot be said to "
            "have missed anything."
        ),
    ),
    limit: int = Query(50, ge=1, le=500, description="Most recent first."),
):
    """As execucoes de ingestao, da mais recente para a mais antiga.

    O `attention` e o `uncovered_days` vem em todas as linhas e nao so quando
    se filtra por eles: uma listagem que so dissesse o veredicto a quem ja o
    tivesse pedido obrigava a saber da pergunta para obter a resposta.

    `min_uncovered_days` e um filtro e nao um alarme, e a diferenca e o
    argumento todo -- esta escrito em `resoiltwin/attention.py`. O atraso de
    publicacao do AgERA5 e um mes de Inverno sem aquisicao nenhuma produzem a
    MESMA forma que a perda de 96% da serie a 29/08/2026, e so diferem em
    magnitude: qualquer fronteira que este servico escrevesse entre as duas
    seria inventada. Por isso o numero vem de quem pergunta.

    O desempate por `id` nao tem significado nenhum -- serve so para que duas
    linhas com o mesmo `started_at` saiam sempre na mesma ordem, senao um
    `limit` devolvia conjuntos diferentes para o mesmo pedido.
    """
    consulta = (
        select(IngestionJob, ATTENTION_REASON, UNCOVERED_DAYS)
        .order_by(IngestionJob.started_at.desc(), IngestionJob.id)
        .limit(limit)
    )
    if job_status is not None:
        consulta = consulta.where(IngestionJob.status == job_status)
    if job_type is not None:
        consulta = consulta.where(IngestionJob.job_type == job_type)
    if needs_attention:
        consulta = consulta.where(ATTENTION_REASON.is_not(None))
    if min_uncovered_days is not None:
        # a expressao e nao o rotulo: um alias do SELECT nao e visivel no WHERE
        # do PostgreSQL. E uma linha sem janela pedida da NULL aqui, portanto
        # nao satisfaz a comparacao e fica de fora -- que e o que se quer.
        consulta = consulta.where(DIAS_FORA_DA_COBERTURA >= min_uncovered_days)
    return [
        IngestionJobStatusRead.a_partir_de(job, atencao, dias_fora)
        for job, atencao, dias_fora in session.execute(consulta)
    ]


@router.get("/jobs/{job_id}", response_model=IngestionJobStatusRead)
def read_job(job_id: uuid.UUID, session: Session = Depends(get_session)):
    """Uma execucao, com o mesmo veredicto que a listagem lhe daria.

    E o mesmo `attention` e o mesmo `uncovered_days`, calculados pelas mesmas
    expressoes: quem chega aqui vindo de um `POST .../sync` fica a saber, sem
    ter de ir buscar a listagem, se aquela linha e das que precisam de atencao
    e quanto da janela que pediu ficou por cobrir.
    """
    linha = session.execute(
        select(IngestionJob, ATTENTION_REASON, UNCOVERED_DAYS).where(IngestionJob.id == job_id)
    ).one_or_none()
    if linha is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job '{job_id}' not found")
    return IngestionJobStatusRead.a_partir_de(*linha)
