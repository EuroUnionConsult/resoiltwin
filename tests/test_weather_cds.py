"""Testes do cliente do Climate Data Store. Nenhum toca a rede.

O ciclo assincrono de jobs e servido por httpx.MockTransport; o NetCDF e
gerado com a mesma biblioteca que o codigo usa para o ler, em tmp_path, em
vez de descarregar um ficheiro real do CDS.
"""

import json
import math
import pathlib
import warnings
import zipfile

import httpx
import pytest
from netCDF4 import Dataset

from resoiltwin.config import Settings
from resoiltwin.weather.cds import (
    _AGREGACAO_AGERA5,
    _VARIAVEIS_AGERA5,
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

# nome da variavel DENTRO do ficheiro, lido de um AgERA5 real a 30/08/2026
# (final-v2.0.0). Nao e o nome com que se pede ao CDS, que e `2m_temperature`.
VAR_TEMPERATURA = "Temperature_Air_2m_Mean_24h"

# idem, do pedido de `reference_evapotranspiration` submetido a 30/08/2026
# (dia 2026-08-10, mesma area): o zip trouxe
# ReferenceET-PenmanMonteith-FAO56_C3S-glob-agric_AgERA5_20260810_final-v2.0.0...nc
# e la dentro a variavel abaixo, com units "mm d-1".
VAR_ET0 = "ReferenceET_PenmanMonteith_FAO56"

_DB_URL = "postgresql+psycopg://test:test@localhost:5432/test"


def _cliente(handler, **kwargs):
    return CDSClient(API, "chave-de-teste", transport=httpx.MockTransport(handler),
                     intervalo_sondagem_s=0.0, **kwargs)


# marcador de "esta celula nao tem dado" nos `valores` dos ficheiros de teste.
# O `_escrever_netcdf` traduz cada ocorrencia para o `_FillValue` declarado, que
# e como o AgERA5 marca um no sem dados -- e como a netCDF4 o devolve mascarado
# na leitura.
SEM_DADO = None

# o valor de enchimento declarado nos ficheiros que levam SEM_DADO. Nao e
# significativo: qualquer numero serve, desde que seja o `_FillValue`.
ENCHIMENTO = -9999.0


def _escrever_netcdf(caminho, valores, nome=VAR_TEMPERATURA, unidades="K",
                     lats=(39.15, 39.05), lons=(-9.35, -9.25), primeiro_dia=14):
    """Ficheiro AgERA5 minimo: uma variavel (time, lat, lon) e as coordenadas.

    `valores` e uma lista por instante, cada uma com os quatro pixeis da
    grelha 2x2, na ordem [(lat0,lon0), (lat0,lon1), (lat1,lon0), (lat1,lon1)].
    Os quatro podem ser bem diferentes de proposito, para que a celula do
    sitio e a media da caixa nunca se possam confundir uma com a outra.

    Um pixel a `SEM_DADO` sai do ficheiro marcado com o `_FillValue`, que e
    como um produtor marca um no sem dados -- em cima do mar, fora do dominio,
    ou simplesmente por publicar. A netCDF4 devolve-o MASCARADO na leitura, e
    e a partir dai que o defeito que o `_e_sem_dado` fecha era possivel.
    """
    ds = Dataset(caminho, "w", format="NETCDF4")
    ds.createDimension("time", len(valores))
    ds.createDimension("lat", 2)
    ds.createDimension("lon", 2)
    t = ds.createVariable("time", "f8", ("time",))
    t.units = "days since 2026-07-01 00:00:00"
    t.calendar = "proleptic_gregorian"
    # por omissao 2026-07-15 em diante; `primeiro_dia` existe para se poderem
    # escrever varios ficheiros de DIAS diferentes, que e como o AgERA5 entrega
    # um mes: um .nc por dia dentro do mesmo zip.
    t[:] = list(range(primeiro_dia, primeiro_dia + len(valores)))
    lat = ds.createVariable("lat", "f8", ("lat",))
    lat[:] = list(lats)
    lon = ds.createVariable("lon", "f8", ("lon",))
    lon[:] = list(lons)
    ha_buracos = any(pixel is SEM_DADO for quatro in valores for pixel in quatro)
    v = ds.createVariable(nome, "f4", ("time", "lat", "lon"),
                          fill_value=ENCHIMENTO if ha_buracos else None)
    v.units = unidades
    for i, quatro in enumerate(valores):
        q = [ENCHIMENTO if pixel is SEM_DADO else pixel for pixel in quatro]
        v[i, :, :] = [[q[0], q[1]], [q[2], q[3]]]
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


def _zip_de_dias(tmp_path, dias, lats_por_dia=None):
    """Um zip com um .nc por dia, que e como o AgERA5 entrega um mes."""
    caminho = tmp_path / "mes.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for i, dia in enumerate(dias):
            lats = (lats_por_dia or {}).get(i, (39.15, 39.05))
            nc = _escrever_netcdf(tmp_path / f"d{i}.nc", [[280.15, 290.15, 300.15, 310.15]],
                                  lats=lats, primeiro_dia=dia)
            z.write(nc, arcname=f"pasta/{i}/dia.nc")
    return caminho


def test_a_zip_with_one_file_per_day_is_read_to_the_end(tmp_path):
    """Ler so o primeiro membro reduzia a serie a um dia por zip.

    O teste do zip acima embrulha UM ficheiro e prova que o caminho do zip
    abre; nao prova que o zip e lido ate ao fim. A 29/08/2026 essa diferenca
    custou 6 linhas gravadas onde havia 159 para trazer -- um dia por variavel
    e por mes -- com o job a dizer `succeeded`.
    """
    caminho = _zip_de_dias(tmp_path, [14, 15, 16])
    serie, cell_lat, cell_lon, _ = ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)
    assert [d for d, _, _ in serie] == ["2026-07-15", "2026-07-16", "2026-07-17"]
    assert (cell_lat, cell_lon) == (39.05, -9.25)


