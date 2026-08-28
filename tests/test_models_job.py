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


def test_failed_job_must_carry_an_error(session, aoi_aprovada):
    j = IngestionJob(aoi_id=aoi_aprovada.id, job_type="eo_sync",
                     date_from=date(2026, 8, 1), date_to=date(2026, 8, 28),
                     request_hash="abc123", status=JobStatus.failed,
                     finished_at=datetime.now(timezone.utc))
    session.add(j)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_failed_job_needs_an_error" in str(exc.value)
