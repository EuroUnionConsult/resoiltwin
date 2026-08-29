"""align ingestion_jobs.processing_version with observations.processing_version

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-29 15:40:00.000000

Escrita a mao, como as 0001-0007, e sem importar nada de `resoiltwin`: uma
migracao e um artefacto congelado e tem de correr no dia em que os modulos da
aplicacao mudarem de nome ou de sitio. (O autogenerate tambem nao serviria: o
Alembic 1.13 nao compara CheckConstraints, e correr `revision --autogenerate`
contra a imagem postgis/postgis:16-3.4 arrasta ainda o ruido das tabelas de
tiger_geocoder e topology, que nao pertencem a este schema.)

A mesma `processing_version` era guardada em duas larguras diferentes:
`observations.processing_version` e VARCHAR(80) desde a migracao 0002, e
`ingestion_jobs.processing_version` nasceu VARCHAR(64) na 0007. O valor e
literalmente o mesmo texto -- o job declara a versao com que correu e escreve-a
em cada observacao que produz.

O que isso significa na pratica: uma versao entre 65 e 80 caracteres seria
aceite numa tabela e recusada na outra. O caminho de escrita passa pelo job
PRIMEIRO (`sync_aoi` grava o job antes de tocar na rede), portanto o que
acontecia era a ingestao rebentar no INSERT do job, antes de qualquer pedido ao
Copernicus, com um erro de comprimento -- por causa de um limite que a tabela
de destino dos dados nao tem. As versoes actuais andam nos 37 caracteres, logo
nada na base esta perto do limite; isto e uma armadilha por disparar, nao uma
avaria.

Alargar e a direccao segura: 64 -> 80 nao valida nem reescreve nada em
PostgreSQL, so muda o atributo de tipo. Nao ha risco de truncatura.

O `downgrade` volta a apertar para 64. Se por essa altura existir alguma linha
com mais de 64 caracteres, o PostgreSQL recusa a operacao -- e e o
comportamento que se quer: preferimos um downgrade que falha em voz alta a um
que corta silenciosamente proveniencia.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "ingestion_jobs",
        "processing_version",
        existing_type=sa.String(length=64),
        type_=sa.String(length=80),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "ingestion_jobs",
        "processing_version",
        existing_type=sa.String(length=80),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