def _zip_de_membros(tmp_path, membros):
    """Um zip com VARIOS dias dentro de cada membro.

    O `_zip_de_dias` monta N membros de exactamente um dia cada, e essa forma
    -- a unica que a suite conhecia -- prova o ciclo pelos membros e nao prova
    nada sobre o que se le DENTRO de um. Com ela, `serie.append(parcial[0])`
    passava a suite inteira: o defeito identico ao de 29/08, um nivel mais
    fundo.

    `membros` e uma lista de (primeiro_dia, quantos_dias).
    """
    caminho = tmp_path / "mes.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for i, (primeiro, quantos) in enumerate(membros):
            nc = _escrever_netcdf(tmp_path / f"m{i}.nc",
                                  [[280.15, 290.15, 300.15, 300.15 + dia]
                                   for dia in range(quantos)],
                                  primeiro_dia=primeiro)
            z.write(nc, arcname=f"pasta/{i}/dias.nc")
    return caminho


def test_a_zip_member_with_several_days_is_read_to_the_end(tmp_path):
    """Tres membros de CINCO dias sao quinze linhas, e nao tres.

    A correccao de 29/08 -- ler o zip ate ao ultimo membro -- moveu o ponto de
    truncatura para dentro do membro, e o teste que o prenderia nao foi atras:
    todos os zips desta suite eram N membros x exactamente 1 dia. Um zip real
    do AgERA5 traz um .nc por dia, mas isso e um formato da origem, nao uma
    garantia dela, e nada no codigo depende de ser assim.

    Os quinze valores sao todos DIFERENTES: com valores iguais, ler o mesmo
    dia quinze vezes seria indistinguivel de ler quinze dias -- e a
    desduplicacao por dia so o apanharia por acaso.
    """
    caminho = _zip_de_membros(tmp_path, [(14, 5), (19, 5), (24, 5)])

    serie, cell_lat, cell_lon, sem_dado = ler_serie_netcdf(
        caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)

    assert len(serie) == 15
    assert [d for d, _, _ in serie] == [f"2026-07-{dia:02d}" for dia in range(15, 30)]
    # o quarto pixel de cada instante e 300,15 + o indice do dia DENTRO do
    # membro: 0..4 em cada um dos tres
    assert [round(v - 300.15) for _, v, _ in serie] == [0, 1, 2, 3, 4] * 3
    assert (cell_lat, cell_lon) == (39.05, -9.25)
    assert sem_dado == []


def test_a_zip_whose_members_choose_different_cells_is_refused(tmp_path):
    """Uma so celula assina a serie toda; duas tornavam a proveniencia falsa em parte dela."""
    caminho = _zip_de_dias(tmp_path, [14, 15], lats_por_dia={1: (39.02, 38.92)})
    with pytest.raises(RuntimeError, match="celula"):
        ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)


def test_a_zip_that_repeats_a_day_is_refused(tmp_path):
    """Dois valores para o mesmo dia: qual fica passaria a depender da ordem dos membros."""
    caminho = _zip_de_dias(tmp_path, [14, 14])
    with pytest.raises(RuntimeError, match="mesmo dia"):
        ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)


def test_members_with_the_same_basename_do_not_overwrite_each_other(tmp_path):
    """Dois membros chamados o mesmo em pastas diferentes sao dois dias, nao um."""
    caminho = _zip_de_dias(tmp_path, [14, 15])     # ambos gravados como `dia.nc`
    serie, _, _, _ = ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)
    assert len(serie) == 2


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
    acima, _, _, _ = ler_serie_netcdf(nc, 39.1001, -9.25, VAR_TEMPERATURA)
    abaixo, _, _, _ = ler_serie_netcdf(nc, 39.0999, -9.25, VAR_TEMPERATURA)
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
    escolhas = {ler_serie_netcdf(nc, 39.125, -9.25, VAR_TEMPERATURA)[1] for _ in range(5)}
    assert escolhas == {39.25}                                 # indice mais baixo desempata
    serie, _, _, _ = ler_serie_netcdf(nc, 39.125, -9.25, VAR_TEMPERATURA)
    assert serie[0][1] == pytest.approx(280.15, abs=0.01)      # a celula do indice 0


