from datetime import datetime

from sqlalchemy import func, select

from resoiltwin.enums import QualityFlag, SourceType, ValueQualifier
from resoiltwin.features import vapour_pressure_deficit
from resoiltwin.models import Observation, Plot
from seeds.turcifal_2026_08 import seed_turcifal

# nota: comparar uma coluna DateTime com uma string ISO nua faz o SQLAlchemy
# inferir o bind como VARCHAR (nao o tipo da coluna) e o postgres recusa
# "timestamptz >= varchar" sem cast explicito -- por isso usa-se aqui um
# datetime com timezone, nao a string do briefing original.
AUG_24 = datetime.fromisoformat("2026-08-24T00:00:00+01:00")


def test_seed_loads_27_screening_observations(session):
    result = seed_turcifal(session)
    assert result["observations"] == 27
    total = session.scalar(
        select(func.count()).select_from(Observation)
        .where(Observation.source_type == SourceType.observed_screening)
    )
    assert total == 27


def test_seed_is_idempotent(session):
    seed_turcifal(session)
    seed_turcifal(session)
    total = session.scalar(select(func.count()).select_from(Observation))
    assert total == 31  # 27 rastreio + 4 VPD derivados


def test_saturated_light_readings_are_censored(session):
    seed_turcifal(session)
    saturated = session.scalars(
        select(Observation).where(Observation.quality_flag == QualityFlag.saturated_high)
    ).all()
    assert len(saturated) == 4
    assert all(o.value_qualifier == ValueQualifier.censored_high for o in saturated)
    assert all(o.value_numeric == 2000.0 for o in saturated)


def test_ph_readings_are_stored_as_ranges(session):
    seed_turcifal(session)
    ph = session.scalars(
        select(Observation).where(Observation.metric == "ph_screening")
    ).all()
    assert len(ph) == 4
    assert all(o.value_qualifier == ValueQualifier.range for o in ph)
    assert all(o.value_min is not None and o.value_max is not None for o in ph)
    assert all(o.value_numeric is None for o in ph)


def test_vpd_is_derived_not_measured(session):
    seed_turcifal(session)
    vpd = session.scalars(
        select(Observation).where(Observation.metric == "vpd").order_by(Observation.observed_at)
    ).all()
    assert len(vpd) == 4
    assert all(o.source_type == SourceType.derived for o in vpd)
    assert all(o.processing_version == "vpd-tetens-v1" for o in vpd)
    assert [round(o.value_numeric, 2) for o in vpd] == [2.97, 1.27, 0.90, 0.67]


def test_vpd_can_be_audited_back_to_the_measurements_that_produced_it(session):
    """Percorre a cadeia ao contrario: de um VPD ate as duas leituras de origem,
    e reproduz o valor guardado a partir delas.

    Antes de derived_from, o VPD so guardava os NUMEROS de entrada em
    evidence.inputs -- nao havia identificador nenhum, e portanto nao havia
    forma de chegar as linhas que os produziram. Um indicador que nao se
    consegue auditar para tras nao sustenta a tese de proveniencia auditavel.
    """
    seed_turcifal(session)
    vpds = session.scalars(
        select(Observation).where(Observation.metric == "vpd").order_by(Observation.observed_at)
    ).all()
    assert len(vpds) == 4

    for vpd in vpds:
        assert vpd.derived_from is not None and len(vpd.derived_from) == 2
        sources = session.scalars(
            select(Observation).where(Observation.id.in_(vpd.derived_from))
        ).all()
        by_metric = {o.metric: o for o in sources}
        assert set(by_metric) == {"air_temperature", "relative_humidity"}
        assert all(o.observed_at == vpd.observed_at for o in sources)
        assert all(o.source_type == SourceType.observed_screening for o in sources)

        recomputed = round(vapour_pressure_deficit(
            by_metric["air_temperature"].value_numeric,
            by_metric["relative_humidity"].value_numeric,
        ), 4)
        assert recomputed == vpd.value_numeric


def test_canopy_and_grass_diverge_on_24_august(session):
    """O unico resultado que a proposta reporta tem de ser consultavel."""
    seed_turcifal(session)
    canopy = session.scalar(
        select(Observation.value_numeric)
        .join(Plot, Observation.plot_id == Plot.id)
        .where(Observation.metric == "soil_moisture_screening", Plot.code == "TUR-CANOPY",
               Observation.observed_at >= AUG_24)
    )
    grass = session.scalar(
        select(Observation.value_numeric)
        .join(Plot, Observation.plot_id == Plot.id)
        .where(Observation.metric == "soil_moisture_screening", Plot.code == "TUR-GRASS",
               Observation.observed_at >= AUG_24)
    )
    assert canopy == 6.0
    assert grass == 8.0
