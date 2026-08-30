import json
from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import event, func, select

from resoiltwin.enums import (
    AoiStatus, GeometryProvenance, JobStatus, QualityFlag, SourceType, ValueQualifier,
)
from resoiltwin.eo import ingest
from resoiltwin.eo.cdse import CDSEClient
from resoiltwin.eo.evalscripts import (
    EVALSCRIPT_VERSION,
    EVALSCRIPT_VERSION_SCL,
    NDVI_NDMI_NDRE,
    NDVI_NDMI_NDRE_SCL,
    SCL_CLASSES_EXCLUIDAS,
    evalscript_hash,
)
from resoiltwin.eo.ingest import sync_aoi
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.models import Aoi, IngestionJob, Observation, Plot, Site

DATAS = ("2026-08-11", "2026-08-21", "2026-08-26")
METRICAS = ("ndvi", "ndmi", "ndre")

_QUADRADO = {
    "type": "Polygon",
    "coordinates": [[
        [-9.2547, 39.0261], [-9.2258, 39.0261],
        [-9.2258, 39.0485], [-9.2547, 39.0485], [-9.2547, 39.0261],
    ]],
}


def _bloco(media, amostras=62750, sem_dados=0):
    return {"bands": {"B0": {"stats": {
        "mean": media, "sampleCount": amostras, "noDataCount": sem_dados}}}}


def _corpo_estatisticas(datas, medias=(0.464, 0.030, 0.326)):
    """Resposta da Statistical API no formato real, uma entrada por aquisicao."""
    ndvi, ndmi, ndre = medias
    return {"data": [
        {"interval": {"from": f"{d}T00:00:00Z"},
         "outputs": {"ndvi": _bloco(ndvi), "ndmi": _bloco(ndmi), "ndre": _bloco(ndre)}}
        for d in datas
    ]}


def _dentro_da_janela(datas, corpo):
    """As datas do duplo, recortadas pela janela que o pedido leva.

    A origem recorta a serie pelo `timeRange` do corpo, e um duplo que devolva
    sempre as mesmas datas seja qual for a janela pedida torna vacuo qualquer
    teste sobre janelas -- foi o que esteve aqui ate 30/08/2026, com o corpo do
    pedido a nunca ser capturado nem afirmado em lado nenhum.
    """
    intervalo = corpo["aggregation"]["timeRange"]
    de, ate = intervalo["from"][:10], intervalo["to"][:10]
    return [d for d in datas if de <= d <= ate]


def _cliente(datas=DATAS, pedidos=None, resposta=None):
    """CDSEClient real por cima de um MockTransport: nenhum teste toca a rede,
    mas o caminho exercitado e o do cliente de producao, guarda de UTM incluida.
    """
    def handler(request):
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        corpo = json.loads(request.content)
        if pedidos is not None:
            pedidos.append(corpo)
        if resposta is not None:
            return resposta
        return httpx.Response(200, json=_corpo_estatisticas(_dentro_da_janela(datas, corpo)))

    return CDSEClient("id", "segredo", transport=httpx.MockTransport(handler))


class _ClienteEspiao:
    """Cliente falso que so regista que foi chamado.

    A guarda da AOI tem de disparar ANTES da rede; um cliente que se limita a
    contar chamadas e a unica forma de provar que nao houve pedido nenhum --
    um MockTransport devolveria uma resposta valida e o teste passaria a verde
    mesmo com a guarda no sitio errado.
    """

    def __init__(self):
        self.chamadas = []

    def token(self):
        self.chamadas.append("token")
        return "t"

    def search_scenes(self, *args, **kwargs):
        self.chamadas.append("search_scenes")
        return []

    def statistics(self, *args, **kwargs):
        self.chamadas.append("statistics")
        return []


class _ClienteQueRebenta:
    """Falha da rede a meio da execucao, depois de o job ja existir."""

    def statistics(self, *args, **kwargs):
        raise httpx.ConnectError("ligacao ao CDSE perdida a meio da serie")


def _linhas_normalizadas(datas=DATAS):
    """O que o `_normalizar` do cliente entrega ao servico."""
    return [{"date": d, "ndvi": 0.464, "ndmi": 0.030, "ndre": 0.326,
             "sampled_pixels": 62750, "contributing_pixels": 62750,
             "no_data_pixels": 0} for d in datas]


class _ClienteQueEspreitaOJob:
    """Le a linha do job na base A MEIO da chamada a rede.

    E a unica janela onde o estado `running` e observavel: quando o sync_aoi
    devolve, o job ja esta succeeded e a passagem por running e indistinguivel
    de nunca ter acontecido.

    Le duas coisas, e sao precisas as duas.

    O estado da linha (`no_autoflush` + `expire_all` para ler o que esta
    gravado e nao o que esta pendente em memoria) apanha o caso de o `running`
    nunca ser atribuido. Mas sozinho nao chega: dentro da mesma transaccao,
    uma alteracao apenas descarregada (o refresh da geometria da AOI provoca
    um autoflush a caminho da rede) e indistinguivel de uma confirmada, e o
    mutante que apaga so o `session.commit()` sobrevivia.

    Dai a contagem de commits. Nesta suite envolvida numa transaccao externa,
    "visivel de fora" nao e observavel de forma directa -- uma segunda ligacao
    nao veria sequer o sitio -- e o commit e o que se pode observar. Dois
    commits antes da rede: o job criado e o `running`.
    """

    def __init__(self, session):
        self._session = session
        self._commits = 0
        self.commits_ate_a_rede = None
        self.estado_a_meio = None
        event.listen(session, "after_commit", self._contar)

    def _contar(self, _sessao):
        self._commits += 1

    def statistics(self, *args, **kwargs):
        self.commits_ate_a_rede = self._commits
        with self._session.no_autoflush:
            self._session.expire_all()
            self.estado_a_meio = self._session.execute(
                select(IngestionJob.status, IngestionJob.rows_written, IngestionJob.finished_at)
            ).one()
        return _linhas_normalizadas()


