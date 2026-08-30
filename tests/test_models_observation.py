from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from resoiltwin.enums import QualityFlag, SourceType, ValueQualifier
from resoiltwin.models import Observation, Plot, Site


def _site_and_plot(session, suffix: str):
    site = Site(code=f"EUC-T-{suffix}", name="Turcifal")
    plot = Plot(site=site, code=f"P-{suffix}", name="Copa", purpose="canopy")
    session.add(plot)
    session.commit()
    return site, plot


def test_censored_light_reading_keeps_the_limit(session):
    """>=2000 lux: o valor real e desconhecido acima de 2000. Guardar 2000 como
    se fosse exacto e uma mentira silenciosa."""
    site, plot = _site_and_plot(session, "A")
    obs = Observation(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        metric="light_screening", value_numeric=2000.0,
        value_qualifier=ValueQualifier.censored_high,
        unit="instrument_scale", source_type=SourceType.observed_screening,
        quality_flag=QualityFlag.saturated_high, processing_version="field-campaign-v1",
    )
    session.add(obs)
    session.commit()
    assert obs.value_qualifier == ValueQualifier.censored_high
    assert obs.quality_flag == QualityFlag.saturated_high


def test_ph_range_reading(session):
    """pH '7-8' nao e um escalar."""
    site, plot = _site_and_plot(session, "B")
    obs = Observation(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc),
        metric="ph_screening", value_min=7.0, value_max=8.0,
        value_qualifier=ValueQualifier.range, unit="pH",
        source_type=SourceType.observed_screening, quality_flag=QualityFlag.range_value,
        processing_version="field-campaign-v1",
    )
    session.add(obs)
    session.commit()
    assert obs.value_numeric is None
    assert (obs.value_min, obs.value_max) == (7.0, 8.0)


def test_observation_needs_some_value(session):
    """Uma observacao sem nenhum valor nao e uma observacao."""
    site, plot = _site_and_plot(session, "C")
    obs = Observation(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        metric="light_screening", unit="instrument_scale",
        value_qualifier=ValueQualifier.exact,
        source_type=SourceType.observed_screening, quality_flag=QualityFlag.valid,
        processing_version="field-campaign-v1",
    )
    session.add(obs)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_observation_has_a_value" in str(exc.value)


def test_range_qualifier_requires_both_bounds(session):
    """value_min sem value_max, com qualifier 'range'.

    O value_text esta preenchido para satisfazer ck_observation_has_a_value:
    sem ele, a linha violaria essa constraint tambem e o teste passaria mesmo
    que ck_range_needs_both_bounds fosse apagada do schema.

    Isso NAO chega para isolar a constraint sob teste. Desde que a 0003 trouxe
    ck_value_qualifier_matches_value_fields, esta linha viola as duas: um
    qualifier 'range' exige value_min E value_max preenchidos nas duas. O que
    o teste afirma e qual delas o PostgreSQL reporta primeiro, e a ordem de
    avaliacao dos CHECK e alfabetica por nome -- ck_range_needs_both_bounds vem
    antes de ck_value_qualifier_matches_value_fields. Quem acrescentar uma
    constraint com nome alfabeticamente anterior tem de reverificar este teste.
    """
    site, plot = _site_and_plot(session, "D")
    obs = Observation(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        metric="ph_screening", value_min=7.0, value_text="7-ish",
        value_qualifier=ValueQualifier.range,
        unit="pH", source_type=SourceType.observed_screening,
        quality_flag=QualityFlag.range_value, processing_version="field-campaign-v1",
    )
    session.add(obs)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_range_needs_both_bounds" in str(exc.value)


def test_censored_qualifier_needs_the_numeric_value(session):
    """censored_high sem value_numeric nao significa nada - o significado e
    'o valor real e >= value_numeric', e sem o numero nao ha o que qualificar.
    Provado ao vivo pelo revisor: a base aceitava value_text sozinho."""
    site, plot = _site_and_plot(session, "F")
    obs = Observation(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        metric="light_screening", value_text="saturated",
        value_qualifier=ValueQualifier.censored_high, unit="instrument_scale",
        source_type=SourceType.observed_screening, quality_flag=QualityFlag.saturated_high,
        processing_version="field-campaign-v1",
    )
    session.add(obs)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_value_qualifier_matches_value_fields" in str(exc.value)


def test_exact_qualifier_rejects_stray_range_bounds(session):
    """exact com value_numeric e value_min/value_max todos preenchidos nao e
    coerente - fora do caso range, min/max nao deviam estar preenchidos.
    Provado ao vivo pelo revisor: a base aceitava as tres colunas juntas."""
    site, plot = _site_and_plot(session, "G")
    obs = Observation(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        metric="ph_screening", value_numeric=7.5, value_min=7.0, value_max=8.0,
        value_qualifier=ValueQualifier.exact, unit="pH",
        source_type=SourceType.observed_screening, quality_flag=QualityFlag.valid,
        processing_version="field-campaign-v1",
    )
    session.add(obs)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_value_qualifier_matches_value_fields" in str(exc.value)


