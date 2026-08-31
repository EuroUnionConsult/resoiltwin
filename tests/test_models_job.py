from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from resoiltwin.enums import JobStatus
from resoiltwin.models import IngestionJob


def test_job_starts_pending(session, aoi_aprovada):
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="eo_sync",
                     date_from=date(2026, 8, 1), date_to=date(2026, 8, 28),
                     request_hash="abc123")
    session.add(j)
    session.commit()
    assert j.status == JobStatus.pending
    assert j.rows_written == 0


def test_invented_status_is_rejected_by_the_database(session, aoi_aprovada):
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="eo_sync",
                     date_from=date(2026, 8, 1), date_to=date(2026, 8, 28),
                     request_hash="abc123", status="a_correr_talvez")
    session.add(j)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_ingestion_job_status_domain" in str(exc.value)


def test_a_job_may_say_nothing_about_the_window_it_asked_for(session, aoi_aprovada):
    """Controlo negativo, e o unico caso honesto para os 25 jobs anteriores a
    migracao 0011: eles nao sabem o que pediram, e NULL diz isso."""
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="ipma_sync",
                     date_from=date(2026, 8, 1), date_to=date(2026, 8, 28),
                     request_hash="abc123")
    session.add(j)
    session.commit()
    assert j.requested_date_from is None
    assert j.requested_date_to is None


def test_a_job_may_carry_both_windows(session, aoi_aprovada):
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="reanalysis_sync",
                     date_from=date(2026, 7, 1), date_to=date(2026, 7, 2),
                     requested_date_from=date(2026, 7, 1),
                     requested_date_to=date(2026, 8, 29),
                     request_hash="abc123")
    session.add(j)
    session.commit()
    assert (j.requested_date_from, j.requested_date_to) == (date(2026, 7, 1), date(2026, 8, 29))
    assert (j.date_from, j.date_to) == (date(2026, 7, 1), date(2026, 7, 2))


@pytest.mark.parametrize(
    ("metade", "valor"),
    [
        # cada metade leva um valor que a CONTENCAO aceitaria: sem isso, a
        # linha era rejeitada por a janela coberta sair da pedida e este teste
        # passava sem a exigencia de "ambas ou nenhuma" existir de todo.
        ("requested_date_from", date(2026, 8, 1)),
        ("requested_date_to", date(2026, 8, 29)),
    ],
)
def test_half_a_requested_window_is_rejected_by_the_database(
        session, aoi_aprovada, metade, valor):
    """Uma so das duas colunas nao diz o que se pediu nem diz que nao se sabe.

    E nao e so feio: a segunda metade da constraint compara `date_to` com
    `requested_date_to`, e com um dos lados a NULL essa comparacao da NULL --
    que num CHECK PASSA. Sem esta exigencia, a guarda ficava cega exactamente
    na linha meio preenchida.
    """
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="reanalysis_sync",
                     date_from=date(2026, 8, 1), date_to=date(2026, 8, 28),
                     request_hash="abc123", **{metade: valor})
    session.add(j)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_job_covered_window_inside_the_requested_one" in str(exc.value)


@pytest.mark.parametrize(
    "coberta",
    [
        (date(2026, 6, 30), date(2026, 8, 28)),  # comeca antes do que se pediu
        (date(2026, 8, 1), date(2026, 8, 30)),   # acaba depois do que se pediu
    ],
)
def test_a_covered_window_outside_the_requested_one_is_rejected(session, aoi_aprovada, coberta):
    """Cobrir dias que nao se pediu e o defeito ao contrario: as linhas
    entraram debaixo de um job que nao diz te-las pedido."""
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="eo_sync",
                     date_from=coberta[0], date_to=coberta[1],
                     requested_date_from=date(2026, 8, 1),
                     requested_date_to=date(2026, 8, 29),
                     request_hash="abc123")
    session.add(j)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_job_covered_window_inside_the_requested_one" in str(exc.value)


def test_failed_job_must_carry_an_error(session, aoi_aprovada):
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="eo_sync",
                     date_from=date(2026, 8, 1), date_to=date(2026, 8, 28),
                     request_hash="abc123", status=JobStatus.failed,
                     finished_at=datetime.now(timezone.utc))
    session.add(j)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_failed_job_needs_an_error" in str(exc.value)