class _ClienteComLinhaMa:
    """Serie valida com uma data corrompida no meio: o ndvi vem sem media.

    Serve para provar que a escrita e tudo-ou-nada. Se cada linha fosse
    gravada e confirmada a medida que chega, ficavam as boas antes da ma.
    """

    def statistics(self, *args, **kwargs):
        linhas = [{"date": d, "ndvi": 0.4, "ndmi": 0.03, "ndre": 0.32,
                   "sampled_pixels": 62750, "contributing_pixels": 62750,
                   "no_data_pixels": 0} for d in DATAS]
        linhas.insert(2, {"date": "2026-08-24", "ndvi": None, "ndmi": None, "ndre": None,
                          "sampled_pixels": 0, "contributing_pixels": 0,
                          "no_data_pixels": 0})
        return linhas


def _versao_de_processamento():
    """A versao do script SEM mascara -- o v1, que produziu as linhas ja gravadas."""
    return f"{EVALSCRIPT_VERSION}+{evalscript_hash(NDVI_NDMI_NDRE)}"


def _versao_mascarada():
    """A versao do script COM mascara SCL ao pixel -- o v2, o caminho por omissao."""
    return f"{EVALSCRIPT_VERSION_SCL}+{evalscript_hash(NDVI_NDMI_NDRE_SCL)}"


def _observacoes(session, aoi):
    return session.scalars(
        select(Observation).where(Observation.site_id == aoi.site_id)
        .order_by(Observation.observed_at, Observation.metric)
    ).all()


@pytest.fixture
def aoi_rascunho(session):
    site = Site(code="EUC-TUR-DRAFT", name="Turcifal por confirmar")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO-DRAFT", purpose="earth_observation",
        geometry=geojson_to_wkt_element(_QUADRADO),
        geometry_provenance=GeometryProvenance.provisional_pending_kml,
        status=AoiStatus.draft,
    )
    session.add(aoi)
    session.commit()
    return aoi


_QUADRADO_PORTO = {
    "type": "Polygon",
    "coordinates": [[
        [-8.61340, 41.14950], [-8.61220, 41.14950],
        [-8.61220, 41.15060], [-8.61340, 41.15060], [-8.61340, 41.14950],
    ]],
}


@pytest.fixture
def aoi_aprovada_outro_sitio(session):
    """Segunda AOI aprovada, noutro SITIO. Este projecto tem quatro AOI em
    sitios diferentes e sincroniza-as na mesma janela: e a configuracao real,
    nao um caso de laboratorio."""
    site = Site(code="EUC-PRT-JOB", name="Porto job de ingestao")
    aoi = Aoi(
        site=site, code="EUC-PRT-EO-JOB", purpose="earth_observation",
        geometry=geojson_to_wkt_element(_QUADRADO_PORTO),
        geometry_provenance=GeometryProvenance.surveyed,
        status=AoiStatus.approved, approved_by="site-manager",
    )
    session.add(aoi)
    session.commit()
    return aoi


@pytest.fixture
def aoi_recusada(session):
    site = Site(code="EUC-TUR-REJ", name="Turcifal recusada")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO-REJ", purpose="earth_observation",
        geometry=geojson_to_wkt_element(_QUADRADO),
        geometry_provenance=GeometryProvenance.derived_from_metrics,
        status=AoiStatus.rejected,
    )
    session.add(aoi)
    session.commit()
    return aoi


# --- Regra 1: so uma AOI approved chega a rede ------------------------------

def test_draft_aoi_is_refused_before_any_network_call(session, aoi_rascunho):
    """Dois dos quatro poligonos deste projecto foram rectangulos inventados
    durante semanas. Esta guarda impede que se gastem pedidos -- e que se
    produzam numeros -- sobre um poligono que ninguem confirmou."""
    espiao = _ClienteEspiao()
    with pytest.raises(ValueError) as exc:
        sync_aoi(session, espiao, "EUC-TUR-EO-DRAFT", "2026-08-01", "2026-08-28")
    assert "approved" in str(exc.value)
    assert espiao.chamadas == []


def test_rejected_aoi_is_refused(session, aoi_recusada):
    espiao = _ClienteEspiao()
    with pytest.raises(ValueError, match="approved"):
        sync_aoi(session, espiao, "EUC-TUR-EO-REJ", "2026-08-01", "2026-08-28")
    assert espiao.chamadas == []


def test_unknown_aoi_code_is_refused(session):
    espiao = _ClienteEspiao()
    with pytest.raises(ValueError) as exc:
        sync_aoi(session, espiao, "NAO-EXISTE", "2026-08-01", "2026-08-28")
    assert "NAO-EXISTE" in str(exc.value)
    assert espiao.chamadas == []


def test_a_refused_aoi_leaves_no_job_behind(session, aoi_rascunho):
    """A guarda corre antes de o job ser criado: uma AOI recusada nao e uma
    execucao falhada, e uma execucao que nunca comecou."""
    with pytest.raises(ValueError):
        sync_aoi(session, _ClienteEspiao(), "EUC-TUR-EO-DRAFT", "2026-08-01", "2026-08-28")
    assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0


# --- Regra 2: a reprojeccao e feita dentro do servico -----------------------

