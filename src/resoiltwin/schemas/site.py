import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from resoiltwin.enums import AoiStatus, GeometryProvenance
from resoiltwin.geo import validate_polygon


class SiteCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9-]{3,64}$")
    name: str = Field(min_length=3, max_length=160)
    crop_type: str | None = Field(default=None, max_length=120)
    timezone: str = "Europe/Lisbon"
    notes: str | None = None


class SiteRead(SiteCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime


class AoiCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9-]{3,64}$")
    purpose: str = Field(pattern=r"^(earth_observation|ground|reference)$")
    geometry: dict
    geometry_provenance: GeometryProvenance
    geometry_source_note: str | None = None

    @field_validator("geometry")
    @classmethod
    def _check(cls, value: dict) -> dict:
        return validate_polygon(value)


class AoiRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    purpose: str
    geometry: dict
    geometry_provenance: GeometryProvenance
    geometry_source_note: str | None
    status: AoiStatus
    approved_by: str | None
    approved_at: datetime | None
    area_m2: float


class AoiApprove(BaseModel):
    approved_by: str = Field(min_length=2, max_length=120)


class PlotCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9-]{3,64}$")
    name: str = Field(min_length=2, max_length=160)
    purpose: str = Field(pattern=r"^(canopy|open_grass|vine|eo_reference|other)$")


class PlotRead(PlotCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
