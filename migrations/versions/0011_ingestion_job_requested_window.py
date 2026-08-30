"""ingestion job records the window it asked for, not only the one it covered

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-30 21:00:00.000000

Escrita a mao, como as 0001-0010, e sem importar nada de `resoiltwin`: uma
migracao e um artefacto congelado e tem de correr no dia em que os modulos da
aplicacao mudarem de nome ou de sitio. O texto da constraint esta INLINE,
literal, congelado em 2026-08-30; a paridade com o modelo e verificada por
`tests/test_schema_parity.py`.

PORQUE. A 29/08/2026 duas execucoes de reanalise responderam `succeeded` com
`error: null` tendo gravado 6 linhas onde havia 159 -- 96% da serie perdida
porque o zip do Climate Data Store era lido so ate ao primeiro membro. O
defeito de leitura ja esta corrigido (96717e8), mas nada na base o teria
denunciado, e a razao e ironica: fomos nos que apagamos a informacao que o
permitia. O commit 68d09d7 fez o job passar a declarar a janela que COBRIU em
vez da que PEDIU. Para a honestidade da linha foi certo -- declarar dois meses
por causa de dois dias e afirmar uma cobertura que a serie desmente -- mas
deixou o job com razao sempre:

    ANTES    pediu 01/07-29/08  .  cobriu 01/07-02/07   -> ha com que comparar
    DEPOIS   cobriu 01/07-02/07                          -> nao ha

Estas duas colunas repoem o outro lado da comparacao. Nao gravam um "esperado"
-- um esperado teria de ser derivado, e todas as derivacoes disponiveis ou sao
circulares ou sao inventadas. Gravam o que o chamador pediu, que e um facto
observado no momento em que a execucao comecou.

ANULAVEIS, E SEM BACKFILL. Os 25 jobs ja gravados nao sabem o que pediram. Os
que correram antes de 68d09d7 tem a janela pedida em `date_from`/`date_to`; os
que correram depois tem la a coberta; e a linha nao diz de que lado esta -- a
unica coisa que as separa e a hora a que correram comparada com a hora de um
commit, que nao esta na base. Copiar `date_from`/`date_to` para as colunas
novas escrevia como "pedido" um valor que em varias linhas e o coberto, o que
e exactamente o defeito que esta migracao existe para fechar. NULL diz "nao
registado", e a ausencia e o que as distingue das linhas novas.

Pela mesma razao nao ha NOT NULL nem CHECK a exigi-las preenchidas: qualquer um
dos dois obrigava a inventar valores para as linhas existentes.

A CONSTRAINT que se acrescenta e outra coisa: nao exige que a janela pedida
exista, exige que, quando existe, esteja INTEIRA -- as duas colunas ou ambas
preenchidas ou ambas a NULL -- e que a janela coberta caia dentro dela. A
primeira metade impede que "meio registado" se disfarce de "nao registado"; sem
ela a segunda metade avaliava a NULL, que num CHECK do PostgreSQL PASSA, e a
guarda ficava cega precisamente nas linhas em que interessa.

CONTAGEM. Nada aqui apaga nem cria linhas: sao duas colunas novas, a NULL em
todas as existentes, mais uma constraint que todas satisfazem pelo primeiro
ramo. A tabela tinha 25 jobs e a de observacoes 1121 linhas antes desta
migracao.

REVERSIVEL sem adivinhar: as colunas sao largadas e nada mais se perde, porque
nenhuma linha anterior a esta migracao as tinha preenchidas.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COVERED_INSIDE_REQUESTED = (
    "(requested_date_from IS NULL AND requested_date_to IS NULL)"
    " OR (requested_date_from IS NOT NULL AND requested_date_to IS NOT NULL"
    " AND date_from >= requested_date_from AND date_to <= requested_date_to)"
)


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs", sa.Column("requested_date_from", sa.Date(), nullable=True)
    )
    op.add_column(
        "ingestion_jobs", sa.Column("requested_date_to", sa.Date(), nullable=True)
    )
    op.create_check_constraint(
        "ck_job_covered_window_inside_the_requested_one",
        "ingestion_jobs",
        _COVERED_INSIDE_REQUESTED,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_job_covered_window_inside_the_requested_one",
        "ingestion_jobs",
        type_="check",
    )
    op.drop_column("ingestion_jobs", "requested_date_to")
    op.drop_column("ingestion_jobs", "requested_date_from")
