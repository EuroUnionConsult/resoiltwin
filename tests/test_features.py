import pytest

from resoiltwin.features import saturation_vapour_pressure, vapour_pressure_deficit


@pytest.mark.parametrize(
    "temp_c,rh_pct,expected_kpa",
    [
        (30.0, 30.0, 2.97),   # 22/08 14:37 sob limoeiro
        (25.0, 60.0, 1.27),   # 22/08 18:05
        (24.0, 70.0, 0.90),   # 23/08 08:00
        (26.0, 80.0, 0.67),   # 24/08 13:48
    ],
)
def test_vpd_matches_turcifal_report(temp_c, rh_pct, expected_kpa):
    assert vapour_pressure_deficit(temp_c, rh_pct) == pytest.approx(expected_kpa, abs=0.005)


def test_saturated_air_has_zero_vpd():
    assert vapour_pressure_deficit(20.0, 100.0) == pytest.approx(0.0, abs=1e-9)


def test_svp_increases_with_temperature():
    assert saturation_vapour_pressure(30.0) > saturation_vapour_pressure(20.0)


def test_rejects_impossible_humidity():
    with pytest.raises(ValueError):
        vapour_pressure_deficit(25.0, 120.0)
