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
from resoiltwin.eo.evalscripts import (
    EVALSCRIPT_VERSION,
    EVALSCRIPT_VERSION_SCL,
    NDVI_NDMI_NDRE,
    NDVI_NDMI_NDRE_SCL,
    SCL_CLASSES_EXCLUIDAS,
    evalscript_hash,
)
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
             max_cloud: int = DEFAULT_MAX_CLOUD,
             *, com_mascara_scl: bool = True) -> IngestionJob:
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

    `com_mascara_scl` e so de palavra-chave, e por omissao verdadeiro: quem
    nao escolher fica com a mascara ao pixel, que e o comportamento correcto.
    O v1 sem mascara continua acessivel para reproduzir as series que ja estao
    gravadas -- nao e o caminho normal, e a forma de repetir o passado.
    """
    aoi = _aoi_aprovada(session, aoi_code)
    inicio, fim = _como_data(date_from), _como_data(date_to)
    evalscript, marca_mascara = _escolher_evalscript(com_mascara_scl)
    # a versao sai do MESMO objecto que vai no pedido, logo abaixo: e o que
    # torna impossivel enviar um script e gravar a identidade de outro.
    versao = processing_version(evalscript)
    pedido = _hash_do_pedido(aoi_code, inicio, fim, versao, resolution_m, max_cloud)

    # a versao fica no job desde o inicio, e nao no fim: um job que falhe, ou
    # que escreva zero linhas por a janela ja estar sincronizada, tem de dizer
    # na mesma com que script correu. Se so fosse gravada no sucesso, o unico
    # caso em que nao havia observacoes onde a ler seria tambem o unico em que
    # o job nao a tinha.
    job = IngestionJob(
        aoi_id=aoi.id, job_type=JOB_TYPE, status=JobStatus.pending,
        date_from=inicio, date_to=fim, request_hash=pedido,
        processing_version=versao,
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
            geometria, inicio.isoformat(), fim.isoformat(), evalscript,
            resolution_m=resolution_m, max_cloud=max_cloud,
        )
        _garantir_dentro_da_janela(linhas, inicio, fim)
        escritas = _gravar(
            session, aoi, linhas, versao, pedido, resolution_m, max_cloud, marca_mascara
        )
        job.date_from, job.date_to = _janela_coberta(linhas, inicio, fim)
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


# O rotulo de cada script vive ao lado do proprio script, num unico sitio. Sem
# este mapa a versao seria escolhida por um `if` a parte da escolha do script,
# e as duas decisoes podiam divergir -- que e exactamente a mentira de
# proveniencia que estamos a impedir.
_VERSAO_POR_EVALSCRIPT = {
    NDVI_NDMI_NDRE: EVALSCRIPT_VERSION,
    NDVI_NDMI_NDRE_SCL: EVALSCRIPT_VERSION_SCL,
}


def _escolher_evalscript(com_mascara_scl: bool) -> tuple[str, dict]:
    """Decide, num so lugar, o script a enviar e a marca que vai no evidence.

    Sai daqui um par porque as duas coisas descrevem a mesma decisao: se a
    marca da mascara fosse construida noutro sitio, uma linha podia dizer que
    foi mascarada tendo sido produzida pelo script sem mascara.

    A ausencia do campo nao serve para dizer "sem mascara": era indistinguivel
    de uma linha gravada antes de a mascara existir. Por isso o `scl_mask`
    aparece sempre, e as classes so quando ha de facto exclusao.
    """
    if com_mascara_scl:
        return NDVI_NDMI_NDRE_SCL, {
            "scl_mask": True,
            "scl_classes_excluded": sorted(SCL_CLASSES_EXCLUIDAS),
        }
    return NDVI_NDMI_NDRE, {"scl_mask": False}


def processing_version(evalscript: str) -> str:
    """Versao do evalscript mais o hash do script que realmente correu.

    O script entra por argumento explicito, sem valor por omissao: e o que
    torna impossivel gravar a identidade de um script diferente daquele que
    foi enviado. Um script desconhecido levanta KeyError de propria vontade --
    gravar uma versao inventada seria pior do que falhar.
    """
    return f"{_VERSAO_POR_EVALSCRIPT[evalscript]}+{evalscript_hash(evalscript)}"


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


def _gravar(session, aoi, linhas, versao, pedido, resolution_m, max_cloud, marca_mascara) -> int:
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
                aoi, quando, metrica, linha, versao, pedido, resolution_m, max_cloud,
                marca_mascara,
            ))

    if not novas:
        return 0
    session.add_all(novas)
    session.flush()
    return len(novas)


def _garantir_dentro_da_janela(linhas, inicio: date, fim: date) -> None:
    """Nenhuma aquisicao pode trazer um dia fora da janela pedida.

    Palavra por palavra a razao que `weather/ingest.py::_garantir_dentro_da_janela`
    ja escrevia, e que se aplicava literalmente a este caminho sem que aqui
    houvesse guarda nenhuma: a janela da consulta de desduplicacao
    (`_identidades_existentes`) sai do `min`/`max` dos dias DEVOLVIDOS, e nao
    dos dias pedidos. Um dia a mais na resposta entrava na base debaixo de um
    job cujo `date_from`/`date_to` diz outra coisa, e o rasto do job passava a
    descrever mal o que ele escreveu.

    Que a Statistical API o faca nao esta provado -- o `aggregation.timeRange`
    do pedido recorta a serie na origem e nunca se viu um dia fora. O que esta
    provado e a assimetria: dois caminhos de ingestao com a mesma estrutura, a
    mesma consequencia e a guarda so num deles.
    """
    fora = sorted({_como_data(linha["date"]).isoformat() for linha in linhas
                   if not (inicio <= _como_data(linha["date"]) <= fim)})
    if fora:
        raise ValueError(
            f"A Statistical API devolveu aquisicoes fora da janela pedida "
            f"[{inicio.isoformat()}, {fim.isoformat()}]: {', '.join(fora)}. Grava-las aqui "
            "punha na base linhas que o job nao diz ter pedido."
        )


def _janela_coberta(linhas, inicio: date, fim: date) -> tuple[date, date]:
    """A janela que o job declara: a que a serie cobriu, nao a que se pediu.

    O job e a unica linha que alguem le para saber o que uma corrida trouxe. O
    Sentinel-2 revisita de cinco em cinco dias e o filtro de nuvens corta a
    maioria: pedir Agosto inteiro e receber quatro aquisicoes e o caso NORMAL,
    nao a excepcao. Ate 30/08/2026 o job nascia com a janela pedida e o sucesso
    nao lhe tocava -- os sete jobs de EO ja na base afirmam todos uma cobertura
    que a propria serie desmente. E a mesma forma do defeito que o
    `_janela_coberta_por_todas` da meteorologia fechou, e que o `water` ja
    nasceu a nao ter.

    Nao ha aqui a interseccao por variavel da meteorologia porque nao ha
    variaveis: o evalscript devolve os tres indices JUNTOS por aquisicao, e uma
    saida incompleta e descartada inteira no cliente (`_normalizar`). Uma
    aquisicao ou traz os tres ou nao conta, portanto o min/max sobre as datas
    ja e verdadeiro para os tres.

    **Zero aquisicoes fica com a janela PEDIDA**, e nao e descuido. A
    meteorologia levanta neste caso, e la faz sentido: o AgERA5 e um arquivo
    continuo e uma variavel sem um unico dia e sinal de que algo correu mal.
    Aqui um mes sem aquisicao utilizavel e meteorologia normal em Portugal no
    Inverno; transformar isso num `failed` era chamar erro ao que nao e, e
    encher de `error` um registo que passa a correr agendado. O que distingue
    os dois casos e o `rows_written = 0` ao lado da janela -- e continua a
    faltar separar "o satelite nao passou" de "passou e nos descartamos", que
    e trabalho por fazer no cliente e nao aqui.
    """
    if not linhas:
        return inicio, fim
    dias = sorted(_como_data(linha["date"]) for linha in linhas)
    return dias[0], dias[-1]


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
    """Pares (observed_at, metric) ja gravados para este sitio e esta versao.

    O filtro repete a identidade toda da uq_observation_identity -- site_id,
    plot_id, observed_at, metric, source_type, processing_version -- e nao um
    subconjunto conveniente. Cada coluna que faltasse aqui alargava o que
    conta como "ja existe": uma linha que NAO e duplicado passaria por
    duplicado e nunca seria escrita, com o job a dizer succeeded na mesma.
    O site_id e o mais caro de esquecer -- duas AOI aprovadas em sitios
    diferentes, mesma janela e mesma versao, e a segunda perdia a serie
    inteira em silencio.
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
    # o que importa e os dois lados serem aware: um datetime com fuso compara
    # -- e faz hash -- pelo instante, portanto +01:00 e UTC batem certo
    # sozinhos, venha a sessao no fuso que vier. O astimezone nao esta aqui a
    # corrigir a comparacao; esta a por as chaves todas no mesmo referencial
    # para quem as inspeccionar as ler sem converter de cabeca. O que partiria
    # a desduplicacao era um lado naive, e a coluna e timestamptz: o psycopg
    # devolve sempre aware.
    return {(quando.astimezone(timezone.utc), metrica) for quando, metrica in filas}


