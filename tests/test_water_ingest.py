"""Ingestao do balanco hidrico: o que se grava, e o que a linha admite sobre si.

Nenhum teste toca a rede, e nenhum precisa de duplo nenhum: ao contrario da
meteorologia, esta camada le as entradas **da base**. O que aqui se monta sao
linhas de observacao reais, escritas pela suite, e o que se verifica e o que a
ingestao faz com elas.

Quatro decisoes ficam presas aqui, e nenhuma se ve olhando para o numero da
serie de saida:

1. **A capacidade utilizavel viaja em cada linha.** E o parametro que domina o
   resultado, ninguem o mediu nestes sitios, e entra tambem na identidade da
   linha -- duas capacidades diferentes sao duas series diferentes, nao duas
   execucoes da mesma.
2. **Uma serie de entrada tem UMA proveniencia na janela inteira.** A
   precipitacao existe hoje como reanalise E como estacao; escolhe-se uma, a
   linha diz qual, e diz tambem quais estavam disponiveis. Os dias que a
   escolhida nao tem ficam por balancar em vez de serem preenchidos pela outra.
3. **Um dia indeterminado grava-se como intervalo, nunca como exacto.** O
   estado inicial do reservatorio nao e conhecido; escrever `exact` com o
   minimo, com o maximo ou com a media era reinventa-lo pela porta de tras.
4. **Nenhuma entrada nao e zero linhas a dizer sucesso.** O job falha e diz
   porque.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, JobStatus, QualityFlag, SourceType, ValueQualifier,
)
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.models import Aoi, IngestionJob, Observation, Site
from resoiltwin.water.balance import VERSAO_DO_BALANCO
from resoiltwin.water.ingest import (
    JOB_TYPE, METRICA_DA_AGUA, UNIDADE_DA_AGUA, processing_version_do_balanco,
    sync_water_balance,
)

TURCIFAL_LON, TURCIFAL_LAT = -9.240247, 39.037317

# a versao de processamento das linhas de reanalise que a Fase C ja grava
VERSAO_REANALISE = "agera5-v2_0"
VERSAO_ESTACAO = "ipma-stations-v1"

CAPACIDADE = 100.0

# os nomes das metricas de entrada escritos POR EXTENSO, e nao importados do
# vocabulario: um teste que compare a constante consigo propria continua verde
# no dia em que ela mudar de valor por engano.
PRECIPITACAO = "precipitation"
ET0 = "reference_evapotranspiration"


def _quadrado(lon: float, lat: float, lado_graus: float = 0.025) -> dict:
    meio = lado_graus / 2
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - meio, lat - meio], [lon + meio, lat - meio],
            [lon + meio, lat + meio], [lon - meio, lat + meio], [lon - meio, lat - meio],
        ]],
    }


def _sitio(session, site_code, aoi_code, status=AoiStatus.approved):
    site = Site(code=site_code, name=f"Sitio {site_code}")
    aoi = Aoi(
        site=site, code=aoi_code, purpose="earth_observation",
        geometry=geojson_to_wkt_element(_quadrado(TURCIFAL_LON, TURCIFAL_LAT)),
        geometry_provenance=(
            GeometryProvenance.surveyed if status == AoiStatus.approved
            else GeometryProvenance.provisional_pending_kml
        ),
        status=status,
        approved_by="site-manager" if status == AoiStatus.approved else None,
    )
    session.add(aoi)
    session.commit()
    return site


@pytest.fixture
def sitio(session):
    return _sitio(session, "EUC-TUR-BAL", "EUC-TUR-BAL-EO")


def _entrada(session, sitio, dia, metrica, valor, source_type=SourceType.reanalysis,
             processing_version=VERSAO_REANALISE, unidade="mm", hora=0,
             coleccao="agera5-daily"):
    """Uma linha de entrada tal como a Fase C a grava."""
    observacao = Observation(
        site_id=sitio.id,
        plot_id=None,
        observed_at=datetime(dia.year, dia.month, dia.day, hora, tzinfo=timezone.utc),
        metric=metrica,
        unit=unidade,
        value_numeric=valor,
        value_qualifier=ValueQualifier.exact,
        source_type=source_type,
        quality_flag=QualityFlag.valid,
        source_collection=coleccao,
        processing_version=processing_version,
        evidence={"escrito_por": "tests/test_water_ingest.py"},
    )
    session.add(observacao)
    session.commit()
    return observacao


def _serie_de_reanalise(session, sitio, inicio, dias, precipitacao=0.0, et0=30.0):
    """`dias` dias contiguos de chuva e de ET0, os dois de reanalise."""
    escritas = []
    for i in range(dias):
        dia = inicio + timedelta(days=i)
        escritas.append(_entrada(session, sitio, dia, PRECIPITACAO, precipitacao))
        escritas.append(_entrada(session, sitio, dia, ET0, et0))
    return escritas


def _linhas_de_agua(session, sitio, versao=None):
    consulta = select(Observation).where(
        Observation.site_id == sitio.id,
        Observation.metric == METRICA_DA_AGUA,
    ).order_by(Observation.observed_at)
    if versao is not None:
        consulta = consulta.where(Observation.processing_version == versao)
    return list(session.scalars(consulta))


# --- o que se grava -----------------------------------------------------------


def test_a_balanced_day_is_written_as_simulated_and_never_as_a_measurement(session, sitio):
    """Um balanco nao e uma medicao: o `source_type` e o unico sitio onde essa
    distincao sobrevive a qualquer mudanca de esquema."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 5)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-05", CAPACIDADE)

    assert job.status == JobStatus.succeeded
    assert job.job_type == JOB_TYPE
    assert job.rows_written == 5
    linhas = _linhas_de_agua(session, sitio)
    assert len(linhas) == 5
    assert {linha.source_type for linha in linhas} == {SourceType.simulated}
    assert not SourceType.is_measurement(SourceType.simulated)
    assert {linha.metric for linha in linhas} == {METRICA_DA_AGUA}
    assert {linha.unit for linha in linhas} == {UNIDADE_DA_AGUA}
    assert {linha.evidence["measured_at_site"] for linha in linhas} == {False}


