import httpx
import pytest

from resoiltwin.eo.cdse import CDSEClient

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