def test_the_returned_coordinates_are_the_cell_not_the_grid_centre(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    serie, cell_lat, cell_lon, _ = ler_serie_netcdf(nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)
    assert (cell_lat, cell_lon) == (39.05, -9.25)
    assert serie[0][1] == pytest.approx(310.15, abs=0.01)


def test_a_file_that_does_not_cover_the_site_is_refused(tmp_path):
    """Ler a celula da borda seria dar um valor de outro sitio com ar de local."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    with pytest.raises(RuntimeError, match="passo de grelha|nao cobre o sitio"):
        ler_serie_netcdf(nc, 41.15, -9.25, VAR_TEMPERATURA)


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
        ler_serie_netcdf(nc, 39.21, -9.25, VAR_TEMPERATURA)          # 0,06 graus = 0,6 passos de 0,1


def test_a_site_within_half_a_step_is_accepted(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 310.15]])
    serie, cell_lat, _, _ = ler_serie_netcdf(nc, 39.19, -9.25, VAR_TEMPERATURA)   # 0,04 graus = 0,4 passos
    assert cell_lat == pytest.approx(39.15, abs=1e-9)
    assert serie[0][1] == pytest.approx(290.15, abs=0.01)


# --------------------------------- um no sem dado nao e uma medicao (F1)


def test_a_masked_cell_does_not_become_a_measurement(tmp_path):
    """O defeito mais grave desta camada a 30/08/2026, e nao era uma hipotese.

    `float()` sobre um elemento MASCARADO de um MaskedArray do numpy nao
    levanta: emite um UserWarning e devolve `nan`. O dia entrava na base como
    `value_numeric = NaN`, `value_qualifier = exact`, `quality_flag = valid`,
    com proveniencia completa, contado no `rows_written` de um job
    `succeeded`. E no PostgreSQL o NaN propaga-se pelos agregados: um dia
    assim punha `avg()`, `max()` e `sum()` a devolver NaN para aquela metrica
    daquele sitio, para sempre.

    A celula do sitio de Turcifal e a (39,05, -9,25), o quarto pixel.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [
        [280.15, 290.15, 300.15, SEM_DADO],       # 2026-07-15: o no do sitio nao tem dado
        [280.15, 290.15, 300.15, 305.15],         # 2026-07-16: tem
    ])
    serie, cell_lat, cell_lon, sem_dado = ler_serie_netcdf(
        nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)

    assert [(d, v) for d, v, _ in serie] == [("2026-07-16", pytest.approx(305.15, abs=0.01))]
    assert sem_dado == ["2026-07-15"]
    assert (cell_lat, cell_lon) == (pytest.approx(39.05), pytest.approx(-9.25))
    # a asercao que define o achado: nenhum valor da serie e NaN nem infinito
    assert all(math.isfinite(v) for _, v, _ in serie)


def test_a_masked_cell_does_not_borrow_the_value_of_the_next_node(tmp_path):
    """Recusa-se a LEITURA, e nao o NO. Saltar para o vizinho era outro sitio.

    A alternativa considerada era procurar o no seguinte quando este nao tem
    dado. Seria pior: a mascara e por INSTANTE, portanto dias diferentes da
    mesma serie sairiam de celulas diferentes debaixo de uma proveniencia
    unica que so descreve uma delas -- exactamente a afirmacao que o bloco do
    zip ja recusa quando dois membros escolhem celulas diferentes. Este teste
    prende a escolha: os tres vizinhos tem valores bem distintos e nenhum
    deles pode aparecer na serie.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, SEM_DADO]])
    serie, cell_lat, cell_lon, sem_dado = ler_serie_netcdf(
        nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)

    assert serie == []
    assert sem_dado == ["2026-07-15"]
    # a celula continua a ser a do sitio, e nao a do vizinho que tinha dado
    assert (cell_lat, cell_lon) == (pytest.approx(39.05), pytest.approx(-9.25))


def test_reading_a_masked_cell_does_not_even_warn(tmp_path):
    """Prende a ORDEM dentro do `_e_sem_dado`, que nao e estilistica.

    Sem a pergunta pela mascara, o `float()` corre na mesma sobre um elemento
    mascarado: emite `UserWarning: converting a masked element to nan` e
    devolve `nan`. O dia acabaria por ser descartado pelo teste de finitude
    logo a seguir -- o resultado seria o mesmo -- mas a leitura passaria a
    depender de um aviso do numpy em vez de uma pergunta explicita, e uma
    versao futura que faca `float()` LEVANTAR sobre um mascarado transformava
    um descarte contado numa excepcao. Este teste e o que impede que a
    pergunta pela mascara seja "simplificada" por redundante.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, SEM_DADO]])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        serie, _, _, sem_dado = ler_serie_netcdf(nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)
    assert serie == []
    assert sem_dado == ["2026-07-15"]


