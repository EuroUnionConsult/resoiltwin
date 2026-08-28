import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from resoiltwin.constraints import OBSERVATION_CHECKS
from resoiltwin.db import Base
from resoiltwin.enums import QualityFlag, SourceType, ValueQualifier


class Observation(Base):
    """Serie temporal canonica. Nunca perde proveniencia e nunca deforma o valor.

    Um valor pode ser: exacto (value_numeric), um intervalo (value_min/value_max),
    censurado no topo de escala (value_numeric + censored_high) ou textual
    (value_text). As constraints garantem que a combinacao e coerente.
    """

    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "plot_id", "observed_at", "metric", "source_type", "processing_version",
            name="uq_observation_identity",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL "
            "OR (value_min IS NOT NULL AND value_max IS NOT NULL)",
            name="ck_observation_has_a_value",
        ),
        CheckConstraint(
            "value_qualifier <> 'range' OR (value_min IS NOT NULL AND value_max IS NOT NULL)",
            name="ck_range_needs_both_bounds",
        ),
        CheckConstraint(
            "value_min IS NULL OR value_max IS NULL OR value_min <= value_max",
            name="ck_range_is_ordered",
        ),
        CheckConstraint(
            "(value_qualifier IN ('censored_high', 'censored_low')"
            "   AND value_numeric IS NOT NULL AND value_min IS NULL AND value_max IS NULL)"
            " OR (value_qualifier = 'range'"
            "   AND value_min IS NOT NULL AND value_max IS NOT NULL AND value_numeric IS NULL)"
            " OR (value_qualifier IN ('exact', 'mean_of_replicates')"
            "   AND value_min IS NULL AND value_max IS NULL)",
            name="ck_value_qualifier_matches_value_fields",
        ),
        # dominio dos enums e coerencia censura/derivados: o texto vem de
        # resoiltwin.constraints, exactamente o mesmo que a migracao 0004 aplica
        *(CheckConstraint(sql, name=name) for name, sql in OBSERVATION_CHECKS.items()),
        Index("ix_observations_site_metric_time", "site_id", "metric", "observed_at"),
        Index("ix_observations_source_type", "source_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    plot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plots.id", ondelete="SET NULL"))
    observation_point_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observation_points.id", ondelete="SET NULL")
    )
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="SET NULL")
    )

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metric: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(32))

    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_min: Mapped[float | None] = mapped_column(Float)
    value_max: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(String(160))
    value_qualifier: Mapped[ValueQualifier] = mapped_column(String(32), default=ValueQualifier.exact)

    source_type: Mapped[SourceType] = mapped_column(String(32))
    quality_flag: Mapped[QualityFlag] = mapped_column(String(32), default=QualityFlag.unchecked)
    source_collection: Mapped[str | None] = mapped_column(String(128))
    processing_version: Mapped[str] = mapped_column(String(80))
    method: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    # none_as_null=True: sem isto o SQLAlchemy grava `None` como o literal JSON
    # `null` e nao como SQL NULL. Sao dois valores diferentes para o Postgres --
    # uma coluna JSONB com `null` la dentro nao e NULL -- e por causa disso a
    # guarda ck_derived_needs_method_and_inputs nao disparava em nenhum caminho
    # de escrita real: `evidence IS NOT NULL` era sempre verdadeiro.
    evidence: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ids das observacoes que produziram este valor. Sem foreign key: o postgres
    # nao suporta FK sobre elementos de um array. Declarada DEPOIS de created_at
    # de proposito -- a migracao 0004 acrescenta a coluna com ADD COLUMN, que a
    # poe no fim da tabela, e o schema construido pelos modelos tem de ficar
    # igual ao construido pelas migracoes, coluna a coluna.
    derived_from: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
