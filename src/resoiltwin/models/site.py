import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from resoiltwin.constraints import AOI_CHECKS
from resoiltwin.db import Base
from resoiltwin.enums import AoiStatus, GeometryProvenance


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    crop_type: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Lisbon")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    aois: Mapped[list["Aoi"]] = relationship(back_populates="site", cascade="all, delete-orphan")
    plots: Mapped[list["Plot"]] = relationship(back_populates="site", cascade="all, delete-orphan")


class Aoi(Base):
    """Area of Interest. Uma AOI provisional nunca pode ficar approved."""

    __tablename__ = "aois"
    __table_args__ = (
        CheckConstraint(
            "NOT (status = 'approved' AND geometry_provenance = 'provisional_pending_kml')",
            name="ck_aoi_provisional_never_approved",
        ),
        CheckConstraint(
            "NOT (status = 'approved' AND approved_by IS NULL)",
            name="ck_aoi_approved_needs_approver",
        ),
        # sem estas, `status = 'Approved'` (maiuscula) entra na base e a guarda
        # ck_aoi_provisional_never_approved nao dispara -- compara com o literal
        # minusculo. Uma AOI provisoria ficava aprovada por diferenca de caixa.
        *(CheckConstraint(sql, name=name) for name, sql in AOI_CHECKS.items()),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(64))          # earth_observation | ground | reference
    geometry: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=4326))
    geometry_provenance: Mapped[GeometryProvenance] = mapped_column(String(48))
    geometry_source_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AoiStatus] = mapped_column(String(16), default=AoiStatus.draft)
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="aois")


class Plot(Base):
    """Sub-unidade espacial dentro de um site: copa, relvado, vinha, area EO."""

    __tablename__ = "plots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(64))          # canopy | open_grass | vine | eo_reference
    geometry: Mapped[object | None] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="plots")
    points: Mapped[list["ObservationPoint"]] = relationship(
        back_populates="plot", cascade="all, delete-orphan"
    )


class ObservationPoint(Base):
    __tablename__ = "observation_points"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plots.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    geometry: Mapped[object | None] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    depth_cm: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    plot: Mapped[Plot] = relationship(back_populates="points")
