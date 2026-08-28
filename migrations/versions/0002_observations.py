"""observations with censored and range values

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28 16:40:43.795855

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("plot_id", sa.UUID(), nullable=True),
        sa.Column("observation_point_id", sa.UUID(), nullable=True),
        sa.Column("instrument_id", sa.UUID(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_min", sa.Float(), nullable=True),
        sa.Column("value_max", sa.Float(), nullable=True),
        sa.Column("value_text", sa.String(length=160), nullable=True),
        sa.Column("value_qualifier", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("quality_flag", sa.String(length=32), nullable=False),
        sa.Column("source_collection", sa.String(length=128), nullable=True),
        sa.Column("processing_version", sa.String(length=80), nullable=False),
        sa.Column("method", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "value_qualifier <> 'range' OR (value_min IS NOT NULL AND value_max IS NOT NULL)",
            name="ck_range_needs_both_bounds",
        ),
        sa.CheckConstraint(
            "value_min IS NULL OR value_max IS NULL OR value_min <= value_max",
            name="ck_range_is_ordered",
        ),
        sa.CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL "
            "OR (value_min IS NOT NULL AND value_max IS NOT NULL)",
            name="ck_observation_has_a_value",
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["observation_point_id"], ["observation_points.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plot_id"], ["plots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id", "plot_id", "observed_at", "metric", "source_type", "processing_version",
            name="uq_observation_identity",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_observations_observed_at"), "observations", ["observed_at"], unique=False)
    op.create_index(op.f("ix_observations_site_id"), "observations", ["site_id"], unique=False)
    op.create_index(
        "ix_observations_site_metric_time", "observations", ["site_id", "metric", "observed_at"], unique=False
    )
    op.create_index("ix_observations_source_type", "observations", ["source_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_observations_source_type", table_name="observations")
    op.drop_index("ix_observations_site_metric_time", table_name="observations")
    op.drop_index(op.f("ix_observations_site_id"), table_name="observations")
    op.drop_index(op.f("ix_observations_observed_at"), table_name="observations")
    op.drop_table("observations")
