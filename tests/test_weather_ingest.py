"""Ingestao da reanalise AgERA5: o que se grava, e o que a linha admite sobre si.

Nenhum teste toca a rede. O cliente entra por argumento e e sempre um duplo
que devolve linhas ja normalizadas -- exactamente o formato que o
`CDSClient.agera5_diario` produz -- e que reutiliza o `expandir_area` real do
cliente, para que a caixa que aparece na proveniencia seja a caixa que o CDS
teria mesmo recebido.
"""

import json
import math
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from netCDF4 import Dataset
from shapely.geometry import shape
from sqlalchemy import event, func, select

from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, JobStatus, QualityFlag, SourceType, ValueQualifier,
)
from resoiltwin.geo import geojson_to_wkt_element, wkb_to_geojson
from resoiltwin.models import Aoi, IngestionJob, Observation, Plot, Site
from resoiltwin.weather.cds import (
    DATASET_AGERA5, VERSAO_AGERA5, CDSClient, _VARIAVEIS_AGERA5, expandir_area,
)
from resoiltwin.weather.ingest import (
    PROCESSING_VERSION, PROCESSING_VERSION_IPMA, _cauda_do_rasto, _texto_do_erro,
    sync_ipma, sync_reanalysis,
)
from resoiltwin.weather.ingest import VARIAVEIS as VARIAVEIS_PADRAO
from resoiltwin.weather.ipma import RAIO_MAXIMO_KM
from resoiltwin.weather.metrics import WeatherMetric

# o ponto canonico do sitio de Turcifal, o mesmo de tests/test_geo.py e de
# tests/test_weather_metrics.py
TURCIFAL_LON, TURCIFAL_LAT = -9.240247, 39.037317
# o no de grelha do AgERA5 que contem Turcifal, medido contra a API real na
# Task 2: fica a ~5,4 km do sitio
CELULA_TURCIFAL = (39.0, -9.2)

PORTO_LON, PORTO_LAT = -8.641731, 41.177928
CELULA_PORTO = (41.2, -8.6)

DATAS = ("2026-07-01", "2026-07-02", "2026-07-03")
JANELA = ("2026-07-01", "2026-07-03")

# variavel do AgERA5 -> (metrica, unidade, valor). Os tres primeiros valores
# sao os que a verificacao real da Task 2 leu para 15/07/2026 em Turcifal; a
# ET0 e a de um dia de Julho na mesma celula.
POR_VARIAVEL = {
    "2m_temperature": (WeatherMetric.air_temperature, "degC", 21.68),
    "precipitation_flux": (WeatherMetric.precipitation, "mm", 0.0),
    "solar_radiation_flux": (WeatherMetric.solar_radiation, "W/m2", 313.71),
    "reference_evapotranspiration": (WeatherMetric.reference_evapotranspiration, "mm", 4.2),
}
VARIAVEIS = tuple(POR_VARIAVEL)

# quantas linhas cada dia produz numa corrida com as variaveis por omissao.
# Vem da constante de producao e nao de um literal: acrescentar uma variavel a
# omissao muda TODAS as contagens desta suite, e um `9` escrito a mao em vinte
# sitios e vinte oportunidades de esconder que uma variavel deixou de vir.
METRICAS = len(VARIAVEIS_PADRAO)


def _quadrado(lon: float, lat: float, lado_graus: float = 0.025) -> dict:
    """Quadrado centrado no ponto: o centroide e o proprio ponto."""
    meio = lado_graus / 2
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - meio, lat - meio], [lon + meio, lat - meio],
            [lon + meio, lat + meio], [lon - meio, lat + meio], [lon - meio, lat - meio],
        ]],
    }


def _aoi(session, site_code, aoi_code, lon, lat, status=AoiStatus.approved,
         proveniencia=GeometryProvenance.surveyed, site=None):
    site = site or Site(code=site_code, name=f"Sitio {site_code}")
    aoi = Aoi(
        site=site, code=aoi_code, purpose="earth_observation",
        geometry=geojson_to_wkt_element(_quadrado(lon, lat)),
        geometry_provenance=proveniencia, status=status,
        approved_by="site-manager" if status == AoiStatus.approved else None,
    )
    session.add(aoi)
    session.commit()
    return aoi


@pytest.fixture
def sitio_turcifal(session):
    """Sitio com uma AOI aprovada centrada no ponto canonico de Turcifal."""
    return _aoi(session, "EUC-TUR-MET", "EUC-TUR-MET-EO", TURCIFAL_LON, TURCIFAL_LAT)


@pytest.fixture
def sitio_porto(session):
    return _aoi(session, "EUC-PTO-MET", "EUC-PTO-MET-EO", PORTO_LON, PORTO_LAT)


@pytest.fixture
def sitio_sem_aoi_aprovada(session):
    return _aoi(session, "EUC-TUR-DRAFT-MET", "EUC-TUR-DRAFT-MET-EO",
                TURCIFAL_LON, TURCIFAL_LAT, status=AoiStatus.draft,
                proveniencia=GeometryProvenance.provisional_pending_kml)


class _ClienteEspiao:
    """Cliente falso que so regista que foi chamado.

    A guarda do sitio tem de disparar ANTES da rede. Um duplo que devolvesse
    linhas validas deixaria o teste verde com a guarda no sitio errado; este
    so conta chamadas, portanto a lista vazia e prova de que nao houve pedido.
    """

    def __init__(self):
        self.chamadas = []

    def agera5_diario(self, *args, **kwargs):
        self.chamadas.append("agera5_diario")
        return []


class _ClienteFalso:
    """Devolve a serie ja normalizada, como o `agera5_diario` do cliente real.

    Alarga a caixa com o `expandir_area` de producao em vez de inventar uma:
    o que a proveniencia grava como "caixa pedida" tem de ser a caixa que o
    CDS teria mesmo recebido, senao o teste confirmava uma area que ninguem
    chegou a transferir.
    """

    def __init__(self, datas=DATAS, celula=CELULA_TURCIFAL, unidades=None, mascarados=0):
        self.datas = tuple(datas)
        self.celula = celula
        self.unidades = unidades or {}
        self.mascarados = mascarados
        self.chamadas = []

    def agera5_diario(self, area, lat_sitio, lon_sitio, date_from, date_to,
                      variaveis=None, timeout_s=900.0):
        variaveis = list(variaveis) if variaveis else ["2m_temperature"]
        caixa, alargada = expandir_area(area)
        self.chamadas.append({
            "area": list(area), "lat_sitio": lat_sitio, "lon_sitio": lon_sitio,
            "date_from": date_from, "date_to": date_to, "variaveis": list(variaveis),
        })
        cell_lat, cell_lon = self.celula
        linhas = []
        for variavel in variaveis:
            metrica, unidade, valor = POR_VARIAVEL[variavel]
            for dia in self.datas:
                linhas.append({
                    "date": dia, "metric": metrica, "value": valor,
                    "unit": self.unidades.get(variavel, unidade),
                    "variable": variavel, "dataset": DATASET_AGERA5,
                    "cell_lat": cell_lat, "cell_lon": cell_lon, "cell_size_deg": 0.1,
                    "area_original": [float(x) for x in area],
                    "area_requested": caixa, "area_expanded": alargada,
                    "masked_days_dropped": self.mascarados,
                })
        linhas.sort(key=lambda linha: (linha["date"], linha["metric"]))
        return linhas