def test_a_raw_nan_without_a_fill_value_is_dropped_too(tmp_path):
    """Nem todo o buraco vem mascarado: um produtor pode escrever `nan` em bruto.

    Sem `_FillValue` declarado nao ha mascara nenhuma para apanhar, e o
    `float()` devolve o mesmo `nan` sem aviso nenhum -- este caminho e ainda
    mais silencioso do que o mascarado, porque nem o UserWarning existe.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [
        [280.15, 290.15, 300.15, float("nan")],
        [280.15, 290.15, 300.15, float("inf")],
        [280.15, 290.15, 300.15, 305.15],
    ])
    serie, _, _, sem_dado = ler_serie_netcdf(nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)

    assert [(d, v) for d, v, _ in serie] == [("2026-07-17", pytest.approx(305.15, abs=0.01))]
    assert sem_dado == ["2026-07-15", "2026-07-16"]


def test_a_masked_day_inside_a_zip_member_is_dropped_and_counted(tmp_path):
    """A conta atravessa os membros do zip, que e como o AgERA5 entrega um mes."""
    caminho = tmp_path / "mes.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for i, (dia, quarto_pixel) in enumerate([(14, SEM_DADO), (15, 305.15), (16, SEM_DADO)]):
            nc = _escrever_netcdf(tmp_path / f"d{i}.nc",
                                  [[280.15, 290.15, 300.15, quarto_pixel]], primeiro_dia=dia)
            z.write(nc, arcname=f"pasta/{i}/dia.nc")

    serie, _, _, sem_dado = ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)

    assert [(d, v) for d, v, _ in serie] == [("2026-07-16", pytest.approx(305.15, abs=0.01))]
    assert sem_dado == ["2026-07-15", "2026-07-17"]


def test_the_dropped_days_are_counted_on_every_row_of_that_variable(tmp_path):
    """Zero e uma afirmacao; a ausencia da chave nao e nada.

    Sem a contagem na linha, os dias saltados so existiam no log da execucao
    -- e quem auditar a tabela daqui a um ano nao tem o log. E a mesma
    disciplina das duas contagens de descarte do caminho do IPMA.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [
        [280.15, 290.15, 300.15, SEM_DADO],
        [280.15, 290.15, 300.15, 300.15],
        [280.15, 290.15, 300.15, 300.15],
    ])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-17", ["2m_temperature"])

    assert [linha["date"] for linha in linhas] == ["2026-07-16", "2026-07-17"]
    assert [linha["masked_days_dropped"] for linha in linhas] == [1, 1]


def test_a_series_with_no_gaps_says_so_with_a_zero(tmp_path):
    nc = _escrever_netcdf(tmp_path / "t.nc", [[280.15, 290.15, 300.15, 300.15]])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-15", ["2m_temperature"])

    assert linhas[0]["masked_days_dropped"] == 0


# ------------------------------------- a variavel lida e a que foi pedida


def _netcdf_com_variaveis(caminho, nomes_e_valores, dia=14, dimensoes=("time", "lat", "lon")):
    """NetCDF com as variaveis dadas, POR ESTA ORDEM, todas do mesmo formato.

    A ordem e um ingrediente do teste, nao um detalhe: a versao anterior deste
    leitor ficava com a primeira variavel tridimensional que encontrasse, e um
    ficheiro cuja primeira variavel nao fosse a pedida era lido em silencio.
    """
    ds = Dataset(str(caminho), "w", format="NETCDF4")
    ds.createDimension("time", 1)
    ds.createDimension("lat", 2)
    ds.createDimension("lon", 2)
    t = ds.createVariable("time", "f8", ("time",))
    t.units = "days since 2026-07-01 00:00:00"
    t.calendar = "proleptic_gregorian"
    t[:] = [dia]
    lat = ds.createVariable("lat", "f8", ("lat",))
    lat[:] = [39.15, 39.05]
    lon = ds.createVariable("lon", "f8", ("lon",))
    lon[:] = [-9.35, -9.25]
    for nome, valor in nomes_e_valores:
        v = ds.createVariable(nome, "f4", dimensoes)
        v[...] = valor
    ds.close()
    return caminho


def test_a_file_with_two_data_variables_reads_the_one_that_was_requested(tmp_path):
    """Com duas candidatas, escolher a primeira era escolher em silencio.

    O `variable` que vai para o `evidence` vem do PEDIDO, nunca do ficheiro:
    a divergencia entre as duas nao aparecia em lado nenhum, e a base ficava
    com o valor de uma grandeza sob o nome de outra, com proveniencia
    completa e ar de correcto.
    """
    nc = _netcdf_com_variaveis(tmp_path / "duas.nc",
                               [("Precipitation_Flux", 3.5), (VAR_TEMPERATURA, 300.15)])
    serie, _, _, _ = ler_serie_netcdf(nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)
    assert serie[0][1] == pytest.approx(300.15, abs=0.01)     # a pedida, nao a primeira


