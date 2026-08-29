"""Testes do cliente do Climate Data Store. Nenhum toca a rede.

O ciclo assincrono de jobs e servido por httpx.MockTransport; o NetCDF e
gerado com a mesma biblioteca que o codigo usa para o ler, em tmp_path, em
vez de descarregar um ficheiro real do CDS.
"""

import json
import pathlib
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
    ler_serie_netcdf,
)
from resoiltwin.weather.metrics import WeatherMetric

API = "https://cds.climate.copernicus.eu/api"

# caixa medida a 29/08/2026: ~3 km, devolveu MultiAdaptorNoDataError
CAIXA_PEQUENA = [39.05, -9.26, 39.02, -9.22]
# caixa medida a 29/08/2026: ~40 km, o pedido correu ate successful
CAIXA_GRANDE = [39.24, -9.44, 38.84, -9.04]

# ponto canonico do sitio de Turcifal, o mesmo de tests/test_geo.py
TURCIFAL_LAT, TURCIFAL_LON = 39.037317, -9.240247

_DB_URL = "postgresql+psycopg://test:test@localhost:5432/test"


def _cliente(handler, **kwargs):
    return CDSClient(API, "chave-de-teste", transport=httpx.MockTransport(handler),
                     intervalo_sondagem_s=0.0, **kwargs)


def _escrever_netcdf(caminho, valores, nome="Temperature_Air_2m_Mean_24h", unidades="K",
                     lats=(39.15, 39.05), lons=(-9.35, -9.25)):
    """Ficheiro AgERA5 minimo: uma variavel (time, lat, lon) e as coordenadas.

    `valores` e uma lista por instante, cada uma com os quatro pixeis da
    grelha 2x2, na ordem [(lat0,lon0), (lat0,lon1), (lat1,lon0), (lat1,lon1)].
    Os quatro podem ser bem diferentes de proposito, para que a celula do
    sitio e a media da caixa nunca se possam confundir uma com a outra.
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
    lat[:] = list(lats)
    lon = ds.createVariable("lon", "f8", ("lon",))
    lon[:] = list(lons)
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


@pytest.mark.timeout(20)
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
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15", ["2m_temperature"])
    assert len(linhas) == 1
    assert linhas[0]["date"] == "2026-07-15"
    assert linhas[0]["metric"] == WeatherMetric.air_temperature
    assert linhas[0]["unit"] == "degC"
    assert linhas[0]["value"] == pytest.approx(27.0, abs=0.01)


def test_agera5_daily_takes_the_cell_of_the_site_not_the_mean_of_the_box(tmp_path):
    """A caixa e alargada por imposicao da API; o valor e de UMA celula.

    Os quatro pixeis sao propositadamente muito diferentes: a media da caixa
    da 22,0 degC e a celula de Turcifal da 37,0 degC. Se algum dia alguem
    voltar a mediar a caixa, a diferenca e de 15 graus, nao de arredondamento.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-15", ["2m_temperature"])
    media_da_caixa = (280.15 + 290.15 + 300.15 + 310.15) / 4 - 273.15
    assert linhas[0]["value"] == pytest.approx(37.0, abs=0.01)
    assert linhas[0]["value"] != pytest.approx(media_da_caixa, abs=0.5)


