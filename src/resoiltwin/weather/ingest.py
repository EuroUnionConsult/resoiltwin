"""Ingestao da reanalise AgERA5 para a tabela canonica de observacoes.

E aqui que o cliente do Climate Data Store encontra a base de dados: pega num
sitio, vai buscar a serie diaria da celula de grelha que o contem e grava-a ao
lado das leituras de campo e dos indices de satelite.

O que distingue esta camada das outras duas e o que cada linha tem de admitir
sobre si propria. A celula do AgERA5 tem ~9 km e a AOI de Turcifal tem 2,5 km:
uma celula cobre o micro-site, o Campo Real e boa parte do concelho. A chuva
que se grava para o sitio nao e a chuva daquele campo, e se isso nao ficar na
linha ninguem o recupera depois -- por isso cada observacao leva no `evidence`
a celula que a produziu, a distancia a que ela esta do sitio, a pegada da
celula nas duas direccoes e a caixa que foi mesmo pedida ao CDS.

O cliente vem de fora, por argumento, como na Fase B: e o que permite que a
suite injecte um duplo e nenhum teste toque na rede.
"""

import hashlib
import json
from datetime import date, datetime, timezone

from shapely.geometry import shape
from sqlalchemy import select

from resoiltwin.enums import AoiStatus, JobStatus, QualityFlag, SourceType, ValueQualifier
from resoiltwin.geo import wkb_to_geojson
from resoiltwin.models import Aoi, IngestionJob, Observation, Site
from resoiltwin.weather.cds import DATASET_AGERA5, VERSAO_AGERA5
from resoiltwin.weather.metrics import UNIDADE_POR_METRICA, WeatherMetric, proveniencia_de_celula

JOB_TYPE = "reanalysis_sync"

# Identifica o dataset E a versao, e as duas saem das constantes do cliente:
# escrever "agera5-v2_0" a mao aqui deixaria a proveniencia gravada a divergir
# do `version` que vai no pedido no dia em que o CDS descontinuar a 2.0.
# Entra na chave de desduplicacao, portanto e isto que distingue estas linhas
# de qualquer reprocessamento futuro.
PROCESSING_VERSION = f"agera5-v{VERSAO_AGERA5}"

# As tres variaveis do AgERA5 que o cliente sabe converter. Ficam aqui como
# omissao do servico, e nao como a unica escolha possivel: quem chama pode
# pedir menos. Uma variavel que o cliente nao conheca e recusada por ele.
VARIAVEIS = ("2m_temperature", "precipitation_flux", "solar_radiation_flux")

# mesmo limite da Fase B: o texto do erro vai para uma coluna Text sem limite,
# mas um traceback arrasta a instrucao SQL inteira com os parametros e o job
# deixa de se ler a olho.
_LIMITE_ERRO = 2000


def sync_reanalysis(session, client, site_code, date_from, date_to,
                    variaveis: list[str] | None = None) -> IngestionJob:
    """Sincroniza a serie diaria de reanalise de um sitio e devolve o job.

    O sitio tem de existir e tem de ter exactamente uma AOI aprovada: e de la
    que sai a geometria, porque a tabela `sites` nao guarda nenhuma. A recusa
    acontece ANTES de qualquer chamada a rede e antes de o job existir -- nao
    e uma execucao falhada, e uma execucao que nunca comecou.

    A partir daqui tudo o que corra mal fica registado no job (failed + error)
    em vez de subir para o chamador: a ingestao vai correr agendada, e o rasto
    util e a linha na base, nao uma excepcao que ninguem apanha. Quem chama
    tem de olhar para o `status` do job devolvido.
    """
    site, aoi = _sitio_e_aoi_aprovada(session, site_code)
    inicio, fim = _como_data(date_from), _como_data(date_to)
    variaveis = list(variaveis) if variaveis else list(VARIAVEIS)
    caixa, lat_sitio, lon_sitio = _caixa_e_ponto(aoi)
    pedido = _hash_do_pedido(site.code, aoi.code, inicio, fim, variaveis, caixa)

    job = IngestionJob(
        aoi_id=aoi.id, job_type=JOB_TYPE, status=JobStatus.pending,
        date_from=inicio, date_to=fim, request_hash=pedido,
        processing_version=PROCESSING_VERSION,
    )
    session.add(job)
    session.commit()

    # o `running` e confirmado sozinho, antes da rede: um pedido ao CDS demora
    # dezenas de segundos a minutos (submit + sondagem + transferencia) e um
    # job preso tem de ser visivel de fora enquanto corre, nao so no fim.
    job.status = JobStatus.running
    session.commit()

    try:
        linhas = client.agera5_diario(
            caixa, lat_sitio, lon_sitio, inicio.isoformat(), fim.isoformat(),
            variaveis=variaveis,
        )
        escritas = _gravar(session, site, aoi, linhas, lat_sitio, lon_sitio, pedido)
        job.status = JobStatus.succeeded
        job.rows_written = escritas
        job.finished_at = _agora()
        session.commit()
    except Exception as erro:
        # `except Exception` largo de proposito: o que interessa nao e a classe
        # do erro, e que nenhuma falha depois deste ponto deixe a execucao sem
        # rasto na base. O rollback vem primeiro e e o que garante que nao
        # ficam linhas meio-escritas -- a serie e uma transaccao, ou entra
        # toda ou nao entra nenhuma. So depois e que o job (confirmado antes
        # da rede, portanto sobrevivente do rollback) e marcado como falhado.
        session.rollback()
        job.status = JobStatus.failed
        job.rows_written = 0
        job.error = _texto_do_erro(erro)
        job.finished_at = _agora()
        session.commit()
    return job