def test_geometry_is_reprojected_to_utm_inside_the_service(session, aoi_aprovada):
    """O chamador passa um codigo de AOI, nao uma geometria. A base guarda
    4326 e a Statistical API exige 32629: quem reprojecta e o servico."""
    pedidos = []
    sync_aoi(session, _cliente(pedidos=pedidos), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    limites = pedidos[0]["input"]["bounds"]
    assert limites["properties"]["crs"].endswith("/32629")
    for x, y in limites["geometry"]["coordinates"][0]:
        # "nao sao graus" nao chega. Trocar a ordem dos eixos (tirar o
        # always_xy) tambem da metros -- 6 482 055 / -1 517 533 -- so que a
        # meio do Atlantico Sul e com a area do poligono errada. Numeros
        # plausiveis mas no sitio errado sao precisamente o modo de falha que
        # a regra 2 existe para impedir, por isso as fronteiras sao as da
        # faixa 29N e as do territorio.
        assert 100_000 <= x <= 900_000, f"easting fora da faixa UTM 29N: {x}"
        assert 4_000_000 <= y <= 4_800_000, f"northing fora de Portugal continental: {y}"


# --- Regras 3 e 6: escrita idempotente e job com rasto ----------------------

def test_first_run_writes_three_metrics_per_date(session, aoi_aprovada):
    job = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    assert job.status == JobStatus.succeeded
    assert job.rows_written == 9                       # 3 metricas x 3 datas
    assert job.job_type == "eo_sync"
    assert job.aoi_id == aoi_aprovada.id
    # a janela COBERTA, e nao a pedida (2026-08-01..2026-08-28): as tres
    # aquisicoes que chegaram vao de 11 a 26 de Agosto
    assert job.date_from == date(2026, 8, 11)
    assert job.date_to == date(2026, 8, 26)
    assert job.request_hash                            # identifica o pedido
    assert job.finished_at is not None
    assert job.error is None
    assert len(_observacoes(session, aoi_aprovada)) == 9


def test_second_identical_run_writes_nothing(session, aoi_aprovada):
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    segundo = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert len(_observacoes(session, aoi_aprovada)) == 9


def test_a_new_date_is_added_without_rewriting_the_old_ones(session, aoi_aprovada):
    """Idempotencia nao e "nao escrever nada na segunda vez": e escrever
    exactamente o que falta."""
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    segundo = sync_aoi(session, _cliente(datas=(*DATAS, "2026-08-31")),
                       aoi_aprovada.code, "2026-08-01", "2026-08-31")

    assert segundo.rows_written == 3                   # so a data nova
    assert len(_observacoes(session, aoi_aprovada)) == 12


def test_dedup_is_scoped_to_the_processing_version(session, aoi_aprovada):
    """Outra versao do evalscript produz outros numeros: e uma serie nova, nao
    uma repeticao. Se a chave de desduplicacao ignorasse a versao, a serie
    reprocessada desaparecia em silencio."""
    session.add(Observation(
        site_id=aoi_aprovada.site_id, plot_id=None,
        observed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        metric="ndvi", unit="index", value_numeric=0.111,
        source_type=SourceType.satellite_observed, quality_flag=QualityFlag.valid,
        value_qualifier=ValueQualifier.exact, source_collection="sentinel-2-l2a",
        processing_version="s2-ndvi-ndmi-ndre-v0+000000000000",
        evidence={"aoi_code": aoi_aprovada.code},
    ))
    session.commit()

    job = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    assert job.rows_written == 9
    assert len(_observacoes(session, aoi_aprovada)) == 10


def test_a_field_reading_on_the_same_day_does_not_block_the_satellite_row(session, aoi_aprovada):
    """A serie de satelite convive com a leitura de campo do mesmo dia: sao
    origens diferentes da mesma grandeza, nao duplicados."""
    session.add(Observation(
        site_id=aoi_aprovada.site_id, plot_id=None,
        observed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        metric="ndvi", unit="index", value_numeric=0.5,
        source_type=SourceType.observed_reference, quality_flag=QualityFlag.valid,
        value_qualifier=ValueQualifier.exact, processing_version="campo-v1",
    ))
    session.commit()

    job = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    assert job.rows_written == 9


def test_dedup_query_mirrors_the_identity_on_source_type(session, aoi_aprovada):
    """A linha plantada aqui e sintetica de proposito: partilha com a serie de
    satelite todas as colunas da uq_observation_identity menos o source_type.

    O que se prova nao e o cenario, e o espelho. A consulta de desduplicacao
    tem de repetir a identidade coluna a coluna; se lhe faltar uma, uma linha
    que NAO e duplicado passa por duplicado e desaparece da serie em silencio
    -- que e o modo de falha que a regra da idempotencia existe para impedir.
    """
    session.add(Observation(
        site_id=aoi_aprovada.site_id, plot_id=None,
        observed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        metric="ndvi", unit="index", value_numeric=0.42,
        source_type=SourceType.simulated, quality_flag=QualityFlag.valid,
        value_qualifier=ValueQualifier.exact,
        processing_version=_versao_mascarada(),
    ))
    session.commit()

    job = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    assert job.rows_written == 9
    assert len(_observacoes(session, aoi_aprovada)) == 10


def test_dedup_query_mirrors_the_identity_on_plot_id(session, aoi_aprovada):
    """O mesmo espelho, do lado do plot_id: uma serie de satelite ao nivel de
    uma parcela nao pode fazer a serie da AOI passar por ja gravada. Sao dois
    poligonos diferentes e dois valores diferentes."""
    parcela = Plot(site_id=aoi_aprovada.site_id, code="EUC-TUR-P-EO",
                   name="Parcela de referencia EO", purpose="eo_reference")
    session.add(parcela)
    session.flush()
    session.add(Observation(
        site_id=aoi_aprovada.site_id, plot_id=parcela.id,
        observed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        metric="ndvi", unit="index", value_numeric=0.42,
        source_type=SourceType.satellite_observed, quality_flag=QualityFlag.valid,
        value_qualifier=ValueQualifier.exact, source_collection="sentinel-2-l2a",
        processing_version=_versao_mascarada(),
    ))
    session.commit()

    job = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    assert job.rows_written == 9


def test_dedup_query_mirrors_the_identity_on_site_id(session, aoi_aprovada, aoi_aprovada_outro_sitio):
    """Duas AOI aprovadas em SITIOS diferentes, mesma janela, mesma versao.

    E o terceiro espelho, e o que apaga mais: sem o site_id no filtro, a serie
    de Turcifal contava como ja existente para a do Porto e a segunda AOI
    escrevia ZERO linhas -- com o job a dizer succeeded. Uma serie inteira
    desaparecia e o sistema declarava sucesso. Este projecto tem quatro AOI e
    sincroniza-as na mesma janela, portanto nao e hipotese: e terca-feira.
    """
    primeiro = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    segundo = sync_aoi(session, _cliente(), aoi_aprovada_outro_sitio.code,
                       "2026-08-01", "2026-08-28")

    assert primeiro.rows_written == 9
    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 9
    assert len(_observacoes(session, aoi_aprovada)) == 9
    assert len(_observacoes(session, aoi_aprovada_outro_sitio)) == 9


def test_the_job_is_visible_as_running_during_the_network_call(session, aoi_aprovada):
    """O `running` e confirmado sozinho, antes da rede, para um job preso numa
    chamada de minutos ser visivel de fora ENQUANTO corre. Sem este teste a
    propriedade era afirmada no comentario e nunca provada: apagar esse commit
    -- pending a saltar directo para succeeded -- nao partia nada."""
    cliente = _ClienteQueEspreitaOJob(session)
    job = sync_aoi(session, cliente, aoi_aprovada.code, "2026-08-01", "2026-08-28")

    estado, escritas, terminado = cliente.estado_a_meio
    assert estado == JobStatus.running
    assert escritas == 0
    assert terminado is None
    # confirmado, nao apenas descarregado: ha pelo menos dois commits antes da
    # rede, o do job criado e o do running. Uma alteracao por confirmar nao e
    # visivel a mais ligacao nenhuma, que e o unico sentido util de "visivel
    # de fora".
    # `>=` e nao `==`: a propriedade e "o running foi confirmado antes da
    # rede", nao "o servico faz exactamente dois commits". Um terceiro commit
    # legitimo aqui -- marcar o arranque efectivo, por exemplo -- nao viola
    # nada e nao pode fazer este teste obstruir a mudanca.
    assert cliente.commits_ate_a_rede >= 2
    assert job.status == JobStatus.succeeded          # e chega ao fim na mesma


def test_request_hash_changes_with_every_parameter_it_claims_to_cover(
    session, aoi_aprovada, aoi_aprovada_outro_sitio
):
    """O hash diz identificar AOI, janela, resolucao e nuvens. Se algum desses
    parametros nao entrasse no material, dois pedidos diferentes partilhavam
    identidade e o rasto deixava de distinguir execucoes -- sem nada a
    assinalar. As asercoes anteriores (`assert job.request_hash`) davam-no por
    bom por ele existir."""
    def hash_de(codigo="", inicio="2026-08-01", fim="2026-08-28", **extra):
        return sync_aoi(session, _cliente(), codigo or aoi_aprovada.code,
                        inicio, fim, **extra).request_hash

    base = hash_de()
    assert hash_de() == base, "mesmo pedido tem de dar sempre o mesmo hash"

    variantes = {
        "date_from": hash_de(inicio="2026-07-01"),
        "date_to": hash_de(fim="2026-08-31"),
        "resolution_m": hash_de(resolution_m=20),
        "max_cloud": hash_de(max_cloud=10),
        "aoi_code": hash_de(codigo=aoi_aprovada_outro_sitio.code),
    }
    for parametro, obtido in variantes.items():
        assert obtido != base, f"o request_hash ignora o {parametro}"


def test_request_hash_covers_the_processing_version(session, aoi_aprovada, monkeypatch):
    """O sexto parametro do material do hash, e o unico que nao se muda pela
    assinatura de sync_aoi.

    Nao e cosmetico: a processing_version muda com o evalscript, portanto varia
    a serio ao longo da vida do projecto. Com ela fora do material, duas
    execucoes com scripts diferentes -- que produzem NUMEROS diferentes --
    partilhavam identidade de pedido, e o `request_hash` gravado no evidence
    deixava de distinguir a serie que veio de um script da que veio do outro.

    (O `collection` tambem entra no material e nao esta pingado: e uma
    constante do modulo, portanto o mutante que a retira e equivalente
    enquanto nao houver uma segunda coleccao.)
    """
    antes = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    monkeypatch.setattr(
        ingest, "processing_version", lambda _evalscript: "s2-outro-evalscript-v9+ffffffffffff"
    )
    depois = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    assert antes.request_hash != depois.request_hash


def test_two_entries_for_the_same_day_are_refused_instead_of_silently_dropped(session, aoi_aprovada):
    """Com agregacao P1D cada dia so pode ter uma leitura. Duas entradas para o
    mesmo dia nao cabem na identidade da observacao: gravar uma e descartar a
    outra seria escolher ao acaso pela ordem da resposta."""
    job = sync_aoi(session, _cliente(datas=("2026-08-21", "2026-08-21")),
                   aoi_aprovada.code, "2026-08-01", "2026-08-28")

    assert job.status == JobStatus.failed
    assert "2026-08-21" in job.error
    # a recusa e explicita e legivel, nao uma parede de IntegrityError: sem a
    # guarda no servico a base tambem rejeitava o lote, mas o rasto que ficava
    # no job era a instrucao SQL inteira com os parametros
    assert "P1D" in job.error
    assert _observacoes(session, aoi_aprovada) == []


# --- Regra 6: falhar sem deixar linhas meio-escritas ------------------------

def test_network_failure_marks_the_job_failed_and_writes_nothing(session, aoi_aprovada):
    job = sync_aoi(session, _ClienteQueRebenta(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    assert job.status == JobStatus.failed
    assert job.error and "CDSE" in job.error
    assert job.rows_written == 0
    assert job.finished_at is not None
    assert _observacoes(session, aoi_aprovada) == []

    # o job sobreviveu ao rollback das linhas: e o unico rasto de que houve
    # tentativa, e a fase seguinte agenda a ingestao sem ninguem a ver o ecra
    gravado = session.get(IngestionJob, job.id)
    assert gravado.status == JobStatus.failed


def test_http_error_from_statistics_is_recorded_on_the_job(session, aoi_aprovada):
    """O erro tem de trazer o CORPO da resposta, nao so o codigo HTTP.

    O statistics() usava raise_for_status() enquanto o token() e o
    search_scenes() ja passavam pelo _erro_resposta: um 500 deixava no
    `job.error` um "Server error '500' for url ..." e o corpo, que e o que diz
    o que o Copernicus recusou, ficava pelo caminho. E este o erro que sobra
    quando a ingestao correr agendada.
    """
    cliente = _cliente(resposta=httpx.Response(
        500, json={"code": 500, "description": "Failed to evaluate script: unknown band B12."}))
    job = sync_aoi(session, cliente, aoi_aprovada.code, "2026-08-01", "2026-08-28")

    assert job.status == JobStatus.failed
    assert "unknown band B12" in job.error
    assert "500" in job.error
    assert _observacoes(session, aoi_aprovada) == []


def test_one_bad_row_rolls_back_the_whole_batch(session, aoi_aprovada):
    job = sync_aoi(session, _ClienteComLinhaMa(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    assert job.status == JobStatus.failed
    assert job.rows_written == 0
    assert _observacoes(session, aoi_aprovada) == []


# --- Regra 4: proveniencia completa em cada linha ---------------------------

def test_every_row_carries_full_provenance(session, aoi_aprovada):
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    linhas = _observacoes(session, aoi_aprovada)

    assert {linha.metric for linha in linhas} == set(METRICAS)
    for linha in linhas:
        assert linha.source_type == SourceType.satellite_observed
        assert SourceType.is_measurement(linha.source_type)   # nao e um derivado
        assert linha.source_collection == "sentinel-2-l2a"
        assert linha.processing_version == _versao_mascarada()
        assert linha.quality_flag == QualityFlag.unchecked
        assert linha.value_qualifier == ValueQualifier.exact
        assert linha.unit == "index"
        assert linha.value_numeric is not None
        assert linha.evidence["aoi_code"] == aoi_aprovada.code
        assert linha.evidence["sampled_pixels"] == 62750
        assert linha.evidence["contributing_pixels"] == 62750
        assert linha.evidence["no_data_pixels"] == 0
        assert linha.evidence["resolution_m"] == 10
        assert linha.evidence["max_cloud"] == 30
        assert linha.evidence["request_hash"]


def test_evidence_request_hash_matches_the_job(session, aoi_aprovada):
    """A linha aponta para a execucao que a produziu: sem isto, uma serie na
    base nao se liga ao registo de como entrou."""
    job = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    for linha in _observacoes(session, aoi_aprovada):
        assert linha.evidence["request_hash"] == job.request_hash


def test_values_and_dates_come_from_the_client(session, aoi_aprovada):
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    linhas = _observacoes(session, aoi_aprovada)

    dias = sorted({linha.observed_at.astimezone(timezone.utc).date().isoformat() for linha in linhas})
    assert dias == list(DATAS)
    por_metrica = {linha.metric: linha.value_numeric for linha in linhas}
    assert por_metrica["ndvi"] == pytest.approx(0.464)
    assert por_metrica["ndmi"] == pytest.approx(0.030)
    assert por_metrica["ndre"] == pytest.approx(0.326)


# --- Regra 5: plot_id nulo e a desduplicacao continua a funcionar -----------

def test_plot_id_is_null_and_dedup_still_works(session, aoi_aprovada):
    """A serie e da AOI, nao de uma parcela. E exactamente por isto que a
    uq_observation_identity leva postgresql_nulls_not_distinct=True: sem essa
    opcao o Postgres trata cada NULL como distinto e a desduplicacao falharia
    em silencio, precisamente aqui."""
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")
    segundo = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    linhas = _observacoes(session, aoi_aprovada)
    assert all(linha.plot_id is None for linha in linhas)
    assert len(linhas) == 9
    # succeeded, nao failed: a segunda execucao tem de ser um nao-evento. Sem
    # esta asercao o teste passava na mesma com a desduplicacao arrancada --
    # a constraint rejeitava o lote e as contagens ficavam iguais por acidente
    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0


# --- Regra 7: a mascara SCL e a proveniencia que lhe corresponde ------------

def _sync_espiado(session, aoi, **extra):
    """Corre um sync e devolve (evalscript que chegou ao cliente, versoes novas).

    As duas coisas tem de ser lidas na mesma execucao: o que se prova nao e
    "gravou o v2", e "gravou a identidade do script que de facto enviou". Ler
    so uma delas deixava passar exactamente a mentira que o argumento
    obrigatorio do evalscript_hash existe para impedir.
    """
    antes = {linha.processing_version for linha in _observacoes(session, aoi)}
    pedidos = []
    sync_aoi(session, _cliente(pedidos=pedidos), aoi.code, "2026-08-01", "2026-08-28", **extra)
    depois = {linha.processing_version for linha in _observacoes(session, aoi)}
    return pedidos[0]["aggregation"]["evalscript"], depois - antes


def test_masked_sync_records_the_v2_version_and_the_v2_hash(session, aoi_aprovada):
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
             com_mascara_scl=True)

    linhas = _observacoes(session, aoi_aprovada)
    assert len(linhas) == 9
    for linha in linhas:
        assert linha.processing_version == _versao_mascarada()
        assert linha.processing_version.startswith(f"{EVALSCRIPT_VERSION_SCL}+")
        assert linha.processing_version.endswith(evalscript_hash(NDVI_NDMI_NDRE_SCL))


def test_unmasked_sync_records_the_v1_version_and_the_two_are_distinguishable(session, aoi_aprovada):
    """O v1 continua disponivel para reproduzir o que ja esta gravado. Se as
    duas versoes colidissem -- mesmo rotulo ou mesmo hash -- a base deixava de
    conseguir dizer quais das suas linhas tinham mascara."""
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
             com_mascara_scl=False)

    linhas = _observacoes(session, aoi_aprovada)
    assert len(linhas) == 9
    for linha in linhas:
        assert linha.processing_version == _versao_de_processamento()
    assert evalscript_hash(NDVI_NDMI_NDRE) != evalscript_hash(NDVI_NDMI_NDRE_SCL)
    assert EVALSCRIPT_VERSION != EVALSCRIPT_VERSION_SCL
    assert _versao_de_processamento() != _versao_mascarada()


def test_the_mask_is_the_default_when_nobody_chooses(session, aoi_aprovada):
    """Quem nao escolher fica com o comportamento correcto: e a razao de ser
    do valor por omissao."""
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    versoes = {linha.processing_version for linha in _observacoes(session, aoi_aprovada)}
    assert versoes == {_versao_mascarada()}


def test_the_script_sent_to_the_client_is_the_one_the_parameter_asks_for(session, aoi_aprovada):
    """Espiar o corpo do pedido, nao assumir. A versao gravada e uma string:
    podia estar certa com o script errado a caminho do Copernicus."""
    enviado_com, _ = _sync_espiado(session, aoi_aprovada, com_mascara_scl=True)
    enviado_sem, _ = _sync_espiado(session, aoi_aprovada, com_mascara_scl=False)

    assert enviado_com == NDVI_NDMI_NDRE_SCL
    assert enviado_sem == NDVI_NDMI_NDRE
    assert enviado_com != enviado_sem
    # a diferenca visivel: so o v2 pede a banda SCL e a usa no dataMask
    assert '"SCL"' in enviado_com and '"SCL"' not in enviado_sem


def test_the_recorded_version_matches_the_script_actually_sent(session, aoi_aprovada):
    """A proveniencia nao pode mentir, nos dois sentidos.

    O hash gravado e recalculado a partir do script que saiu no pedido, nao a
    partir da constante que o teste esperava: e o unico modo de apanhar um
    sync que envia um script e assina outro. Este sistema inteiro existe para
    nao mentir sobre como os numeros foram produzidos.
    """
    enviado_com, versoes_com = _sync_espiado(session, aoi_aprovada, com_mascara_scl=True)
    enviado_sem, versoes_sem = _sync_espiado(session, aoi_aprovada, com_mascara_scl=False)

    assert versoes_com == {f"{EVALSCRIPT_VERSION_SCL}+{evalscript_hash(enviado_com)}"}
    assert versoes_sem == {f"{EVALSCRIPT_VERSION}+{evalscript_hash(enviado_sem)}"}
    assert versoes_com != versoes_sem


def test_choosing_the_script_is_keyword_only(session, aoi_aprovada):
    """Posicional partia chamadores existentes em silencio: o quinto e o sexto
    argumentos posicionais ja sao a resolucao e a nuvem maxima."""
    with pytest.raises(TypeError):
        sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28", 10, 30, False)


def test_a_masked_sync_over_a_window_already_ingested_unmasked_writes_new_rows(session, aoi_aprovada):
    """Nao sao duplicados: sao medicoes de proveniencia diferente do mesmo dia.

    As 54 linhas que ja estao na base foram produzidas pelo v1. Reprocessar a
    mesma janela com mascara tem de acrescentar a serie nova SEM tocar na
    antiga -- e o que vai permitir compara-las lado a lado.
    """
    sem_mascara = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
                           com_mascara_scl=False)
    antigas = {(linha.observed_at, linha.metric, linha.value_numeric)
               for linha in _observacoes(session, aoi_aprovada)}

    com_mascara = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
                           com_mascara_scl=True)

    assert sem_mascara.rows_written == 9
    assert com_mascara.rows_written == 9
    assert com_mascara.status == JobStatus.succeeded

    linhas = _observacoes(session, aoi_aprovada)
    assert len(linhas) == 18
    por_versao = {}
    for linha in linhas:
        por_versao[linha.processing_version] = por_versao.get(linha.processing_version, 0) + 1
    assert por_versao == {_versao_de_processamento(): 9, _versao_mascarada(): 9}

    # as linhas do v1 continuam intactas: mesmas datas, mesmas metricas, mesmos valores
    ainda_la = {(linha.observed_at, linha.metric, linha.value_numeric)
                for linha in linhas
                if linha.processing_version == _versao_de_processamento()}
    assert ainda_la == antigas


def test_a_second_masked_sync_over_the_same_window_writes_nothing(session, aoi_aprovada):
    """A idempotencia continua por consulta: repetir o mesmo sync v2 e um
    nao-evento. Escrever linhas novas so acontece quando a proveniencia muda,
    nao de cada vez que se reexecuta a janela."""
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
             com_mascara_scl=True)
    segundo = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
                       com_mascara_scl=True)

    assert segundo.status == JobStatus.succeeded
    assert segundo.rows_written == 0
    assert len(_observacoes(session, aoi_aprovada)) == 9