def test_the_capacity_that_dominates_the_result_travels_in_every_row(session, sitio):
    """Ninguem mediu a capacidade utilizavel destes sitios. Sem ela na linha, a
    linha nao e auditavel: o numero nao se pode refazer nem contestar."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)

    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", 137.0)

    linhas = _linhas_de_agua(session, sitio)
    assert linhas
    for linha in linhas:
        assert linha.evidence["available_water_capacity_mm"] == 137.0
        # e o que impede o numero de passar por medido
        assert linha.evidence["capacity_is_measured"] is False


def test_every_row_says_where_each_input_series_came_from(session, sitio):
    """Um balanco alimentado por reanalise nao e o mesmo que um alimentado por
    estacao, e a linha tem de permitir distinguir os dois."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)

    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    linha = _linhas_de_agua(session, sitio)[0]
    entradas = linha.evidence["inputs"]
    assert set(entradas) == {PRECIPITACAO, ET0}
    for nome in (PRECIPITACAO, ET0):
        assert entradas[nome]["source_type"] == "reanalysis"
        assert entradas[nome]["processing_version"] == VERSAO_REANALISE
        assert entradas[nome]["source_collection"] == "agera5-daily"


def test_the_row_records_the_segment_the_restart_and_the_runoff(session, sitio):
    """O que a Task 2 devolve sobre o segmento nao se recupera do numero: sem
    isto, dois pontos separados por um buraco de dez dias parecem contiguos."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 2, precipitacao=300.0, et0=0.0)

    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-02", CAPACIDADE)

    linhas = _linhas_de_agua(session, sitio)
    assert [linha.evidence["segment"] for linha in linhas] == [0, 0]
    assert [linha.evidence["days_since_restart"] for linha in linhas] == [0, 1]
    assert [linha.evidence["determined"] for linha in linhas] == [True, True]
    # 300 mm sobre um reservatorio de 100 transbordam -- e sem o escoamento
    # gravado, um dia cheio e um dia em que se perderam 200 mm sao a mesma linha.
    # A agua do primeiro dia ja esta determinada (as duas trajectorias saturaram
    # no tecto) e o escoamento AINDA NAO: quanto transbordou depende de quao
    # cheio o reservatorio estava, que continua por saber. Colapsar o escoamento
    # so porque a agua colapsou era responder a uma pergunta que ninguem fez.
    assert linhas[0].evidence["runoff_min_mm"] == 200.0
    assert linhas[0].evidence["runoff_max_mm"] == 300.0


def test_the_written_row_points_at_the_input_rows_it_came_from(session, sitio):
    """`derived_from` fecha a cadeia: da linha de agua chega-se as duas linhas
    de entrada exactas, e nao apenas a proveniencia delas em texto."""
    escritas = _serie_de_reanalise(session, sitio, date(2026, 7, 1), 1)

    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-01", CAPACIDADE)

    linha = _linhas_de_agua(session, sitio)[0]
    assert sorted(linha.derived_from) == sorted(entrada.id for entrada in escritas)


# --- o intervalo indeterminado ------------------------------------------------


def test_an_undetermined_day_is_written_as_a_range_and_never_as_exact(session, sitio):
    """O estado inicial do reservatorio nao e conhecido. Enquanto as duas
    trajectorias nao se encontram, o que se sabe e um intervalo -- e gravar
    `exact` com o minimo, com o maximo ou com a media era reinventar o estado
    inicial pela porta de tras, depois de todo o trabalho para nao o fazer."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 5, precipitacao=0.0, et0=30.0)

    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-05", CAPACIDADE)

    linhas = _linhas_de_agua(session, sitio)
    assert [linha.evidence["determined"] for linha in linhas] == [
        False, False, False, True, True,
    ]
    primeiro = linhas[0]
    assert primeiro.value_qualifier == ValueQualifier.range
    assert primeiro.value_numeric is None
    # 0 e 70, e nao 35 (a media), nem 0 sozinho, nem 70 sozinho
    assert primeiro.value_min == 0.0
    assert primeiro.value_max == 70.0


