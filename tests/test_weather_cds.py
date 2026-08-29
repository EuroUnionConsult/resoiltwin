"""Testes do cliente do Climate Data Store. Nenhum toca a rede.

O ciclo assincrono de jobs e servido por httpx.MockTransport; o NetCDF e
gerado com a mesma biblioteca que o codigo usa para o ler, em tmp_path, em
vez de descarregar um ficheiro real do CDS.
"""

import json
import zipfile

import httpx
import pytest
from netCDF4 import Dataset

from resoiltwin.config import Settings
from resoiltwin.weather.cds import (
    LADO_MINIMO_GRAUS,
    CDSClient,
    expandir_area,
    inputs_agera5,
    inputs_era5_land,
)
from resoiltwin.weather.metrics import WeatherMetric

API = "https://cds.climate.copernicus.eu/api"

# caixa medida a 29/08/2026: ~3 km, devolveu MultiAdaptorNoDataError
CAIXA_PEQUENA = [39.05, -9.26, 39.02, -9.22]
# caixa medida a 29/08/2026: ~40 km, o pedido correu ate successful
CAIXA_GRANDE = [39.24, -9.44, 38.84, -9.04]

_DB_URL = "postgresql+psycopg://test:test@localhost:5432/test"


def _cliente(handler, **kwargs):
    return CDSClient(API, "chave-de-teste", transport=httpx.MockTransport(handler),
                     intervalo_sondagem_s=0.0, **kwargs)


def _escrever_netcdf(caminho, valores, nome="Temperature_Air_2m_Mean_24h", unidades="K"):
    """Ficheiro AgERA5 minimo: uma variavel (time, lat, lon) e as coordenadas.

    `valores` e uma lista por instante, cada uma com os quatro pixeis da
    grelha 2x2 -- assim a media espacial tem mesmo alguma coisa que media.
    """
    ds = Dataset(caminho, "w", format="NETCDF4")
    ds.createDimension("time", len(valores))
    ds.createDimension("lat", 2)
    ds.createDimension("lon", 2)
    t = ds.createVariable("time", "f8", ("time",))
    t.units = "days since 2026-07-01 00:00:00"
    t.calendar = "proleptic_gregorian"
    t[:] = list(range(14, 14 + len(valores)))          # 2026-07-15 em diante
    lat = ds.createVariable("lat", "f8", ("lat",))
    lat[:] = [39.15, 39.05]
    lon = ds.createVariable("lon", "f8", ("lon",))
    lon[:] = [-9.35, -9.25]
    v = ds.createVariable(nome, "f4", ("time", "lat", "lon"))
    v.units = unidades
    for i, quatro in enumerate(valores):
        v[i, :, :] = [[quatro[0], quatro[1]], [quatro[2], quatro[3]]]
    ds.close()
    return caminho


def _ciclo_de_job(bytes_ficheiro, estados=("successful",)):
    """Handler que serve submit -> jobs -> results -> ficheiro."""
    contador = {"jobs": 0}

    def handler(request):
        url = str(request.url)
        if url.endswith("/execution"):
            return httpx.Response(201, json={"jobID": "job-1", "status": "accepted"})
        if url.endswith("/results"):
            return httpx.Response(200, json={"asset": {"value": {
                "href": "https://object-store.example/job-1.nc"}}})
        if "/jobs/" in url:
            i = min(contador["jobs"], len(estados) - 1)
            contador["jobs"] += 1
            return httpx.Response(200, json={"jobID": "job-1", "status": estados[i]})
        return httpx.Response(200, content=bytes_ficheiro)

    return handler


# --------------------------------------------------------------------- submit


def test_submit_returns_the_job_id():
    def handler(request):
        return httpx.Response(201, json={"jobID": "abc-123", "status": "accepted"})

    c = _cliente(handler)
    assert c.submit("sis-agrometeorological-indicators", {"variable": ["2m_temperature"]}) == "abc-123"


def test_submit_authenticates_with_the_private_token_header():
    """O CDS novo autentica por PRIVATE-TOKEN, nao por Bearer nem por Basic."""
    visto = {}

    def handler(request):
        visto["auth"] = request.headers.get("PRIVATE-TOKEN")
        visto["url"] = str(request.url)
        return httpx.Response(201, json={"jobID": "abc", "status": "accepted"})

    _cliente(handler).submit("sis-agrometeorological-indicators", {})
    assert visto["auth"] == "chave-de-teste"
    assert visto["url"] == f"{API}/retrieve/v1/processes/sis-agrometeorological-indicators/execution"


def test_submit_with_an_unknown_dataset_fails_legibly():
    """Um dataset inexistente tem de dar a razao do CDS, nao um 404 seco."""
    def handler(request):
        return httpx.Response(404, json={
            "type": "not found", "title": "not found",
            "detail": "process sis-agro-typo not found"})

    with pytest.raises(RuntimeError, match="process sis-agro-typo not found"):
        _cliente(handler).submit("sis-agro-typo", {})


