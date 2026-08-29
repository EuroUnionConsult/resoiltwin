"""ingestion job records the processing version it ran with

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-29 12:30:00.000000

Escrita a mao, como as 0001-0006, e sem importar nada de `resoiltwin`: uma
migracao e um artefacto congelado e tem de correr no dia em que os modulos da
aplicacao mudarem de nome ou de sitio.

A coluna e ANULAVEL e nao ha backfill. Os jobs que existiam antes desta
migracao correram sem ter onde guardar a versao, e NULL diz precisamente isso:
"nao registado". Preenche-los com a versao que se presume que usaram seria
escrever proveniencia que ninguem observou -- exactamente o contrario do que
esta coluna existe para permitir. Quem precisar da versao de um job antigo tem
de a ir procurar nas observacoes que ele escreveu.

Tambem nao ha CHECK a exigir a coluna preenchida: um NOT NULL, ou um CHECK
equivalente, obrigaria a inventar valores para as linhas existentes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("processing_version", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "processing_version")