def test_a_file_that_does_not_carry_the_requested_variable_is_refused(tmp_path):
    """Uma unica variavel, mas a errada, passava nas duas versoes anteriores.

    Recusar apenas quando ha MAIS do que uma candidata nao fechava este caso:
    aqui ha exactamente uma, e ela nao e a que se pediu.
    """
    nc = _netcdf_com_variaveis(tmp_path / "outra.nc", [("Precipitation_Flux", 3.5)])
    with pytest.raises(RuntimeError) as erro:
        ler_serie_netcdf(nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)
    assert VAR_TEMPERATURA in str(erro.value)                 # o que se pediu
    assert "Precipitation_Flux" in str(erro.value)            # o que la estava


def test_a_variable_with_the_requested_name_but_the_wrong_shape_is_refused(tmp_path):
    """O nome certo com duas dimensoes nao e a serie que se pediu."""
    nc = _netcdf_com_variaveis(tmp_path / "plana.nc", [(VAR_TEMPERATURA, 300.15)],
                               dimensoes=("lat", "lon"))
    with pytest.raises(RuntimeError, match="esperavam-se tres"):
        ler_serie_netcdf(nc, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)


def test_a_zip_whose_later_member_carries_another_variable_is_refused(tmp_path):
    """A verificacao e por membro, e nao so no primeiro.

    E a forma exacta do defeito que a corrida real de 29/08 revelou noutro
    sitio: o primeiro membro estava bem e a leitura parava de olhar dali para
    a frente.
    """
    caminho = tmp_path / "mes.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        bom = _netcdf_com_variaveis(tmp_path / "d0.nc", [(VAR_TEMPERATURA, 300.15)], dia=14)
        z.write(bom, arcname="0/dia.nc")
        mau = _netcdf_com_variaveis(tmp_path / "d1.nc", [("Precipitation_Flux", 3.5)], dia=15)
        z.write(mau, arcname="1/dia.nc")
    with pytest.raises(RuntimeError, match="Precipitation_Flux"):
        ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)


def test_a_download_carrying_another_variable_never_becomes_a_temperature_row(tmp_path):
    """O prejuizo, ao nivel a que ele acontece: a linha que ia para a base.

    3,5 mm/dia lidos como se fossem Kelvin davam -269,65 C, gravados com
    `metric: air_temperature`, `unit: degC` e `variable: 2m_temperature` --
    porque a conversao de unidade tambem e escolhida pelo nome PEDIDO. Nada
    na linha dizia que o ficheiro trazia outra coisa.
    """
    nc = _netcdf_com_variaveis(tmp_path / "trocada.nc", [("Precipitation_Flux", 3.5)])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    with pytest.raises(RuntimeError, match="Precipitation_Flux"):
        c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                        "2026-07-15", "2026-07-15", ["2m_temperature"])


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


def test_reference_evapotranspiration_keeps_the_millimetres_it_already_has(tmp_path):
    """A ET0 vem do AgERA5 em mm/dia, ja calculada -- nao ha conversao a fazer.

    O que estaria em risco se houvesse: a ET0 e a entrada que domina qualquer
    balanco hidrico, e um factor a mais ou a menos aqui nao aparece em lado
    nenhum na linha gravada, so no resultado do balanco.
    """
    nc = _escrever_netcdf(tmp_path / "et0.nc", [[4.2] * 4],
                          nome=VAR_ET0, unidades="mm d-1")
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-15", ["reference_evapotranspiration"])
    assert linhas[0]["metric"] == WeatherMetric.reference_evapotranspiration
    assert linhas[0]["unit"] == "mm"
    assert linhas[0]["value"] == pytest.approx(4.2, abs=0.001)


def test_the_reference_evapotranspiration_name_inside_the_file_is_pinned(tmp_path):
    """O nome do pedido nao e o nome do ficheiro, e o ficheiro e que manda.

    Pede-se `reference_evapotranspiration` e o AgERA5 devolve a variavel
    `ReferenceET_PenmanMonteith_FAO56`. Um ficheiro que traga o nome do
    PEDIDO tem de ser recusado: se um dia o Copernicus renomear a variavel,
    a ingestao para em voz alta em vez de gravar outra grandeza como ET0.
    """
    nc = _netcdf_com_variaveis(tmp_path / "renomeada.nc",
                               [("reference_evapotranspiration", 4.2)])
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    with pytest.raises(RuntimeError) as erro:
        c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                        "2026-07-15", "2026-07-15", ["reference_evapotranspiration"])
    assert VAR_ET0 in str(erro.value)                          # o que se procurou
    assert "reference_evapotranspiration" in str(erro.value)   # o que la estava