def _observacao(aoi, quando, metrica, linha, versao, pedido, resolution_m, max_cloud,
                marca_mascara):
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
        # `unchecked` e nao `valid`, e nao ha aqui condicao nenhuma de
        # proposito. Ate 30/08/2026 estava aqui o literal `QualityFlag.valid`:
        # as 108 linhas de satelite afirmavam qualidade por construcao, sem uma
        # unica verificacao por tras. Uma delas -- 24/08/2026 em Campo Real --
        # e a media sobre 8,47% da parcela que `docs/evidence/2026-08-29-
        # mascara-scl.md` ja tinha declarado NAO utilizavel, e entrava num
        # `WHERE quality_flag = 'valid'` ao lado das de ceu limpo.
        #
        # A tentacao era escrever um limiar ("abaixo de 20% de cobertura e
        # suspeito"). Nao ha nada neste projecto que sustente um numero desses,
        # e uma percentagem inventada e pior do que nenhuma: da confianca falsa
        # com ar de criterio. As duas fronteiras que nao seriam inventadas
        # tambem nao servem -- "zero pixeis excluidos" marcaria `valid` a serie
        # v1 SEM mascara (onde o noDataCount e sempre zero porque ninguem
        # procurou nuvem) e `unchecked` a serie v2 mascarada, que e melhor:
        # exactamente ao contrario.
        #
        # Fica o que e verdade: nada nesta ingestao verifica a qualidade de um
        # indice espectral. `unchecked` diz isso, e `contributing_pixels` no
        # evidence poe na linha a contagem real para quem quiser aplicar o SEU
        # criterio -- que e uma decisao de quem le a serie, nao de quem a grava.
        quality_flag=QualityFlag.unchecked,
        source_collection=COLLECTION,
        processing_version=versao,
        evidence={
            "aoi_code": aoi.code,
            # `[...]` e nao `.get(...)`: um cliente que nao diga quantos pixeis
            # amostrou e quantos contribuiram nao pode gravar `null` em
            # silencio, que se confundiria com uma linha anterior a 30/08/2026.
            "sampled_pixels": linha["sampled_pixels"],
            "contributing_pixels": linha["contributing_pixels"],
            "no_data_pixels": linha["no_data_pixels"],
            "request_hash": pedido,
            "resolution_m": resolution_m,
            "max_cloud": max_cloud,
            # scl_mask e, quando ha mascara, scl_classes_excluded: quem
            # consultar esta linha daqui a um ano tem de saber se foi
            # mascarada, e o que ficou de fora, sem ir ler o codigo.
            **marca_mascara,
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
