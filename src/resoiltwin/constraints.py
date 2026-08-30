"""Texto SQL das constraints de dominio e de coerencia, num so lugar.

Fonte unica para os MODELOS. As listas de valores nao sao escritas a mao: sao
geradas a partir dos enums de `resoiltwin.enums`.

As migracoes NAO importam este modulo. Uma migracao e um artefacto congelado e
tem de poder correr sem codigo de aplicacao nenhum; se importasse daqui, o dia
em que este ficheiro mudasse de nome seria o dia em que deixaria de ser
possivel construir uma base do zero. A paridade entre o schema das migracoes e
o schema dos modelos e verificada por `tests/test_schema_parity.py`, que
compara nome a nome as CHECK constraints declaradas nos modelos com as que
existem na base construida por `alembic upgrade head`.

Porque e que isto e preciso: `Mapped[SourceType]` com `mapped_column(String(32))`
e decorativo. O SQLAlchemy trata o valor como texto e nao valida nem coage --
`Observation(source_type='observed')` era aceite pelo ORM, que e o caminho que
o seed usa e que os jobs de ingestao das fases seguintes vao usar. A unica
camada duravel que impoe o dominio e um CHECK na base de dados.

Nota para quem acrescentar um valor a um enum: uma base ja migrada continua com
a lista antiga gravada na constraint. E preciso uma migracao nova que largue e
volte a criar a constraint com a lista nova, escrita ali por extenso. O teste
de paridade e que apanha o esquecimento.
"""

from enum import StrEnum

from resoiltwin.enums import (
    AoiStatus,
    GeometryProvenance,
    JobStatus,
    QualityFlag,
    SourceType,
    ValueQualifier,
)


def sql_in(column: str, *members: StrEnum) -> str:
    """`coluna IN ('a', 'b')` a partir dos membros do enum, nunca a mao."""
    values = ", ".join(f"'{member.value}'" for member in members)
    return f"{column} IN ({values})"


def sql_domain(column: str, enum_cls: type[StrEnum]) -> str:
    """`coluna IN (...)` com o dominio completo de um enum."""
    return sql_in(column, *enum_cls)


# Implicacao NUM SO SENTIDO: um instrumento marcado como saturado tem de
# guardar o valor como censurado, e uma leitura marcada como intervalo tem de
# guardar o valor como range. Sem isto, uma leitura no topo de escala entra
# como escalar exacto: o numero perde a informacao de que e um limite e nao uma
# medida, que e a deformacao que este modelo existe para impedir.
#
# O reciproco NAO se impoe, de proposito. `quality_flag` e uma avaliacao de
# qualidade e `value_qualifier` e a semantica do valor -- dois eixos
# ortogonais. Uma versao anterior desta constraint era um bicondicional e
# fundia-os: rejeitava `censored_high` com `unchecked`, `suspect`, `rejected`
# ou `laboratory_confirmed`. Como `unchecked` e o valor por omissao do proprio
# modelo, um job de ingestao que gravasse um valor censurado antes de avaliar a
# qualidade era impossivel -- e e exactamente isso que a fase seguinte faz, que
# escreve por jobs do lado do servidor e nao por POST.
SQL_CENSORING_MATCHES_QUALIFIER = (
    f"(NOT ({sql_in('quality_flag', QualityFlag.saturated_high, QualityFlag.saturated_low)})"
    f" OR {sql_in('value_qualifier', ValueQualifier.censored_high, ValueQualifier.censored_low)})"
    f" AND (quality_flag <> '{QualityFlag.range_value.value}'"
    f" OR value_qualifier = '{ValueQualifier.range.value}')"
)

# Um valor derivado tem de dizer COMO foi calculado (method) e a partir de que
# entradas. `derived_from` guarda os ids das observacoes de origem; `evidence`
# cobre o caso em que a origem nao e uma observacao (a Fase C traz uma tabela
# weather_series separada, e um derivado calculado a partir dela nao tem
# observation_id nenhum para apontar). Exigir so uma das duas seria estreito
# demais; nao exigir nenhuma deixa um derivado sem rasto para tras.
# `jsonb_typeof(evidence) = 'object'` e nao `evidence IS NOT NULL`: em JSONB ha
# DOIS nulos diferentes. O SQL NULL (coluna sem valor) e o literal JSON `null`
# (um valor JSON que existe e nao diz nada). O SQLAlchemy gravava `None` como o
# segundo, logo `evidence IS NOT NULL` era sempre verdadeiro e a constraint
# reduzia-se a `method IS NOT NULL`: nao mordia em caminho de escrita nenhum.
# A coluna passou a JSONB(none_as_null=True), o que resolve o problema na
# origem; esta forma torna a constraint robusta na mesma, porque um `null` JSON
# explicito tambem nao documenta entradas nenhumas.
# Os dois COALESCE nao sao decoracao. Um CHECK que avalie a NULL PASSA -- so
# um FALSE explicito rejeita a linha. `jsonb_typeof(NULL)` e NULL, e
# `array_length('{}', 1)` tambem e NULL (nao 0), portanto sem eles a constraint
# voltava a nao morder exactamente nos dois casos que ela existe para apanhar:
# um derivado sem evidence, e um derivado com derived_from vazio.
SQL_DERIVED_NEEDS_METHOD_AND_INPUTS = (
    f"source_type <> '{SourceType.derived.value}'"
    " OR (method IS NOT NULL"
    " AND (COALESCE(jsonb_typeof(evidence), '') = 'object'"
    " OR COALESCE(array_length(derived_from, 1), 0) > 0))"
)