class _ClienteQueRebenta:
    """Falha da rede a meio, depois de o job ja existir na base."""

    def agera5_diario(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao CDS perdida a meio da serie")


class _ClienteComDiaSemValor(_ClienteFalso):
    """Serie valida com um dia corrompido: o valor vem a None.

    Uma observacao sem valor nenhum viola ck_observation_has_a_value. Serve
    para provar que a escrita e tudo-ou-nada -- se cada linha fosse confirmada
    a medida que chega, ficavam gravadas as boas antes da ma.
    """

    def agera5_diario(self, *args, **kwargs):
        linhas = super().agera5_diario(*args, **kwargs)
        linhas[-1]["value"] = None
        return linhas


class _ClienteQueEspreitaOJob(_ClienteFalso):
    """Le a linha do job na base A MEIO da chamada a rede.

    E a unica janela em que o estado `running` e observavel: quando o
    sync_reanalysis devolve, o job ja esta succeeded e a passagem por running
    seria indistinguivel de nunca ter acontecido.

    Le duas coisas. O estado da linha apanha o caso de o `running` nunca ser
    atribuido; a contagem de commits apanha o caso de ser atribuido e nao
    confirmado -- dentro da transaccao externa desta suite, uma alteracao
    apenas descarregada e indistinguivel de uma confirmada, e o commit e o
    unico "visivel de fora" que se pode observar aqui.
    """

    def __init__(self, session, **kwargs):
        super().__init__(**kwargs)
        self._session = session
        self._commits = 0
        self.commits_ate_a_rede = None
        self.estado_a_meio = None
        event.listen(session, "after_commit", self._contar)

    def _contar(self, _sessao):
        self._commits += 1

    def agera5_diario(self, *args, **kwargs):
        self.commits_ate_a_rede = self._commits
        with self._session.no_autoflush:
            self._session.expire_all()
            self.estado_a_meio = self._session.execute(
                select(IngestionJob.status, IngestionJob.rows_written, IngestionJob.finished_at)
            ).one()
        return super().agera5_diario(*args, **kwargs)


def _jobs(session) -> int:
    return session.scalar(select(func.count()).select_from(IngestionJob))


def _observacoes(session, aoi):
    return session.scalars(
        select(Observation).where(Observation.site_id == aoi.site_id)
        .order_by(Observation.observed_at, Observation.metric)
    ).all()


def _linha_de_campo(site_id, **trocas):
    """Linha com a identidade da serie de reanalise, mudada em UMA coluna.

    O valor por omissao repete, coluna a coluna, a identidade de uma linha que
    a sincronizacao vai escrever (1 de julho, temperatura, reanalysis, versao
    do AgERA5, sem parcela). Cada teste de espelho troca exactamente um campo:
    o que se prova nao e o cenario, e que a consulta de desduplicacao repete a
    uq_observation_identity inteira. Se lhe faltar uma coluna, uma linha que
    NAO e duplicado passa por duplicado e desaparece da serie em silencio.
    """
    campos = {
        "site_id": site_id,
        "plot_id": None,
        "observed_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "metric": WeatherMetric.air_temperature,
        "source_type": SourceType.reanalysis,
        "processing_version": PROCESSING_VERSION,
        "unit": "degC",
        "value_numeric": 99.0,
        "value_qualifier": ValueQualifier.exact,
        "quality_flag": QualityFlag.valid,
    }
    campos.update(trocas)
    return Observation(**campos)


# --- Regra 1: o sitio tem de existir, e a guarda corre antes da rede --------

def test_unknown_site_is_refused_before_any_network_call(session):
    espiao = _ClienteEspiao()
    with pytest.raises(ValueError) as exc:
        sync_reanalysis(session, espiao, "NAO-EXISTE", *JANELA)

    assert "NAO-EXISTE" in str(exc.value)
    assert espiao.chamadas == []


def test_a_refused_site_leaves_no_job_behind(session):
    """Um sitio que nao existe nao e uma execucao falhada: e uma execucao que
    nunca comecou. A guarda corre antes de o job ser criado."""
    with pytest.raises(ValueError):
        sync_reanalysis(session, _ClienteEspiao(), "NAO-EXISTE", *JANELA)

    assert _jobs(session) == 0


def test_a_site_without_an_approved_aoi_is_refused(session, sitio_sem_aoi_aprovada):
    """O ponto do sitio sai do centroide da AOI. Uma AOI por confirmar pode ser
    um rectangulo inventado -- foi o que dois dos quatro poligonos deste
    projecto foram durante semanas -- e a distancia gravada em cada linha
    passaria a ser ficcao com ar de proveniencia."""
    espiao = _ClienteEspiao()
    with pytest.raises(ValueError) as exc:
        sync_reanalysis(session, espiao, "EUC-TUR-DRAFT-MET", *JANELA)

    assert "approved" in str(exc.value)
    assert espiao.chamadas == []
    # e nao fica job nenhum para tras: uma guarda que corresse DEPOIS de
    # `session.add(job); commit()` tambem nao chegaria a rede, e deixava a base
    # a coleccionar jobs eternamente `pending`. Sem esta linha, os dois casos
    # sao indistinguiveis daqui.
    assert _jobs(session) == 0


def test_two_approved_aois_are_refused_instead_of_picking_one(session, sitio_turcifal):
    """Duas AOI aprovadas no mesmo sitio dao dois centroides, logo duas
    distancias possiveis para a mesma linha. Escolher uma pela ordem da
    consulta seria escolher ao acaso e nao deixar rasto da escolha."""
    _aoi(session, None, "EUC-TUR-MET-EO2", TURCIFAL_LON + 0.02, TURCIFAL_LAT,
         site=session.get(Site, sitio_turcifal.site_id))
    espiao = _ClienteEspiao()
    with pytest.raises(ValueError) as exc:
        sync_reanalysis(session, espiao, "EUC-TUR-MET", *JANELA)

    assert "EUC-TUR-MET-EO" in str(exc.value) and "EUC-TUR-MET-EO2" in str(exc.value)
    assert espiao.chamadas == []
    assert _jobs(session) == 0


def test_an_inverted_window_is_refused_before_the_job_exists(session, sitio_turcifal):
    """`date_from` depois de `date_to` e recusado aqui, nao la dentro do
    cliente: o `_meses_do_intervalo` do CDS tambem a apanha, mas ja depois de
    o job existir, e ficava um `failed` na base para uma execucao que nunca
    devia ter comecado."""
    espiao = _ClienteEspiao()
    with pytest.raises(ValueError) as exc:
        sync_reanalysis(session, espiao, "EUC-TUR-MET", "2026-07-03", "2026-07-01")

    assert "2026-07-03" in str(exc.value) and "2026-07-01" in str(exc.value)
    assert espiao.chamadas == []
    assert _jobs(session) == 0


# --- Regra 1a: o contrato entre o cliente real e o consumidor --------------

ENCHIMENTO = -9999.0


def _netcdf_agera5(caminho, lats=(39.05, 38.95), lons=(-9.25, -9.15), dias_sem_dado=()):
    """Ficheiro AgERA5 minimo, escrito com a mesma biblioteca que o le.

    A grelha 2x2 esta alinhada com multiplos de 0,05 de proposito: o no mais
    proximo do sitio de Turcifal (39,0373 / -9,2402) e o (39,05, -9,25), e os
    quatro pixeis valem coisas diferentes para que a celula escolhida nunca se
    possa confundir com a media da caixa.

    `dias_sem_dado` sao os indices de instante em que a celula DO SITIO leva o
    `_FillValue` -- o no sem dados que a netCDF4 devolve mascarado. Os outros
    tres pixeis continuam com valores bons, para que um valor emprestado do
    vizinho se veja logo.
    """
    ds = Dataset(str(caminho), "w", format="NETCDF4")
    ds.createDimension("time", 2)
    ds.createDimension("lat", 2)
    ds.createDimension("lon", 2)
    t = ds.createVariable("time", "f8", ("time",))
    t.units = "days since 2026-07-01 00:00:00"
    t.calendar = "proleptic_gregorian"
    t[:] = [0, 1]                                      # 2026-07-01 e 07-02
    lat = ds.createVariable("lat", "f8", ("lat",))
    lat[:] = list(lats)
    lon = ds.createVariable("lon", "f8", ("lon",))
    lon[:] = list(lons)
    v = ds.createVariable("Temperature_Air_2m_Mean_24h", "f4", ("time", "lat", "lon"),
                          fill_value=ENCHIMENTO if dias_sem_dado else None)
    v.units = "K"
    for i in range(2):
        primeiro = ENCHIMENTO if i in dias_sem_dado else 294.15
        v[i, :, :] = [[primeiro, 300.15], [305.15, 310.15]]
    ds.close()
    return caminho


def _cds_real(caminho_nc):
    """`CDSClient` de producao por cima de um MockTransport. Nao toca a rede.

    Serve o ciclo assincrono inteiro do CDS -- execution, jobs, results, e o
    ficheiro no object store -- para que o caminho exercitado seja o do
    cliente a serio, montagem da linha incluida.
    """
    bytes_nc = caminho_nc.read_bytes()

    def handler(request):
        url = str(request.url)
        if url.endswith("/execution"):
            return httpx.Response(201, json={"jobID": "job-1", "status": "accepted"})
        if url.endswith("/results"):
            return httpx.Response(200, json={"asset": {"value": {
                "href": "https://object-store.example/job-1.nc"}}})
        if "/jobs/" in url:
            return httpx.Response(200, json={"jobID": "job-1", "status": "successful"})
        return httpx.Response(200, content=bytes_nc)

    return CDSClient("https://cds.example/api", "chave-de-teste",
                     transport=httpx.MockTransport(handler), intervalo_sondagem_s=0.0)


def test_the_real_client_row_satisfies_everything_the_service_indexes(session, sitio_turcifal,
                                                                     tmp_path):
    """Contrato entre `CDSClient.agera5_diario` e `_observacao`, sem rede.

    `_observacao` indexa treze chaves da linha sem `.get()`
    (`date`, `metric`, `value`, `unit`, `variable`, `dataset`, `cell_lat`,
    `cell_lon`, `cell_size_deg`, `area_original`, `area_requested`,
    `area_expanded`, `masked_days_dropped`) e o duplo desta suite reconstroi
    essa forma A MAO, noutro ficheiro. Sao duas copias independentes, e nenhuma verifica a outra: se o
    cliente renomear `area_original` para `area_aoi` -- tentador, porque o
    `evidence` ja lhe chama assim -- ou deixar cair `cell_size_deg`, TODAS as
    sincronizacoes reais passam a ficar `failed` com um `KeyError` como unico
    rasto, e os outros testes deste ficheiro continuam verdes, porque o duplo
    continua a fornecer a chave antiga.

    Este teste fecha isso pelo unico sitio onde se pode fechar sem rede: corre
    o cliente de PRODUCAO sobre um MockTransport e um NetCDF verdadeiro, e
    passa as linhas que ele monta pelo servico. Falha se o produtor deixar de
    dar exactamente o que o consumidor consome -- em qualquer dos lados.
    """
    cliente = _cds_real(_netcdf_agera5(tmp_path / "agera5.nc"))
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", "2026-07-01", "2026-07-02",
                          variaveis=["2m_temperature"])

    assert job.status == JobStatus.succeeded, job.error
    linhas = _observacoes(session, sitio_turcifal)
    assert len(linhas) == 2                            # 1 metrica x 2 dias
    for linha in linhas:
        assert linha.metric == "air_temperature"
        assert linha.unit == "degC"
        assert linha.source_collection == DATASET_AGERA5
        # 294,15 K -> 21,0 degC: a celula (39,05, -9,25), nao a media dos
        # quatro pixeis (que daria 29,9 degC)
        assert linha.value_numeric == pytest.approx(21.0, abs=0.01)
        assert linha.evidence["cell_lat"] == pytest.approx(39.05)
        assert linha.evidence["cell_lon"] == pytest.approx(-9.25)
        assert linha.evidence["cell_size_deg"] == 0.1
        assert linha.evidence["distance_km"] == pytest.approx(1.6, abs=0.3)
        assert linha.evidence["area_expanded"] is True
        assert linha.evidence["variable"] == "2m_temperature"
        assert linha.evidence["masked_days_dropped"] == 0


