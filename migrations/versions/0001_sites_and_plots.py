"""sites, aois, plots, observation points, instruments

Revision ID: 0001
Revises:
Create Date: 2026-08-28 16:28:24.751456

"""
from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # a extensao postgis tem de existir antes de qualquer coluna Geometry
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "instruments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("grade", sa.String(length=32), nullable=False),
        sa.Column("scale_min", sa.Float(), nullable=True),
        sa.Column("scale_max", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("calibration_status", sa.String(length=48), nullable=False),
        sa.Column("limitations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_instruments_code"), "instruments", ["code"], unique=True)

    op.create_table(
        "sites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("crop_type", sa.String(length=120), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sites_code"), "sites", ["code"], unique=True)

    op.create_table(
        "aois",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(srid=4326, from_text="ST_GeomFromEWKT", name="geometry", nullable=False),
            nullable=False,
        ),
        sa.Column("geometry_provenance", sa.String(length=48), nullable=False),
        sa.Column("geometry_source_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "NOT (status = 'approved' AND approved_by IS NULL)", name="ck_aoi_approved_needs_approver"
        ),
        sa.CheckConstraint(
            "NOT (status = 'approved' AND geometry_provenance = 'provisional_pending_kml')",
            name="ck_aoi_provisional_never_approved",
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # nota: nao criar aqui o indice gist da geometria - a coluna Geometry do
    # geoalchemy2 tem spatial_index=True por omissao e cria-o sozinha via
    # evento DDL quando a tabela e criada; repeti-lo dava "already exists"
    op.create_index(op.f("ix_aois_code"), "aois", ["code"], unique=True)
    op.create_index(op.f("ix_aois_site_id"), "aois", ["site_id"], unique=False)

    op.create_table(
        "plots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(srid=4326, from_text="ST_GeomFromEWKT", name="geometry"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plots_code"), "plots", ["code"], unique=True)
    op.create_index(op.f("ix_plots_site_id"), "plots", ["site_id"], unique=False)

    op.create_table(
        "observation_points",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plot_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, from_text="ST_GeomFromEWKT", name="geometry"
            ),
            nullable=True,
        ),
        sa.Column("depth_cm", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["plot_id"], ["plots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_observation_points_code"), "observation_points", ["code"], unique=True)
    op.create_index(op.f("ix_observation_points_plot_id"), "observation_points", ["plot_id"], unique=False)


def downgrade() -> None:
    # ordem inversa das dependencias de foreign key
    op.drop_table("observation_points")
    op.drop_table("plots")
    op.drop_table("aois")
    op.drop_table("sites")
    op.drop_table("instruments")