def _sitio_e_aoi_aprovada(session, site_code: str) -> tuple[Site, Aoi]:
    """O sitio e a AOI de onde sai a sua posicao.

    A tabela `sites` nao tem coluna de geometria: a posicao de um sitio existe
    na base apenas atraves da sua AOI, e o ponto usado e o CENTROIDE dessa AOI
    -- o mesmo ponto canonico de Turcifal que `tests/test_geo.py` ja usa e que
    a Task 1 assume nas suas contas de distancia.

    Duas exigencias, e nenhuma delas e cerimonia:

    - a AOI tem de estar `approved`. Dois dos quatro poligonos deste projecto
      foram rectangulos inventados durante semanas; o centroide de um poligono
      por confirmar e um ponto inventado, e a distancia gravada em cada linha
      passaria a ser ficcao com ar de proveniencia.
    - tem de haver exactamente uma. Duas AOI aprovadas dao dois centroides,
      logo duas distancias possiveis para a mesma linha; escolher uma pela
      ordem da consulta seria escolher ao acaso e nao deixar rasto da escolha.
      Quando isso acontecer, o que falta e um argumento explicito, nao um
      criterio de desempate silencioso.
    """
    site = session.scalar(select(Site).where(Site.code == site_code))
    if site is None:
        raise ValueError(
            f"O sitio '{site_code}' nao existe. Nao se pede reanalise ao CDS sobre um "
            "sitio que nao esta na base: a caixa e o ponto vem da geometria gravada."
        )
    aois = session.scalars(
        select(Aoi).where(Aoi.site_id == site.id, Aoi.status == AoiStatus.approved)
        .order_by(Aoi.code)
    ).all()
    if not aois:
        raise ValueError(
            f"O sitio '{site_code}' nao tem nenhuma AOI approved. O ponto do sitio e o "
            "centroide da sua AOI; sobre um poligono por confirmar, a distancia a celula "
            "gravada em cada linha seria inventada."
        )
    if len(aois) > 1:
        codigos = ", ".join(aoi.code for aoi in aois)
        raise ValueError(
            f"O sitio '{site_code}' tem mais do que uma AOI approved ({codigos}) e cada uma "
            "da um centroide diferente. Escolher uma pela ordem da consulta seria escolher "
            "ao acaso a posicao que fica gravada na proveniencia."
        )
    return site, aois[0]


def _caixa_e_ponto(aoi: Aoi) -> tuple[list[float], float, float]:
    """Envelope da AOI em [Norte, Oeste, Sul, Este] e o seu centroide.

    A caixa e o pedido de transporte; o ponto e o que decide a celula. Sao
    coisas diferentes de proposito: o CDS recusa uma caixa menor do que a
    celula da grelha, portanto o cliente alarga-a, mas o valor lido continua a
    ser o da celula que contem ESTE ponto.
    """
    geojson = wkb_to_geojson(aoi.geometry)
    if geojson is None:
        raise ValueError(f"A AOI '{aoi.code}' nao tem geometria: nao ha ponto onde ler a serie.")
    geometria = shape(geojson)
    oeste, sul, este, norte = geometria.bounds
    centro = geometria.centroid
    return [norte, oeste, sul, este], centro.y, centro.x