def test_a_masked_day_never_reaches_the_table_and_the_row_says_how_many(
        session, sitio_turcifal, tmp_path):
    """Pelo caminho REAL: cliente de producao, NetCDF verdadeiro, servico, base.

    O achado F1, ponta a ponta. Ate 30/08/2026 este ficheiro produzia duas
    linhas, e a do dia mascarado tinha `value_numeric = NaN`,
    `value_qualifier = exact`, `quality_flag = valid`, proveniencia completa, e
    era contada no `rows_written` de um job `succeeded`. A base nao a impedia:
    `NaN IS NOT NULL` e verdadeiro. E no PostgreSQL bastava essa linha para
    `avg()`, `max()` e `sum()` da temperatura daquele sitio devolverem NaN.

    A asercao sobre o `avg()` nao e decoracao: e a unica que fala do estrago
    real, que nunca foi uma linha, foi a serie.
    """
    cliente = _cds_real(_netcdf_agera5(tmp_path / "agera5.nc", dias_sem_dado=(0,)))
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", "2026-07-01", "2026-07-02",
                          variaveis=["2m_temperature"])

    assert job.status == JobStatus.succeeded, job.error
    assert job.rows_written == 1
    # o job declara a janela que COBRIU, e o dia mascarado nao existe nela
    assert (job.date_from, job.date_to) == (date(2026, 7, 2), date(2026, 7, 2))

    linhas = _observacoes(session, sitio_turcifal)
    assert len(linhas) == 1
    assert linhas[0].observed_at == datetime(2026, 7, 2, tzinfo=timezone.utc)
    assert linhas[0].value_numeric == pytest.approx(21.0, abs=0.01)
    # nao herdou o valor do vizinho: 300,15 K -> 27,0 degC, 305,15 -> 32,0
    assert linhas[0].value_numeric != pytest.approx(27.0, abs=0.5)
    assert linhas[0].evidence["masked_days_dropped"] == 1

    media = session.scalar(
        select(func.avg(Observation.value_numeric)).where(
            Observation.site_id == sitio_turcifal.site_id,
            Observation.metric == "air_temperature",
        )
    )
    assert media is not None and math.isfinite(float(media))


def test_the_service_calls_the_client_with_the_signature_the_client_declares(session,
                                                                            sitio_turcifal,
                                                                            tmp_path):
    """A chamada e posicional (`area, lat_sitio, lon_sitio, date_from, date_to`).

    Se a ordem dos parametros do cliente mudar, o duplo desta suite aceita
    tudo na mesma -- recebe posicionalmente e nao verifica nada. O cliente
    real nao: com `lat` e `lon` trocados, o `_garantir_sitio_dentro` recusa o
    pedido e o job fica `failed`. E o teste acima que carrega essa prova; este
    isola-a, afirmando que a caixa que chega ao corpo do pedido HTTP e a
    alargada e que contem o sitio.
    """
    corpos = []
    bytes_nc = (_netcdf_agera5(tmp_path / "agera5.nc")).read_bytes()

    def handler(request):
        url = str(request.url)
        if url.endswith("/execution"):
            corpos.append(json.loads(request.content)["inputs"])
            return httpx.Response(201, json={"jobID": "job-1", "status": "accepted"})
        if url.endswith("/results"):
            return httpx.Response(200, json={"asset": {"value": {
                "href": "https://object-store.example/job-1.nc"}}})
        if "/jobs/" in url:
            return httpx.Response(200, json={"jobID": "job-1", "status": "successful"})
        return httpx.Response(200, content=bytes_nc)

    cliente = CDSClient("https://cds.example/api", "chave-de-teste",
                        transport=httpx.MockTransport(handler), intervalo_sondagem_s=0.0)
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", "2026-07-01", "2026-07-02",
                          variaveis=["2m_temperature"])

    assert job.status == JobStatus.succeeded, job.error
    norte, oeste, sul, este = corpos[0]["area"]
    assert sul <= TURCIFAL_LAT <= norte
    assert oeste <= TURCIFAL_LON <= este
    assert norte - sul == pytest.approx(0.4, abs=1e-6)


# --- Regra 1b: a versao de processamento identifica o dataset E a versao ----

def test_the_processing_version_names_the_dataset_and_the_version():
    """A unica asercao da suite contra o LITERAL, e nao contra a constante.

    Todas as outras comparam `PROCESSING_VERSION` consigo propria: importam-na
    de `ingest.py` e afirmam que a linha gravada tem o mesmo valor. Sao
    tautologias -- passam com qualquer valor, incluindo `"2_0"`, que nao
    identifica dataset nenhum. E `processing_version` e uma coluna partilhada
    com as series do Sentinel (`s2-ndvi-ndmi-ndre-v...`): um `2_0` solto la
    dentro nao diz de que produto veio a linha.

    A segunda asercao prende a constante ao `VERSAO_AGERA5` de que deriva. Sao
    duas afirmacoes diferentes e sao precisas as duas: a primeira sozinha
    deixava passar `"agera5-v2_0"` escrito a mao, desligado do cliente, e no
    dia em que o CDS descontinuar a 2.0 a proveniencia gravada divergia
    silenciosamente do `version` que vai no pedido.
    """
    assert PROCESSING_VERSION == "agera5-v2_0"
    assert PROCESSING_VERSION == f"agera5-v{VERSAO_AGERA5}"