def test_masked_rows_record_the_mask_and_the_excluded_classes(session, aoi_aprovada):
    """Quem consultar uma observacao daqui a um ano tem de saber se foi
    mascarada sem ir ler o codigo -- e quais classes ficaram de fora, porque
    esse conjunto pode mudar."""
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
             com_mascara_scl=True)

    linhas = _observacoes(session, aoi_aprovada)
    assert len(linhas) == 9
    for linha in linhas:
        assert linha.evidence["scl_mask"] is True
        assert linha.evidence["scl_classes_excluded"] == sorted(SCL_CLASSES_EXCLUIDAS)
        assert linha.evidence["aoi_code"] == aoi_aprovada.code   # a restante proveniencia fica


def test_unmasked_rows_say_so_instead_of_staying_silent(session, aoi_aprovada):
    """Ausencia do campo nao pode ser a forma de dizer "sem mascara": era
    indistinguivel de uma linha gravada antes de a mascara existir."""
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
             com_mascara_scl=False)

    for linha in _observacoes(session, aoi_aprovada):
        assert linha.evidence["scl_mask"] is False
        assert "scl_classes_excluded" not in linha.evidence


def test_the_request_hash_separates_the_masked_run_from_the_unmasked_one(session, aoi_aprovada):
    """A processing_version ja entrava no material do hash; agora varia a
    serio dentro da mesma janela. Dois pedidos que produzem numeros diferentes
    nao podem partilhar identidade."""
    com = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
                   com_mascara_scl=True)
    sem = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28",
                   com_mascara_scl=False)

    assert com.request_hash != sem.request_hash