def _gravar(session, site, aoi, linhas, lat_sitio, lon_sitio, pedido) -> int:
    """Insere so o que falta. Devolve quantas linhas foram escritas."""
    if not linhas:
        return 0

    chaves = [(_momento(linha["date"]), str(linha["metric"])) for linha in linhas]
    _garantir_chaves_distintas(chaves)
    momentos = [quando for quando, _ in chaves]
    metricas = sorted({metrica for _, metrica in chaves})
    # a leitura e por consulta, nao por excepcao: um INSERT por linha a espera
    # de apanhar IntegrityError tambem funcionaria, mas transformava a operacao
    # normal -- reexecutar uma janela ja sincronizada -- num caminho de
    # excepcao e enchia os logs de uma coisa que nao e erro.
    ja_existem = _identidades_existentes(
        session, site.id, metricas, min(momentos), max(momentos)
    )

    novas = []
    for (quando, metrica), linha in zip(chaves, linhas, strict=True):
        if (quando, metrica) in ja_existem:
            continue
        novas.append(_observacao(
            site, aoi, quando, metrica, linha, lat_sitio, lon_sitio, pedido
        ))

    if not novas:
        return 0
    session.add_all(novas)
    session.flush()
    return len(novas)


def _garantir_chaves_distintas(chaves: list[tuple[datetime, str]]) -> None:
    """Duas linhas para o mesmo dia e a mesma metrica nao cabem na identidade.

    O AgERA5 e diario: cada dia so pode ter um valor por metrica. Se vierem
    dois, uma das leituras teria de desaparecer -- e a que ficasse era
    escolhida pela ordem da resposta, ou seja ao acaso. Preferimos dize-lo: um
    job failed com o dia e a metrica nomeados e melhor do que uma serie
    silenciosamente amputada.
    """
    vistas = set()
    for quando, metrica in chaves:
        if (quando, metrica) in vistas:
            raise ValueError(
                f"A serie traz mais do que um valor de '{metrica}' para {quando.date()}. "
                "O AgERA5 e diario: gravar um e descartar o outro seria escolher ao acaso "
                "pela ordem da resposta. Rever a janela ou as variaveis do pedido."
            )
        vistas.add((quando, metrica))


def _identidades_existentes(session, site_id, metricas, inicio, fim) -> set:
    """Pares (observed_at, metric) ja gravados para este sitio e esta versao.

    O filtro repete a identidade toda da uq_observation_identity -- site_id,
    plot_id, observed_at, metric, source_type, processing_version -- e nao um
    subconjunto conveniente. Cada coluna que faltasse aqui alargava o que
    conta como "ja existe": uma linha que NAO e duplicado passaria por
    duplicado e nunca seria escrita, com o job a dizer succeeded na mesma. O
    source_type e o mais caro de esquecer nesta camada, porque
    air_temperature e relative_humidity ja existem na base como leituras de
    campo do mesmo sitio e dos mesmos dias.
    """
    filas = session.execute(
        select(Observation.observed_at, Observation.metric).where(
            Observation.site_id == site_id,
            Observation.plot_id.is_(None),
            Observation.source_type == SourceType.reanalysis,
            Observation.processing_version == PROCESSING_VERSION,
            Observation.metric.in_(metricas),
            Observation.observed_at >= inicio,
            Observation.observed_at <= fim,
        )
    ).all()
    # os dois lados aware: a coluna e timestamptz e o psycopg devolve sempre
    # com fuso, portanto a comparacao ja seria pelo instante. O astimezone
    # esta aqui para por as chaves todas no mesmo referencial, para quem as
    # inspeccionar as ler sem converter de cabeca.
    return {(quando.astimezone(timezone.utc), metrica) for quando, metrica in filas}