def test_the_written_row_carries_the_dataset_in_its_processing_version(session, sitio_turcifal):
    """O mesmo, mas do lado da base: e la que o valor tem de se defender."""
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    for linha in _observacoes(session, sitio_turcifal):
        assert linha.processing_version == "agera5-v2_0"


# --- Regra 1c: o que o servico pede por omissao ------------------------------

def test_the_default_variables_are_named_here_and_the_client_knows_them_all():
    """Uma asercao contra os LITERAIS, como a da PROCESSING_VERSION.

    As outras comparam `VARIAVEIS` consigo propria e passavam com a tuple
    vazia. Esta nomeia as quatro, e a segunda metade impede o erro simetrico:
    um nome mal escrito na omissao do servico so se manifestava em execucao,
    com o cliente a recusar o pedido inteiro depois de o job ja existir.

    A ET0 esta na lista porque o balanco hidrico da Fase D nao tem o que ler
    sem ela, e e a entrada que domina esse balanco. Nao chega o cliente saber
    pedi-la: o que nao for pedido nao entra no arquivo, e o arquivo nao se
    recupera para tras.
    """
    assert VARIAVEIS_PADRAO == (
        "2m_temperature", "precipitation_flux", "solar_radiation_flux",
        "reference_evapotranspiration",
    )
    assert set(VARIAVEIS_PADRAO) <= set(_VARIAVEIS_AGERA5)


def test_the_default_run_writes_the_reference_evapotranspiration(session, sitio_turcifal):
    """Do lado da base, que e onde a Fase D a vai procurar."""
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    et0 = [linha for linha in _observacoes(session, sitio_turcifal)
           if linha.metric == WeatherMetric.reference_evapotranspiration]
    assert len(et0) == len(DATAS)
    for linha in et0:
        assert linha.unit == "mm"
        assert linha.source_type == SourceType.reanalysis
        assert linha.evidence["variable"] == "reference_evapotranspiration"


# --- Regra 2: a caixa e o ponto vem da base, nao do chamador ----------------

def test_the_box_and_the_site_point_come_from_the_database(session, sitio_turcifal):
    """O chamador passa um codigo de sitio. A caixa e o envelope da AOI que
    esta na base e o ponto e o seu centroide -- o mesmo ponto canonico de
    tests/test_geo.py."""
    cliente = _ClienteFalso()
    sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    chamada = cliente.chamadas[0]
    assert chamada["lat_sitio"] == pytest.approx(TURCIFAL_LAT, abs=1e-9)
    assert chamada["lon_sitio"] == pytest.approx(TURCIFAL_LON, abs=1e-9)

    norte, oeste, sul, este = chamada["area"]
    oeste_aoi, sul_aoi, este_aoi, norte_aoi = shape(
        wkb_to_geojson(sitio_turcifal.geometry)).bounds
    assert (norte, oeste, sul, este) == pytest.approx((norte_aoi, oeste_aoi, sul_aoi, este_aoi))
    assert chamada["date_from"] == "2026-07-01"
    assert chamada["date_to"] == "2026-07-03"


# --- Regra 3: escrita idempotente, com rasto no job ------------------------

def test_first_run_writes_one_row_per_metric_and_day(session, sitio_turcifal):
    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.succeeded
    assert job.rows_written == len(DATAS) * METRICAS
    assert job.job_type == "reanalysis_sync"
    assert job.aoi_id == sitio_turcifal.id
    assert job.date_from == date(2026, 7, 1)
    assert job.date_to == date(2026, 7, 3)
    assert job.processing_version == PROCESSING_VERSION
    assert job.request_hash
    assert job.finished_at is not None
    assert job.error is None
    assert len(_observacoes(session, sitio_turcifal)) == len(DATAS) * METRICAS


def test_second_identical_run_writes_nothing(session, sitio_turcifal):
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    segundo = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert len(_observacoes(session, sitio_turcifal)) == len(DATAS) * METRICAS


def test_a_new_day_is_added_without_rewriting_the_old_ones(session, sitio_turcifal):
    """Idempotencia nao e "nao escrever nada na segunda vez": e escrever
    exactamente o que falta."""
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    segundo = sync_reanalysis(session, _ClienteFalso(datas=(*DATAS, "2026-07-04")),
                              "EUC-TUR-MET", "2026-07-01", "2026-07-04")

    assert segundo.rows_written == METRICAS            # so o dia novo
    assert len(_observacoes(session, sitio_turcifal)) == (len(DATAS) + 1) * METRICAS


def test_the_job_is_visible_as_running_during_the_network_call(session, sitio_turcifal):
    """O `running` e confirmado sozinho, antes da rede, para um job preso numa
    chamada de minutos ser visivel de fora ENQUANTO corre."""
    cliente = _ClienteQueEspreitaOJob(session)
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    estado, escritas, terminado = cliente.estado_a_meio
    assert estado == JobStatus.running
    assert escritas == 0
    assert terminado is None
    # `>=` e nao `==`: a propriedade e "o running foi confirmado antes da
    # rede", nao "o servico faz exactamente dois commits".
    assert cliente.commits_ate_a_rede >= 2
    assert job.status == JobStatus.succeeded


# --- Regra 4: falhar sem deixar linhas meio-escritas -----------------------