# ------------------------- a linha nao afirma qualidade que ninguem verificou


def _cliente_com_mascara_pesada():
    """O 24/08/2026 real: 62 750 amostrados, 57 432 excluidos, 5 318 a contribuir.

    O NDVI de 0,4130 e a media sobre 8,47% da parcela, e
    `docs/evidence/2026-08-29-mascara-scl.md` ja declarou esse dia explicavel
    mas NAO mensuravel. O que o codigo nao sabia era isso: gravava-o com
    `quality_flag = valid`, literal, ao lado dos dias de ceu limpo.
    """
    def statistics(*args, **kwargs):
        return [{"date": "2026-08-24", "ndvi": 0.4130, "ndmi": 0.2313, "ndre": 0.3018,
                 "sampled_pixels": 62750, "contributing_pixels": 5318,
                 "no_data_pixels": 57432}]

    return type("_ClienteMascaraPesada", (), {"statistics": staticmethod(statistics)})()


def test_a_91_percent_masked_acquisition_is_not_answered_by_a_query_for_valid(
        session, aoi_aprovada):
    """`SELECT ... WHERE quality_flag = 'valid'` e o filtro obvio, e era o que
    devolvia esta linha ao lado das de ceu limpo."""
    sync_aoi(session, _cliente_com_mascara_pesada(), aoi_aprovada.code,
             "2026-08-01", "2026-08-28")

    validas = session.scalars(
        select(Observation).where(Observation.site_id == aoi_aprovada.site_id,
                                  Observation.quality_flag == QualityFlag.valid)
    ).all()
    assert validas == []
    assert len(_observacoes(session, aoi_aprovada)) == 3


