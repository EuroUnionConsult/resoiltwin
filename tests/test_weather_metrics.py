import pytest

from resoiltwin.weather.metrics import (
    UNIDADE_POR_METRICA,
    WeatherMetric,
    proveniencia_de_celula,
    proveniencia_de_estacao,
)


def test_every_metric_has_a_unit():
    for m in WeatherMetric:
        assert UNIDADE_POR_METRICA[m], f"{m} sem unidade"


def test_metrics_reuse_the_names_already_in_the_database():
    """air_temperature e relative_humidity ja existem como observed_screening.
    A mesma grandeza tem de ter o mesmo nome, seja qual for a fonte — quem as
    distingue e o source_type, nao o nome da metrica."""
    assert WeatherMetric.air_temperature == "air_temperature"
    assert WeatherMetric.relative_humidity == "relative_humidity"


def test_station_provenance_records_the_distance():
    p = proveniencia_de_estacao("1210739", "Torres Vedras, Dois Portos", 6.8)
    assert p["station_id"] == "1210739"
    assert p["distance_km"] == 6.8
    assert p["measured_at_site"] is False


def test_a_station_on_top_of_the_site_is_still_not_at_the_site():
    """0,8 km e perto, mas nao e no sitio. A distincao e binaria de proposito:
    ou o instrumento esta na parcela, ou nao esta."""
    p = proveniencia_de_estacao("1210649", "S. Gens", 0.8)
    assert p["measured_at_site"] is False


def test_cell_provenance_computes_the_distance_to_the_site():
    # celula centrada a ~0,05 grau a norte do sitio -> ~5,5 km
    p = proveniencia_de_celula(39.087, -9.240, 39.037, -9.240, 0.1)
    assert 5.0 <= p["distance_km"] <= 6.0
    assert p["cell_size_deg"] == 0.1
    assert p["measured_at_site"] is False


def test_cell_provenance_reports_the_footprint_in_km():
    p = proveniencia_de_celula(39.087, -9.240, 39.037, -9.240, 0.1)
    assert 8.0 <= p["cell_size_km"] <= 12.0


def test_a_negative_distance_is_refused():
    with pytest.raises(ValueError):
        proveniencia_de_estacao("x", "y", -1.0)
