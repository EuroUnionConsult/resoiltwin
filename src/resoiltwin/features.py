import math

VPD_PROCESSING_VERSION = "vpd-tetens-v1"


def saturation_vapour_pressure(temp_c: float) -> float:
    """Pressao de vapor de saturacao em kPa (equacao de Tetens).

    es = 0.6108 * exp(17.27 * T / (T + 237.3))
    """
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def vapour_pressure_deficit(temp_c: float, relative_humidity_pct: float) -> float:
    """Vapour Pressure Deficit em kPa.

    VPD = es(T) * (1 - RH/100). E um produto DERIVADO, nao uma medicao:
    quem gravar isto na base usa source_type=derived e
    processing_version=VPD_PROCESSING_VERSION.
    """
    if not 0.0 <= relative_humidity_pct <= 100.0:
        raise ValueError("relative humidity must be between 0 and 100 percent")
    return saturation_vapour_pressure(temp_c) * (1.0 - relative_humidity_pct / 100.0)
