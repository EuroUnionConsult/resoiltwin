"""Ingestao de series Sentinel-2 para a tabela canonica de observacoes.

E aqui que o cliente HTTP do Copernicus encontra a base de dados: pega numa AOI
aprovada, vai buscar as series agregadas ao poligono e grava-as ao lado das
leituras de campo, com a proveniencia toda e sem nunca duplicar.

O cliente vem de fora, por argumento. Nao e cerimonia de testes: e o que
permite que a suite injecte um CDSEClient sobre httpx.MockTransport e nenhum
teste toque na rede.
"""

import hashlib
import json
from datetime import date, datetime, timezone

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform
from sqlalchemy import select

from resoiltwin.enums import AoiStatus, JobStatus, QualityFlag, SourceType, ValueQualifier
from resoiltwin.eo.evalscripts import EVALSCRIPT_VERSION, NDVI_NDMI_NDRE, evalscript_hash
from resoiltwin.geo import PROCESSING_SRID, STORAGE_SRID, wkb_to_geojson
from resoiltwin.models import Aoi, IngestionJob, Observation

JOB_TYPE = "eo_sync"
COLLECTION = "sentinel-2-l2a"
UNIT = "index"
METRICS = ("ndvi", "ndmi", "ndre")

DEFAULT_RESOLUTION_M = 10
DEFAULT_MAX_CLOUD = 30

# o texto do erro vai para uma coluna Text sem limite, mas um traceback de
# IntegrityError arrasta a instrucao SQL inteira com os parametros: cortamos
# para o job continuar legivel a olho.
_LIMITE_ERRO = 2000

# a base guarda 4326 e a Statistical API exige 32629; os dois numeros vem de
# resoiltwin.geo para nao existir uma segunda opiniao sobre qual e qual.
_PARA_UTM = Transformer.from_crs(
    f"EPSG:{STORAGE_SRID}", f"EPSG:{PROCESSING_SRID}", always_xy=True
)


def sync_aoi(session, client, aoi_code, date_from, date_to,
             resolution_m: int = DEFAULT_RESOLUTION_M,
             max_cloud: int = DEFAULT_MAX_CLOUD) -> IngestionJob:
    """Sincroniza a serie de indices espectrais de uma AOI e devolve o job.

    A AOI tem de estar `approved`: uma draft, rejected ou inexistente levanta
    ValueError ANTES de qualquer chamada a rede. Dois dos quatro poligonos
    deste projecto foram, durante semanas, rectangulos inventados -- esta
    guarda impede que se gastem pedidos, e que se produzam numeros, sobre um
    poligono que ninguem confirmou. Por isso a recusa acontece antes de o job
    existir: nao e uma execucao falhada, e uma execucao que nunca comecou.

    A partir daqui tudo o que corra mal fica registado no job (failed + error)
    em vez de subir para o chamador. A ingestao passa a correr agendada na
    fase seguinte, sem ninguem a ver o ecra: o rasto util e a linha na base,
    nao uma excepcao que ninguem apanha. Quem chama tem de olhar para o
    `status` do job devolvido -- succeeded nao e o unico fim possivel.
    """
    aoi = _aoi_aprovada(session, aoi_code)
    inicio, fim = _como_data(date_from), _como_data(date_to)
    versao = processing_version()
    pedido = _hash_do_pedido(aoi_code, inicio, fim, versao, resolution_m, max_cloud)

    job = IngestionJob(
        aoi_id=aoi.id, job_type=JOB_TYPE, status=JobStatus.pending,
        date_from=inicio, date_to=fim, request_hash=pedido,
    )
    session.add(job)
    session.commit()

    # o `running` e confirmado sozinho, antes da rede: um job que fique preso
    # numa chamada de minutos tem de ser visivel de fora enquanto corre, e nao
    # so quando acabar.
    job.status = JobStatus.running
    session.commit()

    try:
        geometria = _para_utm(wkb_to_geojson(aoi.geometry))
        linhas = client.statistics(
            geometria, inicio.isoformat(), fim.isoformat(), NDVI_NDMI_NDRE,
            resolution_m=resolution_m, max_cloud=max_cloud,
        )
        escritas = _gravar(session, aoi, linhas, versao, pedido, resolution_m, max_cloud)
        job.status = JobStatus.succeeded
        job.rows_written = escritas
        job.finished_at = _agora()
        session.commit()
    except Exception as erro:
        # o `except Exception` e largo de proposito: o que interessa nao e a
        # classe do erro, e que nenhuma falha depois deste ponto deixe a
        # execucao sem rasto na base.
        # o rollback vem primeiro e e o que garante que nao ficam linhas
        # meio-escritas: a serie inteira e uma transaccao, ou entra toda ou
        # nao entra nenhuma. So depois de a limpar e que o job -- ja
        # confirmado antes da rede, portanto sobrevivente do rollback -- e
        # marcado como falhado.
        session.rollback()
        job.status = JobStatus.failed
        job.rows_written = 0
        job.error = _texto_do_erro(erro)
        job.finished_at = _agora()
        session.commit()
    return job


