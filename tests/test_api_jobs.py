"""O estado dos jobs deixa de ser invisivel.

Duas metades: a regra que decide o que precisa de atencao
(`resoiltwin/attention.py`) e a rota que a poe a vista (`api/jobs.py`).

Os `started_at` sao todos escritos a mao. O `server_default` da coluna e
`now()`, que no PostgreSQL e a hora de inicio da TRANSACCAO -- e a sessao de
testes corre tudo dentro de uma so, portanto todas as linhas nasceriam com o
mesmo instante e a ordenacao da listagem nao teria nada que ordenar.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select

from resoiltwin.attention import ATTENTION_REASON, AttentionReason
from resoiltwin.enums import JobStatus
from resoiltwin.models import IngestionJob

_INICIO = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
_FIM = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _job(session, aoi, *, status, rows=0, request_hash="pedido-a", error=None,
         finished_at=_FIM, job_type="eo_sync", minuto=0):
    job = IngestionJob(
        aoi_id=aoi.id,
        job_type=job_type,
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 29),
        request_hash=request_hash,
        status=status,
        rows_written=rows,
        error=error,
        started_at=_INICIO.replace(minute=minuto),
        finished_at=finished_at,
    )
    session.add(job)
    session.commit()
    return job


def _atencao(session, job):
    """O veredicto que a base da a esta linha."""
    return session.execute(
        select(ATTENTION_REASON).select_from(IngestionJob).where(IngestionJob.id == job.id)
    ).scalar_one()


# -- a regra -----------------------------------------------------------------


def test_a_failed_job_needs_attention(session, aoi_aprovada):
    job = _job(session, aoi_aprovada, status=JobStatus.failed, error="ReadTimeout")
    assert _atencao(session, job) == AttentionReason.failed


def test_a_job_that_wrote_rows_and_said_so_needs_nothing(session, aoi_aprovada):
    """Controlo negativo. Sem ele, uma regra que marcasse tudo passava nos
    testes todos e a lista deixava de distinguir o que quer que fosse."""
    job = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33)
    assert _atencao(session, job) is None


def test_a_job_that_said_it_went_well_and_wrote_nothing_needs_attention(session, aoi_aprovada):
    job = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=0,
               request_hash="pedido-nunca-visto")
    assert _atencao(session, job) == AttentionReason.succeeded_without_writing


def test_a_repeat_of_a_request_that_already_wrote_is_not_flagged(session, aoi_aprovada):
    """A forma exacta das tres linhas com zero que a base tem hoje.

    Uma segunda execucao do mesmo pedido escreve zero porque a desduplicacao ja
    tem as linhas. Marcar isso enchia a lista de ruido, e uma lista que grita
    por nada deixa de ser lida.
    """
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33,
         request_hash="mesmo-pedido", minuto=0)
    repeticao = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=0,
                     request_hash="mesmo-pedido", minuto=1)
    assert _atencao(session, repeticao) is None


def test_a_request_whose_every_run_wrote_nothing_stays_flagged(session, aoi_aprovada):
    """Controlo negativo do anterior: nao e "houve uma repeticao" que sossega a
    regra, e ter havido alguma execucao que escreveu."""
    primeira = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=0,
                    request_hash="pedido-vazio", minuto=0)
    segunda = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=0,
                   request_hash="pedido-vazio", minuto=1)
    assert _atencao(session, primeira) == AttentionReason.succeeded_without_writing
    assert _atencao(session, segunda) == AttentionReason.succeeded_without_writing


def test_the_rows_written_by_a_different_request_do_not_excuse_this_one(session, aoi_aprovada):
    """O que sossega a regra tem de ser o MESMO pedido.

    Sem a correlacao pelo `request_hash`, bastava existir na tabela um job com
    linhas -- qualquer um -- para nenhum vazio voltar a ser marcado. E como o
    teste acima tambem passaria, a lista ficava vazia para sempre sem que nada
    o denunciasse.
    """
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33,
         request_hash="outro-pedido", minuto=0)
    vazio = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=0,
                 request_hash="este-pedido", minuto=1)
    assert _atencao(session, vazio) == AttentionReason.succeeded_without_writing


def test_a_job_still_running_with_no_end_needs_attention(session, aoi_aprovada):
    """O unico estado que "falhar alto" nao consegue gravar.

    Um processo abatido a meio nao chega a escrever `failed`: a linha fica para
    sempre a dizer que esta a correr, com `error` a null.
    """
    job = _job(session, aoi_aprovada, status=JobStatus.running, finished_at=None)
    assert _atencao(session, job) == AttentionReason.never_finished


def test_a_job_still_pending_with_no_end_needs_attention(session, aoi_aprovada):
    job = _job(session, aoi_aprovada, status=JobStatus.pending, finished_at=None)
    assert _atencao(session, job) == AttentionReason.never_finished


def test_a_finished_job_is_not_reported_as_never_finished(session, aoi_aprovada):
    """Controlo negativo: e a ausencia de `finished_at` que conta, e nao o
    estado sozinho."""
    job = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=7, finished_at=_FIM)
    assert _atencao(session, job) is None


def test_a_failed_job_that_never_finished_is_reported_as_failed(session, aoi_aprovada):
    """A ordem dos ramos: quem falhou e, antes de tudo, quem falhou."""
    job = _job(session, aoi_aprovada, status=JobStatus.failed, error="boom", finished_at=None)
    assert _atencao(session, job) == AttentionReason.failed


# -- a rota ------------------------------------------------------------------


def test_the_listing_answers_the_question_that_has_no_id(client, session, aoi_aprovada):
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33, minuto=0)
    _job(session, aoi_aprovada, status=JobStatus.failed, error="boom", minuto=1)

    r = client.get("/api/v1/jobs")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_the_listing_puts_the_most_recent_first(client, session, aoi_aprovada):
    velho = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=1,
                 request_hash="velho", minuto=0)
    novo = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=1,
                request_hash="novo", minuto=30)

    ids = [linha["id"] for linha in client.get("/api/v1/jobs").json()]
    assert ids == [str(novo.id), str(velho.id)]


def test_every_listed_job_carries_the_verdict_even_without_asking_for_it(
    client, session, aoi_aprovada
):
    """Um veredicto que so aparecesse a quem filtrasse por ele obrigava a saber
    da pergunta para obter a resposta."""
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33)

    corpo = client.get("/api/v1/jobs").json()
    assert [linha["attention"] for linha in corpo] == [None]


def test_needs_attention_returns_only_the_ones_that_do(client, session, aoi_aprovada):
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33,
         request_hash="escreveu", minuto=0)
    falhado = _job(session, aoi_aprovada, status=JobStatus.failed, error="boom",
                   request_hash="falhado", minuto=1)
    vazio = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=0,
                 request_hash="vazio", minuto=2)

    corpo = client.get("/api/v1/jobs?needs_attention=true").json()

    assert {linha["id"] for linha in corpo} == {str(falhado.id), str(vazio.id)}
    assert {linha["id"]: linha["attention"] for linha in corpo} == {
        str(falhado.id): "failed",
        str(vazio.id): "succeeded_without_writing",
    }


def test_the_status_filter_narrows_the_listing(client, session, aoi_aprovada):
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33, minuto=0)
    falhado = _job(session, aoi_aprovada, status=JobStatus.failed, error="boom", minuto=1)

    corpo = client.get("/api/v1/jobs?status=failed").json()
    assert [linha["id"] for linha in corpo] == [str(falhado.id)]


def test_the_job_type_filter_narrows_the_listing(client, session, aoi_aprovada):
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33,
         job_type="eo_sync", minuto=0)
    meteorologia = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=153,
                        job_type="reanalysis_sync", request_hash="meteo", minuto=1)

    corpo = client.get("/api/v1/jobs?job_type=reanalysis_sync").json()
    assert [linha["id"] for linha in corpo] == [str(meteorologia.id)]


def test_the_limit_caps_the_listing_at_the_most_recent(client, session, aoi_aprovada):
    _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=1,
         request_hash="a", minuto=0)
    do_meio = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=1,
                   request_hash="b", minuto=10)
    ultimo = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=1,
                  request_hash="c", minuto=20)

    corpo = client.get("/api/v1/jobs?limit=2").json()
    assert [linha["id"] for linha in corpo] == [str(ultimo.id), str(do_meio.id)]


def test_a_limit_outside_the_range_is_refused(client):
    assert client.get("/api/v1/jobs?limit=0").status_code == 422
    assert client.get("/api/v1/jobs?limit=501").status_code == 422


def test_an_invented_status_is_refused_instead_of_returning_everything(client):
    """422 e nao "ignora o filtro": um filtro silenciosamente ignorado devolve
    a lista toda com ar de resposta a pergunta que se fez."""
    assert client.get("/api/v1/jobs?status=a_correr_talvez").status_code == 422


def test_reading_one_job_by_id_carries_the_same_verdict(client, session, aoi_aprovada):
    """Quem chega aqui vindo de um POST .../sync fica a saber, sem ir a
    listagem, se aquela linha e das que precisam de atencao."""
    falhado = _job(session, aoi_aprovada, status=JobStatus.failed, error="boom")

    corpo = client.get(f"/api/v1/jobs/{falhado.id}").json()
    assert corpo["attention"] == "failed"
    assert corpo["status"] == "failed"


def test_reading_a_healthy_job_by_id_says_there_is_nothing_to_flag(client, session, aoi_aprovada):
    bom = _job(session, aoi_aprovada, status=JobStatus.succeeded, rows=33)
    assert client.get(f"/api/v1/jobs/{bom.id}").json()["attention"] is None


def test_reading_an_unknown_job_is_still_a_404(client):
    """A rota mudou de modulo; o que ela responde a um id que nao existe nao."""
    assert client.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404