def test_agera5_daily_reports_the_chosen_cell_not_the_box_centre(tmp_path):
    """cell_lat/cell_lon tem de ser a celula lida, senao o cell_size_deg mente."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-15", ["2m_temperature"])
    assert linhas[0]["cell_lat"] == pytest.approx(39.05, abs=1e-9)
    assert linhas[0]["cell_lon"] == pytest.approx(-9.25, abs=1e-9)
    # centro da grelha do ficheiro (39.10, -9.30) e centro da caixa pedida
    assert linhas[0]["cell_lat"] != pytest.approx(39.10, abs=1e-6)
    centro_caixa = (CAIXA_GRANDE[0] + CAIXA_GRANDE[2]) / 2
    assert linhas[0]["cell_lat"] != pytest.approx(centro_caixa, abs=1e-6)
    # e a celula fica a menos de meia resolucao do sitio
    assert abs(linhas[0]["cell_lat"] - TURCIFAL_LAT) <= 0.05 + 1e-9
    assert abs(linhas[0]["cell_lon"] - TURCIFAL_LON) <= 0.05 + 1e-9


def test_agera5_daily_reads_a_zipped_download(tmp_path):
    """O CDS entrega alguns pedidos em zip; um .nc la dentro tem de ser lido."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    zip_path = tmp_path / "t.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.write(nc, arcname="t.nc")
    c = _cliente(_ciclo_de_job(zip_path.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15", ["2m_temperature"])
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
    c.agera5_diario(CAIXA_PEQUENA, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15", ["2m_temperature"])
    esperada, _ = expandir_area(CAIXA_PEQUENA)
    assert corpos[0]["inputs"]["area"] == esperada
    assert corpos[0]["inputs"]["area"] != CAIXA_PEQUENA
    assert "time" not in corpos[0]["inputs"]


def test_agera5_daily_reports_the_box_actually_requested(tmp_path):
    """Quem grava a proveniencia tem de gravar a caixa alargada, nao a pedida."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_PEQUENA, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15", ["2m_temperature"])
    esperada, _ = expandir_area(CAIXA_PEQUENA)
    assert linhas[0]["area_requested"] == esperada
    assert linhas[0]["area_requested"] != CAIXA_PEQUENA
    assert linhas[0]["area_original"] == CAIXA_PEQUENA
    assert linhas[0]["area_expanded"] is True


def test_agera5_daily_records_that_a_large_box_was_not_widened(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15, 300.15, 300.15, 300.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15", ["2m_temperature"])
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
    c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-30", "2026-08-02", ["2m_temperature"])
    assert [(x["year"], x["month"]) for x in corpos] == [("2026", "07"), ("2026", "08")]
    assert corpos[0]["day"] == ["30", "31"]
    assert corpos[1]["day"] == ["01", "02"]


def test_agera5_daily_refuses_an_unsupported_variable(tmp_path):
    c = _cliente(_ciclo_de_job(b""))
    with pytest.raises(ValueError, match="2m_temperature"):
        c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15", ["temperatura_marciana"])


def test_agera5_daily_refuses_an_inverted_date_range(tmp_path):
    c = _cliente(_ciclo_de_job(b""))
    with pytest.raises(ValueError, match="date_from"):
        c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-01", ["2m_temperature"])


# -------------------------------------------------- escolha da celula (ler_serie_netcdf)


def test_the_cell_is_the_nearest_grid_node_to_the_site(tmp_path):
    """Cada lado de uma fronteira de celulas escolhe o no do seu lado."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    # fronteira entre lat 39.15 e lat 39.05 fica em 39.10
    acima, _, _ = ler_serie_netcdf(nc, 39.1001, -9.25)
    abaixo, _, _ = ler_serie_netcdf(nc, 39.0999, -9.25)
    assert acima[0][1] == pytest.approx(290.15, abs=0.01)     # celula de lat 39.15
    assert abaixo[0][1] == pytest.approx(310.15, abs=0.01)    # celula de lat 39.05


def test_a_site_exactly_on_the_boundary_is_deterministic(tmp_path):
    """Empate exacto: escolhe sempre a mesma celula, nao uma a cada corrida.

    A grelha aqui e 39.25/39.00 com o sitio em 39.125 de proposito: sao
    numeros exactos em binario, portanto as duas distancias sao mesmo iguais
    (0,125) e o desempate e mesmo exercido. Com a grelha 39.15/39.05 e o
    sitio em 39.10 -- que parece o mesmo teste -- as distancias diferem na
    15a casa decimal, nao ha empate nenhum e o teste passaria por acidente,
    qualquer que fosse a regra de desempate.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]],
                          lats=(39.25, 39.00), lons=(-9.25, -9.00))
    assert abs(39.25 - 39.125) == abs(39.125 - 39.00)          # o empate e exacto
    escolhas = {ler_serie_netcdf(nc, 39.125, -9.25)[1] for _ in range(5)}
    assert escolhas == {39.25}                                 # indice mais baixo desempata
    serie, _, _ = ler_serie_netcdf(nc, 39.125, -9.25)
    assert serie[0][1] == pytest.approx(280.15, abs=0.01)      # a celula do indice 0


def test_the_returned_coordinates_are_the_cell_not_the_grid_centre(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    serie, cell_lat, cell_lon = ler_serie_netcdf(nc, TURCIFAL_LAT, TURCIFAL_LON)
    assert (cell_lat, cell_lon) == (39.05, -9.25)
    assert serie[0][1] == pytest.approx(310.15, abs=0.01)


def test_a_file_that_does_not_cover_the_site_is_refused(tmp_path):
    """Ler a celula da borda seria dar um valor de outro sitio com ar de local."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    with pytest.raises(RuntimeError, match="passo de grelha|nao cobre o sitio"):
        ler_serie_netcdf(nc, 41.15, -9.25)


def test_a_site_inside_the_widened_box_but_outside_the_aoi_is_refused(tmp_path):
    """O alargamento cresce ~0,2 graus por lado: validar contra ele deixava
    passar um sitio a ~20 km fora da propria AOI, que so por acaso cai dentro
    da caixa que se pediu ao CDS por imposicao da grelha."""
    caixa, _ = expandir_area(CAIXA_PEQUENA)
    fora_da_aoi = (39.20, -9.30)
    assert caixa[2] <= fora_da_aoi[0] <= caixa[0]          # esta dentro da caixa alargada
    assert not (CAIXA_PEQUENA[2] <= fora_da_aoi[0] <= CAIXA_PEQUENA[0])   # e fora da AOI
    c = _cliente(_ciclo_de_job(b""))
    with pytest.raises(ValueError, match="fora da AOI"):
        c.agera5_diario(CAIXA_PEQUENA, *fora_da_aoi, "2026-07-15", "2026-07-15",
                        ["2m_temperature"])


def test_agera5_daily_refuses_a_site_outside_the_requested_box(tmp_path):
    c = _cliente(_ciclo_de_job(b""))
    with pytest.raises(ValueError, match="fora da AOI"):
        c.agera5_diario(CAIXA_GRANDE, 41.15, -8.61, "2026-07-15", "2026-07-15", ["2m_temperature"])


# ------------------------------------------- respostas malformadas (o erro a tratar o erro)


JSON = {"content-type": "application/json"}

# atencao: httpx.Response(500, json=None) manda o corpo VAZIO, nao "null" --
# a primeira versao deste teste passava pelo ramo do corpo vazio e nunca
# chegava a exercer o `null`. O corpo tem de ir em bruto.
@pytest.mark.parametrize("corpo", [
    pytest.param({"content": b"null", "headers": JSON}, id="500 com null"),
    pytest.param({"content": b'[{"detail": "x"}]', "headers": JSON}, id="500 com uma lista"),
])
def test_a_malformed_error_body_is_reported_not_crashed(corpo):
    """`null` e listas sao JSON valido: o `.get()` directo rebentava com AttributeError."""
    def handler(request):
        return httpx.Response(500, **corpo)

    with pytest.raises(RuntimeError) as erro:
        _cliente(handler).submit("sis-agrometeorological-indicators", {})
    assert "500" in str(erro.value)
    assert not isinstance(erro.value, AttributeError)


def test_html_from_a_proxy_on_a_2xx_submit_is_reported_not_crashed():
    """Um 201 com HTML de proxy fazia `r.json()` levantar JSONDecodeError."""
    def handler(request):
        return httpx.Response(201, text="<html><body>502 Bad Gateway</body></html>")

    with pytest.raises(RuntimeError, match="jobID"):
        _cliente(handler).submit("sis-agrometeorological-indicators", {})


def test_html_in_the_job_status_is_reported_not_crashed():
    """Um 200 com HTML no estado nao pode rebentar nem ser sondado ate ao tecto."""
    def handler(request):
        return httpx.Response(200, text="<html>manutencao</html>")

    with pytest.raises(RuntimeError) as erro:
        _cliente(handler).wait("job-1", timeout_s=30.0)
    assert "job-1" in str(erro.value)
    assert "status" in str(erro.value)


def test_a_failed_job_with_a_null_results_body_still_raises_the_failure():
    """O pior dos quatro: perder a razao da falha exactamente quando ela faz falta."""
    def handler(request):
        if str(request.url).endswith("/results"):
            return httpx.Response(500, content=b"null", headers=JSON)
        return httpx.Response(200, json={"status": "failed"})

    with pytest.raises(RuntimeError) as erro:
        _cliente(handler).wait("job-1", timeout_s=30.0)
    assert "job-1" in str(erro.value)
    assert "failed" in str(erro.value)


# ------------------------------------------------- cobertura da grelha: meio passo


def test_a_site_beyond_half_a_step_from_the_nearest_node_is_refused(tmp_path):
    """0,6 passos: o no mais proximo nao pode conter o sitio, logo nao serve.

    Antes o criterio era um passo INTEIRO, e um sitio a ~11 km recebia a
    celula da borda em silencio. Este caso e o par do de baixo: 0,6 e 0,4 do
    passo, um de cada lado do criterio -- sem eles, afrouxar a guarda para
    tres passos nao partia teste nenhum.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    with pytest.raises(RuntimeError, match="meio passo"):
        ler_serie_netcdf(nc, 39.21, -9.25)          # 0,06 graus = 0,6 passos de 0,1


def test_a_site_within_half_a_step_is_accepted(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    serie, cell_lat, _ = ler_serie_netcdf(nc, 39.19, -9.25)   # 0,04 graus = 0,4 passos
    assert cell_lat == pytest.approx(39.15, abs=1e-9)
    assert serie[0][1] == pytest.approx(290.15, abs=0.01)


# ------------------------------------------------- conversoes das outras variaveis


def test_solar_radiation_is_converted_from_joules_per_day_to_watts(tmp_path):
    """27 MJ/m2/dia sao 312,5 W/m2. Sem dividir, a linha publica 27.000.000."""
    nc = _escrever_netcdf(tmp_path / "r.nc", [[27_000_000.0] * 4],
                          nome="Solar_Radiation_Flux", unidades="J m-2 day-1")
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-15", ["solar_radiation_flux"])
    assert linhas[0]["metric"] == WeatherMetric.solar_radiation
    assert linhas[0]["unit"] == "W/m2"
    assert linhas[0]["value"] == pytest.approx(312.5, abs=0.01)


def test_precipitation_keeps_the_millimetres_it_already_has(tmp_path):
    nc = _escrever_netcdf(tmp_path / "p.nc", [[3.5] * 4],
                          nome="Precipitation_Flux", unidades="mm d-1")
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-15", ["precipitation_flux"])
    assert linhas[0]["metric"] == WeatherMetric.precipitation
    assert linhas[0]["unit"] == "mm"
    assert linhas[0]["value"] == pytest.approx(3.5, abs=0.001)


# --------------------------------------------------------- credenciais e partilha


def test_a_client_without_credentials_fails_saying_what_is_missing():
    """Sem isto, um .env sem CDS_API_URL dava AttributeError no rstrip("/")."""
    with pytest.raises(ValueError, match="CDS_API_URL"):
        CDSClient(None, "chave")
    with pytest.raises(ValueError, match="CDS_API_KEY"):
        CDSClient(API, "")


def test_env_example_declares_the_cds_credentials():
    """Quem seguir o `cp .env.example .env` tem de ficar com as duas variaveis."""
    texto = (pathlib.Path(__file__).resolve().parent.parent / ".env.example").read_text()
    assert "CDS_API_URL=" in texto
    assert "CDS_API_KEY=" in texto
    for linha in texto.splitlines():
        if linha.startswith("CDS_API_KEY="):
            assert linha.strip() == "CDS_API_KEY=", "nenhum segredo no .env.example"


def test_each_row_carries_its_own_copy_of_the_box(tmp_path):
    """Duas linhas nao podem partilhar a mesma lista: quem escrever numa altera as outras."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15] * 4, [301.15] * 4])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_PEQUENA, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-16", ["2m_temperature"])
    assert len(linhas) == 2
    assert linhas[0]["area_requested"] is not linhas[1]["area_requested"]
    linhas[0]["area_requested"][0] = 0.0
    assert linhas[1]["area_requested"][0] != 0.0


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