def processing_version() -> str:
    """Versao do evalscript mais o hash do script que realmente correu.

    O hash entra por argumento explicito: e o que torna impossivel gravar a
    identidade de um script diferente daquele que foi enviado.
    """
    return f"{EVALSCRIPT_VERSION}+{evalscript_hash(NDVI_NDMI_NDRE)}"


def _aoi_aprovada(session, aoi_code: str) -> Aoi:
    aoi = session.scalar(select(Aoi).where(Aoi.code == aoi_code))
    if aoi is None:
        raise ValueError(
            f"AOI '{aoi_code}' nao existe. So uma AOI approved pode ser sincronizada: "
            "nao se gastam pedidos ao Copernicus sobre um poligono que nao esta na base."
        )
    if aoi.status != AoiStatus.approved:
        raise ValueError(
            f"AOI '{aoi_code}' esta '{aoi.status}' e a ingestao exige 'approved'. "
            "Um poligono por confirmar produz numeros que nao se podem defender; "
            "aprovar a AOI antes de sincronizar."
        )
    return aoi


def _para_utm(geometria_4326: dict) -> dict:
    """Reprojeccao feita aqui dentro, nao pelo chamador.

    Com coordenadas em graus a Statistical API le resx:10 como 10 GRAUS por
    pixel e devolve uma serie de um pixel que parece plausivel. O cliente tem
    uma guarda para isso, mas a guarda e a rede de seguranca, nao o mecanismo:
    quem sabe que a base guarda 4326 e a API quer 32629 e este servico.
    """
    if geometria_4326 is None:
        raise ValueError("A AOI nao tem geometria: nada para pedir ao Copernicus.")
    return mapping(shapely_transform(_PARA_UTM.transform, shape(geometria_4326)))


def _gravar(session, aoi, linhas, versao, pedido, resolution_m, max_cloud) -> int:
    """Insere so o que falta. Devolve quantas linhas foram escritas."""
    if not linhas:
        return 0

    momentos = [_momento(linha["date"]) for linha in linhas]
    _garantir_datas_distintas(momentos)
    # a leitura e por consulta, nao por excepcao: um INSERT por linha a espera
    # de apanhar IntegrityError tambem funcionaria, mas transformava a
    # operacao normal (reexecutar uma janela ja sincronizada) num caminho de
    # excepcao e enchia os logs de uma coisa que nao e erro.
    ja_existem = _identidades_existentes(
        session, aoi.site_id, versao, min(momentos), max(momentos)
    )

    novas = []
    for quando, linha in zip(momentos, linhas, strict=True):
        for metrica in METRICS:
            if (quando, metrica) in ja_existem:
                continue
            novas.append(_observacao(
                aoi, quando, metrica, linha, versao, pedido, resolution_m, max_cloud
            ))

    if not novas:
        return 0
    session.add_all(novas)
    session.flush()
    return len(novas)


def _garantir_datas_distintas(momentos: list[datetime]) -> None:
    """Duas entradas para o mesmo dia nao cabem na identidade da observacao.

    A agregacao e P1D, portanto o Copernicus devolve um intervalo por dia; se
    devolver dois, uma das leituras teria de desaparecer. Preferimos dize-lo:
    a que ficasse era escolhida ao acaso pela ordem da resposta, e uma serie
    silenciosamente amputada e pior do que um job failed com o dia indicado.
    """
    vistos = set()
    for quando in momentos:
        if quando in vistos:
            raise ValueError(
                f"A Statistical API devolveu mais do que uma entrada para {quando.date()}. "
                "Com agregacao P1D cada dia so pode ter uma leitura; gravar uma e descartar "
                "a outra seria escolher ao acaso. Rever a janela ou a agregacao do pedido."
            )
        vistos.add(quando)