def test_the_reference_evapotranspiration_request_carries_no_statistic(tmp_path):
    """A ET0 do AgERA5 ja e diaria: o corpo medido a funcionar nao leva `statistic`.

    O corpo e apanhado no transporte, e nao construido a mao pelo teste:
    `inputs_agera5` faz o que lhe mandarem, e quem escolhe a estatistica de
    cada variavel e a tabela. Um `24_hour_mean` a mais aqui faria o CDS
    recusar o pedido inteiro com "not a valid combination of values".
    """
    corpos = []
    servir = _ciclo_de_job(
        _escrever_netcdf(tmp_path / "et0.nc", [[4.2] * 4],
                         nome=VAR_ET0, unidades="mm d-1").read_bytes())

    def handler(request):
        if str(request.url).endswith("/execution"):
            corpos.append(json.loads(request.content)["inputs"])
        return servir(request)

    _cliente(handler).agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                                    "2026-08-10", "2026-08-10",
                                    ["reference_evapotranspiration"])
    assert len(corpos) == 1
    assert "statistic" not in corpos[0]
    assert "time" not in corpos[0]
    assert corpos[0]["variable"] == ["reference_evapotranspiration"]
    assert corpos[0]["version"] == "2_0"


def test_precipitation_keeps_the_millimetres_it_already_has(tmp_path):
    nc = _escrever_netcdf(tmp_path / "p.nc", [[3.5] * 4],
                          nome="Precipitation_Flux", unidades="mm d-1")
    c = _cliente(_ciclo_de_job(nc.read_bytes()))
    linhas = c.agera5_diario(CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON,
                             "2026-07-15", "2026-07-15", ["precipitation_flux"])
    assert linhas[0]["metric"] == WeatherMetric.precipitation
    assert linhas[0]["unit"] == "mm"
    assert linhas[0]["value"] == pytest.approx(3.5, abs=0.001)


# ------------------------------- mais do que uma variavel no mesmo pedido


def _ciclo_por_variavel(ficheiros: dict):
    """Serve o ciclo do CDS devolvendo o ficheiro CERTO para cada variavel.

    O `_ciclo_de_job` devolve sempre o mesmo ficheiro, o que so serve para um
    pedido de uma variavel: com tres, as tres liam o mesmo NetCDF e o teste nao
    distinguia "as tres foram pedidas" de "a primeira foi pedida tres vezes".
    Devolve tambem a lista das variaveis pedidas, pela ordem em que o foram.
    """
    pedidas = []

    def handler(request):
        url = str(request.url)
        if url.endswith("/execution"):
            pedidas.append(json.loads(request.content)["inputs"]["variable"][0])
            return httpx.Response(201, json={"jobID": f"job-{len(pedidas)}",
                                             "status": "accepted"})
        if url.endswith("/results"):
            job = url.split("/jobs/")[1].split("/")[0]
            return httpx.Response(200, json={"asset": {"value": {
                "href": f"https://object-store.example/{job}.nc"}}})
        if "/jobs/" in url:
            return httpx.Response(200, json={"status": "successful"})
        indice = int(url.rsplit("/", 1)[1].removesuffix(".nc").split("-")[1]) - 1
        return httpx.Response(200, content=ficheiros[pedidas[indice]])

    return handler, pedidas


def test_every_requested_variable_is_fetched_and_not_just_the_first(tmp_path):
    """O unico teste desta suite que corre o ciclo com mais do que uma variavel.

    Todos os outros passam uma lista de UM elemento, portanto o
    `for variavel in variaveis` so alguma vez corria uma vez: um `break` depois
    da primeira -- ou a leitura da mesma variavel tres vezes -- deixava a suite
    inteira verde. E a armadilha da "coleccao de um", e este e o sitio onde ela
    se fecha do lado do cliente.
    """
    ficheiros = {
        "2m_temperature": _escrever_netcdf(
            tmp_path / "t.nc", [[300.15] * 4], nome=VAR_TEMPERATURA, unidades="K").read_bytes(),
        "precipitation_flux": _escrever_netcdf(
            tmp_path / "p.nc", [[3.5] * 4],
            nome="Precipitation_Flux", unidades="mm d-1").read_bytes(),
        "solar_radiation_flux": _escrever_netcdf(
            tmp_path / "r.nc", [[27_000_000.0] * 4],
            nome="Solar_Radiation_Flux", unidades="J m-2 day-1").read_bytes(),
    }
    handler, pedidas = _ciclo_por_variavel(ficheiros)

    linhas = _cliente(handler).agera5_diario(
        CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15",
        list(ficheiros))

    assert pedidas == list(ficheiros)                  # tres pedidos, um por variavel
    assert len(linhas) == 3
    assert {linha["variable"] for linha in linhas} == set(ficheiros)
    # e cada uma trouxe o SEU valor, ja convertido pela sua propria formula
    por_variavel = {linha["variable"]: linha["value"] for linha in linhas}
    assert por_variavel["2m_temperature"] == pytest.approx(27.0, abs=0.01)
    assert por_variavel["precipitation_flux"] == pytest.approx(3.5, abs=0.001)
    assert por_variavel["solar_radiation_flux"] == pytest.approx(312.5, abs=0.01)


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


# ------------------------------------- o que cada numero da reanalise resume


