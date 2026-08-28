from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

STORAGE_SRID = 4326          # WGS84, para armazenamento e intercambio
PROCESSING_SRID = 32629      # UTM 29N: cobre Turcifal e Porto; metros reais

_TO_UTM = Transformer.from_crs(f"EPSG:{STORAGE_SRID}", f"EPSG:{PROCESSING_SRID}", always_xy=True)


def validate_polygon(geometry: dict) -> dict:
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("AOI geometry must be a GeoJSON Polygon or MultiPolygon")
    rings = geometry["coordinates"] if geometry["type"] == "Polygon" else [
        ring for poly in geometry["coordinates"] for ring in poly
    ]
    for ring in rings:
        # duas condicoes, duas mensagens: juntas num unico `or`, o curto-circuito
        # fazia com que um anel curto disparasse sempre pelo comprimento e o ramo
        # do fecho nunca fosse exercitado. Importa porque a shapely fecha aneis
        # sozinha e em silencio: se a verificacao do fecho se partir, a area passa
        # a ser calculada sobre um poligono diferente do que foi submetido.
        if len(ring) < 4:
            raise ValueError("Polygon ring must have at least 4 positions")
        if list(ring[0]) != list(ring[-1]):
            raise ValueError("Polygon ring must be closed: first and last position must match")
    return geometry


def area_m2(geometry: dict) -> float:
    """Area em metros quadrados, reprojectando para UTM 29N.

    Calcular area em graus da resultados sem significado fisico; e por isso
    que a reprojeccao e feita aqui e nao deixada ao chamador.
    """
    validate_polygon(geometry)
    geom = shape(geometry)
    return shapely_transform(_TO_UTM.transform, geom).area


def geojson_to_wkt_element(geometry: dict, srid: int = STORAGE_SRID) -> WKTElement:
    validate_polygon(geometry)
    return WKTElement(shape(geometry).wkt, srid=srid)


def wkb_to_geojson(element) -> dict | None:
    if element is None:
        return None
    from shapely.geometry import mapping

    return mapping(to_shape(element))
