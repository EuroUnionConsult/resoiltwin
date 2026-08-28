def _seed_site(client):
    client.post("/api/v1/sites", json={"code": "EUC-OBS-01", "name": "Turcifal", "crop_type": "citrus"})
    client.post("/api/v1/sites/EUC-OBS-01/plots", json={
        "code": "OBS-CANOPY", "name": "Sob copa", "purpose": "canopy"})
    client.post("/api/v1/sites/EUC-OBS-01/plots", json={
        "code": "OBS-GRASS", "name": "Relvado", "purpose": "open_grass"})


def test_observation_requires_source_type(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-22T14:37:00+01:00",
        "metric": "air_temperature", "value_numeric": 30.0, "unit": "degC",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_ambiguous_observed_source_type_is_rejected(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-22T14:37:00+01:00",
        "metric": "air_temperature", "value_numeric": 30.0, "unit": "degC",
        "source_type": "observed", "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_censored_reading_round_trips(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-GRASS",
        "observed_at": "2026-08-22T11:00:00+01:00",
        "metric": "light_screening", "value_numeric": 2000.0,
        "value_qualifier": "censored_high", "unit": "instrument_scale",
        "source_type": "observed_screening", "quality_flag": "saturated_high",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 201
    assert r.json()["value_qualifier"] == "censored_high"


def test_timeseries_carries_provenance_per_point(client):
    _seed_site(client)
    for hour, value in [(8, 24.0), (14, 30.0)]:
        client.post("/api/v1/observations", json={
            "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
            "observed_at": f"2026-08-23T{hour:02d}:00:00+01:00",
            "metric": "air_temperature", "value_numeric": value, "unit": "degC",
            "source_type": "observed_screening", "quality_flag": "valid",
            "processing_version": "field-campaign-v1",
        })
    r = client.get("/api/v1/sites/EUC-OBS-01/timeseries?metric=air_temperature")
    assert r.status_code == 200
    points = r.json()["points"]
    assert len(points) == 2
    assert all(p["source_type"] == "observed_screening" for p in points)
    assert points[0]["observed_at"] < points[1]["observed_at"]


def test_timeseries_filters_by_plot(client):
    _seed_site(client)
    for plot, value in [("OBS-CANOPY", 6.0), ("OBS-GRASS", 8.0)]:
        client.post("/api/v1/observations", json={
            "site_code": "EUC-OBS-01", "plot_code": plot,
            "observed_at": "2026-08-24T16:00:00+01:00",
            "metric": "soil_moisture_screening", "value_numeric": value,
            "unit": "instrument_scale_0_10", "source_type": "observed_screening",
            "quality_flag": "repeated", "processing_version": "field-campaign-v1",
        })
    r = client.get("/api/v1/sites/EUC-OBS-01/timeseries?metric=soil_moisture_screening&plot=OBS-CANOPY")
    points = r.json()["points"]
    assert len(points) == 1
    assert points[0]["value"] == 6.0


def test_duplicate_observation_returns_409(client):
    _seed_site(client)
    payload = {
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-22T18:05:00+01:00",
        "metric": "relative_humidity", "value_numeric": 60.0, "unit": "percent",
        "source_type": "observed_screening", "quality_flag": "valid",
        "processing_version": "field-campaign-v1",
    }
    assert client.post("/api/v1/observations", json=payload).status_code == 201
    assert client.post("/api/v1/observations", json=payload).status_code == 409


# ronda 2: espelhar ck_value_qualifier_matches_value_fields no pydantic para
# que estes 4 casos levem 422 e nunca cheguem ao CHECK da base de dados.


def test_censored_reading_rejects_stray_range_bounds(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-25T10:00:00+01:00",
        "metric": "light_screening", "value_numeric": 2000.0,
        "value_min": 1900.0, "value_max": 2100.0,
        "value_qualifier": "censored_high", "unit": "instrument_scale",
        "source_type": "observed_screening", "quality_flag": "saturated_high",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_censored_reading_requires_value_numeric_even_with_text(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-25T11:00:00+01:00",
        "metric": "light_screening", "value_text": "off-scale",
        "value_qualifier": "censored_high", "unit": "instrument_scale",
        "source_type": "observed_screening", "quality_flag": "saturated_high",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_range_reading_rejects_stray_value_numeric(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-25T12:00:00+01:00",
        "metric": "soil_ph_screening", "value_numeric": 6.5,
        "value_min": 6.0, "value_max": 7.0,
        "value_qualifier": "range", "unit": "ph_unit",
        "source_type": "observed_screening", "quality_flag": "range_value",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_exact_reading_rejects_stray_range_bounds(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-25T13:00:00+01:00",
        "metric": "air_temperature", "value_numeric": 28.0,
        "value_min": 27.0, "value_max": 29.0, "unit": "degC",
        "source_type": "observed_screening", "quality_flag": "valid",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


# ronda 3: a marca de censura tem de estar nos dois campos, e os campos de
# texto longos tem de dar 422 e nao um DataError opaco a sair como 500.


def test_saturated_flag_requires_a_censored_qualifier(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-GRASS",
        "observed_at": "2026-08-26T11:00:00+01:00",
        "metric": "light_screening", "value_numeric": 2000.0,
        "value_qualifier": "exact", "unit": "instrument_scale",
        "source_type": "observed_screening", "quality_flag": "saturated_high",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_range_flag_requires_a_range_qualifier(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-26T12:00:00+01:00",
        "metric": "ph_screening", "value_numeric": 7.5,
        "value_qualifier": "exact", "unit": "pH",
        "source_type": "observed_screening", "quality_flag": "range_value",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_overlong_source_collection_is_rejected_with_422(client):
    """source_collection e String(128) na base: sem max_length no pydantic o
    postgres levantava DataError, que nao e IntegrityError e escapa ao except
    da rota -- o cliente recebia 500. E o campo onde vao os identificadores de
    produto de satelite, que sao compridos."""
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-26T13:00:00+01:00",
        "metric": "ndvi", "value_numeric": 0.42, "unit": "index",
        "source_type": "satellite_observed", "quality_flag": "valid",
        "source_collection": "C" * 129, "processing_version": "s2-l2a-v1",
    })
    assert r.status_code == 422


def test_overlong_method_is_rejected_with_422(client):
    _seed_site(client)
    r = client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-26T14:00:00+01:00",
        "metric": "air_temperature", "value_numeric": 21.0, "unit": "degC",
        "source_type": "observed_screening", "quality_flag": "valid",
        "method": "m" * 161, "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 422


def test_genuine_duplicate_still_returns_409_after_validation_fix(client):
    _seed_site(client)
    payload = {
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-25T14:00:00+01:00",
        "metric": "wind_speed", "value_numeric": 3.2, "unit": "m_s",
        "source_type": "observed_screening", "quality_flag": "valid",
        "processing_version": "field-campaign-v1",
    }
    assert client.post("/api/v1/observations", json=payload).status_code == 201
    assert client.post("/api/v1/observations", json=payload).status_code == 409


# ronda 4: os tres achados desta ronda sao da mesma familia -- guardas que
# pareciam impostas e nao mordiam no caminho que o codigo de producao usa. Os
# testes abaixo correm todos contra `prod_client`, que devolve 500 em vez de
# levantar a excepcao, para que a diferenca entre "recusado" e "explodiu"
# apareca no assert e nao num traceback.


def test_derived_observation_without_evidence_is_rejected_with_422(prod_client):
    """N1, pelo caminho real: a rota nao tem campo `derived_from`, portanto por
    aqui a unica forma de documentar as entradas de um derivado e `evidence`.

    Omitir o campo no JSON faz o pydantic por `None`, e o `None` chega a coluna
    JSONB -- que era exactamente onde a guarda deixava de morder, porque o
    SQLAlchemy o gravava como o literal JSON `null`. Os dois testes de modelo
    que cobriam esta constraint passavam so por OMITIREM o kwarg no construtor
    do ORM, caminho que nem o seed nem esta rota usam.
    """
    _seed_site(prod_client)
    r = prod_client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-27T09:00:00+01:00",
        "metric": "vpd", "value_numeric": 2.97, "unit": "kPa",
        "source_type": "derived", "quality_flag": "valid",
        "method": "tetens_saturation_vapour_pressure",
        "processing_version": "vpd-tetens-v1",
    })
    assert r.status_code == 422


def test_derived_observation_with_evidence_is_accepted(prod_client):
    """O caso de controlo: com as entradas documentadas, a mesma linha entra."""
    _seed_site(prod_client)
    r = prod_client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-27T09:30:00+01:00",
        "metric": "vpd", "value_numeric": 2.97, "unit": "kPa",
        "source_type": "derived", "quality_flag": "valid",
        "method": "tetens_saturation_vapour_pressure",
        "evidence": {"inputs": {"air_temperature_degC": 30.0, "relative_humidity_pct": 30.0}},
        "processing_version": "vpd-tetens-v1",
    })
    assert r.status_code == 201


def test_derived_observation_without_method_is_rejected_with_422(prod_client):
    """N2: antes desta ronda dava 201; depois da ronda anterior passou a dar 500.
    Nenhum dos dois esta certo -- o payload e incoerente e isso e 422."""
    _seed_site(prod_client)
    r = prod_client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-27T10:00:00+01:00",
        "metric": "vpd", "value_numeric": 2.97, "unit": "kPa",
        "source_type": "derived", "quality_flag": "valid",
        "evidence": {"inputs": {"air_temperature_degC": 30.0}},
        "processing_version": "vpd-tetens-v1",
    })
    assert r.status_code == 422


