import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from resoiltwin.db import Base


class Instrument(Base):
    """O instrumento e a sua limitacao. Guardar o limite de escala e o que
    permite marcar uma leitura como censurada em vez de a fingir exacta."""

    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model: Mapped[str] = mapped_column(String(160))
    grade: Mapped[str] = mapped_column(String(32))            # screening | reference | laboratory
    scale_min: Mapped[float | None] = mapped_column()
    scale_max: Mapped[float | None] = mapped_column()
    unit: Mapped[str | None] = mapped_column(String(32))
    calibration_status: Mapped[str] = mapped_column(String(48), default="uncalibrated")
    limitations: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