def test_the_masked_row_carries_the_count_that_a_reader_needs_to_judge_it(
        session, aoi_aprovada):
    """Nao ha limiar no codigo, portanto o criterio e de quem le -- e sem a
    contagem real na linha ninguem o pode aplicar."""
    sync_aoi(session, _cliente_com_mascara_pesada(), aoi_aprovada.code,
             "2026-08-01", "2026-08-28")

    for linha in _observacoes(session, aoi_aprovada):
        assert linha.evidence["sampled_pixels"] == 62750
        assert linha.evidence["contributing_pixels"] == 5318
        assert linha.evidence["no_data_pixels"] == 57432
        assert linha.quality_flag == QualityFlag.unchecked


def test_a_cloud_free_acquisition_is_unchecked_too_because_nothing_checks_it(
        session, aoi_aprovada):
    """Um dia sem um unico pixel excluido nao passa a `valid`.

    Isto e a decisao escrita, e nao um descuido: nenhum limiar deste projecto
    esta sustentado por coisa nenhuma, e a fronteira "zero excluidos" marcaria
    `valid` a serie v1 SEM mascara -- a contaminada -- e `unchecked` a v2
    mascarada. `unchecked` diz o que e verdade: ninguem verificou.
    """
    sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-28")

    linhas = _observacoes(session, aoi_aprovada)
    assert len(linhas) == 9
    assert {linha.evidence["no_data_pixels"] for linha in linhas} == {0}
    assert {linha.quality_flag for linha in linhas} == {QualityFlag.unchecked}


