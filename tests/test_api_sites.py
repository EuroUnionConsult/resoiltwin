SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [-9.24034, 39.03725], [-9.24016, 39.03725],
        [-9.24016, 39.03739], [-9.24034, 39.03739], [-9.24034, 39.03725],
    ]],
}


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_read_site(client):
    r = client.post("/api/v1/sites", json={
        "code": "EUC-TUR-01", "name": "Turcifal", "crop_type": "citrus",
    })
    assert r.status_code == 201
    r = client.get("/api/v1/sites/EUC-TUR-01")
    assert r.status_code == 200
    assert r.json()["crop_type"] == "citrus"


def test_duplicate_site_returns_409(client):
    payload = {"code": "EUC-DUP-01", "name": "Duplicado"}
    assert client.post("/api/v1/sites", json=payload).status_code == 201
    assert client.post("/api/v1/sites", json=payload).status_code == 409


def test_unknown_site_returns_404(client):
    assert client.get("/api/v1/sites/NAO-EXISTE").status_code == 404


def test_aoi_is_created_as_draft_with_area(client):
    client.post("/api/v1/sites", json={"code": "EUC-AOI-01", "name": "Teste AOI"})
    r = client.post("/api/v1/sites/EUC-AOI-01/aois", json={
        "code": "EUC-AOI-EO1", "purpose": "earth_observation",
        "geometry": SQUARE, "geometry_provenance": "provisional_pending_kml",
        "geometry_source_note": "Rectangulo por confirmar",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["area_m2"] > 0


def test_provisional_aoi_cannot_be_approved_via_api(client):
    client.post("/api/v1/sites", json={"code": "EUC-AOI-02", "name": "Teste AOI 2"})
    client.post("/api/v1/sites/EUC-AOI-02/aois", json={
        "code": "EUC-AOI-EO2", "purpose": "earth_observation",
        "geometry": SQUARE, "geometry_provenance": "provisional_pending_kml",
    })
    r = client.post("/api/v1/aois/EUC-AOI-EO2/approve", json={"approved_by": "site-manager"})
    assert r.status_code == 409
    assert "provisional" in r.json()["detail"].lower()


def test_documented_aoi_can_be_approved(client):
    client.post("/api/v1/sites", json={"code": "EUC-AOI-03", "name": "Teste AOI 3"})
    client.post("/api/v1/sites/EUC-AOI-03/aois", json={
        "code": "EUC-AOI-EO3", "purpose": "earth_observation",
        "geometry": SQUARE, "geometry_provenance": "documented_exact",
    })
    r = client.post("/api/v1/aois/EUC-AOI-EO3/approve", json={"approved_by": "site-manager"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["approved_by"] == "site-manager"


def test_duplicate_aoi_returns_409(client):
    """O 409 passou a depender do nome do indice unico violado. Se o nome
    estiver errado, um duplicado genuino deixa de dar 409 e sai como 500."""
    client.post("/api/v1/sites", json={"code": "EUC-AOI-05", "name": "Teste AOI 5"})
    payload = {
        "code": "EUC-AOI-EO5", "purpose": "earth_observation",
        "geometry": SQUARE, "geometry_provenance": "documented_exact",
    }
    assert client.post("/api/v1/sites/EUC-AOI-05/aois", json=payload).status_code == 201
    assert client.post("/api/v1/sites/EUC-AOI-05/aois", json=payload).status_code == 409


def test_duplicate_plot_returns_409(client):
    client.post("/api/v1/sites", json={"code": "EUC-PLOT-01", "name": "Teste parcelas"})
    payload = {"code": "PLOT-DUP-01", "name": "Sob copa", "purpose": "canopy"}
    assert client.post("/api/v1/sites/EUC-PLOT-01/plots", json=payload).status_code == 201
    assert client.post("/api/v1/sites/EUC-PLOT-01/plots", json=payload).status_code == 409


def test_rejects_point_geometry(client):
    client.post("/api/v1/sites", json={"code": "EUC-AOI-04", "name": "Teste AOI 4"})
    r = client.post("/api/v1/sites/EUC-AOI-04/aois", json={
        "code": "EUC-AOI-EO4", "purpose": "earth_observation",
        "geometry": {"type": "Point", "coordinates": [-9.24, 39.03]},
        "geometry_provenance": "documented_exact",
    })
    assert r.status_code == 422
