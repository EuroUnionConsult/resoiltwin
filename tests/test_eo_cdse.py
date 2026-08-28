import json

import httpx
import pytest

from resoiltwin.eo.cdse import CDSEClient
from resoiltwin.eo.evalscripts import NDVI_NDMI_NDRE, EVALSCRIPT_VERSION, evalscript_hash

SQUARE = {"type": "Polygon", "coordinates": [[
    [-9.2547, 39.0261], [-9.2258, 39.0261], [-9.2258, 39.0485], [-9.2547, 39.0485], [-9.2547, 39.0261]]]}


def _transport(handler):
    return httpx.MockTransport(handler)


def test_token_is_fetched_once_and_reused():
    chamadas = {"token": 0}

    def handler(request):
        if "openid-connect/token" in str(request.url):
            chamadas["token"] += 1
            return httpx.Response(200, json={"access_token": "tok-abc", "expires_in": 1800})
        return httpx.Response(200, json={"features": []})

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    assert c.token() == "tok-abc"
    assert c.token() == "tok-abc"
    assert chamadas["token"] == 1


def test_expired_token_is_refetched():
    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok-curto", "expires_in": 1})
        return httpx.Response(200, json={"features": []})

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    c.token()
    c._expires_at = 0.0          # simula expiracao sem esperar
    assert c.token() == "tok-curto"


def test_bad_credentials_raise_a_clear_error():
    def handler(request):
        return httpx.Response(401, json={"error": "invalid_client",
                                         "error_description": "Invalid client credentials"})

    c = CDSEClient("id", "errado", transport=_transport(handler))
    with pytest.raises(RuntimeError, match="invalid_client"):
        c.token()


def test_search_scenes_returns_acquisitions_with_cloud_cover():
    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        return httpx.Response(200, json={"features": [
            {"id": "S2A_X", "properties": {"datetime": "2026-08-21T11:39:11Z", "eo:cloud_cover": 0.5}},
            {"id": "S2B_Y", "properties": {"datetime": "2026-08-24T11:33:19Z", "eo:cloud_cover": 29.94}},
        ]})

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    cenas = c.search_scenes(SQUARE, "2026-08-01", "2026-08-28")
    assert [x["id"] for x in cenas] == ["S2A_X", "S2B_Y"]
    assert cenas[1]["properties"]["eo:cloud_cover"] == 29.94


def test_search_scenes_declares_filter_lang():
    """Sem filter-lang o Catalog do CDSE devolve 400 (confirmado contra a API
    real em 28/08/2026): o filtro de nuvens e CQL2-JSON e tem de ser declarado,
    senao e rejeitado, nao ignorado em silencio."""
    capturado = {}

    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        capturado["body"] = json.loads(request.content)
        return httpx.Response(200, json={"features": []})

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    c.search_scenes(SQUARE, "2026-08-01", "2026-08-28", max_cloud=5)
    assert capturado["body"]["filter-lang"] == "cql2-json"


def test_search_scenes_error_includes_body():
    """O 400 do Catalog real vem como code/description, nao error/error_description
    do token. raise_for_status() sozinho dava so '400 Bad Request for url ...'."""
    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        return httpx.Response(400, json={"code": 400,
                                         "description": "Cannot parse parameter `filter`."})

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    with pytest.raises(RuntimeError, match="Cannot parse parameter"):
        c.search_scenes(SQUARE, "2026-08-01", "2026-08-28")


def test_search_scenes_follows_pagination_until_exhausted():
    """Formato de paginacao confirmado contra a API real: links rel=next com
    body a mesclar (merge=true) no pedido original ate deixar de haver next."""
    paginas = {"n": 0}

    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        paginas["n"] += 1
        if paginas["n"] == 1:
            return httpx.Response(200, json={
                "features": [{"id": "A"}, {"id": "B"}],
                "links": [{"rel": "next", "method": "POST", "merge": True, "body": {"next": "2"}}],
            })
        return httpx.Response(200, json={"features": [{"id": "C"}], "links": []})

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    cenas = c.search_scenes(SQUARE, "2026-08-01", "2026-08-28")
    assert [x["id"] for x in cenas] == ["A", "B", "C"]
    assert paginas["n"] == 2


def test_search_scenes_raises_instead_of_truncating_silently():
    """Uma AOI grande pode ter paginacao sem fim visivel dentro do tecto de
    seguranca; nesse caso levantamos erro em vez de devolver uma serie parcial
    como se fosse completa."""
    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        return httpx.Response(200, json={
            "features": [{"id": "X"}],
            "links": [{"rel": "next", "method": "POST", "merge": True, "body": {"next": "x"}}],
        })

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    with pytest.raises(RuntimeError, match="tecto"):
        c.search_scenes(SQUARE, "2026-08-01", "2026-08-28")


def test_evalscript_declares_the_three_indices():
    for banda in ("B04", "B05", "B08", "B8A", "B11", "dataMask"):
        assert banda in NDVI_NDMI_NDRE
    for saida in ("ndvi", "ndmi", "ndre"):
        assert saida in NDVI_NDMI_NDRE


def test_evalscript_hash_is_stable_and_short():
    h = evalscript_hash()
    assert len(h) == 12 and h == evalscript_hash()


def test_version_is_recorded():
    assert EVALSCRIPT_VERSION.startswith("s2-ndvi-ndmi-ndre-v")


def test_statistics_rejects_geometry_in_degrees():
    """Coordenadas em graus na Statistical API fazem o Copernicus ler resx:10 como
    10 GRAUS por pixel. Ja aconteceu uma vez; a segunda e apanhada aqui."""
    c = CDSEClient("id", "segredo", transport=_transport(lambda r: httpx.Response(200, json={})))
    graus = {"type": "Polygon", "coordinates": [[
        [-9.2547, 39.0261], [-9.2258, 39.0261], [-9.2258, 39.0485], [-9.2547, 39.0261]]]}
    with pytest.raises(ValueError, match="UTM"):
        c.statistics(graus, "2026-08-01", "2026-08-28", NDVI_NDMI_NDRE)


def test_statistics_returns_one_entry_per_valid_acquisition():
    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        return httpx.Response(200, json={"data": [
            {"interval": {"from": "2026-08-21T00:00:00Z"}, "outputs": {
                "ndvi": {"bands": {"B0": {"stats": {"mean": 0.464, "sampleCount": 62750,
                                                    "noDataCount": 0}}}},
                "ndmi": {"bands": {"B0": {"stats": {"mean": 0.030, "sampleCount": 62750,
                                                    "noDataCount": 0}}}},
                "ndre": {"bands": {"B0": {"stats": {"mean": 0.326, "sampleCount": 62750,
                                                    "noDataCount": 0}}}}}},
            {"interval": {"from": "2026-08-22T00:00:00Z"}, "outputs": {}},
        ]})

    c = CDSEClient("id", "segredo", transport=_transport(handler))
    utm = {"type": "Polygon", "coordinates": [[
        [478000.0, 4321000.0], [480500.0, 4321000.0], [480500.0, 4323500.0],
        [478000.0, 4323500.0], [478000.0, 4321000.0]]]}
    linhas = c.statistics(utm, "2026-08-01", "2026-08-28", NDVI_NDMI_NDRE)
    assert len(linhas) == 1                       # a entrada sem outputs e descartada
    assert linhas[0]["ndvi"] == 0.464
    assert linhas[0]["valid_pixels"] == 62750
    assert linhas[0]["date"] == "2026-08-21"
