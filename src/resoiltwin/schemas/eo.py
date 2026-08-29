import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resoiltwin.enums import JobStatus


class EoSyncRequest(BaseModel):
    aoi_code: str = Field(pattern=r"^[A-Z0-9-]{3,64}$")
    date_from: date
    date_to: date
    # mascara SCL ao pixel, ligada por omissao: quem nao escolher fica com o
    # comportamento correcto. `false` reproduz o evalscript v1, que produziu as
    # series que ja estao gravadas -- e para repetir o passado, nao o caminho
    # normal. O tipo e bool a serio: uma string a passar por verdadeira
    # escolhia o script errado sem ninguem dar por isso.
    scl_mask: bool = True

    @model_validator(mode="after")
    def _janela_coerente(self):
        # recusar aqui, com 422, e mais barato do que criar um job so para
        # ele falhar na Statistical API por uma janela invertida.
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class IngestionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    aoi_id: uuid.UUID
    job_type: str
    status: JobStatus
    date_from: date
    date_to: date
    request_hash: str
    started_at: datetime
    finished_at: datetime | None
    rows_written: int
    error: str | None
