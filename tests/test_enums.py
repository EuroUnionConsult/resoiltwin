import pytest

from resoiltwin.enums import GeometryProvenance, QualityFlag, SourceType, ValueQualifier


def test_ambiguous_observed_value_does_not_exist():
    """'observed' e ambiguo: nao distingue instrumento de rastreio de sensor calibrado."""
    with pytest.raises(ValueError):
        SourceType("observed")


def test_screening_and_reference_are_distinct():
    assert SourceType.observed_screening != SourceType.observed_reference
    assert SourceType("observed_screening") == SourceType.observed_screening


def test_simulated_is_not_a_measurement():
    assert SourceType.is_measurement(SourceType.observed_screening) is True
    assert SourceType.is_measurement(SourceType.observed_lab) is True
    assert SourceType.is_measurement(SourceType.satellite_observed) is True
    assert SourceType.is_measurement(SourceType.simulated) is False
    assert SourceType.is_measurement(SourceType.reanalysis) is False
    assert SourceType.is_measurement(SourceType.derived) is False


def test_quality_flag_covers_saturation_and_range():
    assert QualityFlag("saturated_high")
    assert QualityFlag("range_value")


def test_value_qualifier_covers_censoring():
    assert ValueQualifier("censored_high")
    assert ValueQualifier("range")


def test_provisional_geometry_is_distinguishable():
    assert GeometryProvenance("provisional_pending_kml")
    assert GeometryProvenance("documented_exact")
