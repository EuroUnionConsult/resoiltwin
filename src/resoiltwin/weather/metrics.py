"""Vocabulario de metricas meteorologicas e a disciplina do "nao e local".

Nenhuma das duas fontes desta camada mede na parcela: a estacao IPMA mais
proxima fica a alguns km, e a celula de reanalise AgERA5 cobre ~9 km. As duas
funcoes abaixo produzem o dicionario de proveniencia que vai para o `evidence`
de cada observacao, para que essa distancia nunca se perca.
"""

import math
from enum import StrEnum

# raio medio da terra, usado no haversine e na conversao grosseira de graus para km
EARTH_RADIUS_KM = 6371.0088


class WeatherMetric(StrEnum):
    """Metricas meteorologicas partilhadas pelas duas fontes (IPMA e AgERA5).

    air_temperature e relative_humidity reusam exactamente os nomes que ja
    existem na base como observed_screening (campanha de campo). Quem separa
    as tres proveniencias da mesma grandeza e o source_type, nao o nome da
    metrica -- por isso nao ha aqui `ipma_air_temperature` nem `era5_temperature`.
    """

    precipitation = "precipitation"
    air_temperature = "air_temperature"
    relative_humidity = "relative_humidity"
    solar_radiation = "solar_radiation"
    wind_speed = "wind_speed"
    reference_evapotranspiration = "reference_evapotranspiration"


UNIDADE_POR_METRICA: dict[WeatherMetric, str] = {
    WeatherMetric.precipitation: "mm",
    WeatherMetric.air_temperature: "degC",
    WeatherMetric.relative_humidity: "percent",
    WeatherMetric.solar_radiation: "W/m2",
    WeatherMetric.wind_speed: "m/s",
    WeatherMetric.reference_evapotranspiration: "mm",
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia em linha reta entre dois pontos lat/lon, em km.

    Escolhida em vez da reprojeccao para UTM 29N de resoiltwin.geo porque o
    que ha aqui e a distancia entre dois pontos, nao a area de um poligono --
    nao ha vantagem em construir uma geometria e reprojecta-la so para medir
    um segmento. O haversine erra por defeito (assume esfera, nao elipsoide)
    numa fraccao de porcento, muito abaixo dos ~100 m de precisao pedidos a
    esta escala de poucos km.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _validar_lat_lon(lat: float, lon: float) -> None:
    """Recusa coordenadas fora do intervalo fisicamente possivel.

    Guarda mantida depois de a distancia deixar de ser um argumento directo:
    ja nao ha "distancia negativa" para recusar (o haversine nunca devolve
    uma), mas uma latitude ou longitude invalida produzia uma distancia
    calculada sobre lixo, em silencio. Isto apanha esse caso mais cedo.
    """
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"latitude fora do intervalo valido: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude fora do intervalo valido: {lon}")


def proveniencia_de_estacao(
    station_id: str,
    station_name: str,
    lat_estacao: float,
    lon_estacao: float,
    lat_sitio: float,
    lon_sitio: float,
) -> dict:
    """Proveniencia de um valor vindo de uma estacao meteorologica (IPMA).

    A API do IPMA nao devolve a distancia da estacao ao sitio -- so as
    coordenadas da estacao (idEstacao, localEstacao, geometry.coordinates).
    Por isso esta funcao recebe coordenadas e calcula a distancia com o
    mesmo haversine de proveniencia_de_celula, em vez de confiar num numero
    que quem chama teria de calcular por fora -- exactamente o erro
    silencioso que a proveniencia da celula ja evitava. measured_at_site e
    sempre False -- a distincao e binaria de proposito, ou o instrumento
    esta na parcela ou nao esta, e nenhuma estacao do IPMA fica na parcela,
    mesmo quando a distancia e pequena.
    """
    _validar_lat_lon(lat_estacao, lon_estacao)
    _validar_lat_lon(lat_sitio, lon_sitio)
    distancia_km = _haversine_km(lat_estacao, lon_estacao, lat_sitio, lon_sitio)
    return {
        "station_id": station_id,
        "station_name": station_name,
        "distance_km": distancia_km,
        "measured_at_site": False,
    }


def proveniencia_de_celula(
    lat_celula: float,
    lon_celula: float,
    lat_sitio: float,
    lon_sitio: float,
    resolucao_graus: float,
) -> dict:
    """Proveniencia de um valor vindo de uma celula de reanalise (AgERA5).

    Recebe as coordenadas da celula e do sitio e calcula a distancia entre
    elas -- nao a recebe por argumento, para que a conta nao fique a cargo
    de quem chama. cell_size_km converte a resolucao da grelha (graus) para
    km, como referencia grosseira do tamanho do pixel que produziu o valor.
    measured_at_site e sempre False: uma grelha de ~9 km nunca e uma medicao
    no sitio.
    """
    if resolucao_graus <= 0:
        raise ValueError("resolucao_graus tem de ser positiva")
    _validar_lat_lon(lat_celula, lon_celula)
    _validar_lat_lon(lat_sitio, lon_sitio)
    distancia_km = _haversine_km(lat_celula, lon_celula, lat_sitio, lon_sitio)
    cell_size_km = resolucao_graus * (math.pi * EARTH_RADIUS_KM / 180)
    return {
        "cell_lat": lat_celula,
        "cell_lon": lon_celula,
        "distance_km": distancia_km,
        "cell_size_deg": resolucao_graus,
        "cell_size_km": cell_size_km,
        "measured_at_site": False,
    }
