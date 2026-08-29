"""Ingestao da reanalise AgERA5: o que se grava, e o que a linha admite sobre si.

Nenhum teste toca a rede. O cliente entra por argumento e e sempre um duplo
que devolve linhas ja normalizadas -- exactamente o formato que o
`CDSClient.agera5_diario` produz -- e que reutiliza o `expandir_area` real do
cliente, para que a caixa que aparece na proveniencia seja a caixa que o CDS
teria mesmo recebido.
"""

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from shapely.geometry import shape
from sqlalchemy import event, func, select

from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, JobStatus, QualityFlag, SourceType, ValueQualifier,
)
from resoiltwin.geo import geojson_to_wkt_element, wkb_to_geojson
from resoiltwin.models import Aoi, IngestionJob, Observation, Plot, Site
from resoiltwin.weather.cds import DATASET_AGERA5, expandir_area
from resoiltwin.weather.ingest import PROCESSING_VERSION, sync_reanalysis
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

# variavel do AgERA5 -> (metrica, unidade, valor). Os tres valores sao os que a
# verificacao real da Task 2 leu para 15/07/2026 em Turcifal.
POR_VARIAVEL = {
    "2m_temperature": (WeatherMetric.air_temperature, "degC", 21.68),
    "precipitation_flux": (WeatherMetric.precipitation, "mm", 0.0),
    "solar_radiation_flux": (WeatherMetric.solar_radiation, "W/m2", 313.71),
}
VARIAVEIS = tuple(POR_VARIAVEL)


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

    def __init__(self, datas=DATAS, celula=CELULA_TURCIFAL, unidades=None):
        self.datas = tuple(datas)
        self.celula = celula
        self.unidades = unidades or {}
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

    assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0


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
    assert job.rows_written == 9                       # 3 metricas x 3 dias
    assert job.job_type == "reanalysis_sync"
    assert job.aoi_id == sitio_turcifal.id
    assert job.date_from == date(2026, 7, 1)
    assert job.date_to == date(2026, 7, 3)
    assert job.processing_version == PROCESSING_VERSION
    assert job.request_hash
    assert job.finished_at is not None
    assert job.error is None
    assert len(_observacoes(session, sitio_turcifal)) == 9


def test_second_identical_run_writes_nothing(session, sitio_turcifal):
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    segundo = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert len(_observacoes(session, sitio_turcifal)) == 9


def test_a_new_day_is_added_without_rewriting_the_old_ones(session, sitio_turcifal):
    """Idempotencia nao e "nao escrever nada na segunda vez": e escrever
    exactamente o que falta."""
    sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    segundo = sync_reanalysis(session, _ClienteFalso(datas=(*DATAS, "2026-07-04")),
                              "EUC-TUR-MET", "2026-07-01", "2026-07-04")

    assert segundo.rows_written == 3                   # so o dia novo, 3 metricas
    assert len(_observacoes(session, sitio_turcifal)) == 12


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

    assert primeiro.rows_written == 9
    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 9
    assert len(_observacoes(session, sitio_turcifal)) == 9
    assert len(_observacoes(session, sitio_porto)) == 9


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
    assert job.rows_written == 9


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
    assert job.rows_written == 6                       # 3 metricas x 2 dias


def test_dedup_query_mirrors_the_identity_on_metric(session, sitio_turcifal):
    """Outra metrica, mesmo dia: uma linha de vento nao pode bloquear a
    temperatura do dia 1.

    Ressalva registada, porque conta: este teste sozinho nao consegue falhar.
    A consulta filtra por `metric IN (metricas da serie)`, portanto a linha de
    vento nem chega a ser devolvida; so um mutante que tirasse ao mesmo tempo
    o filtro e a metrica da chave o faria cair. Quem prova mesmo a metrica na
    chave e o teste seguinte.
    """
    session.add(_linha_de_campo(
        sitio_turcifal.site_id, metric=WeatherMetric.wind_speed, unit="m/s"))
    session.commit()

    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    assert job.rows_written == 9


def test_a_metric_added_later_is_written_next_to_the_ones_already_there(session, sitio_turcifal):
    """Primeiro so a temperatura, depois as tres variaveis. As duas metricas
    novas tem de entrar nos MESMOS dias que ja estao gravados.

    E este o teste que carrega a metrica na chave de desduplicacao: com uma
    chave so de dia, os tres dias ja escritos contavam como completos e a
    precipitacao e a radiacao desapareciam em silencio, com o job a dizer
    succeeded.
    """
    primeiro = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA,
                               variaveis=["2m_temperature"])
    segundo = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)

    assert primeiro.rows_written == 3                  # 1 metrica x 3 dias
    assert segundo.rows_written == 6                   # as outras 2 metricas x 3 dias
    assert len(_observacoes(session, sitio_turcifal)) == 9


def test_dedup_query_mirrors_the_identity_on_source_type(session, sitio_turcifal):
    """A leitura de campo do mesmo dia convive com a reanalise: sao origens
    diferentes da mesma grandeza, nao duplicados."""
    session.add(_linha_de_campo(
        sitio_turcifal.site_id, source_type=SourceType.observed_screening))
    session.commit()

    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    assert job.rows_written == 9
    assert len(_observacoes(session, sitio_turcifal)) == 10


def test_dedup_query_mirrors_the_identity_on_processing_version(session, sitio_turcifal):
    """Outra versao do dataset produz outros numeros: e uma serie nova, nao uma
    repeticao. Se a chave ignorasse a versao, a serie reprocessada desaparecia
    em silencio."""
    session.add(_linha_de_campo(sitio_turcifal.site_id, processing_version="agera5-v1_1"))
    session.commit()

    job = sync_reanalysis(session, _ClienteFalso(), "EUC-TUR-MET", *JANELA)
    assert job.rows_written == 9
    assert len(_observacoes(session, sitio_turcifal)) == 10


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
