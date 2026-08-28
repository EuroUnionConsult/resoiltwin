"""enum domains, censoring coherence and derived lineage

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-28 18:30:00.000000

Escrita a mao, como as 0001-0003: o autogenerate do Alembic 1.13 compara
indices, uniques e foreign keys, mas NAO compara CheckConstraints (SQL livre,
sem estrutura fixa). Correr `alembic revision --autogenerate` contra a imagem
PostGIS produz ainda por cima ruido das tabelas de tiger_geocoder/topology, que
nao pertencem a este schema.

O texto das constraints esta INLINE, literal, de proposito. Uma versao anterior
desta migracao importava `resoiltwin.constraints` para gerar as listas a partir
dos enums; isso fazia a historia depender de codigo de aplicacao para poder
correr. No dia em que `constraints.py` ou `enums.py` mudasse de nome ou de
sitio, esta migracao deixava de importar e ja nao era possivel construir uma
base nova a partir do zero -- isso nao degrada, parte. Uma migracao e um
artefacto congelado: descreve o que foi aplicado naquele dia, nao o que os
modelos dizem hoje.

`resoiltwin.constraints` continua a ser a fonte unica para os MODELOS. A
paridade entre o schema das migracoes e o schema dos modelos e verificada pelo
teste `tests/test_schema_parity.py`, que corre contra a base construida por
`alembic upgrade head`.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# congelado em 2026-08-28. NAO gerar a partir dos enums: ver a nota acima.
OBSERVATION_CHECKS = {
    "ck_censoring_flag_matches_qualifier": (
        "(quality_flag IN ('saturated_high', 'saturated_low'))"
        " = (value_qualifier IN ('censored_high', 'censored_low'))"
        " AND (quality_flag = 'range_value') = (value_qualifier = 'range')"
    ),
    "ck_derived_needs_method_and_inputs": (
        "source_type <> 'derived'"
        " OR (method IS NOT NULL"
        " AND (evidence IS NOT NULL"
        " OR (derived_from IS NOT NULL AND array_length(derived_from, 1) > 0)))"
    ),
    "ck_observation_processing_version_not_blank": "length(trim(processing_version)) > 0",
    "ck_observation_quality_flag_domain": (
        "quality_flag IN ('unchecked', 'valid', 'repeated', 'saturated_high',"
        " 'saturated_low', 'range_value', 'approximate', 'suspect', 'rejected',"
        " 'laboratory_confirmed')"
    ),
    "ck_observation_source_type_domain": (
        "source_type IN ('observed_screening', 'observed_reference', 'observed_lab',"
        " 'satellite_observed', 'weather_observed', 'reanalysis', 'simulated', 'derived')"
    ),
    "ck_observation_value_qualifier_domain": (
        "value_qualifier IN ('exact', 'mean_of_replicates', 'censored_high',"
        " 'censored_low', 'range')"
    ),
}

AOI_CHECKS = {
    "ck_aoi_geometry_provenance_domain": (
        "geometry_provenance IN ('documented_exact', 'surveyed', 'derived_from_metrics',"
        " 'provisional_pending_kml')"
    ),
    "ck_aoi_status_domain": "status IN ('draft', 'approved', 'rejected')",
}


def upgrade() -> None:
    # sem foreign key: o postgres nao suporta FK sobre elementos de um array.
    # ADD COLUMN poe a coluna no fim da tabela, que e onde o modelo tambem a
    # declara -- os dois caminhos de construcao do schema tem de coincidir.
    op.add_column(
        "observations",
        sa.Column("derived_from", ARRAY(UUID(as_uuid=True)), nullable=True),
    )

    for name, sql in OBSERVATION_CHECKS.items():
        op.create_check_constraint(name, "observations", sql)
    for name, sql in AOI_CHECKS.items():
        op.create_check_constraint(name, "aois", sql)


def downgrade() -> None:
    for name in AOI_CHECKS:
        op.drop_constraint(name, "aois", type_="check")
    for name in OBSERVATION_CHECKS:
        op.drop_constraint(name, "observations", type_="check")
    op.drop_column("observations", "derived_from")
