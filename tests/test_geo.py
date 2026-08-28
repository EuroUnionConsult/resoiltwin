import pytest

from resoiltwin.geo import area_m2, validate_polygon

TURCIFAL_LON, TURCIFAL_LAT = -9.240247, 39.037317


def _square_around(lon: float, lat: float, side_m: float) -> dict:
    """Quadrado aproximado em graus, so para teste de area."""
    import math

    dlat = side_m / 2 / 111_320
    dlon = side_m / 2 / (111_320 * math.cos(math.radians(lat)))
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - dlon, lat - dlat],
            [lon + dlon, lat - dlat],
            [lon + dlon, lat + dlat],
            [lon - dlon, lat + dlat],
            [lon - dlon, lat - dlat],
        ]],
    }


def test_area_of_turcifal_microsite_is_about_240_m2():
    poly = _square_around(TURCIFAL_LON, TURCIFAL_LAT, 15.51)
    assert area_m2(poly) == pytest.approx(240.6, rel=0.01)


def test_validate_rejects_point():
    with pytest.raises(ValueError, match="Polygon"):
        validate_polygon({"type": "Point", "coordinates": [0, 0]})


def test_validate_rejects_ring_with_too_few_positions():
    """Tres posicoes nunca fecham um anel. Ramo do comprimento."""
    with pytest.raises(ValueError, match="at least 4 positions"):
        validate_polygon({
            "type": "Polygon",
            "coordinates": [[[0, 0], [0, 1], [1, 1]]],
        })


def test_validate_rejects_unclosed_ring():
    """Quatro posicoes distintas: comprimento suficiente, fecho em falta. Este e
    o ramo que o teste antigo nunca chegava a avaliar, porque o anel de tres
    posicoes disparava primeiro pelo comprimento."""
    with pytest.raises(ValueError, match="closed"):
        validate_polygon({
            "type": "Polygon",
            "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0]]],
        })


def test_validate_accepts_valid_polygon():
    poly = _square_around(TURCIFAL_LON, TURCIFAL_LAT, 10)
    assert validate_polygon(poly) == poly


def _multipolygon(*polygons: dict) -> dict:
    return {"type": "MultiPolygon", "coordinates": [p["coordinates"] for p in polygons]}


def test_validate_accepts_multipolygon():
    multi = _multipolygon(
        _square_around(TURCIFAL_LON, TURCIFAL_LAT, 10),
        _square_around(TURCIFAL_LON + 0.01, TURCIFAL_LAT, 10),
    )
    assert validate_polygon(multi) == multi


def test_validate_rejects_multipolygon_with_an_unclosed_ring():
    """A segunda parte do MultiPolygon e que esta aberta: a validacao tem de
    percorrer todos os aneis de todos os poligonos, nao so o primeiro."""
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            _square_around(TURCIFAL_LON, TURCIFAL_LAT, 10)["coordinates"],
            [[[0, 0], [0, 1], [1, 1], [1, 0]]],
        ],
    }
    with pytest.raises(ValueError, match="closed"):
        validate_polygon(multi)


def test_validate_rejects_multipolygon_with_a_short_ring():
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            _square_around(TURCIFAL_LON, TURCIFAL_LAT, 10)["coordinates"],
            [[[0, 0], [0, 1], [1, 1]]],
        ],
    }
    with pytest.raises(ValueError, match="at least 4 positions"):
        validate_polygon(multi)


def test_area_of_multipolygon_sums_its_parts():
    single = _square_around(TURCIFAL_LON, TURCIFAL_LAT, 10)
    multi = _multipolygon(single, _square_around(TURCIFAL_LON + 0.01, TURCIFAL_LAT, 10))
    assert area_m2(multi) == pytest.approx(2 * area_m2(single), rel=0.01)
