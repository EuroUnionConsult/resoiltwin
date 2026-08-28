"""ingestion job with status domain and failed-needs-error implication

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-28 20:10:00.000000

Escrita a mao, como as 0001-0005: o autogenerate do Alembic 1.13 nao compara
CheckConstraints, e correr `alembic revision --autogenerate` contra a imagem
postgis/postgis:16-3.4 produz ainda por cima ruido das tabelas de
tiger_geocoder/topology, que nao pertencem a este schema.

O texto das constraints esta INLINE, literal, congelado em 2026-08-28. Esta
migracao nao importa nada de `resoiltwin`: a historia tem de continuar a
correr no dia em que os modulos da aplicacao mudarem de nome ou de sitio.

Duas guardas:

1. ck_ingestion_job_status_domain -- o mesmo padrao das outras colunas de
   enum (status da AOI, source_type e afins). `Mapped[JobStatus]` com
   `mapped_column(String(16))` e decorativo; sem o CHECK, um valor inventado
   como 'a_correr_talvez' entrava na base sem o ORM se queixar.

2. ck_failed_job_needs_an_error -- um job failed tem de dizer porque. `error`
   e uma coluna anulavel: um CHECK que avalie a NULL PASSA, so um FALSE
   explicito rejeita. `length(trim(error))` sobre `error IS NULL` da NULL, nao
   FALSE -- por isso o COALESCE(length(trim(error)), 0) > 0, que fecha o
   mesmo buraco que ja tinha cegado ck_derived_needs_method_and_inputs na
   migracao 0004/0005.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INGESTION_JOB_CHECKS = {
    "ck_ingestion_job_status_domain": "status IN ('pending', 'running', 'succeeded', 'failed')",
    "ck_failed_job_needs_an_error": (
        "status <> 'failed' OR COALESCE(length(trim(error)), 0) > 0"
    ),
}


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("aoi_id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            INGESTION_JOB_CHECKS["ck_failed_job_needs_an_error"], name="ck_failed_job_needs_an_error"
        ),
        sa.CheckConstraint(
            INGESTION_JOB_CHECKS["ck_ingestion_job_status_domain"], name="ck_ingestion_job_status_domain"
        ),
        sa.ForeignKeyConstraint(["aoi_id"], ["aois.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_jobs_aoi_id"), "ingestion_jobs", ["aoi_id"], unique=False)
    op.create_index(op.f("ix_ingestion_jobs_request_hash"), "ingestion_jobs", ["request_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_jobs_request_hash"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_aoi_id"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