def test_a_determined_day_is_written_as_an_exact_value(session, sitio):
    """Controlo negativo do teste acima: a partir do dia em que as duas
    trajectorias se encontram, o numero ja nao depende do que ninguem mediu, e
    grava-lo como intervalo era admitir uma ignorancia que ja nao existe."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 5, precipitacao=0.0, et0=30.0)

    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-05", CAPACIDADE)

    ultimo = _linhas_de_agua(session, sitio)[-1]
    assert ultimo.evidence["determined"] is True
    assert ultimo.value_qualifier == ValueQualifier.exact
    assert ultimo.value_numeric == 0.0
    assert ultimo.value_min is None
    assert ultimo.value_max is None


def test_a_series_that_never_determines_is_written_all_the_same(session, sitio):
    """Com uma capacidade grande sobre uma serie curta, o intervalo pode nao
    colapsar uma unica vez. Recusar perdia o que se sabe de facto -- "esta
    algures entre estes dois numeros" e informacao verdadeira."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 5, precipitacao=0.0, et0=1.0)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-05", 500.0)

    assert job.status == JobStatus.succeeded
    assert job.rows_written == 5
    linhas = _linhas_de_agua(session, sitio)
    assert [linha.evidence["determined"] for linha in linhas] == [False] * 5
    assert {linha.value_qualifier for linha in linhas} == {ValueQualifier.range}
    assert all(linha.value_numeric is None for linha in linhas)
    assert all(linha.value_min < linha.value_max for linha in linhas)


# --- proveniencias concorrentes -----------------------------------------------