def _observacao(site, aoi, quando, metrica, linha, lat_sitio, lon_sitio, pedido):
    """Uma linha de reanalise, com a proveniencia da celula que a produziu.

    source_type e `reanalysis` e nao `weather_observed`: o AgERA5 e a saida de
    um modelo alimentado por observacoes, nao a leitura de um instrumento --
    `SourceType.is_measurement` confirma que esta origem nao e uma medicao. A
    diferenca importa num sistema MRV, onde o que se pode defender e o que se
    mediu.

    plot_id fica a None de proposito: a serie e do sitio, nao de uma parcela.
    Uma celula de 9 km nao distingue duas parcelas separadas por 200 m, e
    atribui-la a uma delas seria inventar resolucao. E por isto que a
    uq_observation_identity leva postgresql_nulls_not_distinct=True; sem essa
    opcao o Postgres trataria cada NULL como distinto e a desduplicacao
    falhava exactamente aqui.
    """
    proveniencia = proveniencia_de_celula(
        linha["cell_lat"], linha["cell_lon"], lat_sitio, lon_sitio, linha["cell_size_deg"],
    )
    return Observation(
        site_id=site.id,
        plot_id=None,
        observed_at=quando,
        metric=metrica,
        unit=_unidade(metrica, linha),
        value_numeric=linha["value"],
        value_qualifier=ValueQualifier.exact,
        source_type=SourceType.reanalysis,
        # o AgERA5 v2.0 e um campo completo e ja controlado na origem; o que
        # separa modelo de medicao e o source_type, nao a bandeira de
        # qualidade, que continua a ser sobre o valor e nao sobre a fonte.
        quality_flag=QualityFlag.valid,
        source_collection=linha["dataset"],
        processing_version=PROCESSING_VERSION,
        evidence={
            "site_code": site.code,
            "aoi_code": aoi.code,
            # o ponto a que a distancia se refere, para a conta se poder
            # refazer sem ir buscar a geometria da AOI de hoje -- que pode ser
            # corrigida depois de a serie estar gravada
            "site_lat": lat_sitio,
            "site_lon": lon_sitio,
            "variable": linha["variable"],
            "request_hash": pedido,
            # o que foi pedido ao CDS, que e muito maior do que a AOI: a
            # caixa alargada e imposicao da API (uma caixa menor do que a
            # celula devolve MultiAdaptorNoDataError). Fica escrito para que
            # ninguem confunda o que foi transferido com o que foi lido.
            "area_aoi": linha["area_original"],
            "area_requested": linha["area_requested"],
            "area_expanded": linha["area_expanded"],
            # cell_lat, cell_lon, distance_km, cell_size_deg, cell_size_km_ns,
            # cell_size_km_ew e measured_at_site=False
            **proveniencia,
        },
    )


def _unidade(metrica: str, linha: dict) -> str:
    """A unidade sai do vocabulario, e tem de bater certo com a da linha.

    Sao duas fontes para a mesma coisa de proposito. Um valor em Kelvin
    rotulado degC entra na base sem nada a assinalar -- o numero e plausivel e
    a unidade e credivel -- e depois nao ha volta. Se as duas discordarem, o
    job falha em vez de gravar.
    """
    esperada = UNIDADE_POR_METRICA[WeatherMetric(metrica)]
    if linha.get("unit") != esperada:
        raise ValueError(
            f"A linha de '{metrica}' vem em '{linha.get('unit')}' e o vocabulario diz "
            f"'{esperada}'. Gravar o valor com a unidade errada e irreversivel: o numero "
            "continua plausivel e ninguem volta a olhar para ele."
        )
    return esperada


def _hash_do_pedido(site_code, aoi_code, inicio, fim, variaveis, caixa) -> str:
    """Identidade do pedido: mesmo sitio, mesma janela, mesmas variaveis, mesma
    caixa, mesma versao -- mesmo hash. E o que liga cada observacao a execucao
    que a produziu, e o que permite reconhecer duas execucoes do mesmo pedido
    sem repetir o pedido."""
    material = json.dumps({
        "site_code": site_code,
        "aoi_code": aoi_code,
        "date_from": inicio.isoformat(),
        "date_to": fim.isoformat(),
        "dataset": DATASET_AGERA5,
        "processing_version": PROCESSING_VERSION,
        "variables": sorted(variaveis),
        "area": [float(x) for x in caixa],
    }, sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


def _como_data(valor) -> date:
    """Aceita `date` ou texto ISO. O job guarda Date; o cliente quer texto."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _momento(texto: str) -> datetime:
    """O AgERA5 agrega por dia: a data e o dia, sem hora. Gravar meia-noite UTC
    e o unico instante honesto -- inventar uma hora seria precisao que o dado
    nao tem."""
    dia = date.fromisoformat(str(texto)[:10])
    return datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)


def _texto_do_erro(erro: Exception) -> str:
    detalhe = str(erro).strip()
    texto = f"{type(erro).__name__}: {detalhe}" if detalhe else type(erro).__name__
    return texto[:_LIMITE_ERRO]


def _agora() -> datetime:
    return datetime.now(timezone.utc)