def test_every_agera5_variable_declares_what_its_number_summarises():
    """As duas tabelas tem de cobrir exactamente as mesmas variaveis.

    Sao tabelas separadas de proposito -- uma diz o que pedir ao CDS, a outra
    o que o numero significa -- e tabelas separadas derivam. Uma variavel nova
    em `_VARIAVEIS_AGERA5` que faltasse aqui so se revelava com um `KeyError`
    na primeira sincronizacao real, ou seja num job `failed` em producao.

    O sentido contrario tambem importa: uma entrada de agregacao para uma
    variavel que ja nao se pede e uma afirmacao sobre uma coisa que nao existe.
    """
    assert set(_AGREGACAO_AGERA5) == set(_VARIAVEIS_AGERA5)


def test_the_row_says_it_is_a_daily_aggregate_even_when_the_request_has_no_statistic(tmp_path):
    """O achado inteiro num teste: o `statistic` do PEDIDO nao e a agregacao.

    A precipitacao do AgERA5 nao leva `statistic` nenhum -- a API recusa-o,
    porque a variavel ja e diaria por definicao. A correccao obvia (copiar o
    campo do pedido para o `evidence`) gravava `statistic: null` nesta linha,
    e um `null` ali le-se como "isto nao e um agregado": o CONTRARIO da
    verdade, porque o numero sao os milimetros de um dia inteiro.

    Os dois lados sao afirmados na mesma corrida, sobre o mesmo pedido: o
    corpo apanhado no transporte NAO leva `statistic`, e a linha que sai dele
    diz na mesma que resume 24 horas.
    """
    corpos = []
    servir = _ciclo_de_job(
        _escrever_netcdf(tmp_path / "p.nc", [[3.5] * 4],
                         nome="Precipitation_Flux", unidades="mm d-1").read_bytes())

    def handler(request):
        if str(request.url).endswith("/execution"):
            corpos.append(json.loads(request.content)["inputs"])
        return servir(request)

    linhas = _cliente(handler).agera5_diario(
        CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15",
        ["precipitation_flux"])

    assert "statistic" not in corpos[0]
    assert linhas[0]["aggregation"] == {
        "aggregation_operator": "total", "aggregation_period_hours": 24.0}


def test_the_temperature_row_says_it_is_a_24_hour_mean(tmp_path):
    """O caso onde o pedido LEVA estatistica, para o par ficar completo.

    Uma media de 24 horas carimbada a meia-noite, ao lado de duas outras
    series de `air_temperature` em `degC` no mesmo sitio. Sem esta chave, a
    unica maneira de saber que este 21,0 nao e a temperatura da meia-noite era
    saber de cor como o AgERA5 funciona.
    """
    corpos = []
    servir = _ciclo_de_job(
        _escrever_netcdf(tmp_path / "t.nc", [[294.15] * 4]).read_bytes())

    def handler(request):
        if str(request.url).endswith("/execution"):
            corpos.append(json.loads(request.content)["inputs"])
        return servir(request)

    linhas = _cliente(handler).agera5_diario(
        CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15",
        ["2m_temperature"])

    assert corpos[0]["statistic"] == ["24_hour_mean"]
    assert linhas[0]["aggregation"] == {
        "aggregation_operator": "mean", "aggregation_period_hours": 24.0}


def test_the_radiation_row_says_it_is_a_24_hour_mean_and_not_an_hourly_one(tmp_path):
    """A metade da reanalise do par que o achado nomeia.

    27 000 000 J m-2 no dia dao 312,5 W/m2 -- dentro da banda 185-350 que a
    producao mostra. A estacao do IPMA escreve a MESMA metrica na MESMA
    unidade entre 0 e 872 W/m2, porque a media dela e de UMA hora. E este
    campo que permite ao leitor aprender a diferenca a partir da linha.
    """
    nc = _escrever_netcdf(tmp_path / "r.nc", [[27_000_000.0] * 4],
                          nome="Solar_Radiation_Flux", unidades="J m-2 day-1")
    linhas = _cliente(_ciclo_de_job(nc.read_bytes())).agera5_diario(
        CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15",
        ["solar_radiation_flux"])

    assert linhas[0]["unit"] == "W/m2"
    assert linhas[0]["value"] == pytest.approx(312.5, abs=0.01)
    assert linhas[0]["aggregation"]["aggregation_period_hours"] == 24.0
    assert linhas[0]["aggregation"]["aggregation_operator"] == "mean"


def test_each_row_carries_its_own_copy_of_the_aggregation(tmp_path):
    """Mesma armadilha da caixa: um dicionario partilhado por N linhas deixa
    quem escreva numa a alterar todas as outras."""
    nc = _escrever_netcdf(tmp_path / "t.nc", [[300.15] * 4, [301.15] * 4])
    linhas = _cliente(_ciclo_de_job(nc.read_bytes())).agera5_diario(
        CAIXA_PEQUENA, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-16",
        ["2m_temperature"])
    assert len(linhas) == 2
    assert linhas[0]["aggregation"] is not linhas[1]["aggregation"]
    linhas[0]["aggregation"]["aggregation_period_hours"] = 999
    assert linhas[1]["aggregation"]["aggregation_period_hours"] == 24.0