def _observation(site, plot, **overrides):
    kwargs = dict(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        metric="air_temperature", value_numeric=30.0, unit="degC",
        value_qualifier=ValueQualifier.exact,
        source_type=SourceType.observed_screening, quality_flag=QualityFlag.valid,
        processing_version="field-campaign-v1",
    )
    kwargs.update(overrides)
    return Observation(**kwargs)


def test_ambiguous_observed_source_type_is_rejected_by_the_database(session):
    """'observed' e o valor que o enum omite de proposito, por ser ambiguo entre
    um instrumento de rastreio e um sensor calibrado.

    Mapped[SourceType] com mapped_column(String(32)) nao impoe nada: o
    SQLAlchemy trata o valor como texto e o ORM aceitava esta linha. E o ORM o
    caminho que o seed usa e que os jobs de ingestao das fases seguintes vao
    usar -- nenhum deles passa pela validacao pydantic da API. So um CHECK na
    base o impede."""
    site, plot = _site_and_plot(session, "H")
    session.add(_observation(site, plot, source_type="observed"))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_observation_source_type_domain" in str(exc.value)


def test_invented_quality_flag_is_rejected_by_the_database(session):
    site, plot = _site_and_plot(session, "I")
    session.add(_observation(site, plot, quality_flag="muito_fiavel"))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_observation_quality_flag_domain" in str(exc.value)


def test_invented_value_qualifier_is_rejected_by_the_database(session):
    site, plot = _site_and_plot(session, "J")
    session.add(_observation(site, plot, value_qualifier="mais_ou_menos"))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_observation_value_qualifier_domain" in str(exc.value)


def test_blank_processing_version_is_rejected(session):
    """NOT NULL nao chega: uma string de espacos nao identifica versao nenhuma."""
    site, plot = _site_and_plot(session, "K")
    session.add(_observation(site, plot, processing_version="   "))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_observation_processing_version_not_blank" in str(exc.value)


def test_saturated_flag_cannot_carry_an_exact_value(session):
    """A mentira silenciosa que a constraint existe para apanhar: o instrumento
    ficou no topo de escala e o valor foi gravado como se fosse uma medida."""
    site, plot = _site_and_plot(session, "M")
    session.add(_observation(
        site, plot, metric="light_screening", unit="instrument_scale",
        value_numeric=2000.0, value_qualifier=ValueQualifier.exact,
        quality_flag=QualityFlag.saturated_high,
    ))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_censoring_flag_matches_qualifier" in str(exc.value)


def test_range_flag_cannot_carry_a_scalar_qualifier(session):
    """O mesmo para o par range_value/range."""
    site, plot = _site_and_plot(session, "N")
    session.add(_observation(
        site, plot, metric="ph_screening", unit="pH",
        value_numeric=7.5, value_qualifier=ValueQualifier.exact,
        quality_flag=QualityFlag.range_value,
    ))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_censoring_flag_matches_qualifier" in str(exc.value)


@pytest.mark.parametrize(
    "flag", [QualityFlag.unchecked, QualityFlag.suspect, QualityFlag.rejected,
             QualityFlag.laboratory_confirmed],
)
def test_censored_value_accepts_any_quality_assessment(session, flag):
    """A implicacao e num so sentido, de proposito.

    quality_flag e uma avaliacao de qualidade; value_qualifier e a semantica do
    valor. Sao eixos ortogonais. A versao bicondicional desta constraint
    rejeitava um valor censurado com `unchecked` -- que e o valor por omissao
    do proprio modelo --, o que tornava impossivel um job de ingestao gravar uma
    leitura no topo de escala antes de a ter avaliado. E e por jobs, e nao por
    POST, que a fase seguinte escreve.
    """
    site, plot = _site_and_plot(session, f"CENS-{flag.value}")
    session.add(_observation(
        site, plot, metric="light_screening", unit="instrument_scale",
        value_numeric=2000.0, value_qualifier=ValueQualifier.censored_high,
        quality_flag=flag,
    ))
    session.commit()


def test_range_value_accepts_an_unassessed_reading(session):
    site, plot = _site_and_plot(session, "RANGE-UNCHECKED")
    session.add(_observation(
        site, plot, metric="ph_screening", unit="pH",
        value_numeric=None, value_min=7.0, value_max=8.0,
        value_qualifier=ValueQualifier.range, quality_flag=QualityFlag.unchecked,
    ))
    session.commit()