def test_when_both_provenances_have_the_same_day_only_one_is_chosen_and_named(session, sitio):
    """A precipitacao existe hoje como reanalise E como estacao para o mesmo
    dia. Escolhe-se uma para a serie inteira, e a linha diz qual foi e quais
    estavam disponiveis -- sem a segunda metade, ninguem sabe que houve
    escolha nenhuma."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)
    for i in range(3):
        _entrada(session, sitio, date(2026, 7, 1) + timedelta(days=i), PRECIPITACAO, 8.0,
                 source_type=SourceType.weather_observed,
                 processing_version=VERSAO_ESTACAO, coleccao="ipma-observations")

    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    chuva = _linhas_de_agua(session, sitio)[0].evidence["inputs"][PRECIPITACAO]
    assert chuva["source_type"] == "reanalysis"
    assert chuva["processing_version"] == VERSAO_REANALISE
    assert chuva["provenances_available"] == ["reanalysis", "weather_observed"]
    # o valor usado e o da escolhida, e nao o da outra: sem isto, a linha podia
    # nomear uma proveniencia e ter sido alimentada pela outra
    assert chuva["value_mm"] == 0.0


def test_the_two_provenances_are_never_mixed_across_days_of_the_same_series(session, sitio):
    """A reanalise cobre tres dias e a estacao cobre o quarto. Preencher o
    quarto com a estacao produzia uma serie cujo numero do dia N depende de uma
    cadeia de dias de proveniencias diferentes, sem que nenhuma linha o diga.
    O dia sem a proveniencia escolhida fica por balancar, e a linha conta-o."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)
    # ET0 tambem no quarto dia: o unico que falta ali e a chuva da reanalise
    _entrada(session, sitio, date(2026, 7, 4), ET0, 30.0)
    _entrada(session, sitio, date(2026, 7, 4), PRECIPITACAO, 8.0,
             source_type=SourceType.weather_observed, processing_version=VERSAO_ESTACAO)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-04", CAPACIDADE)

    linhas = _linhas_de_agua(session, sitio)
    assert [linha.observed_at.date() for linha in linhas] == [
        date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3),
    ]
    assert job.date_to == date(2026, 7, 3)
    # o dia de ET0 que ficou sem chuva da proveniencia escolhida fica contado:
    # sem isto, a serie encurta e nada na base diz que encurtou
    assert linhas[0].evidence["inputs"][ET0]["days_without_the_other_input"] == 1


def test_an_hourly_input_series_is_refused_instead_of_being_silently_aggregated(session, sitio):
    """A estacao publica de hora a hora e o balanco e diario. Somar 24 leituras
    num total diario e uma segunda decisao -- o que fazer com um dia de cinco
    horas -- e um dia incompleto lido como dia seco e exactamente a forma de
    defeito que este projecto persegue. Enquanto essa decisao nao for tomada, o
    job falha e nomeia o dia."""
    for i in range(3):
        _entrada(session, sitio, date(2026, 7, 1) + timedelta(days=i), ET0, 30.0)
    for hora in (9, 10, 11):
        _entrada(session, sitio, date(2026, 7, 1), PRECIPITACAO, 2.0, hora=hora,
                 source_type=SourceType.weather_observed, processing_version=VERSAO_ESTACAO)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert job.status == JobStatus.failed
    assert job.rows_written == 0
    assert "2026-07-01" in job.error
    assert PRECIPITACAO in job.error
    assert _linhas_de_agua(session, sitio) == []


def test_two_processing_versions_of_the_same_input_series_are_refused(session, sitio):
    """Duas versoes de processamento da mesma serie dao dois valores possiveis
    para o mesmo dia; escolher uma pela ordem da consulta era escolher ao acaso
    e nao deixar rasto da escolha."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)
    _entrada(session, sitio, date(2026, 7, 2), PRECIPITACAO, 9.0,
             processing_version="agera5-v3_0")

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert job.status == JobStatus.failed
    assert "agera5-v2_0" in job.error and "agera5-v3_0" in job.error
    assert _linhas_de_agua(session, sitio) == []


def test_running_over_a_window_already_written_from_another_provenance_fails(session, sitio):
    """Se a proveniencia de entrada mudar, a re-execucao bate na identidade das
    linhas antigas e escreve zero -- indistinguivel de uma re-execucao
    legitima. A serie nova desaparecia sem deixar rasto."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)
    sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)
    for linha in _linhas_de_agua(session, sitio):
        evidencia = dict(linha.evidence)
        entradas = dict(evidencia["inputs"])
        entradas[PRECIPITACAO] = {**entradas[PRECIPITACAO], "source_type": "weather_observed"}
        evidencia["inputs"] = entradas
        linha.evidence = evidencia
    session.commit()

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert job.status == JobStatus.failed
    assert "weather_observed" in job.error and "reanalysis" in job.error