# ------------------------------- o job diz a janela que cobriu, e so essa


class _ClienteForaDaJanela:
    """Devolve uma aquisicao de fora do intervalo pedido.

    Nao ha prova de que a Statistical API o faca -- o `timeRange` do pedido
    recorta a serie na origem. O que ha e a assimetria: a razao escrita em
    `weather/ingest.py::_garantir_dentro_da_janela` (a consulta de
    desduplicacao tem a janela dos dias DEVOLVIDOS, nao dos PEDIDOS) aplica-se
    palavra por palavra a este caminho, que nao tinha guarda nenhuma.
    """

    def statistics(self, *args, **kwargs):
        return [{"date": d, "ndvi": 0.46, "ndmi": 0.03, "ndre": 0.32,
                 "sampled_pixels": 62750, "contributing_pixels": 62750,
                 "no_data_pixels": 0}
                for d in ("2026-08-21", "2026-09-04")]


def test_the_request_body_carries_the_window_that_was_asked_for(session, aoi_aprovada):
    """O corpo do pedido nunca era capturado nem afirmado: um teste que peca
    07-01..08-28 e receba datas de Agosto passava tanto com a janela certa
    como com uma qualquer outra."""
    pedidos = []
    sync_aoi(session, _cliente(pedidos=pedidos), aoi_aprovada.code,
             "2026-07-01", "2026-08-28")

    intervalo = pedidos[0]["aggregation"]["timeRange"]
    assert intervalo["from"] == "2026-07-01T00:00:00Z"
    assert intervalo["to"] == "2026-08-28T23:59:59Z"