def test_derived_value_without_method_or_inputs_is_rejected(session):
    """Um derivado sem method e sem forma de documentar as entradas nao e
    auditavel para tras -- e a auditabilidade e a tese do produto."""
    site, plot = _site_and_plot(session, "O")
    session.add(_observation(
        site, plot, metric="vpd", unit="kPa", value_numeric=2.97,
        source_type=SourceType.derived, processing_version="vpd-tetens-v1",
    ))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_derived_needs_method_and_inputs" in str(exc.value)


def test_derived_value_with_method_but_no_inputs_is_rejected(session):
    site, plot = _site_and_plot(session, "P")
    session.add(_observation(
        site, plot, metric="vpd", unit="kPa", value_numeric=2.97,
        source_type=SourceType.derived, processing_version="vpd-tetens-v1",
        method="tetens_saturation_vapour_pressure",
    ))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_derived_needs_method_and_inputs" in str(exc.value)


def test_derived_value_with_explicit_none_evidence_is_rejected(session):
    """O caminho real, e nao a omissao do kwarg.

    Omitir `evidence` no construtor do ORM e um caminho que nem o seed nem a
    rota POST usam: os dois passam sempre um valor, e esse valor e `None`
    quando nao ha proveniencia a documentar. Com JSONB por omissao, o
    SQLAlchemy gravava esse `None` como o literal JSON `null`, que nao e SQL
    NULL -- e `evidence IS NOT NULL` era verdadeiro. A constraint reduzia-se a
    `method IS NOT NULL` e esta linha era ACEITE.
    """
    site, plot = _site_and_plot(session, "P2")
    session.add(_observation(
        site, plot, metric="vpd", unit="kPa", value_numeric=2.97,
        source_type=SourceType.derived, processing_version="vpd-tetens-v1",
        method="tetens_saturation_vapour_pressure", evidence=None,
    ))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_derived_needs_method_and_inputs" in str(exc.value)


def test_none_evidence_is_written_as_sql_null(session):
    """A causa por tras da N1, medida na coluna e nao no comportamento.

    none_as_null=True e a correccao na origem: sem ela a coluna ficava com
    jsonb 'null' e qualquer guarda futura escrita com `IS NOT NULL` voltava a
    nao morder.
    """
    site, plot = _site_and_plot(session, "P3")
    obs = _observation(site, plot, evidence=None)
    session.add(obs)
    session.commit()
    row = session.execute(
        text("SELECT evidence IS NULL AS sql_null, jsonb_typeof(evidence) AS kind "
             "FROM observations WHERE id = :id"),
        {"id": obs.id},
    ).one()
    assert row.sql_null is True
    assert row.kind is None


def test_derived_value_with_an_empty_derived_from_is_rejected(session):
    """Um array vazio nao documenta entrada nenhuma.

    `array_length('{}', 1)` devolve NULL e nao 0, e um CHECK que avalie a NULL
    PASSA -- so um FALSE explicito rejeita a linha. Sem o COALESCE, a guarda
    deixava entrar um derivado com `derived_from=[]`.
    """
    site, plot = _site_and_plot(session, "P4")
    session.add(_observation(
        site, plot, metric="vpd", unit="kPa", value_numeric=2.97,
        source_type=SourceType.derived, processing_version="vpd-tetens-v1",
        method="tetens_saturation_vapour_pressure", evidence=None, derived_from=[],
    ))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_derived_needs_method_and_inputs" in str(exc.value)


def test_derived_value_is_accepted_with_derived_from_alone(session):
    """derived_from sozinho chega: nem todo o derivado tera evidence."""
    site, plot = _site_and_plot(session, "Q")
    source = _observation(site, plot)
    session.add(source)
    session.flush()
    session.add(_observation(
        site, plot, metric="vpd", unit="kPa", value_numeric=2.97,
        source_type=SourceType.derived, processing_version="vpd-tetens-v1",
        method="tetens_saturation_vapour_pressure", derived_from=[source.id],
    ))
    session.commit()


def test_derived_value_is_accepted_with_evidence_alone(session):
    """evidence sozinho tambem chega: a Fase C traz uma tabela weather_series
    separada, e um derivado calculado a partir dela nao tem observation_id
    nenhum para apontar em derived_from."""
    site, plot = _site_and_plot(session, "R")
    session.add(_observation(
        site, plot, metric="vpd", unit="kPa", value_numeric=2.97,
        source_type=SourceType.derived, processing_version="vpd-tetens-v1",
        method="tetens_saturation_vapour_pressure",
        evidence={"inputs": {"air_temperature_degC": 30.0, "relative_humidity_pct": 30.0}},
    ))
    session.commit()