def test_whitespace_processing_version_is_rejected_with_422(prod_client):
    """N2: `min_length=1` do pydantic aceita tres espacos sem esforco, e a
    string batia depois em ck_observation_processing_version_not_blank."""
    _seed_site(prod_client)
    r = prod_client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-CANOPY",
        "observed_at": "2026-08-27T11:00:00+01:00",
        "metric": "air_temperature", "value_numeric": 22.0, "unit": "degC",
        "source_type": "observed_screening", "quality_flag": "valid",
        "processing_version": "   ",
    })
    assert r.status_code == 422


def test_censored_reading_accepts_an_unassessed_quality_flag(prod_client):
    """N3: `unchecked` e o valor por omissao do proprio ObservationCreate. Com
    o bicondicional, um job que gravasse um valor censurado sem ter avaliado a
    qualidade primeiro era impossivel -- e e isso que a fase seguinte faz."""
    _seed_site(prod_client)
    r = prod_client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-GRASS",
        "observed_at": "2026-08-27T12:00:00+01:00",
        "metric": "light_screening", "value_numeric": 2000.0,
        "value_qualifier": "censored_high", "unit": "instrument_scale",
        "source_type": "observed_screening", "quality_flag": "unchecked",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 201
    assert r.json()["quality_flag"] == "unchecked"
    assert r.json()["value_qualifier"] == "censored_high"


def test_censored_reading_accepts_a_suspect_quality_flag(prod_client):
    """O mesmo do outro lado da avaliacao: duvidar da leitura nao apaga o facto
    de o valor ser um limite e nao uma medida."""
    _seed_site(prod_client)
    r = prod_client.post("/api/v1/observations", json={
        "site_code": "EUC-OBS-01", "plot_code": "OBS-GRASS",
        "observed_at": "2026-08-27T13:00:00+01:00",
        "metric": "light_screening", "value_numeric": 2000.0,
        "value_qualifier": "censored_high", "unit": "instrument_scale",
        "source_type": "observed_screening", "quality_flag": "suspect",
        "processing_version": "field-campaign-v1",
    })
    assert r.status_code == 201
    assert r.json()["quality_flag"] == "suspect"