def test_a_narrower_window_brings_fewer_acquisitions_and_the_job_says_so(
        session, aoi_aprovada):
    """A metade que faltava ao duplo: com a janela ignorada, este teste era
    impossivel de escrever -- as tres datas vinham na mesma."""
    job = sync_aoi(session, _cliente(), aoi_aprovada.code, "2026-08-01", "2026-08-22")

    assert job.status == JobStatus.succeeded
    assert job.rows_written == 6                       # 2 datas x 3 metricas
    assert job.date_from == date(2026, 8, 11)
    assert job.date_to == date(2026, 8, 21)            # 26/08 fica fora da janela


def test_a_month_with_a_single_acquisition_does_not_claim_to_cover_the_month(
        session, aoi_aprovada):
    """O caso NORMAL do Sentinel-2: pede-se o mes, o filtro de nuvens corta
    quase tudo. Os sete jobs de EO ja na base afirmam uma cobertura que a
    propria serie desmente."""
    job = sync_aoi(session, _cliente(datas=("2026-08-21",)), aoi_aprovada.code,
                   "2026-08-01", "2026-08-31")

    assert job.date_from == date(2026, 8, 21)
    assert job.date_to == date(2026, 8, 21)
    assert job.rows_written == 3


def test_a_window_with_no_acquisition_at_all_keeps_the_requested_one(
        session, aoi_aprovada):
    """Zero aquisicoes num mes de Inverno e meteorologia, nao erro: falhar
    aqui enchia de `error` um registo que passa a correr agendado. O que
    distingue este caso e o `rows_written = 0` ao lado da janela."""
    job = sync_aoi(session, _cliente(datas=()), aoi_aprovada.code,
                   "2026-01-01", "2026-01-31")

    assert job.status == JobStatus.succeeded
    assert job.rows_written == 0
    assert (job.date_from, job.date_to) == (date(2026, 1, 1), date(2026, 1, 31))


def test_the_job_keeps_the_window_it_asked_for_next_to_the_one_it_covered(
        session, aoi_aprovada):
    """Uma aquisicao num mes inteiro: o caso NORMAL do Sentinel-2, e a razao
    de a diferenca entre as duas janelas nao poder ser um alarme.

    O par fica na mesma gravado, porque so ele permite responder a pergunta
    "de que janela e que estes tres numeros sao a serie?" -- que sem a janela
    pedida so se responde relendo o pedido original, que ninguem guarda.
    """
    job = sync_aoi(session, _cliente(datas=("2026-08-21",)), aoi_aprovada.code,
                   "2026-08-01", "2026-08-31")

    assert (job.requested_date_from, job.requested_date_to) == (
        date(2026, 8, 1), date(2026, 8, 31))
    assert (job.date_from, job.date_to) == (date(2026, 8, 21), date(2026, 8, 21))


def test_a_window_with_no_acquisition_says_it_asked_for_the_whole_month(
        session, aoi_aprovada):
    """Zero aquisicoes deixa a janela COBERTA igual a pedida -- e a decisao
    tomada em `_janela_coberta`, e nao muda. O que muda e que agora a igualdade
    das duas e afirmavel: antes nao havia segundo lado onde a ler.
    """
    job = sync_aoi(session, _cliente(datas=()), aoi_aprovada.code,
                   "2026-01-01", "2026-01-31")

    assert job.rows_written == 0
    assert (job.requested_date_from, job.requested_date_to) == (
        date(2026, 1, 1), date(2026, 1, 31))
    assert (job.date_from, job.date_to) == (job.requested_date_from, job.requested_date_to)


def test_an_acquisition_outside_the_requested_window_is_refused(session, aoi_aprovada):
    """Sem esta guarda, 04/09 entrava na base debaixo de um job que diz ter
    pedido ate 28/08 -- e a consulta de desduplicacao, que tira a janela dos
    dias DEVOLVIDOS, nem dava por isso."""
    job = sync_aoi(session, _ClienteForaDaJanela(), aoi_aprovada.code,
                   "2026-08-01", "2026-08-28")

    assert job.status == JobStatus.failed
    assert "2026-09-04" in job.error
    assert job.rows_written == 0
    assert _observacoes(session, aoi_aprovada) == []    # nem a aquisicao boa entra