# processing_version e obrigatorio por regra de proveniencia; uma string vazia
# ou so com espacos satisfaz NOT NULL e nao identifica versao nenhuma.
SQL_PROCESSING_VERSION_NOT_BLANK = "length(trim(processing_version)) > 0"

# NaN, +Infinity e -Infinity nao sao medicoes, e `double precision` aceita os
# tres. Nenhuma das guardas que ja existiam mordia neles: `NaN IS NOT NULL` e
# verdadeiro, portanto ck_observation_has_a_value passa; `value_qualifier =
# 'exact'` e coerente com um NaN em value_numeric; e o dominio dos enums nao
# olha para o valor. Uma linha assim entra com proveniencia completa,
# `quality_flag = valid` e ar de correcta.
#
# O que a torna diferente de um valor simplesmente errado: no PostgreSQL o NaN
# ordena ACIMA de qualquer numero e propaga-se pelos agregados. Um so dia com
# NaN poe `avg()`, `max()` e `sum()` a devolver NaN para aquela metrica daquele
# sitio, para sempre -- o estrago nao e a linha, e a serie inteira.
#
# Vai aqui, na base, e nao apenas no leitor de NetCDF que produziu o primeiro
# caso: um CHECK protege TODOS os caminhos de escrita, incluindo os que ainda
# nao existem. E fecha tambem um defeito anterior a Fase A que estava
# documentado e vivo (`docs/fase-b-condicoes-de-entrada.md`, seccao 2): um
# `value_numeric = NaN` por `POST /observations` passava o pydantic, a linha
# era GRAVADA, e so depois a serializacao da resposta rebentava com "Out of
# range float values are not JSON compliant" -- o cliente via um 500 com a
# escrita ja feita, que e pior do que um 500 normal porque nao e seguro repetir.
#
# `> '-Infinity' AND < 'Infinity'` e nao `= value_numeric`: em PostgreSQL
# `NaN = NaN` e VERDADEIRO (o NaN e igual a si proprio para efeitos de ordem e
# de indice), portanto a forma obvia nao apanharia nada. Esta apanha os tres:
# NaN falha o `<` (ordena acima de Infinity), Infinity falha o `<` e -Infinity
# falha o `>`. Cada coluna leva o seu `IS NULL OR` porque as tres sao
# anulaveis e um CHECK que avalie a NULL PASSA -- aqui isso e o que se quer,
# porque a ausencia de valor e assunto da ck_observation_has_a_value.
def _sql_finito(coluna: str) -> str:
    return (f"({coluna} IS NULL OR ({coluna} > '-Infinity'::double precision"
            f" AND {coluna} < 'Infinity'::double precision))")


SQL_VALUES_ARE_FINITE = " AND ".join(
    _sql_finito(coluna) for coluna in ("value_numeric", "value_min", "value_max")
)


OBSERVATION_CHECKS: dict[str, str] = {
    "ck_censoring_flag_matches_qualifier": SQL_CENSORING_MATCHES_QUALIFIER,
    "ck_derived_needs_method_and_inputs": SQL_DERIVED_NEEDS_METHOD_AND_INPUTS,
    "ck_observation_processing_version_not_blank": SQL_PROCESSING_VERSION_NOT_BLANK,
    "ck_observation_quality_flag_domain": sql_domain("quality_flag", QualityFlag),
    "ck_observation_source_type_domain": sql_domain("source_type", SourceType),
    "ck_observation_value_qualifier_domain": sql_domain("value_qualifier", ValueQualifier),
    "ck_observation_values_are_finite": SQL_VALUES_ARE_FINITE,
}

AOI_CHECKS: dict[str, str] = {
    "ck_aoi_geometry_provenance_domain": sql_domain("geometry_provenance", GeometryProvenance),
    "ck_aoi_status_domain": sql_domain("status", AoiStatus),
}

# Um job failed tem de dizer PORQUE falhou -- e o rasto que a proxima fase
# (ingestao agendada) precisa para uma falha as tres da manha nao passar em
# silencio. `error` e uma coluna anulavel: um CHECK que avalie a NULL PASSA, so
# um FALSE explicito rejeita. `length(trim(error))` sobre `error IS NULL` da
# NULL, nao FALSE -- sem o COALESCE, um job failed sem error passava a
# constraint por vacuidade, exactamente o caso que ela existe para apanhar.
SQL_FAILED_JOB_NEEDS_ERROR = (
    f"status <> '{JobStatus.failed.value}' OR COALESCE(length(trim(error)), 0) > 0"
)

INGESTION_JOB_CHECKS: dict[str, str] = {
    "ck_ingestion_job_status_domain": sql_domain("status", JobStatus),
    "ck_failed_job_needs_an_error": SQL_FAILED_JOB_NEEDS_ERROR,
}