# --- entradas em falta --------------------------------------------------------


def test_no_input_at_all_fails_the_job_and_says_which_series_is_missing(session, sitio):
    """Zero linhas a dizer `succeeded` e a forma exacta do defeito que este
    projecto ja teve: um job verde a esconder a perda de uma serie."""
    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert job.status == JobStatus.failed
    assert job.rows_written == 0
    assert PRECIPITACAO in job.error
    # a janela nomeada, e nao so a metrica: "nao ha uma unica linha" e uma
    # afirmacao sobre um intervalo concreto, e sem ele quem le o job nao sabe
    # onde e que nao havia nada
    assert "2026-07-01" in job.error and "2026-07-03" in job.error
    assert _linhas_de_agua(session, sitio) == []


def test_a_missing_et0_series_fails_even_with_all_the_rain(session, sitio):
    """A ET0 e a entrada que domina o balanco. Sem ela nao ha balanco nenhum, e
    trata-la como zero era afirmar que nao houve procura de agua nenhuma."""
    for i in range(3):
        _entrada(session, sitio, date(2026, 7, 1) + timedelta(days=i), PRECIPITACAO, 5.0)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert job.status == JobStatus.failed
    assert ET0 in job.error
    assert "2026-07-01" in job.error and "2026-07-03" in job.error
    assert _linhas_de_agua(session, sitio) == []


def test_a_day_with_rain_but_without_et0_is_not_balanced(session, sitio):
    """A serie de ET0 comeca depois das outras. Os dias em que so uma das
    entradas existe nao sao balancados -- nem com a outra a zero, que era
    inventar -- e ficam como buraco, que a Task 2 trata cortando o segmento."""
    for i in range(5):
        _entrada(session, sitio, date(2026, 7, 1) + timedelta(days=i), PRECIPITACAO, 5.0)
    for i in range(3, 5):
        _entrada(session, sitio, date(2026, 7, 1) + timedelta(days=i), ET0, 30.0)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-05", CAPACIDADE)

    assert job.status == JobStatus.succeeded
    assert job.rows_written == 2
    linhas = _linhas_de_agua(session, sitio)
    assert [linha.observed_at.date() for linha in linhas] == [date(2026, 7, 4), date(2026, 7, 5)]
    assert linhas[0].evidence["inputs"][PRECIPITACAO]["days_without_the_other_input"] == 3
    assert linhas[0].evidence["inputs"][ET0]["days_without_the_other_input"] == 0


def test_a_window_where_the_two_inputs_never_meet_fails(session, sitio):
    """Duas series que nao partilham um unico dia nao produzem balanco nenhum."""
    for i in range(2):
        _entrada(session, sitio, date(2026, 7, 1) + timedelta(days=i), PRECIPITACAO, 5.0)
    for i in range(2):
        _entrada(session, sitio, date(2026, 7, 10) + timedelta(days=i), ET0, 30.0)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-15", CAPACIDADE)

    assert job.status == JobStatus.failed
    assert job.rows_written == 0
    # as duas series nomeadas com o que cada uma trouxe: sem isso, quem le o job
    # sabe que nao houve balanco e nao sabe qual das duas o impediu
    assert PRECIPITACAO in job.error and ET0 in job.error
    assert _linhas_de_agua(session, sitio) == []


