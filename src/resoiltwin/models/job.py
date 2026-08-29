import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from resoiltwin.constraints import INGESTION_JOB_CHECKS
from resoiltwin.db import Base
from resoiltwin.enums import JobStatus


class IngestionJob(Base):
    """Rasto de uma execucao de ingestao de dados de satelite.

    Numa tese de proveniencia auditavel, uma serie sem registo de como entrou
    e meia proveniencia: este modelo guarda quando comecou, que AOI e que
    intervalo pediu, quantas linhas escreveu e, se falhou, porque. Na fase
    seguinte a ingestao passa a correr agendada -- sem este registo, uma falha
    as tres da manha nao deixa vestigio nenhum.
    """

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        # dominio do estado e a implicacao failed->error: o texto vem de
        # resoiltwin.constraints, exactamente o mesmo que a migracao 0006 aplica
        *(CheckConstraint(sql, name=name) for name, sql in INGESTION_JOB_CHECKS.items()),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aoi_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aois.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(64))                # ex: eo_sync
    status: Mapped[JobStatus] = mapped_column(String(16), default=JobStatus.pending)

    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    # hash do pedido (aoi + intervalo + parametros): permite reconhecer duas
    # execucoes do mesmo pedido sem repetir o pedido em si
    request_hash: Mapped[str] = mapped_column(String(64), index=True)

    # a mesma processing_version que vai em cada observacao que este job
    # escreveu. Sem ela, saber se um job correu com mascara ao pixel obrigava
    # a ir a tabela de observacoes -- e um job que escreveu zero linhas nao
    # tinha sequer onde ser lido. O request_hash nao serve para isto: e
    # derivado da versao, portanto nao se inverte.
    #
    # Anulavel de proposito: os jobs gravados antes da migracao 0007 nao
    # tinham onde guardar isto e NULL diz exactamente isso -- "nao registado",
    # nao "sem versao". Inventar-lhes um valor no backfill seria escrever
    # proveniencia que ninguem observou.
    processing_version: Mapped[str | None] = mapped_column(String(64))

    # quando esta execucao comecou -- server_default, nao depende de o
    # chamador passar a hora certa
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
