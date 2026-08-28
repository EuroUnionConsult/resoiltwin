import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resoiltwin.enums import QualityFlag, SourceType, ValueQualifier


class ObservationCreate(BaseModel):
    site_code: str
    plot_code: str | None = None
    observation_point_code: str | None = None
    instrument_code: str | None = None
    observed_at: datetime
    metric: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    unit: str = Field(min_length=1, max_length=32)
    value_numeric: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    value_text: str | None = Field(default=None, max_length=160)
    value_qualifier: ValueQualifier = ValueQualifier.exact
    source_type: SourceType
    quality_flag: QualityFlag = QualityFlag.unchecked
    # os limites espelham String(128)/String(160) das colunas: sem eles o
    # pydantic aceita, o postgres levanta DataError (que nao e IntegrityError,
    # logo escapa ao except da rota) e o cliente recebe 500 em vez de 422.
    # source_collection e onde vao os identificadores de produto de satelite.
    source_collection: str | None = Field(default=None, max_length=128)
    processing_version: str = Field(min_length=1, max_length=80)
    method: str | None = Field(default=None, max_length=160)
    notes: str | None = None
    evidence: dict | None = None

    @model_validator(mode="after")
    def _coherent_value(self):
        has_scalar = self.value_numeric is not None
        has_range = self.value_min is not None and self.value_max is not None
        has_bound = self.value_min is not None or self.value_max is not None
        if not (has_scalar or has_range or self.value_text):
            raise ValueError("observation must carry value_numeric, value_text or value_min+value_max")
        if has_range and self.value_min > self.value_max:
            raise ValueError("value_min must not exceed value_max")

        # espelha a constraint ck_value_qualifier_matches_value_fields da base
        # de dados: cada qualifier so aceita uma combinacao exacta de campos.
        # sem isto, um payload incoerente passa o pydantic e so e apanhado
        # pelo CHECK da base, o que da 500 em vez de 422.
        if self.value_qualifier in (ValueQualifier.censored_high, ValueQualifier.censored_low):
            if self.value_numeric is None:
                raise ValueError(f"value_qualifier '{self.value_qualifier}' requires value_numeric")
            if has_bound:
                raise ValueError(
                    f"value_qualifier '{self.value_qualifier}' must not carry value_min or value_max"
                )
        elif self.value_qualifier == ValueQualifier.range:
            if not has_range:
                raise ValueError("value_qualifier 'range' requires both value_min and value_max")
            if self.value_numeric is not None:
                raise ValueError("value_qualifier 'range' must not carry value_numeric")
        elif self.value_qualifier in (ValueQualifier.exact, ValueQualifier.mean_of_replicates):
            if has_bound:
                raise ValueError(
                    f"value_qualifier '{self.value_qualifier}' must not carry value_min or value_max"
                )

        # espelha a constraint ck_censoring_flag_matches_qualifier da base, com
        # a MESMA direccao: saturado obriga a censurado, range_value obriga a
        # range. Sem isto uma leitura no topo de escala (2000, saturada) entra
        # como escalar exacto -- o numero perde a informacao de que e um limite
        # inferior e nao uma medida, que e a deformacao que este modelo existe
        # para impedir.
        #
        # O reciproco NAO se impoe: quality_flag e uma avaliacao de qualidade e
        # value_qualifier e a semantica do valor. Um valor censurado pode
        # legitimamente estar `unchecked` (o valor por omissao), `suspect` ou
        # `rejected` -- exigir o par tornava impossivel gravar um censurado
        # antes de avaliar a qualidade.
        saturated = self.quality_flag in (QualityFlag.saturated_high, QualityFlag.saturated_low)
        censored = self.value_qualifier in (ValueQualifier.censored_high, ValueQualifier.censored_low)
        if saturated and not censored:
            raise ValueError(
                f"quality_flag '{self.quality_flag}' requires value_qualifier "
                "'censored_high' or 'censored_low'"
            )
        if self.quality_flag == QualityFlag.range_value and self.value_qualifier != ValueQualifier.range:
            raise ValueError("quality_flag 'range_value' requires value_qualifier 'range'")

        # espelha ck_observation_processing_version_not_blank: min_length=1 nao
        # chega, uma string so de espacos passa por ele e bate na constraint,
        # o que dava 500 em vez de 422.
        if not self.processing_version.strip():
            raise ValueError("processing_version must not be blank")

        # espelha ck_derived_needs_method_and_inputs. `derived_from` nao existe
        # neste payload -- por esta rota, a unica forma de documentar as
        # entradas e `evidence`, portanto sao as duas obrigatorias. Sem isto um
        # derivado sem method, ou sem evidence, passava o pydantic e batia na
        # constraint da base: 500 em vez de 422.
        # espelhado ao milimetro, sem apertar mais do que a base: a constraint
        # exige `method IS NOT NULL` e `jsonb_typeof(evidence) = 'object'`, e e
        # isso que se verifica aqui. Apertar mais faria a rota recusar payloads
        # que os jobs do lado do servidor gravam sem problema.
        if self.source_type == SourceType.derived:
            if self.method is None:
                raise ValueError("source_type 'derived' requires method")
            if self.evidence is None:
                raise ValueError(
                    "source_type 'derived' requires evidence documenting the inputs"
                )
        return self


class ObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    observed_at: datetime
    metric: str
    unit: str
    value_numeric: float | None
    value_min: float | None
    value_max: float | None
    value_text: str | None
    value_qualifier: ValueQualifier
    source_type: SourceType
    quality_flag: QualityFlag
    processing_version: str


class TimeseriesPoint(BaseModel):
    observed_at: datetime
    value: float | None
    value_min: float | None
    value_max: float | None
    value_qualifier: ValueQualifier
    unit: str
    source_type: SourceType
    quality_flag: QualityFlag
    plot_code: str | None
    processing_version: str


class TimeseriesResponse(BaseModel):
    site_code: str
    metric: str
    point_count: int
    source_types: list[SourceType]
    points: list[TimeseriesPoint]