def test_an_input_in_the_wrong_unit_fails_instead_of_being_taken_as_millimetres(session, sitio):
    """Um valor em metros gravado como milimetros continua plausivel e ninguem
    volta a olhar para ele."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)
    session.execute(
        Observation.__table__.update()
        .where(Observation.metric == PRECIPITACAO)
        .values(unit="m")
    )
    session.commit()

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert job.status == JobStatus.failed
    assert "'m'" in job.error
    assert _linhas_de_agua(session, sitio) == []


# --- a segunda execucao e a identidade ----------------------------------------


def test_a_second_run_over_the_same_window_writes_nothing(session, sitio):
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 4)
    primeiro = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-04", CAPACIDADE)

    segundo = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-04", CAPACIDADE)

    assert primeiro.rows_written == 4
    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert len(_linhas_de_agua(session, sitio)) == 4


def test_two_capacities_are_two_series_side_by_side_and_not_one_overwritten(session, sitio):
    """A capacidade domina o resultado, portanto entra na identidade da linha.
    Sem isso, a segunda corrida batia na identidade da primeira, escrevia zero
    linhas e respondia `succeeded` -- e a serie da segunda capacidade nunca
    tinha existido."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 3)

    cem = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", 100.0)
    duzentos = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", 200.0)

    assert cem.rows_written == 3
    assert duzentos.rows_written == 3
    assert cem.processing_version != duzentos.processing_version
    assert len(_linhas_de_agua(session, sitio)) == 6
    versoes = {linha.processing_version for linha in _linhas_de_agua(session, sitio)}
    assert versoes == {
        processing_version_do_balanco(100.0), processing_version_do_balanco(200.0),
    }
    assert VERSAO_DO_BALANCO in processing_version_do_balanco(100.0)


def test_the_job_declares_the_window_it_actually_balanced(session, sitio):
    """O job e a unica linha que alguem le para saber o que uma corrida trouxe.
    Declarar a janela PEDIDA quando so parte dela foi balancada e afirmar uma
    cobertura que a serie desmente."""
    _serie_de_reanalise(session, sitio, date(2026, 7, 3), 2)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-10", CAPACIDADE)

    assert job.date_from == date(2026, 7, 3)
    assert job.date_to == date(2026, 7, 4)


def test_rows_outside_the_requested_window_are_not_balanced(session, sitio):
    _serie_de_reanalise(session, sitio, date(2026, 7, 1), 5)

    job = sync_water_balance(session, "EUC-TUR-BAL", "2026-07-02", "2026-07-03", CAPACIDADE)

    linhas = _linhas_de_agua(session, sitio)
    assert job.rows_written == 2
    assert [linha.observed_at.date() for linha in linhas] == [date(2026, 7, 2), date(2026, 7, 3)]


# --- as recusas que acontecem antes de o job existir --------------------------


def test_an_unknown_site_is_refused_before_any_job_exists(session):
    antes = session.scalar(select(func.count()).select_from(IngestionJob))

    with pytest.raises(ValueError):
        sync_water_balance(session, "EUC-NAO-EXISTE", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert session.scalar(select(func.count()).select_from(IngestionJob)) == antes


def test_a_site_without_an_approved_aoi_is_refused_before_any_job_exists(session):
    _sitio(session, "EUC-TUR-RASC", "EUC-TUR-RASC-EO", status=AoiStatus.draft)
    antes = session.scalar(select(func.count()).select_from(IngestionJob))

    with pytest.raises(ValueError):
        sync_water_balance(session, "EUC-TUR-RASC", "2026-07-01", "2026-07-03", CAPACIDADE)

    assert session.scalar(select(func.count()).select_from(IngestionJob)) == antes


def test_a_capacity_that_is_not_a_reservoir_is_refused_before_any_job_exists(session, sitio):
    """Um reservatorio de zero mm nao e um reservatorio, e isso sabe-se antes
    de se ler uma unica linha da base: nao e uma execucao falhada, e uma que
    nunca devia ter comecado."""
    antes = session.scalar(select(func.count()).select_from(IngestionJob))

    for valor in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            sync_water_balance(session, "EUC-TUR-BAL", "2026-07-01", "2026-07-03", valor)

    assert session.scalar(select(func.count()).select_from(IngestionJob)) == antes


def test_an_inverted_window_is_refused_before_any_job_exists(session, sitio):
    antes = session.scalar(select(func.count()).select_from(IngestionJob))

    with pytest.raises(ValueError):
        sync_water_balance(session, "EUC-TUR-BAL", "2026-07-05", "2026-07-01", CAPACIDADE)

    assert session.scalar(select(func.count()).select_from(IngestionJob)) == antes


def test_the_capacity_has_no_default_value(session):
    """Um valor por omissao seria um numero inventado a fingir de medicao, e o
    parametro por omissao dominava o resultado de todas as corridas."""
    import inspect

    parametro = inspect.signature(sync_water_balance).parameters["capacidade_mm"]
    assert parametro.default is inspect.Parameter.empty