def test_submit_without_a_job_id_is_refused():
    """Uma resposta 2xx sem jobID nao pode passar por submissao bem sucedida."""
    def handler(request):
        return httpx.Response(200, json={"status": "accepted"})

    with pytest.raises(RuntimeError, match="jobID"):
        _cliente(handler).submit("sis-agrometeorological-indicators", {})


# ----------------------------------------------------------------------- wait


def test_wait_polls_until_the_job_is_successful():
    estados = ["accepted", "running", "successful"]
    contador = {"n": 0}

    def handler(request):
        i = min(contador["n"], len(estados) - 1)
        contador["n"] += 1
        return httpx.Response(200, json={"status": estados[i]})

    assert _cliente(handler).wait("job-1", timeout_s=30.0) == "successful"
    assert contador["n"] == 3          # nao pode devolver successful sem sondar


def test_a_failed_job_raises_with_the_cds_traceback():
    """A razao esta em /results, no campo traceback -- nao em /jobs/{id}."""
    tb = ("Traceback (most recent call last):\n  ...\n"
          "MultiAdaptorNoDataError: no data available within your requested subset")

    def handler(request):
        if str(request.url).endswith("/results"):
            return httpx.Response(400, json={"type": "job results failed",
                                             "title": "job failed", "traceback": tb})
        return httpx.Response(200, json={"status": "failed"})

    with pytest.raises(RuntimeError) as erro:
        _cliente(handler).wait("job-1", timeout_s=30.0)
    assert "MultiAdaptorNoDataError" in str(erro.value)
    assert "job-1" in str(erro.value)
    assert not isinstance(erro.value, httpx.HTTPStatusError)


def test_wait_respects_the_ceiling_and_names_the_pending_job():
    def handler(request):
        return httpx.Response(200, json={"status": "running"})

    with pytest.raises(TimeoutError) as erro:
        _cliente(handler).wait("job-pendente", timeout_s=0.0)
    assert "job-pendente" in str(erro.value)
    assert "running" in str(erro.value)


# ------------------------------------------------------------------- download


def test_download_writes_the_asset_to_the_given_path(tmp_path):
    def handler(request):
        if str(request.url).endswith("/results"):
            return httpx.Response(200, json={"asset": {"value": {
                "href": "https://object-store.example/job-1.nc"}}})
        return httpx.Response(200, content=b"CDF-bytes")

    destino = tmp_path / "saida.nc"
    caminho = _cliente(handler).download("job-1", destino)
    assert caminho == destino
    assert destino.read_bytes() == b"CDF-bytes"


def test_download_does_not_send_the_api_key_to_the_asset_host(tmp_path):
    """O href aponta para o object store, nao para o CDS: a chave nao vai la."""
    visto = {}

    def handler(request):
        if str(request.url).endswith("/results"):
            return httpx.Response(200, json={"asset": {"value": {
                "href": "https://object-store.example/job-1.nc"}}})
        visto["auth"] = request.headers.get("PRIVATE-TOKEN")
        return httpx.Response(200, content=b"x")

    _cliente(handler).download("job-1", tmp_path / "a.nc")
    assert visto["auth"] is None


# ----------------------------------------------------------- caixa demasiado pequena


def test_a_small_box_is_widened_to_the_safe_minimum():
    """Medido a 29/08/2026: ~3 km da MultiAdaptorNoDataError, ~40 km funciona."""
    caixa, alargada = expandir_area(CAIXA_PEQUENA)
    assert alargada is True
    norte, oeste, sul, este = caixa
    assert norte - sul == pytest.approx(LADO_MINIMO_GRAUS, abs=1e-6)
    assert este - oeste == pytest.approx(LADO_MINIMO_GRAUS, abs=1e-6)
    # continua centrada na caixa original
    assert (norte + sul) / 2 == pytest.approx((39.05 + 39.02) / 2, abs=1e-4)
    assert (este + oeste) / 2 == pytest.approx((-9.26 + -9.22) / 2, abs=1e-4)


def test_a_box_already_large_enough_is_left_alone():
    caixa, alargada = expandir_area(CAIXA_GRANDE)
    assert alargada is False
    assert caixa == CAIXA_GRANDE


def test_an_upside_down_box_is_refused():
    with pytest.raises(ValueError, match="Norte"):
        expandir_area([38.84, -9.44, 39.24, -9.04])


# -------------------------------------------------------------- corpos de pedido


def test_agera5_body_never_carries_time():
    """Com estatistica diaria, enviar `time` da 'not a valid combination of values'."""
    corpo = inputs_agera5("2m_temperature", "24_hour_mean", "2026", "07", ["15"], CAIXA_GRANDE)
    assert "time" not in corpo
    assert corpo["variable"] == ["2m_temperature"]
    assert corpo["statistic"] == ["24_hour_mean"]
    assert corpo["version"] == "2_0"
    assert corpo["area"] == CAIXA_GRANDE       # [Norte, Oeste, Sul, Este]


def test_era5_land_body_carries_both_formats():
    """Sem data_format e download_format o pedido ao ERA5-Land falha."""
    corpo = inputs_era5_land(["total_precipitation"], "2026", "07", ["15"], ["12:00"], CAIXA_GRANDE)
    assert corpo["data_format"] == "netcdf"
    assert corpo["download_format"] == "unarchived"
    assert corpo["time"] == ["12:00"]