def test_duplicate_ingestion_is_rejected(session):
    """Reexecutar a mesma ingestao nao pode duplicar linhas."""
    site, plot = _site_and_plot(session, "E")
    kwargs = dict(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 14, 37, tzinfo=timezone.utc),
        metric="air_temperature", value_numeric=30.0,
        value_qualifier=ValueQualifier.exact, unit="degC",
        source_type=SourceType.observed_screening, quality_flag=QualityFlag.valid,
        processing_version="field-campaign-v1",
    )
    session.add(Observation(**kwargs))
    session.commit()
    session.add(Observation(**kwargs))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "uq_observation_identity" in str(exc.value)


def test_duplicate_with_null_plot_is_rejected(session):
    """plot_id nulo nao pode escapar a desduplicacao: as series de satelite
    vao ter plot_id nulo e a ingestao tem de ser idempotente."""
    site = Site(code="EUC-T-F", name="Turcifal")
    session.add(site)
    session.commit()
    kwargs = dict(
        site_id=site.id, plot_id=None,
        observed_at=datetime(2026, 8, 22, 11, 0, tzinfo=timezone.utc),
        metric="ndvi", value_numeric=0.42,
        value_qualifier=ValueQualifier.exact, unit="index",
        source_type=SourceType.satellite_observed, quality_flag=QualityFlag.valid,
        processing_version="s2-l2a-v1",
    )
    session.add(Observation(**kwargs))
    session.commit()
    session.add(Observation(**kwargs))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "uq_observation_identity" in str(exc.value)


# --- valores nao finitos: NaN, +Infinity, -Infinity ------------------------


def _linha_com(session, sufixo: str, **valores):
    """Uma observacao valida em tudo menos no que o teste esta a mudar."""
    site, plot = _site_and_plot(session, sufixo)
    campos = dict(
        site_id=site.id, plot_id=plot.id,
        observed_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        metric="air_temperature", unit="degC",
        value_qualifier=ValueQualifier.exact,
        source_type=SourceType.reanalysis, quality_flag=QualityFlag.valid,
        processing_version="agera5-v2_0",
    )
    campos.update(valores)
    return Observation(**campos)


@pytest.mark.parametrize("nome,valor", [
    ("nan", float("nan")),
    ("mais_infinito", float("inf")),
    ("menos_infinito", float("-inf")),
])
def test_a_non_finite_value_is_refused_by_the_database(session, nome, valor):
    """NaN nao e uma medicao, e nenhuma das outras guardas mordia nele.

    `ck_observation_has_a_value` passa porque `NaN IS NOT NULL` e verdadeiro;
    `ck_value_qualifier_matches_value_fields` passa porque um NaN em
    value_numeric e coerente com 'exact'; os CHECK de dominio olham para os
    enums e nao para o valor. A linha entrava com proveniencia completa e
    `quality_flag = valid`.

    O estrago nao e a linha: no PostgreSQL o NaN ordena acima de qualquer
    numero e propaga-se pelos agregados, portanto um so dia punha `avg()`,
    `max()` e `sum()` a devolver NaN para aquela metrica daquele sitio, para
    sempre.
    """
    session.add(_linha_com(session, f"NF-{nome}", value_numeric=valor))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_observation_values_are_finite" in str(exc.value)


def test_a_non_finite_bound_is_refused_too(session):
    """A guarda cobre as tres colunas de valor, e nao so a que ja rebentou.

    Um intervalo com um extremo infinito satisfaz ck_range_is_ordered
    (`-Infinity <= 8.0` e verdadeiro) e ck_range_needs_both_bounds, e um
    `avg(value_max)` sobre a coluna fica igualmente envenenado.
    """
    session.add(_linha_com(
        session, "NF-limite", value_min=7.0, value_max=float("inf"),
        value_qualifier=ValueQualifier.range, quality_flag=QualityFlag.range_value,
        metric="ph_screening", unit="pH",
    ))
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_observation_values_are_finite" in str(exc.value)


def test_an_ordinary_number_still_passes(session):
    """Controlo negativo: sem ele, `CHECK (false)` passava os testes acima."""
    obs = _linha_com(session, "NF-normal", value_numeric=21.68)
    session.add(obs)
    session.commit()
    assert obs.value_numeric == 21.68


def test_the_guard_does_not_fire_on_a_row_without_a_numeric_value(session):
    """Um CHECK que avalie a NULL passa, e aqui isso e o que se quer: a
    ausencia de valor e assunto da ck_observation_has_a_value, nao desta."""
    obs = _linha_com(session, "NF-texto", value_text="sem leitura",
                     metric="ph_screening", unit="pH")
    session.add(obs)
    session.commit()
    assert obs.value_numeric is None
