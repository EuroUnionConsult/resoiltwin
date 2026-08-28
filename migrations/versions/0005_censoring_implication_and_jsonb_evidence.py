"""censoring as a one-way implication and evidence as a real jsonb object

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-28 19:20:00.000000

Escrita a mao, como as 0001-0004: o autogenerate do Alembic 1.13 nao compara
CheckConstraints, e correr `alembic revision --autogenerate` contra a imagem
postgis/postgis:16-3.4 produz ainda por cima ruido das tabelas de
tiger_geocoder e topology, que nao pertencem a este schema.

O texto das constraints esta INLINE, literal. Esta migracao nao importa nada de
`resoiltwin`: a historia tem de continuar a correr no dia em que os modulos da
aplicacao mudarem de nome ou de sitio.

Duas correccoes, ambas da mesma familia -- guardas que pareciam impostas e nao
mordiam no caminho que o codigo de producao usa:

1. ck_derived_needs_method_and_inputs testava `evidence IS NOT NULL`. O
   SQLAlchemy gravava `None` numa coluna JSONB como o literal JSON `null`, que
   NAO e SQL NULL, portanto a condicao era sempre verdadeira e a constraint
   reduzia-se a `method IS NOT NULL`. Passa a testar
   `jsonb_typeof(evidence) = 'object'`, e as linhas que ja tinham o `null` JSON
   sao normalizadas para SQL NULL.

2. ck_censoring_flag_matches_qualifier era um bicondicional e fundia dois eixos
   ortogonais: `quality_flag` e uma avaliacao de qualidade, `value_qualifier` e
   a semantica do valor. Rejeitava um valor censurado com `unchecked` -- que e
   o valor por omissao do modelo --, com `suspect` ou com `rejected`, o que
   torna impossivel um job de ingestao que grave o valor antes de avaliar a
   qualidade. Passa a implicacao num so sentido: saturado obriga a censurado, e
   range_value obriga a range, mas nao o reciproco. Continua a apanhar a
   mentira silenciosa que a motivou (marcado saturado, guardado como escalar
   exacto).

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CENSORING_NEW = (
    "(NOT (quality_flag IN ('saturated_high', 'saturated_low'))"
    " OR value_qualifier IN ('censored_high', 'censored_low'))"
    " AND (quality_flag <> 'range_value' OR value_qualifier = 'range')"
)
CENSORING_OLD = (
    "(quality_flag IN ('saturated_high', 'saturated_low'))"
    " = (value_qualifier IN ('censored_high', 'censored_low'))"
    " AND (quality_flag = 'range_value') = (value_qualifier = 'range')"
)

# os dois COALESCE fecham a segunda metade do mesmo problema: um CHECK que
# avalie a NULL passa, e tanto `jsonb_typeof(NULL)` como `array_length('{}', 1)`
# sao NULL. Sem eles a guarda continuava a nao morder num derivado sem evidence
# nem num derivado com derived_from vazio.
DERIVED_NEW = (
    "source_type <> 'derived'"
    " OR (method IS NOT NULL"
    " AND (COALESCE(jsonb_typeof(evidence), '') = 'object'"
    " OR COALESCE(array_length(derived_from, 1), 0) > 0))"
)
DERIVED_OLD = (
    "source_type <> 'derived'"
    " OR (method IS NOT NULL"
    " AND (evidence IS NOT NULL"
    " OR (derived_from IS NOT NULL AND array_length(derived_from, 1) > 0)))"
)


def upgrade() -> None:
    # normalizar o literal JSON `null` para SQL NULL. As linhas gravadas antes
    # do none_as_null=True tem `null` la dentro; sao indistinguiveis de "sem
    # valor" para quem le, mas nao para o Postgres.
    op.execute("UPDATE observations SET evidence = NULL WHERE evidence = 'null'::jsonb")

    op.drop_constraint("ck_derived_needs_method_and_inputs", "observations", type_="check")
    op.create_check_constraint("ck_derived_needs_method_and_inputs", "observations", DERIVED_NEW)

    op.drop_constraint("ck_censoring_flag_matches_qualifier", "observations", type_="check")
    op.create_check_constraint("ck_censoring_flag_matches_qualifier", "observations", CENSORING_NEW)


def downgrade() -> None:
    # o bicondicional antigo e MAIS apertado do que a implicacao: reverter pode
    # falhar se entretanto tiver entrado uma linha censurada com quality_flag
    # fora do par saturado. E o comportamento correcto -- a reversao tem de
    # avisar em vez de largar dados.
    op.drop_constraint("ck_censoring_flag_matches_qualifier", "observations", type_="check")
    op.create_check_constraint("ck_censoring_flag_matches_qualifier", "observations", CENSORING_OLD)

    op.drop_constraint("ck_derived_needs_method_and_inputs", "observations", type_="check")
    op.create_check_constraint("ck_derived_needs_method_and_inputs", "observations", DERIVED_OLD)