def test_network_failure_marks_the_job_failed_and_writes_nothing(session, sitio_turcifal):
    job = sync_reanalysis(session, _ClienteQueRebenta(), "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert job.error and "CDS" in job.error
    assert job.rows_written == 0
    assert job.finished_at is not None
    assert _observacoes(session, sitio_turcifal) == []

    # o job sobreviveu ao rollback das linhas: e o unico rasto de que houve
    # tentativa, e a ingestao vai correr agendada, sem ninguem a ver o ecra
    gravado = session.get(IngestionJob, job.id)
    assert gravado.status == JobStatus.failed


def test_one_bad_row_rolls_back_the_whole_batch(session, sitio_turcifal):
    job = sync_reanalysis(session, _ClienteComDiaSemValor(), "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert job.rows_written == 0
    assert _observacoes(session, sitio_turcifal) == []


def test_a_day_outside_the_requested_window_is_refused(session, sitio_turcifal):
    """O cliente recorta dia a dia, portanto hoje isto nunca dispara. Mas a
    janela da consulta de desduplicacao sai dos dias DEVOLVIDOS e nao dos dias
    pedidos: um dia a mais na resposta entrava na base debaixo de um job cujo
    `date_from`/`date_to` diz outra coisa. O corpo do CDS aceita um mes de
    cada vez, portanto alargar o recorte do cliente e uma mudanca plausivel.
    """
    cliente = _ClienteFalso(datas=(*DATAS, "2026-07-09"))
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert "2026-07-09" in job.error
    assert _observacoes(session, sitio_turcifal) == []


def test_a_short_series_makes_the_job_declare_the_days_it_covered(session, sitio_turcifal):
    """Menos dias do que se pediu nao e um erro, mas o job nao pode dizer o contrario.

    O AgERA5 tem atraso de publicacao: a 29/08/2026 um pedido de 01/07 a 29/08
    devolveu ate 22/08 e mais nada. Falhar o job por isso fazia falhar toda a
    ingestao proxima do presente, que e a que interessa -- mas deixa-lo a
    declarar a janela PEDIDA punha na base uma linha de job que diz cobrir
    sete dias que nao existem em lado nenhum.
    """
    cliente = _ClienteFalso(datas=("2026-07-01", "2026-07-02"))
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.succeeded
    assert job.rows_written == 2 * METRICAS            # 2 dias
    assert job.date_from == date(2026, 7, 1)
    assert job.date_to == date(2026, 7, 2)             # o pedido ia ate 03/07


class _ClienteComJanelasDiferentes(_ClienteFalso):
    """Cada variavel para num dia seu, que e o que a origem faz.

    O AgERA5 e um arquivo com atraso de publicacao, e nada obriga a que o
    atraso seja igual para as tres variaveis: cada uma vem do seu proprio zip,
    pedida no seu proprio job.
    """

    def __init__(self, datas_por_variavel, **kwargs):
        super().__init__(**kwargs)
        self.datas_por_variavel = dict(datas_por_variavel)

    def agera5_diario(self, *args, **kwargs):
        linhas = super().agera5_diario(*args, **kwargs)
        return [linha for linha in linhas
                if linha["date"] in self.datas_por_variavel.get(linha["variable"], DATAS)]


def test_the_job_window_is_true_for_every_variable_and_not_just_for_some(session,
                                                                        sitio_turcifal):
    """A janela do job era `min`/`max` sobre TODAS as linhas de uma vez.

    Com 3 dias de temperatura, 3 de precipitacao e 2 de radiacao, o job
    declarava 01/07--03/07: verdade para duas variaveis e FALSA para a
    terceira, com `succeeded` e `error: null`. Nada no job nem em linha nenhuma
    dizia que a radiacao tinha parado a meio. E o defeito de 29/08 outra vez,
    cortado por variavel em vez de por dia.

    A regra e a interseccao. As linhas do dia 3 continuam gravadas e contadas
    -- subdeclarar e seguro, sobredeclarar e uma mentira que ninguem consegue
    desmentir a partir da base.
    """
    cliente = _ClienteComJanelasDiferentes(
        {"solar_radiation_flux": ("2026-07-01", "2026-07-02")})
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.succeeded, job.error
    # todas as variaveis menos uma com os 3 dias, a da radiacao com 2
    esperadas = len(DATAS) * (METRICAS - 1) + 2
    assert job.rows_written == esperadas
    assert job.date_from == date(2026, 7, 1)
    assert job.date_to == date(2026, 7, 2)             # e nao 03/07, que so as outras cobrem
    assert len(_observacoes(session, sitio_turcifal)) == esperadas


def test_a_requested_variable_that_brought_nothing_fails_the_job(session, sitio_turcifal):
    """Uma variavel sem uma unica linha nao tem janela para intersectar.

    Este e o caso do achado: `_ler_netcdf_solto` devolve `([], lat, lon)` para
    um membro com eixo de tempo vazio, e vazio nao e erro a nivel nenhum --
    nem no cliente, nem aqui. A execucao gravava as outras variaveis, dizia
    `succeeded`, e declarava a janela delas como se cobrisse esta.
    """
    cliente = _ClienteComJanelasDiferentes({"solar_radiation_flux": ()})
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert "solar_radiation_flux" in job.error
    assert job.rows_written == 0
    assert _observacoes(session, sitio_turcifal) == []


def test_variables_with_no_day_in_common_fail_the_job(session, sitio_turcifal):
    """Sem um dia partilhado nao ha par de datas verdadeiro para todas."""
    cliente = _ClienteComJanelasDiferentes(
        {"2m_temperature": ("2026-07-01",), "precipitation_flux": ("2026-07-01",),
         "solar_radiation_flux": ("2026-07-03",)})
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert "2026-07-01" in job.error and "2026-07-03" in job.error
    assert _observacoes(session, sitio_turcifal) == []


def test_an_empty_response_no_longer_claims_the_requested_window(session, sitio_turcifal):
    """Zero linhas com `succeeded` a declarar a janela PEDIDA era o mesmo defeito puro.

    O `if linhas:` que protegia a atribuicao da janela deixava o job com as
    datas do PEDIDO quando nao vinha nada -- a afirmacao de cobertura mais
    falsa possivel, porque nao ha uma unica linha por tras dela.
    """
    cliente = _ClienteFalso(datas=())
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert "2m_temperature" in job.error
    assert job.rows_written == 0


def test_a_unit_that_disagrees_with_the_vocabulary_is_refused(session, sitio_turcifal):
    """A unidade da linha tem de bater certo com a do vocabulario. Um valor em
    Kelvin rotulado degC entra na base sem nada a assinalar e ja nao ha volta:
    o numero e plausivel e a unidade e credivel."""
    cliente = _ClienteFalso(unidades={"2m_temperature": "K"})
    job = sync_reanalysis(session, cliente, "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert "degC" in job.error and "K" in job.error
    assert _observacoes(session, sitio_turcifal) == []


# --- Regra 5: cada linha carrega a proveniencia da celula ------------------

def test_every_row_carries_the_cell_provenance(session, sitio_turcifal):
    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    linhas = _observacoes(session, sitio_turcifal)

    assert {linha.metric for linha in linhas} == {
        str(metrica) for metrica, _, _ in POR_VARIAVEL.values()}
    for linha in linhas:
        assert linha.source_type == SourceType.reanalysis
        # a linha NAO se declara uma medicao: e a saida de um modelo
        assert SourceType.is_measurement(linha.source_type) is False
        assert linha.processing_version == PROCESSING_VERSION
        assert linha.source_collection == DATASET_AGERA5
        assert linha.quality_flag == QualityFlag.valid
        assert linha.value_qualifier == ValueQualifier.exact
        assert linha.value_numeric is not None
        assert linha.plot_id is None

        evidencia = linha.evidence
        assert evidencia["cell_lat"] == CELULA_TURCIFAL[0]
        assert evidencia["cell_lon"] == CELULA_TURCIFAL[1]
        assert evidencia["cell_size_deg"] == 0.1
        assert evidencia["measured_at_site"] is False
        assert evidencia["site_lat"] == pytest.approx(TURCIFAL_LAT, abs=1e-9)
        assert evidencia["site_lon"] == pytest.approx(TURCIFAL_LON, abs=1e-9)
        # o ponto nao foi levantado no sitio: e o centroide do poligono da
        # AOI, e a linha tem de o dizer em vez de o deixar a convencao
        assert evidencia["site_point_source"] == "aoi_centroid"
        assert evidencia["site_code"] == "EUC-TUR-MET"
        assert evidencia["aoi_code"] == "EUC-TUR-MET-EO"
        assert evidencia["request_hash"] == job.request_hash
        assert evidencia["variable"] in POR_VARIAVEL


def test_the_recorded_distance_is_the_real_distance_from_site_to_cell(session, sitio_turcifal):
    """A celula do AgERA5 que contem Turcifal fica a ~5,4 km do sitio.

    E este numero que impede a leitura ingenua: a chuva gravada para este
    sitio nao e a chuva daquele campo. Um valor arredondado a zero, ou uma
    distancia que nao dependesse das coordenadas, tornava a linha
    indistinguivel de uma medicao local.
    """
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    for linha in _observacoes(session, sitio_turcifal):
        assert linha.evidence["distance_km"] == pytest.approx(5.412, abs=0.02)


def test_the_cell_footprint_is_recorded_in_both_directions(session, sitio_turcifal):
    """0,1 grau sao 11,1 km norte-sul mas so ~8,6 km este-oeste a esta
    latitude. Um so numero para as duas direccoes exagera a pegada da celula
    em 22% num dos eixos."""
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    linha = _observacoes(session, sitio_turcifal)[0]
    assert linha.evidence["cell_size_km_ns"] == pytest.approx(11.12, abs=0.02)
    assert linha.evidence["cell_size_km_ew"] == pytest.approx(8.64, abs=0.02)


def test_the_evidence_reports_the_box_actually_requested(session, sitio_turcifal):
    """A caixa transferida e MUITO maior do que a AOI: o CDS recusa uma caixa
    menor do que a celula da grelha. So se le a celula do sitio, mas o que foi
    pedido tem de ficar escrito -- senao o `evidence` afirma uma area que nao
    corresponde ao que houve."""
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    linha = _observacoes(session, sitio_turcifal)[0]
    norte, oeste, sul, este = linha.evidence["area_requested"]
    assert linha.evidence["area_expanded"] is True
    assert norte - sul == pytest.approx(0.4, abs=1e-6)
    assert este - oeste == pytest.approx(0.4, abs=1e-6)

    n_aoi, o_aoi, s_aoi, e_aoi = linha.evidence["area_aoi"]
    assert n_aoi - s_aoi == pytest.approx(0.025, abs=1e-9)
    assert sul < s_aoi and norte > n_aoi          # a caixa pedida contem a AOI


def test_the_daily_value_is_stamped_at_midnight_utc(session, sitio_turcifal):
    """A agregacao do AgERA5 e diaria: gravar meia-noite UTC e o unico instante
    honesto, inventar uma hora seria precisao que o dado nao tem."""
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    momentos = sorted({linha.observed_at.astimezone(timezone.utc)
                       for linha in _observacoes(session, sitio_turcifal)})
    assert momentos == [datetime.fromisoformat(f"{dia}T00:00:00+00:00") for dia in DATAS]


# --- Regra 6: a desduplicacao espelha a identidade, coluna a coluna --------

def test_dedup_query_mirrors_the_identity_on_site_id(session, sitio_turcifal, sitio_porto):
    """Dois sitios, mesma janela, mesma versao. Sem o site_id no filtro, a
    serie de Turcifal contava como ja existente para a do Porto e a segunda
    escrevia ZERO linhas -- com o job a dizer succeeded."""
    primeiro = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    segundo = sync_reanalysis(session, _ClienteFalso(celula=CELULA_PORTO), "EUC-PTO-MET", *JANELA)

    assert primeiro.rows_written == len(DATAS) * METRICAS
    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == len(DATAS) * METRICAS
    assert len(_observacoes(session, sitio_turcifal)) == len(DATAS) * METRICAS
    assert len(_observacoes(session, sitio_porto)) == len(DATAS) * METRICAS


def test_dedup_query_mirrors_the_identity_on_plot_id(session, sitio_turcifal):
    """A mesma serie ao nivel de uma parcela nao pode fazer a serie do sitio
    passar por ja gravada: sao duas geometrias e dois valores diferentes."""
    parcela = Plot(site_id=sitio_turcifal.site_id, code="EUC-TUR-MET-P1",
                   name="Parcela de referencia", purpose="canopy")
    session.add(parcela)
    session.flush()
    session.add(_linha_de_campo(sitio_turcifal.site_id, plot_id=parcela.id))
    session.commit()

    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    assert job.rows_written == len(DATAS) * METRICAS


def test_dedup_query_mirrors_the_identity_on_observed_at(session, sitio_turcifal):
    """A linha plantada e do dia do MEIO de uma serie com falha: 1 e 3 de
    julho vem do CDS, o dia 2 ja esta gravado.

    O dia 2 tem de ficar dentro da janela lida (senao a linha plantada nem
    seria devolvida pela consulta e o teste nao podia falhar). Sem o
    observed_at na chave, uma linha de 2 de julho tapava a temperatura dos
    outros dois dias.
    """
    session.add(_linha_de_campo(
        sitio_turcifal.site_id, observed_at=datetime(2026, 7, 2, tzinfo=timezone.utc)))
    session.commit()

    job = sync_reanalysis(session, _ClienteFalso(datas=("2026-07-01", "2026-07-03")),
                          "EUC-TUR-MET", *JANELA)
    assert job.rows_written == 2 * METRICAS            # 2 dias


def test_dedup_query_mirrors_the_identity_on_metric(session, sitio_turcifal):
    """A coluna `metric` da chave, provada pelo unico cenario que pode falhar.

    A versao anterior deste teste plantava uma linha de `wind_speed` no mesmo
    dia -- "difere em exactamente uma coluna", como as outras cinco. **Era
    vacua**: a consulta filtra `metric IN (metricas da serie)`, portanto a
    linha de vento nunca chegava a ser devolvida e nenhum mutante da chave a
    podia usar. Passava com a chave certa e com a chave errada. Foi retirada,
    e nao mantida com uma ressalva: um teste que nao pode falhar ocupa o lugar
    de um que pode, e esta suite ja teve dois desses.

    O que a substitui e a mesma propriedade por outro caminho: primeiro so a
    temperatura, depois as tres variaveis. As duas metricas novas tem de
    entrar nos MESMOS dias que ja estao gravados. Com uma chave so de dia, os
    tres dias contavam como completos e a precipitacao e a radiacao
    desapareciam em silencio, com o job a dizer succeeded.
    """
    primeiro = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA,
                               variaveis=["2m_temperature"])
    segundo = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    assert primeiro.rows_written == len(DATAS)         # 1 metrica x 3 dias
    assert segundo.rows_written == len(DATAS) * (METRICAS - 1)   # as restantes
    assert len(_observacoes(session, sitio_turcifal)) == len(DATAS) * METRICAS


def test_dedup_query_mirrors_the_identity_on_source_type(session, sitio_turcifal):
    """A leitura de campo do mesmo dia convive com a reanalise: sao origens
    diferentes da mesma grandeza, nao duplicados."""
    session.add(_linha_de_campo(
        sitio_turcifal.site_id, source_type=SourceType.observed_screening))
    session.commit()

    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    assert job.rows_written == len(DATAS) * METRICAS
    assert len(_observacoes(session, sitio_turcifal)) == len(DATAS) * METRICAS + 1


def test_dedup_query_mirrors_the_identity_on_processing_version(session, sitio_turcifal):
    """Outra versao do dataset produz outros numeros: e uma serie nova, nao uma
    repeticao. Se a chave ignorasse a versao, a serie reprocessada desaparecia
    em silencio."""
    session.add(_linha_de_campo(sitio_turcifal.site_id, processing_version="agera5-v1_1"))
    session.commit()

    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    assert job.rows_written == len(DATAS) * METRICAS
    assert len(_observacoes(session, sitio_turcifal)) == len(DATAS) * METRICAS + 1


def test_two_entries_for_the_same_day_and_metric_are_refused(session, sitio_turcifal):
    """Duas entradas para o mesmo dia e a mesma metrica nao cabem na
    identidade da observacao: gravar uma e descartar a outra seria escolher ao
    acaso pela ordem da resposta."""
    job = sync_reanalysis(session, _ClienteFalso(datas=("2026-07-01", "2026-07-01")),
                          "EUC-TUR-MET", *JANELA)

    assert job.status == JobStatus.failed
    assert "2026-07-01" in job.error
    assert "air_temperature" in job.error
    assert _observacoes(session, sitio_turcifal) == []


def test_the_request_hash_changes_with_the_window(session, sitio_turcifal):
    """O hash identifica o pedido. Duas janelas diferentes nao podem partilhar
    identidade, senao o rasto deixa de distinguir execucoes."""
    base = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    outra_janela = sync_reanalysis(
        session, _ClienteFalso(datas=(*DATAS, "2026-07-04")),
        "EUC-TUR-MET", "2026-07-01", "2026-07-04")
    igual = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    assert base.request_hash == igual.request_hash
    assert base.request_hash != outra_janela.request_hash


def test_dates_can_be_given_as_date_objects(session, sitio_turcifal):
    """O job guarda Date e o cliente quer texto ISO: a conversao e do servico,
    nao do chamador."""
    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET",
                          date(2026, 7, 1), date(2026, 7, 1) + timedelta(days=2))

    assert job.status == JobStatus.succeeded
    assert job.date_from == date(2026, 7, 1)
    assert job.date_to == date(2026, 7, 3)


# --- Regra 7: a politica de escolha da estacao e do chamador, e fica escrita -
#
# Estes testes sao sobre `sync_ipma`, que vive neste modulo (`weather/ingest.py`)
# e nao em `weather/ipma.py`. Ficam neste ficheiro por isso: e o ficheiro do
# modulo sob teste. O que exercita o CLIENTE do IPMA -- a ordem [lon, lat], o
# -99, as guardas do feed -- continua em tests/test_weather_ipma.py, contra o
# cliente real sobre MockTransport.

_ESTACOES_FALSAS = [
    {"station_id": "1210739", "station_name": "Torres Vedras, Dois Portos",
     "lat": 39.04389444, "lon": -9.179, "distance_km": 5.3399},
    {"station_id": "1210746", "station_name": "Santa Cruz (Aerodromo)",
     "lat": 39.12594166, "lon": -9.3790388, "distance_km": 15.2},
    {"station_id": "1210649", "station_name": "S. Gens",
     "lat": 41.18445, "lon": -8.64445, "distance_km": 249.1},
    {"station_id": "1210881", "station_name": "Olhao, EPPO",
     "lat": 37.033, "lon": -7.821, "distance_km": 259.7},
]

_INSTANTE_IPMA = "2026-08-20T13:00"


def _feed_ipma(instantes=(_INSTANTE_IPMA,), id_estacao="1210739"):
    """{instante: {id: registo}}, a forma do observations.json do IPMA.

    So temperatura e humidade: chega para haver linhas, e as guardas de feed
    (fuso e radiacao nocturna) vivem no cliente real, que aqui nao entra.
    """
    return {instante: {id_estacao: {"temperatura": 24.6, "humidade": 77.0}}
            for instante in instantes}


class _ClienteIpmaFalso:
    """Duplo do IPMAClient com a MESMA politica de tecto do cliente real.

    Repete a recusa acima do raio de proposito: se o duplo aceitasse tudo, um
    `raio_maximo_km` que nunca chegasse ao cliente passaria despercebido --
    o teste do tecto apertado ficaria verde com o argumento a ser ignorado.
    """

    def __init__(self, feed=None, estacoes=None, descartes=None):
        self._feed = _feed_ipma() if feed is None else feed
        self._estacoes = list(_ESTACOES_FALSAS if estacoes is None else estacoes)
        self.raios_recebidos = []
        # parte do contrato do cliente desde que a guarda de radiacao nocturna
        # passou a contar o que descarta: `sync_ipma` le a contagem daqui para
        # a gravar no evidence. Nao e um `getattr` com omissao do lado do
        # servico de proposito -- zero descartes e uma afirmacao, e um cliente
        # que nao saiba dizer quantos apagou nao pode fazer essa afirmacao por
        # omissao.
        self.descartes_por_estacao = dict(descartes or {})

    def stations(self):
        # `sync_ipma` nao chama isto: o numero de estacoes consideradas vem
        # dentro do que o `nearest_station` devolve, que e quem ordenou a
        # lista. Fica implementado na mesma, porque um duplo que so tem o que
        # hoje e chamado transforma cada uso novo do cliente numa falha de
        # teste alheia -- foi exactamente isso que atrasou este campo uma ronda.
        return list(self._estacoes)

    def nearest_station(self, lat, lon, raio_maximo_km=RAIO_MAXIMO_KM):
        self.raios_recebidos.append(raio_maximo_km)
        proxima = dict(min(self._estacoes, key=lambda e: e["distance_km"]),
                       stations_considered=len(self._estacoes))
        if proxima["distance_km"] > raio_maximo_km:
            raise ValueError(
                f"a estacao do IPMA mais proxima de ({lat}, {lon}) e "
                f"'{proxima['station_name']}' a {proxima['distance_km']:.1f} km, acima do "
                f"tecto de {raio_maximo_km:.0f} km.")
        return dict(proxima)

    def observations(self):
        return self._feed


# a estacao que o IPMA passa a publicar entre duas execucoes: mais proxima do
# que Dois Portos, portanto passa a ser a escolhida sem ninguem mudar nada
ESTACAO_NOVA = {"station_id": "1210999", "station_name": "Turcifal (estacao nova)",
                "lat": 39.0373, "lon": -9.2402, "distance_km": 0.4}


def _cliente_com_a_estacao_nova(instantes=(_INSTANTE_IPMA,)):
    return _ClienteIpmaFalso(
        feed=_feed_ipma(instantes, id_estacao=ESTACAO_NOVA["station_id"]),
        estacoes=[*_ESTACOES_FALSAS, ESTACAO_NOVA],
    )


def test_a_station_change_between_runs_fails_instead_of_discarding_in_silence(
    session, sitio_turcifal
):
    """O gatilho e o feed do IPMA mudar de estacoes, nao o raio.

    A estacao nao entra na identidade da observacao nem no `request_hash`.
    Publicada uma estacao mais proxima, o MESMO pedido passa a trazer as
    leituras dela para os mesmos instantes -- e todas batem na identidade das
    que ja la estao. Sem guarda, isto responde `succeeded` com zero linhas, que
    e indistinguivel de uma reexecucao legitima, e a serie da estacao nova
    desaparece sem deixar rasto: um job de zero linhas nao regista que estacao
    teria usado.
    """
    primeiro = sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")
    assert primeiro.status == JobStatus.succeeded

    segundo = sync_ipma(session, _cliente_com_a_estacao_nova(), "EUC-TUR-MET")

    assert segundo.status == JobStatus.failed
    # as DUAS estacoes nomeadas: com so uma delas, quem le o job nao sabe se o
    # que mudou foi a origem ou o sitio
    assert "1210739" in segundo.error
    assert ESTACAO_NOVA["station_id"] in segundo.error
    # e a serie da estacao antiga fica intacta -- nao se apaga o que ja estava
    linhas = _observacoes(session, sitio_turcifal)
    assert {linha.evidence["station_id"] for linha in linhas} == {"1210739"}


def test_a_partial_write_after_a_station_change_is_not_refused(session, sitio_turcifal):
    """A fronteira que a guarda nao pode atravessar: escreveu alguma coisa, passa.

    Depois de uma passagem de estacao, as 23 execucoes horarias seguintes
    continuam a ter horas NOVAS para escrever e a janela de 24 h continua a
    conter linhas da estacao antiga. Se a guarda disparasse tambem nestas, o
    `except` do sincronizador fazia `rollback` das linhas novas: a serie ficava
    congelada 24 h e so recuperava na execucao h+24, com margem zero -- um
    atraso de uma hora perdia essa hora para sempre.

    A troca certa e falhar so quando nao se escreveu NADA, que e o caso que a
    guarda existe para apanhar. Aqui a mudanca de estacao continua visivel sem
    nenhum job `failed`: a linha nova leva o `station_id` da estacao nova.
    """
    sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")

    segundo = sync_ipma(
        session,
        _cliente_com_a_estacao_nova(("2026-08-20T13:00", "2026-08-20T14:00")),
        "EUC-TUR-MET",
    )

    # as 13:00 colidem com as da estacao antiga; as 14:00 sao novas
    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 2
    assert segundo.error is None
    novas = [linha for linha in _observacoes(session, sitio_turcifal)
             if linha.observed_at.hour == 14]
    assert len(novas) == 2
    for linha in novas:
        assert linha.evidence["station_id"] == ESTACAO_NOVA["station_id"]


def test_the_same_station_twice_is_still_a_clean_no_op(session, sitio_turcifal):
    """O lado verde da guarda, e nao e cerimonia: uma guarda que disparasse
    sempre que houvesse descarte partia a reexecucao de hora a hora, que e o
    modo normal de funcionamento desta ingestao."""
    sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")

    segundo = sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert segundo.error is None


def test_a_handover_that_writes_everything_is_not_refused(session, sitio_turcifal):
    """A guarda so olha para o que foi DESCARTADO, e nao para a janela toda.

    Aqui a estacao nova traz horas novas de um e do outro lado da hora que a
    antiga ja tinha: a janela lida contem as linhas da antiga, mas nenhuma
    leitura colide. Uma guarda que olhasse para a janela em vez do descarte
    recusava esta execucao -- e recusar aqui era trocar uma perda silenciosa
    por outra, porque estas quatro leituras nao existem em lado nenhum.
    """
    sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")

    segundo = sync_ipma(
        session,
        _cliente_com_a_estacao_nova(("2026-08-20T12:00", "2026-08-20T14:00")),
        "EUC-TUR-MET",
    )

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 4
    assert len(_observacoes(session, sitio_turcifal)) == 6


def test_another_processing_version_in_the_window_is_not_a_station_change(
    session, sitio_turcifal
):
    """A consulta das estacoes ja gravadas repete a identidade, e nao um
    subconjunto conveniente.

    Uma serie da mesma estacao ou de outra, gravada sob OUTRA
    `processing_version`, coexiste com esta por construcao -- e para isso que a
    versao entra na chave. Se a consulta a ignorasse, uma reexecucao normal
    passava a falhar por causa de uma serie que nao colide com nada.
    """
    sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")
    outra_versao = _observacoes(session, sitio_turcifal)[0]
    session.add(Observation(
        site_id=outra_versao.site_id, plot_id=None,
        observed_at=outra_versao.observed_at, metric=outra_versao.metric,
        unit=outra_versao.unit, value_numeric=outra_versao.value_numeric,
        value_qualifier=ValueQualifier.exact, source_type=SourceType.weather_observed,
        quality_flag=QualityFlag.unchecked, source_collection=outra_versao.source_collection,
        processing_version="ipma-stations-v0",
        evidence={"station_id": "9999999", "station_name": "Estacao de outra versao",
                  "measured_at_site": False},
    ))
    session.commit()

    segundo = sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert segundo.error is None


def test_another_source_type_in_the_window_is_not_a_station_change(
    session, sitio_turcifal
):
    """O filtro `source_type` da consulta e matavel, e este teste e quem o mata.

    Declarei-o na ronda 1 como linha sem mutante, com o argumento de que
    nenhuma outra origem do `src/` poe `station_id` no `evidence`. O argumento
    era verdadeiro e a conclusao errada: `POST /api/v1/observations` aceita
    `source_type`, `processing_version` e `evidence` arbitrarios do cliente.
    Uma linha inserida por essa porta, com um `station_id` no `evidence`, entra
    na consulta assim que o filtro cair -- e a partir dai toda a reexecucao
    horaria com descarte falha a dizer que a estacao mudou.
    """
    sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")
    gravada = _observacoes(session, sitio_turcifal)[0]
    session.add(Observation(
        site_id=gravada.site_id, plot_id=None,
        observed_at=gravada.observed_at, metric=gravada.metric,
        unit=gravada.unit, value_numeric=gravada.value_numeric,
        value_qualifier=ValueQualifier.exact,
        # mesma versao de processamento, outra origem: e o que isola o filtro
        # que este teste existe para fixar
        source_type=SourceType.observed_screening,
        quality_flag=QualityFlag.unchecked, source_collection=gravada.source_collection,
        processing_version=PROCESSING_VERSION_IPMA,
        evidence={"station_id": "9999999", "station_name": "Estacao de outra origem",
                  "measured_at_site": False},
    ))
    session.commit()

    segundo = sync_ipma(session, _ClienteIpmaFalso(), "EUC-TUR-MET")

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert segundo.error is None


def test_without_an_explicit_radius_the_client_policy_is_the_one_recorded(
    session, sitio_turcifal
):
    """Omitir o raio nao pode inventar um: mantem-se o tecto do cliente, e e
    esse que fica escrito na linha."""
    cliente = _ClienteIpmaFalso()

    job = sync_ipma(session, cliente, "EUC-TUR-MET")

    assert job.status == JobStatus.succeeded
    assert cliente.raios_recebidos == [RAIO_MAXIMO_KM]
    for linha in _observacoes(session, sitio_turcifal):
        assert linha.evidence["station_search_radius_km"] == RAIO_MAXIMO_KM


def test_the_radius_given_by_the_caller_reaches_the_client_and_the_row(
    session, sitio_turcifal
):
    """O tecto passou a ser alcancavel do ponto de entrada. Provar as duas
    pontas: chega ao cliente (senao a politica nao muda nada) e fica na linha
    (senao ninguem sabe depois com que tecto a estacao foi escolhida)."""
    cliente = _ClienteIpmaFalso()

    job = sync_ipma(session, cliente, "EUC-TUR-MET", raio_maximo_km=12.5)

    assert job.status == JobStatus.succeeded
    assert cliente.raios_recebidos == [12.5]
    for linha in _observacoes(session, sitio_turcifal):
        assert linha.evidence["station_search_radius_km"] == 12.5


def test_a_tighter_radius_than_the_nearest_station_fails_the_job(session, sitio_turcifal):
    """Apertar o tecto abaixo da estacao mais proxima nao pode dar uma serie:
    e o caso que justifica o parametro existir."""
    cliente = _ClienteIpmaFalso()

    job = sync_ipma(session, cliente, "EUC-TUR-MET", raio_maximo_km=1.0)

    assert job.status == JobStatus.failed
    assert "Dois Portos" in job.error
    assert _observacoes(session, sitio_turcifal) == []


def test_the_duplicate_instant_error_does_not_send_the_operator_to_a_window(
    session, sitio_turcifal
):
    """O feed do IPMA pode escrever o mesmo instante de duas maneiras
    ("13:00" e "13:00:00"): sao duas chaves diferentes e o mesmo momento.

    A mensagem tem de servir as duas fontes. Mandar «rever a janela ou as
    variaveis do pedido» manda o operador do IPMA procurar onde nao ha nada:
    aquele caminho nao tem janela nem variaveis, o URL e fixo e devolve sempre
    as ultimas 24 horas.
    """
    cliente = _ClienteIpmaFalso(feed=_feed_ipma(("2026-08-20T13:00", "2026-08-20T13:00:00")))

    job = sync_ipma(session, cliente, "EUC-TUR-MET")

    assert job.status == JobStatus.failed
    assert "2026-08-20T13:00:00+00:00" in job.error
    assert "air_temperature" in job.error or "relative_humidity" in job.error
    assert "janela" not in job.error
    assert "variaveis" not in job.error
    assert _observacoes(session, sitio_turcifal) == []


# --- o job.error diz ONDE, e nao so o que -----------------------------------

def _feed_com_registo_estragado():
    """Um feed em que o registo de uma hora e texto em vez de mapa.

    Nao e um caso que uma guarda nossa apanhe: e o AttributeError de dentro de
    uma biblioteca a que o desenho desta camada chama "o rasto util e a linha
    na base". Sem o rasto, a linha diz `'str' object has no attribute 'get'` e
    mais nada.
    """
    feed = dict(_feed_ipma())
    feed[_INSTANTE_IPMA] = {"1210739": "isto devia ser um registo"}
    return feed


def test_an_unexpected_failure_records_where_it_happened(session, sitio_turcifal):
    """`AttributeError: 'str' object has no attribute 'get'` sem localizacao e
    um rasto que nao serve para nada.

    Quem opera a ingestao le a linha do job semanas depois e nao tem os logs do
    processo que a produziu. O `_motivo_de_falha` do CDS ja guardava a cauda do
    traceback pela mesma razao; este caminho nao guardava nenhuma.
    """
    cliente = _ClienteIpmaFalso(feed=_feed_com_registo_estragado())

    job = sync_ipma(session, cliente, "EUC-TUR-MET")

    assert job.status == JobStatus.failed
    assert job.error.startswith("AttributeError:")
    # o ficheiro e a funcao onde o defeito esta, que era o que faltava
    assert "ipma.py" in job.error
    assert "linhas_da_estacao" in job.error
    assert _observacoes(session, sitio_turcifal) == []


def test_the_message_comes_first_and_survives_a_trace_that_does_not_fit():
    """A mensagem e o que diz o que aconteceu, e e ela que sobrevive ao corte.

    Duas metades, e as duas fazem falta. Com uma mensagem curta ha espaco e o
    rasto TEM de aparecer, depois dela. Com uma mensagem que enche o limite
    sozinha, o que se perde e o rasto e nao a mensagem: pos o rasto a frente e
    os 2000 caracteres passavam a poder comer a unica parte que o operador (e
    os testes deste ficheiro) procuram dentro do `job.error`.
    """
    try:
        raise ValueError("curta")
    except ValueError as erro:
        com_espaco = _texto_do_erro(erro)

    assert com_espaco.startswith("ValueError: curta\n-- cauda do rasto --\n")
    assert "test_weather_ingest.py" in com_espaco

    try:
        raise ValueError("x" * 4000)
    except ValueError as erro:
        sem_espaco = _texto_do_erro(erro)

    assert len(sem_espaco) <= 2000
    assert sem_espaco.startswith("ValueError: xxx")
    assert "cauda do rasto" not in sem_espaco


def test_the_trace_kept_is_the_tail_and_not_the_head():
    """Os quadros de cima sao sempre os mesmos; o que localiza o defeito e o
    mais interior, que fica no fim. Mesma escolha do `_motivo_de_falha` do CDS.
    """
    def mais_fundo():
        raise ValueError("rebentou")

    def pelo_meio():
        mais_fundo()

    try:
        pelo_meio()
    except ValueError as erro:
        curto = _cauda_do_rasto(erro, 120)
        inteiro = _cauda_do_rasto(erro, 10_000)

    assert "mais_fundo" in inteiro and "pelo_meio" in inteiro
    # apertado, o que se perde e a cabeca: o quadro interior fica
    assert curto.startswith("...")
    assert "mais_fundo" in curto
    assert "pelo_meio" not in curto


def test_an_exception_with_no_trace_still_gives_the_message():
    """Uma excepcao construida a mao nao tem rasto nenhum: a linha do job passa
    a ser so a mensagem, e nao um separador a apontar para o vazio.

    E um CONTROLO, e nao um teste da correccao: passa tal e qual contra a
    versao anterior do ficheiro, porque prende o que a mudanca NAO podia
    alterar. O que ele defende de facto e o `if rasto else texto` -- sem essa
    condicao, toda a falha sem rasto passava a acabar num cabecalho seguido de
    nada.
    """
    texto = _texto_do_erro(ValueError("sem rasto"))

    assert texto == "ValueError: sem rasto"