# ------------------------------- de que ficheiro veio cada dia (achado F5)

# Um nome REAL de membro do zip do AgERA5, lido a 30/08/2026. O token
# `final-v2.0.0` e o que da sentido a esta chave toda: um marcador `final-` so
# significa alguma coisa se existir um nao-final -- e a origem a dizer, no
# proprio nome do ficheiro, que ha valores que ela ainda pode rever.
NOME_REAL_DO_MEMBRO = (
    "ReferenceET-PenmanMonteith-FAO56_C3S-glob-agric_AgERA5_20260810_final-v2.0.0"
    ".area-subset.39.24.-9.44.38.84.-9.04.nc"
)


def test_each_day_records_the_zip_member_it_came_from_and_not_the_call(tmp_path):
    """A identidade e por DIA, e nao por pedido.

    Um zip mensal pode trazer os primeiros dias ja finais e os ultimos ainda
    preliminares: uma unica identidade para a chamada inteira nao distinguia
    os dois. Dois membros de dois dias cada, e cada uma das quatro linhas tem
    de nomear o SEU membro -- com uma identidade por chamada, as quatro sairiam
    iguais e o teste passava por engano.
    """
    caminho = tmp_path / "mes.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for i, primeiro in enumerate((14, 16)):
            nc = _escrever_netcdf(tmp_path / f"m{i}.nc",
                                  [[280.15, 290.15, 300.15, 300.15 + d] for d in range(2)],
                                  primeiro_dia=primeiro)
            z.write(nc, arcname=f"pasta/{i}/{primeiro}_final-v2.0.0.nc")

    serie, _, _, _ = ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)

    assert [(dia, ficheiro) for dia, _, ficheiro in serie] == [
        ("2026-07-15", "pasta/0/14_final-v2.0.0.nc"),
        ("2026-07-16", "pasta/0/14_final-v2.0.0.nc"),
        ("2026-07-17", "pasta/1/16_final-v2.0.0.nc"),
        ("2026-07-18", "pasta/1/16_final-v2.0.0.nc"),
    ]


def test_the_member_name_is_the_one_inside_the_zip_and_not_the_extracted_one(tmp_path):
    """O membro e extraido para um ficheiro com um indice NOSSO a frente.

    Esse prefixo existe para dois membros homonimos em pastas diferentes nao se
    sobreporem, e nao pode chegar a base: o que a linha tem de nomear e o
    ficheiro que a origem emitiu, nao o nome que nos lhe demos no disco. Sem
    esta asercao, gravar `destino.name` -- que esta a duas linhas de distancia
    -- passava despercebido.
    """
    caminho = tmp_path / "mes.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        nc = _escrever_netcdf(tmp_path / "m.nc", [[280.15, 290.15, 300.15, 310.15]])
        z.write(nc, arcname=NOME_REAL_DO_MEMBRO)

    serie, _, _, _ = ler_serie_netcdf(caminho, TURCIFAL_LAT, TURCIFAL_LON, VAR_TEMPERATURA)

    assert [ficheiro for _, _, ficheiro in serie] == [NOME_REAL_DO_MEMBRO]
    assert not serie[0][2].startswith("0000-")


def test_a_loose_download_records_the_name_the_origin_served(tmp_path):
    """O .nc solto tambem tem de trazer um nome da ORIGEM, e nao um nosso.

    Ate aqui o `agera5_diario` mandava descarregar para `{job_id}.nc`, um nome
    inventado por nos; com o destino a ser a pasta, o `download` fica com o
    nome que vem no href. O jobID e o nome do href sao DIFERENTES neste teste
    de proposito: nos duplos da suite os dois calham iguais (`job-1.nc`), e com
    eles gravar o nosso nome era indistinguivel de gravar o da origem.
    """
    nc = _escrever_netcdf(tmp_path / "t.nc", [[294.15] * 4])
    bytes_nc = nc.read_bytes()

    def handler(request):
        url = str(request.url)
        if url.endswith("/execution"):
            return httpx.Response(201, json={"jobID": "job-1", "status": "accepted"})
        if url.endswith("/results"):
            return httpx.Response(200, json={"asset": {"value": {
                "href": f"https://object-store.example/{NOME_REAL_DO_MEMBRO}"}}})
        if "/jobs/" in url:
            return httpx.Response(200, json={"status": "successful"})
        return httpx.Response(200, content=bytes_nc)

    linhas = _cliente(handler).agera5_diario(
        CAIXA_GRANDE, TURCIFAL_LAT, TURCIFAL_LON, "2026-07-15", "2026-07-15",
        ["2m_temperature"])

    assert linhas[0]["source_file"] == NOME_REAL_DO_MEMBRO
    assert "job-1" not in linhas[0]["source_file"]
