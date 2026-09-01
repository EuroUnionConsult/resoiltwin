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
        # Continua a nomear UM valor, e nao uma lista do que pode ser aprovado.
        # Revisto a 01/09/2026, quando o dominio passou de quatro valores para
        # seis: `digitised_from_basemap` e `constructed_extent` PODEM ser
        # aprovados, de proposito.
        #
        # O que esta guarda recusa nao e "geometria pouco exacta" -- e
        # geometria cuja POSICAO nao se sabe. `provisional_pending_kml`
        # significa um poligono com a area certa e a posicao e a rotacao
        # inventadas: estatisticas de satelite sobre ele sao estatisticas de
        # sitio nenhum, e nenhuma quantidade de aprovacao humana as torna
        # defensaveis. Os dois valores novos nao tem esse defeito. Um contorno
        # tracado sobre mapa base esta onde se ve que esta, e qualquer pessoa
        # pode reabrir o mapa e conferi-lo. Uma caixa construida a volta de um
        # ponto documentado e reproduzivel ao metro -- nao e um limite do
        # terreno, mas nunca disse que era, e para uma extensao de analise
        # escolhida isso e a verdade inteira e nao uma falta.
        #
        # As duas AOI em producao sao exactamente estes dois casos e estao
        # aprovadas com dados ja recolhidos. Torna-las nao-aprovaveis apagava
        # trabalho correcto para castigar uma palavra errada, que e o oposto do
        # que a correccao de 01/09 faz.
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