def _identidades_existentes(session, site_id, versao, inicio, fim) -> set:
    """Pares (observed_at, metric) ja gravados para esta AOI e esta versao.

    O filtro tem de repetir a identidade toda da uq_observation_identity, o
    plot_id nulo incluido: uma linha de satelite de uma parcela nao pode
    passar por duplicado da serie da AOI, que e outra linha e outro valor.
    """
    filas = session.execute(
        select(Observation.observed_at, Observation.metric).where(
            Observation.site_id == site_id,
            Observation.plot_id.is_(None),
            Observation.source_type == SourceType.satellite_observed,
            Observation.processing_version == versao,
            Observation.metric.in_(METRICS),
            Observation.observed_at >= inicio,
            Observation.observed_at <= fim,
        )
    ).all()
    # o Postgres devolve timestamptz no fuso da sessao; normalizar para UTC
    # antes de comparar, senao a mesma instante em +01:00 nao bate certo com o
    # mesmo instante em UTC e a desduplicacao falha em silencio.
    return {(quando.astimezone(timezone.utc), metrica) for quando, metrica in filas}


def _observacao(aoi, quando, metrica, linha, versao, pedido, resolution_m, max_cloud):
    """Uma linha de indice espectral, com a proveniencia completa.

    source_type e satellite_observed e nao derived: um indice calculado sobre
    a reflectancia de uma aquisicao continua a ser uma medicao do satelite --
    SourceType.is_measurement confirma-o -- e nao um produto calculado sobre
    outras observacoes da base.

    plot_id fica a None de proposito: a serie e da AOI inteira, nao de uma
    parcela. E por isto que a uq_observation_identity leva
    postgresql_nulls_not_distinct=True; sem essa opcao o Postgres trataria
    cada NULL como distinto e a desduplicacao falharia exactamente aqui.
    """
    return Observation(
        site_id=aoi.site_id,
        plot_id=None,
        observed_at=quando,
        metric=metrica,
        unit=UNIT,
        value_numeric=linha.get(metrica),
        value_qualifier=ValueQualifier.exact,
        source_type=SourceType.satellite_observed,
        quality_flag=QualityFlag.valid,
        source_collection=COLLECTION,
        processing_version=versao,
        evidence={
            "aoi_code": aoi.code,
            "valid_pixels": linha.get("valid_pixels"),
            "no_data_pixels": linha.get("no_data_pixels"),
            "request_hash": pedido,
            "resolution_m": resolution_m,
            "max_cloud": max_cloud,
        },
    )


def _hash_do_pedido(aoi_code, inicio, fim, versao, resolution_m, max_cloud) -> str:
    """Identidade do pedido: mesma AOI, mesma janela, mesmos parametros, mesmo
    hash. E o que liga cada observacao a execucao que a produziu, e o que
    permite reconhecer duas execucoes do mesmo pedido sem repetir o pedido."""
    material = json.dumps({
        "aoi_code": aoi_code,
        "date_from": inicio.isoformat(),
        "date_to": fim.isoformat(),
        "collection": COLLECTION,
        "processing_version": versao,
        "resolution_m": resolution_m,
        "max_cloud": max_cloud,
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
    """A Statistical API agrega por dia (P1D): a data e o dia da aquisicao, sem
    hora. Gravar meia-noite UTC e o unico instante honesto -- inventar a hora
    de passagem do satelite seria precisao que os dados nao tem."""
    dia = date.fromisoformat(str(texto)[:10])
    return datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)


def _texto_do_erro(erro: Exception) -> str:
    detalhe = str(erro).strip()
    texto = f"{type(erro).__name__}: {detalhe}" if detalhe else type(erro).__name__
    return texto[:_LIMITE_ERRO]


def _agora() -> datetime:
    return datetime.now(timezone.utc)
