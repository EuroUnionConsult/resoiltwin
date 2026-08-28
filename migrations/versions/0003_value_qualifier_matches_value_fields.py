"""observation value qualifier must match its value fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28 17:05:00.000000

Nota: o `alembic revision --autogenerate` nao detecta a adicao desta
constraint - a comparacao automatica de CheckConstraint (SQL livre, sem
estrutura fixa) nao e suportada pelo autogenerate do Alembic 1.13, ao
contrario de indices/uniques/foreign keys. A migracao foi escrita a mao.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_value_qualifier_matches_value_fields"
CONSTRAINT_SQL = (
    "(value_qualifier IN ('censored_high', 'censored_low')"
    "   AND value_numeric IS NOT NULL AND value_min IS NULL AND value_max IS NULL)"
    " OR (value_qualifier = 'range'"
    "   AND value_min IS NOT NULL AND value_max IS NOT NULL AND value_numeric IS NULL)"
    " OR (value_qualifier IN ('exact', 'mean_of_replicates')"
    "   AND value_min IS NULL AND value_max IS NULL)"
)


def upgrade() -> None:
    op.create_check_constraint(CONSTRAINT_NAME, "observations", CONSTRAINT_SQL)


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "observations", type_="check")
