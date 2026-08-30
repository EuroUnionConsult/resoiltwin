"""refuse non-finite observation values (NaN, +/-Infinity)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-30 12:00:00.000000

Escrita a mao, como as 0001-0008, e sem importar nada de `resoiltwin`: uma
migracao e um artefacto congelado e tem de correr no dia em que os modulos da
aplicacao mudarem de nome ou de sitio. (O autogenerate tambem nao serviria: o
Alembic 1.13 nao compara CheckConstraints, e correr `revision --autogenerate`
contra a imagem postgis/postgis:16-3.4 arrasta o ruido das tabelas de
tiger_geocoder e topology, que nao pertencem a este schema.)

O texto abaixo e o literal congelado do que `resoiltwin.constraints`
(SQL_VALUES_ARE_FINITE) declara para os modelos. `tests/test_schema_parity.py`
compara os dois lados pela boca do PostgreSQL e apanha a divergencia.

PORQUE. `double precision` aceita NaN, +Infinity e -Infinity, e nenhuma das
guardas ja existentes morde neles:

- `ck_observation_has_a_value` passa, porque `NaN IS NOT NULL` e verdadeiro;
- `ck_value_qualifier_matches_value_fields` passa, porque um NaN em
  `value_numeric` e coerente com `value_qualifier = 'exact'`;
- os CHECKs de dominio olham para os enums, nao para o valor.

Uma linha assim entra com proveniencia completa, `quality_flag = 'valid'` e ar
de correcta. E no PostgreSQL o NaN ordena ACIMA de qualquer numero e propaga-se
pelos agregados: um so dia com NaN poe `avg()`, `max()` e `sum()` a devolver
NaN para aquela metrica daquele sitio, para sempre. O estrago nao e a linha, e
a serie.

Dois caminhos de escrita reais que isto fecha, e nenhum deles era hipotetico:

1. o leitor de NetCDF do AgERA5 fazia `float(var[...])` sobre uma celula
   MASCARADA. O `MaskedArray.__float__` do numpy nao levanta: emite um
   UserWarning e devolve `nan`. O dia era gravado como medicao exacta e
   contado no `rows_written` de um job `succeeded`. Corrigido tambem na
   origem, no mesmo lote;
2. `POST /observations` com `value_numeric = NaN` -- documentado em
   `docs/fase-b-condicoes-de-entrada.md`, seccao 2, desde o fecho da Fase A. O
   pydantic aceitava, a linha era GRAVADA, e so depois a serializacao da
   resposta rebentava com "Out of range float values are not JSON compliant".
   O cliente recebia 500 com a escrita ja feita, que e pior do que um 500
   normal: nao e seguro repetir.

`> '-Infinity' AND < 'Infinity'` e nao `= value_numeric`: em PostgreSQL
`NaN = NaN` e VERDADEIRO, portanto a forma obvia nao apanhava nada. Esta apanha
os tres valores. O `IS NULL OR` de cada coluna e deliberado -- as tres sao
anulaveis, e a ausencia de valor e assunto da `ck_observation_has_a_value`.

A tabela de producao foi verificada antes desta migracao: zero valores nao
finitos em 697 linhas. Nada aqui reescreve dados; se um dia houvesse uma linha
assim, o `ADD CONSTRAINT` recusava-se em voz alta, que e o que se quer.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_observation_values_are_finite"

# literal congelado -- espelha SQL_VALUES_ARE_FINITE de resoiltwin.constraints
SQL = (
    "(value_numeric IS NULL OR (value_numeric > '-Infinity'::double precision"
    " AND value_numeric < 'Infinity'::double precision))"
    " AND (value_min IS NULL OR (value_min > '-Infinity'::double precision"
    " AND value_min < 'Infinity'::double precision))"
    " AND (value_max IS NULL OR (value_max > '-Infinity'::double precision"
    " AND value_max < 'Infinity'::double precision))"
)


def upgrade() -> None:
    op.create_check_constraint(CONSTRAINT, "observations", SQL)


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "observations", type_="check")