# ----------------------------------------------------------------- agera5_diario


def test_agera5_daily_returns_degrees_celsius(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, "2026-07-15", "2026-07-15", ["2m_temperature"])
    assert len(linhas) == 1
    assert linhas[0]["date"] == "2026-07-15"
    assert linhas[0]["metric"] == WeatherMetric.air_temperature
    assert linhas[0]["unit"] == "degC"
    assert linhas[0]["value"] == pytest.approx(27.0, abs=0.01)


def test_agera5_daily_averages_the_cells(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[299.15, 300.15, 301.15, 302.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, "2026-07-15", "2026-07-15", ["2m_temperature"])
    assert linhas[0]["value"] == pytest.approx(27.5, abs=0.01)
    assert linhas[0]["cell_lat"] == pytest.approx(39.10, abs=1e-6)
    assert linhas[0]["cell_lon"] == pytest.approx(-9.30, abs=1e-6)


def test_agera5_daily_reads_a_zipped_download(tmp_path):
    """O CDS entrega alguns pedidos em zip; um .nc la dentro tem de ser lido."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    zip_path = tmp_path / "t.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.write(nc, arcname="t.nc")
    c = _cliente(_ciclo_de_job(zip_path.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, "2026-07-15", "2026-07-15", ["2m_temperature"])
    assert linhas[0]["value"] == pytest.approx(27.0, abs=0.01)


def test_agera5_daily_requests_the_widened_box_not_the_original(tmp_path):
    """Se pedisse a caixa original, o CDS devolvia MultiAdaptorNoDataError."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    corpos = []
    base = _ciclo_de_job(nc.read_bytes())

    def handler(request):
        if str(request.url).endswith("/execution"):
            corpos.append(json.loads(request.content))
        return base(request)

    c = _cliente(handler)
    c.agera5_diario(CAIXA_PEQUENA, "2026-07-15", "2026-07-15", ["2m_temperature"])
    esperada, _ = expandir_area(CAIXA_PEQUENA)
    assert corpos[0]["inputs"]["area"] == esperada
    assert corpos[0]["inputs"]["area"] != CAIXA_PEQUENA
    assert "time" not in corpos[0]["inputs"]


def test_agera5_daily_reports_the_box_actually_requested(tmp_path):
    """Quem grava a proveniencia tem de gravar a caixa alargada, nao a pedida."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_PEQUENA, "2026-07-15", "2026-07-15", ["2m_temperature"])
    esperada, _ = expandir_area(CAIXA_PEQUENA)
    assert linhas[0]["area_requested"] == esperada
    assert linhas[0]["area_requested"] != CAIXA_PEQUENA
    assert linhas[0]["area_original"] == CAIXA_PEQUENA
    assert linhas[0]["area_expanded"] is True


def test_agera5_daily_records_that_a_large_box_was_not_widened(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, "2026-07-15", "2026-07-15", ["2m_temperature"])
    assert linhas[0]["area_expanded"] is False
    assert linhas[0]["area_requested"] == CAIXA_GRANDE


def test_agera5_daily_splits_the_range_by_month(tmp_path):
    """O corpo do CDS leva um mes de cada vez: dois meses sao dois jobs."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    corpos = []
    base = _ciclo_de_job(nc.read_bytes())

    def handler(request):
        if str(request.url).endswith("/execution"):
            corpos.append(json.loads(request.content)["inputs"])
        return base(request)

    c = _cliente(handler)
    c.agera5_diario(CAIXA_GRANDE, "2026-07-30", "2026-08-02", ["2m_temperature"])
    assert [(x["year"], x["month"]) for x in corpos] == [("2026", "07"), ("2026", "08")]
    assert corpos[0]["day"] == ["30", "31"]
    assert corpos[1]["day"] == ["01", "02"]


def test_agera5_daily_refuses_an_unsupported_variable(tmp_path):
    c = _cliente(_ciclo_de_job(b""))
    with pytest.raises(ValueError, match="2m_temperature"):
        c.agera5_diario(CAIXA_GRANDE, "2026-07-15", "2026-07-15", ["temperatura_marciana"])


def test_agera5_daily_refuses_an_inverted_date_range(tmp_path):
    c = _cliente(_ciclo_de_job(b""))
    with pytest.raises(ValueError, match="date_from"):
        c.agera5_diario(CAIXA_GRANDE, "2026-07-15", "2026-07-01", ["2m_temperature"])


# ---------------------------------------------------------------------- config


def test_settings_declare_the_cds_credentials_without_defaults():
    for nome in ("cds_api_url", "cds_api_key"):
        assert Settings.model_fields[nome].default is None


def test_settings_read_the_cds_credentials_from_the_environment(monkeypatch):
    monkeypatch.setenv("CDS_API_URL", "https://exemplo.invalid/api")
    monkeypatch.setenv("CDS_API_KEY", "chave-do-ambiente")
    s = Settings(_env_file=None, database_url=_DB_URL)
    assert s.cds_api_url == "https://exemplo.invalid/api"
    assert s.cds_api_key == "chave-do-ambiente"
