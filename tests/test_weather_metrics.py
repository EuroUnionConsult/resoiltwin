import pytest

from resoiltwin.weather.metrics import (
    UNIDADE_POR_METRICA,
    WeatherMetric,
    proveniencia_de_celula,
    proveniencia_de_estacao,
)

# coordenadas do sitio de Turcifal, as mesmas usadas em tests/test_geo.py
TURCIFAL_LAT, TURCIFAL_LON = 39.037317, -9.240247


def test_every_metric_has_a_unit():
    for m in WeatherMetric:
        assert UNIDADE_POR_METRICA[m], f"{m} sem unidade"


def test_metrics_reuse_the_names_already_in_the_database():
    """air_temperature e relative_humidity ja existem como observed_screening.
    A mesma grandeza tem de ter o mesmo nome, seja qual for a fonte — quem as
    distingue e o source_type, nao o nome da metrica."""
    assert WeatherMetric.air_temperature == "air_temperature"
    assert WeatherMetric.relative_humidity == "relative_humidity"


def test_station_provenance_computes_the_distance():
    """A API do IPMA nao devolve distancia, so coordenadas -- por isso a
    funcao recebe coordenadas e calcula, tal como proveniencia_de_celula.
    Coordenadas da estacao (1210739, Torres Vedras/Dois Portos) verificadas
    em api.ipma.pt/open-data/observation/meteorology/stations/stations.json."""
    p = proveniencia_de_estacao(
        "1210739",
        "Torres Vedras, Dois Portos",
        39.04389444,
        -9.179,
        TURCIFAL_LAT,
        TURCIFAL_LON,
    )
    assert p["station_id"] == "1210739"
    assert p["distance_km"] == pytest.approx(5.340, abs=0.05)
    assert p["measured_at_site"] is False


def test_a_station_on_top_of_the_site_is_still_not_at_the_site():
    """S. Gens fica a ~0,9 km do sitio do Porto -- perto, mas nao no sitio.
    A distincao e binaria de proposito: ou o instrumento esta na parcela, ou
    nao esta."""
    p = proveniencia_de_estacao(
        "1210649",
        "S. Gens",
        41.1848,
        -8.6350,
        41.177928,
        -8.641731,
    )
    assert p["distance_km"] == pytest.approx(0.949, abs=0.05)
    assert p["measured_at_site"] is False


def test_cell_provenance_computes_the_distance_to_the_site():
    # celula centrada a 0,05 grau a norte do sitio, mesma longitude -> ~5,56 km
    p = proveniencia_de_celula(39.087, -9.240, 39.037, -9.240, 0.1)
    assert p["distance_km"] == pytest.approx(5.560, abs=0.05)
    assert p["cell_size_deg"] == 0.1
    assert p["measured_at_site"] is False


def test_cell_provenance_reports_the_footprint_in_km():
    p = proveniencia_de_celula(39.087, -9.240, 39.037, -9.240, 0.1)
    assert p["cell_size_km"] == pytest.approx(11.120, abs=0.05)


def test_invalid_coordinates_are_refused():
    """Ja nao ha "distancia negativa" para recusar -- a distancia passou a
    ser sempre calculada, e o haversine nunca devolve um valor negativo.
    O que continua a poder vir errado e a coordenada: uma latitude fora de
    [-90, 90] produzia, antes desta guarda, uma distancia calculada sobre
    lixo, em silencio."""
    with pytest.raises(ValueError):
        proveniencia_de_estacao("x", "y", 999.0, 0.0, TURCIFAL_LAT, TURCIFAL_LON)
