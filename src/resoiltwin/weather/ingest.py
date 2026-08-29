"""Ingestao meteorologica para a tabela canonica de observacoes.

Duas fontes, dois sincronizadores, uma so tabela: a reanalise AgERA5 (o
cliente do Climate Data Store, `sync_reanalysis`) e as estacoes do IPMA
(`sync_ipma`). Pegam num sitio, vao buscar a serie da celula de grelha que o
contem ou da estacao mais proxima dele, e gravam-na ao lado das leituras de
campo e dos indices de satelite.

O que as separa na base nao e o nome da metrica -- as duas escrevem
`air_temperature` -- e o `source_type`: `reanalysis` para o modelo,
`weather_observed` para a estacao, que e uma medicao. As linhas do mesmo
instante e da mesma grandeza coexistem por isso, e a chave de identidade
admite-as as duas.

O que distingue esta camada das outras duas e o que cada linha tem de admitir
sobre si propria. A celula do AgERA5 tem ~9 km e a AOI de Turcifal tem 2,5 km:
uma celula cobre o micro-site, o Campo Real e boa parte do concelho. A chuva
que se grava para o sitio nao e a chuva daquele campo, e se isso nao ficar na
linha ninguem o recupera depois -- por isso cada observacao leva no `evidence`
a celula que a produziu, a distancia a que ela esta do sitio, a pegada da
celula nas duas direccoes e a caixa que foi mesmo pedida ao CDS.

O cliente vem de fora, por argumento, como na Fase B: e o que permite que a
suite injecte um duplo e nenhum teste toque na rede.

Duas linguas nas mensagens de erro, com uma regra e nao por acaso. O que se
recusa ANTES de o job existir sobe como excepcao e sai pela rota
`POST /sites/{code}/weather/sync` como corpo de um erro HTTP: e superficie de
API e esta em INGLES, como o resto dela. O que corre mal depois nao sobe -- fica
em `job.error`, que e lido por quem opera a ingestao -- e continua em portugues,
como os comentarios. A fronteira e o `session.add(job)`.
"""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from shapely.geometry import shape
from sqlalchemy import select

from resoiltwin.enums import AoiStatus, JobStatus, QualityFlag, SourceType, ValueQualifier
from resoiltwin.geo import wkb_to_geojson
from resoiltwin.models import Aoi, IngestionJob, Observation, Site
from resoiltwin.weather.cds import DATASET_AGERA5, VERSAO_AGERA5
from resoiltwin.weather.ipma import (
    COLECCAO_IPMA, RAIO_MAXIMO_KM, URL_OBSERVACOES, VERSAO_IPMA, linhas_da_estacao,
)
from resoiltwin.weather.metrics import (
    UNIDADE_POR_METRICA, WeatherMetric, proveniencia_de_celula, proveniencia_de_estacao,
)

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

JOB_TYPE_IPMA = "ipma_sync"

# Mesma funcao que a PROCESSING_VERSION da reanalise, e pela mesma razao
# (entra na chave de identidade), mas o numero e NOSSO: o IPMA nao versiona o
# feed. Muda-la e dizer "isto foi processado por outro mapa de campos ou por
# outra conversao de unidades", e a serie nova fica ao lado da antiga em vez
# de colidir com ela.
PROCESSING_VERSION_IPMA = f"ipma-stations-v{VERSAO_IPMA}"

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
    _garantir_janela_valida(inicio, fim)
    variaveis = list(variaveis) if variaveis else list(VARIAVEIS)
    caixa, lat_sitio, lon_sitio = _caixa_e_ponto(aoi)
    pedido = _hash_do_pedido({
        "site_code": site.code,
        "aoi_code": aoi.code,
        "date_from": inicio.isoformat(),
        "date_to": fim.isoformat(),
        "dataset": DATASET_AGERA5,
        "processing_version": PROCESSING_VERSION,
        "variables": sorted(variaveis),
        # o ENVELOPE da AOI, e nao a caixa alargada que segue para o CDS. As
        # duas identificam o mesmo pedido: o alargamento e uma funcao
        # deterministica do envelope (`expandir_area`), portanto nao ha dois
        # envelopes diferentes a dar a mesma caixa alargada. O nome diz qual
        # das duas e, porque o `evidence` grava as duas e confundi-las era
        # afirmar que se pediu uma area que nao foi a pedida.
        "area_aoi": [float(x) for x in caixa],
    })

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
        _garantir_dentro_da_janela(linhas, inicio, fim)

        def construir(quando, metrica, linha):
            return _observacao(site, aoi, quando, metrica, linha, lat_sitio, lon_sitio, pedido)

        escritas = _gravar(session, site, linhas, SourceType.reanalysis, PROCESSING_VERSION,
                           construir)
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


def sync_ipma(session, client, site_code, raio_maximo_km: float | None = None) -> IngestionJob:
    """Sincroniza as ultimas 24 horas da estacao do IPMA mais proxima do sitio.

    Nao leva janela por argumento, ao contrario da reanalise, e a diferenca
    nao e de conveniencia: o feed do IPMA nao tem parametro de data nenhum e
    so publica as ultimas 24 horas. Aceitar um `date_from` aqui era prometer
    um arquivo que nao existe. O historico deste sitio comeca no dia em que
    esta funcao comecar a correr e cresce uma hora de cada vez, e e a
    desduplicacao que permite corre-la de hora a hora: de cada 24 horas
    lidas, 23 ja la estao e nao voltam a ser escritas.

    A estacao e escolhida por proximidade ao ponto do sitio (o centroide da
    AOI aprovada), e a distancia vai no `evidence` de cada linha. Nao ha
    nenhuma estacao do IPMA dentro de uma parcela: 5,34 km em Turcifal e o
    melhor que ha, e continua a nao ser uma medicao no campo.

    `raio_maximo_km` e o tecto acima do qual a estacao mais proxima deixa de
    servir. Ate aqui a politica estava so no valor por omissao do cliente e
    era inalcancavel de fora: quem chamasse `sync_ipma` nao tinha como alarga-la
    nem como aperta-la, e o cliente e construido por quem monta a aplicacao, nao
    por quem pede a sincronizacao. `None` mantem o tecto do cliente
    (RAIO_MAXIMO_KM), que continua a ser a politica por omissao.

    O tecto fica gravado em cada linha: "esta e a mais proxima" so quer dizer
    alguma coisa com o tecto que estava em vigor ao lado, e o tecto passou a
    ser do chamador. O numero de estacoes consideradas fecharia a verificacao
    e ainda falta -- ver o comentario em `_observacao_de_estacao`.

    Como em `sync_reanalysis`, o sitio e a AOI sao resolvidos ANTES de o job
    existir e antes da rede -- uma recusa nao e uma execucao falhada, e uma
    que nunca comecou -- e tudo o que corra mal a partir dai fica no job em
    vez de subir para quem chama.
    """
    site, aoi = _sitio_e_aoi_aprovada(session, site_code)
    _, lat_sitio, lon_sitio = _caixa_e_ponto(aoi)
    raio = RAIO_MAXIMO_KM if raio_maximo_km is None else float(raio_maximo_km)

    # A janela nominal do pedido: o feed cobre as ultimas 24 horas, portanto
    # ontem e hoje em UTC. Nao e o que vai ser gravado -- e o que vai ser
    # PEDIDO, e o job tem de nascer com uma janela porque as duas colunas nao
    # sao anulaveis e ele existe antes de a resposta chegar. Quando a resposta
    # chegar, o job passa a declarar as horas que foram mesmo escritas.
    hoje = _agora().date()
    janela = (hoje - timedelta(days=1), hoje)
    pedido = _hash_do_pedido({
        "site_code": site.code,
        "aoi_code": aoi.code,
        "date_from": janela[0].isoformat(),
        "date_to": janela[1].isoformat(),
        "dataset": COLECCAO_IPMA,
        "processing_version": PROCESSING_VERSION_IPMA,
        # o URL nao leva parametros: e a identidade toda do pedido, com o dia.
        # A estacao nao entra no hash de proposito -- so se sabe qual e depois
        # da rede, e o job tem de existir antes dela. Quem quiser saber que
        # estacao produziu uma linha le-o no `evidence` dessa linha, que e
        # onde ele nao pode ficar por saber.
        "source_url": URL_OBSERVACOES,
    })

    job = IngestionJob(
        aoi_id=aoi.id, job_type=JOB_TYPE_IPMA, status=JobStatus.pending,
        date_from=janela[0], date_to=janela[1], request_hash=pedido,
        processing_version=PROCESSING_VERSION_IPMA,
    )
    session.add(job)
    session.commit()

    job.status = JobStatus.running
    session.commit()

    try:
        estacao = client.nearest_station(lat_sitio, lon_sitio, raio_maximo_km=raio)
        observacoes = client.observations()
        # quantas leituras de radiacao nocturna o cliente apagou DESTA estacao.
        # Lido depois de `observations()` de proposito: e essa chamada que faz
        # a limpeza e publica a contagem.
        descartes = client.descartes_por_estacao.get(estacao["station_id"], 0)
        linhas = linhas_da_estacao(observacoes, estacao["station_id"])

        def construir(quando, metrica, linha):
            return _observacao_de_estacao(
                site, aoi, quando, metrica, linha, estacao, lat_sitio, lon_sitio, pedido, raio,
                descartes)

        escritas = _gravar(session, site, linhas, SourceType.weather_observed,
                           PROCESSING_VERSION_IPMA, construir)
        _garantir_que_a_estacao_nao_mudou(session, site, linhas, escritas, estacao)
        if linhas:
            # o intervalo real, e nao o nominal: a janela deslizante nao
            # comeca a horas certas nem tem sempre 24 instantes, e um job que
            # declarasse dois dias inteiros por causa de tres horas lidas
            # dizia sobre a cobertura uma coisa que a serie desmente
            momentos = [_momento(linha["date"]) for linha in linhas]
            job.date_from = min(momentos).date()
            job.date_to = max(momentos).date()
        job.status = JobStatus.succeeded
        job.rows_written = escritas
        job.finished_at = _agora()
        session.commit()
    except Exception as erro:
        # mesma disciplina da reanalise: rollback primeiro, para nao ficarem
        # linhas meio-escritas, e so depois o job marcado como falhado
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
            f"Site '{site_code}' not found. A weather series is never requested for a site "
            "that is not in the database: the box and the point come from the stored geometry."
        )
    aois = session.scalars(
        select(Aoi).where(Aoi.site_id == site.id, Aoi.status == AoiStatus.approved)
        .order_by(Aoi.code)
    ).all()
    if not aois:
        raise ValueError(
            f"Site '{site_code}' has no approved AOI. The site point is the centroid of its "
            "AOI; over a polygon still to be confirmed, the distance recorded on every row "
            "would be invented."
        )
    if len(aois) > 1:
        codigos = ", ".join(aoi.code for aoi in aois)
        raise ValueError(
            f"Site '{site_code}' has more than one approved AOI ({codigos}) and each one gives "
            "a different centroid. Picking one by query order would be picking at random the "
            "position that ends up recorded as provenance."
        )
    return site, aois[0]


def _garantir_janela_valida(inicio: date, fim: date) -> None:
    """Uma janela invertida e recusada AQUI, nao la dentro do cliente.

    O `_meses_do_intervalo` do CDS tambem a recusa, mas so depois de o job
    existir: ficava um `failed` na base para uma execucao que nunca devia ter
    comecado. E a mesma regra da guarda do sitio -- o que se pode saber antes
    da rede recusa-se antes de haver rasto.
    """
    if inicio > fim:
        raise ValueError(
            f"The requested window is inverted: date_from ({inicio.isoformat()}) is after "
            f"date_to ({fim.isoformat()}). There is no series to ask for."
        )


def _garantir_dentro_da_janela(linhas, inicio: date, fim: date) -> None:
    """Nenhuma linha pode trazer um dia fora da janela pedida.

    Hoje o `_meses_do_intervalo` do cliente recorta dia a dia e isto nunca
    dispara. Mas a janela da consulta de desduplicacao sai dos dias
    DEVOLVIDOS, e nao dos dias pedidos: um dia a mais na resposta entrava na
    base debaixo de um job cujo `date_from`/`date_to` diz outra coisa, e o
    rasto do job passava a descrever mal o que ele escreveu. Nao e uma
    hipotese remota -- e o que acontece se alguem alargar o recorte do
    cliente para o mes inteiro, que e a unidade que o corpo do CDS aceita.
    """
    fora = sorted({_como_data(linha["date"]).isoformat() for linha in linhas
                   if not (inicio <= _como_data(linha["date"]) <= fim)})
    if fora:
        raise ValueError(
            f"A serie traz dias fora da janela pedida [{inicio.isoformat()}, {fim.isoformat()}]: "
            f"{', '.join(fora)}. Grava-los aqui punha na base linhas que o job nao diz ter "
            "pedido."
        )


def _caixa_e_ponto(aoi: Aoi) -> tuple[list[float], float, float]:
    """Envelope da AOI em [Norte, Oeste, Sul, Este] e o seu centroide.

    A caixa e o pedido de transporte; o ponto e o que decide a celula. Sao
    coisas diferentes de proposito: o CDS recusa uma caixa menor do que a
    celula da grelha, portanto o cliente alarga-a, mas o valor lido continua a
    ser o da celula que contem ESTE ponto.
    """
    geojson = wkb_to_geojson(aoi.geometry)
    if geojson is None:
        raise ValueError(
            f"AOI '{aoi.code}' has no geometry: there is no point at which to read the series.")
    geometria = shape(geojson)
    oeste, sul, este, norte = geometria.bounds
    # centroide PLANAR sobre coordenadas em graus, sem reprojectar para UTM
    # 29N como manda a regra deste projecto para areas e distancias. Aqui e
    # seguro e a excepcao esta justificada: a AOI tem ~2,5 km de lado, e a
    # anisotropia grau-a-grau (um grau de longitude vale cos(lat) do de
    # latitude) so deforma o centroide se o poligono for assimetrico, e nessa
    # escala o desvio fica na ordem do centimetro. Comparar com o que esta em
    # jogo: a celula lida tem 9 km e a grelha tem nos de 0,1 grau, portanto
    # seriam precisos ~5 km de erro no ponto para escolher outra celula.
    # A regra do UTM continua a valer para areas (`geo.area_m2`), onde o erro
    # nao e submetrico mas percentual.
    centro = geometria.centroid
    return [norte, oeste, sul, este], centro.y, centro.x


def _gravar(session, site, linhas, source_type, processing_version, construir) -> int:
    """Insere so o que falta. Devolve quantas linhas foram escritas.

    Serve as duas fontes: o que muda entre elas e o `construir`, que faz a
    Observation a partir de uma linha ja normalizada, e o par
    (source_type, processing_version), que e a parte da identidade que
    distingue as duas proveniencias da mesma grandeza no mesmo instante.
    """
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
        session, site.id, metricas, min(momentos), max(momentos),
        source_type, processing_version,
    )

    novas = []
    for (quando, metrica), linha in zip(chaves, linhas, strict=True):
        if (quando, metrica) in ja_existem:
            continue
        novas.append(construir(quando, metrica, linha))

    if not novas:
        return 0
    session.add_all(novas)
    session.flush()
    return len(novas)


def _garantir_chaves_distintas(chaves: list[tuple[datetime, str]]) -> None:
    """Duas linhas para o mesmo instante e a mesma metrica nao cabem na identidade.

    Serve as duas fontes, e o texto tambem tem de servir. O AgERA5 agrega por
    DIA e o IPMA por HORA, mas a regra e a mesma nos dois: um instante so pode
    ter um valor por metrica. Se vierem dois, uma das leituras teria de
    desaparecer -- e a que ficasse era escolhida pela ordem da resposta, ou
    seja ao acaso. Preferimos dize-lo: um job failed com o instante e a metrica
    nomeados e melhor do que uma serie silenciosamente amputada.

    A saida nao e "rever a janela ou as variaveis do pedido", que era o que
    esta mensagem dizia: o caminho do IPMA nao tem nem janela nem variaveis
    -- o feed e um URL fixo com as ultimas 24 horas -- e mandar rever coisas
    que nao existem manda o operador procurar onde nao ha nada. Quem duplicou
    foi a origem, e e la que se resolve.
    """
    vistas = set()
    for quando, metrica in chaves:
        if (quando, metrica) in vistas:
            raise ValueError(
                f"A serie traz mais do que um valor de '{metrica}' para "
                f"{quando.isoformat()}. Cada instante so pode ter um valor por metrica: "
                "gravar um e descartar o outro seria escolher ao acaso pela ordem da "
                "resposta. A origem devolveu o mesmo instante duas vezes -- e ai que a "
                "duplicacao tem de ser resolvida, nao aqui."
            )
        vistas.add((quando, metrica))


def _garantir_que_a_estacao_nao_mudou(session, site, linhas, escritas, estacao) -> None:
    """Descartar linhas de uma estacao DIFERENTE da que ja esta gravada e perda silenciosa.

    A estacao nao entra na identidade da observacao
    (site_id, plot_id, observed_at, metric, source_type, processing_version)
    nem no `request_hash` -- e nao entra por uma razao boa: so se sabe qual e
    depois da rede, e o job tem de existir antes dela. A consequencia e esta:

      1. as 14h05 corre-se o sitio, a mais proxima e a estacao A, escrevem-se
         as 24 horas;
      2. o IPMA publica uma estacao nova mais proxima, ou retira a A do
         `stations.json`;
      3. as 14h20 repete-se o MESMO pedido, byte a byte. A escolhida e agora a
         B, o feed ainda nao avancou, e as leituras da B batem todas na
         identidade das da A -> sao todas descartadas.

    Sem esta guarda o passo 3 responde `succeeded` com `rows_written: 0`, que e
    exactamente o que uma reexecucao legitima responde. A serie da B foi
    deitada fora e nao ha por onde descobri-lo depois: o `IngestionJob` nao tem
    `evidence`, a estacao esta fora do `request_hash`, e o `evidence` da estacao
    so existe em linhas que foram ESCRITAS -- um job de zero linhas nao regista
    que estacao teria usado.

    Nao e a identidade que muda aqui: muda-la e decisao de quem e dono dela, e
    mudaria tambem a identidade de um job. O que muda e o que se diz sobre o
    que aconteceu -- um `failed` com as duas estacoes nomeadas em vez de um
    `succeeded` enganador. A perda continua a existir; deixa e de ser silenciosa.

    Duas condicoes, e a segunda foi paga caro. So dispara quando houve mesmo
    descarte -- uma execucao que escreve tudo o que trouxe nao colidiu com nada
    e nao tem com quem discordar -- E quando a execucao nao escreveu NADA, que
    e literalmente o caso que esta guarda existe para apanhar: `rows_written: 0`
    indistinguivel de uma reexecucao legitima.

    Sem a segunda condicao, a guarda pega tambem nas 23 execucoes horarias
    seguintes a uma passagem de estacao legitima. Nessas, a estacao nova traz
    horas NOVAS e o feed continua a publicar: `_gravar` escreve-as, a guarda
    levanta a mesma (a janela de 24 h ainda contem linhas da estacao antiga), e
    o `except` do sincronizador faz `session.rollback()` -- as linhas novas sao
    deitadas fora. A serie fica congelada durante 24 h e so recupera na
    execucao h+24, com margem ZERO: uma execucao atrasada uma hora perde essa
    hora para sempre, porque a janela do feed e deslizante. Era trocar uma perda
    silenciosa por uma perda visivel maior.

    Nas execucoes que escrevem, a mudanca de estacao continua a nao ser
    silenciosa: cada linha nova leva o `station_id` da estacao nova no
    `evidence`, e a costura le-se ao ponto -- que e a regra global desta fase.
    O que se perde nessas execucoes sao as leituras da estacao nova para horas
    que a antiga ja cobre, e essas sao redundantes.
    """
    descartadas = len(linhas) - escritas
    if descartadas <= 0 or escritas > 0:
        return
    momentos = [_momento(linha["date"]) for linha in linhas]
    outras = _estacoes_ja_gravadas(session, site.id, min(momentos), max(momentos))
    # a propria estacao sai da lista: reexecutar a mesma janela com a mesma
    # estacao e o caminho normal, e e o que permite correr isto de hora a hora
    outras.pop(str(estacao["station_id"]), None)
    if not outras:
        return
    # as duas pontas nomeadas, cada uma na sua linha: com so uma delas, quem le
    # o job nao sabe se o que mudou foi a origem ou o sitio
    ja_gravadas = ", ".join(f"'{ident}' ({nome})" for ident, nome in sorted(outras.items()))
    escolhida = f"'{estacao['station_id']}' ({estacao['station_name']})"
    raise ValueError(
        f"{descartadas} das {len(linhas)} leituras desta execucao foram descartadas por ja "
        f"existirem, mas as que ja estao gravadas nesta janela vieram de {ja_gravadas} e esta "
        f"execucao escolheu {escolhida}. A estacao nao entra na identidade da observacao, "
        "portanto as leituras da estacao nova passariam por duplicados das da antiga e "
        "desapareciam sem deixar rasto. Escolher uma das duas exige subir a "
        "PROCESSING_VERSION_IPMA, para as duas series ficarem lado a lado em vez de colidirem."
    )


def _estacoes_ja_gravadas(session, site_id, inicio, fim) -> dict[str, str]:
    """id -> nome das estacoes que ja escreveram nesta janela, para este sitio.

    Le do `evidence` porque e o unico sitio onde a estacao existe: nao ha
    coluna para ela na tabela de observacoes, e nao devia haver -- a
    proveniencia de uma leitura meteorologica e mais do que um identificador, e
    e por viajar dentro do ponto que ela sobrevive a qualquer mudanca de
    esquema.

    O filtro repete a parte da identidade que nao depende da metrica nem do
    instante (sitio, sem parcela, `weather_observed`, esta versao). Alargar a
    janela para alem da que foi lida traria estacoes de dias que esta execucao
    nao tocou, e essas nao colidem com nada.
    """
    filas = session.execute(
        select(
            Observation.evidence["station_id"].astext,
            Observation.evidence["station_name"].astext,
        ).where(
            Observation.site_id == site_id,
            Observation.plot_id.is_(None),
            Observation.source_type == SourceType.weather_observed,
            Observation.processing_version == PROCESSING_VERSION_IPMA,
            Observation.observed_at >= inicio,
            Observation.observed_at <= fim,
        ).distinct()
    ).all()
    return {ident: nome for ident, nome in filas if ident is not None}


def _identidades_existentes(session, site_id, metricas, inicio, fim,
                            source_type, processing_version) -> set:
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
            Observation.source_type == source_type,
            Observation.processing_version == processing_version,
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
            # corrigida depois de a serie estar gravada.
            #
            # `site_point_source` diz de onde saiu este ponto, e nao e
            # decoracao: `site_lat`/`site_lon` leem-se como uma coordenada
            # levantada no sitio, e nao e -- e o centroide do poligono da AOI,
            # calculado. Sem esta chave, a distincao ficava por convencao
            # (a presenca do `aoi_code` ao lado), que e a mesma classe de
            # afirmacao implicita que esta camada existe para eliminar.
            "site_lat": lat_sitio,
            "site_lon": lon_sitio,
            "site_point_source": "aoi_centroid",
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


def _observacao_de_estacao(site, aoi, quando, metrica, linha, estacao, lat_sitio, lon_sitio,
                           pedido, raio_maximo_km, descartes_de_radiacao):
    """Uma leitura de estacao, com a estacao que a produziu e a distancia a que esta.

    source_type e `weather_observed` e nao `reanalysis`: por tras deste numero
    esta um instrumento real numa estacao real, e `SourceType.is_measurement`
    confirma-o. E a diferenca que importa num sistema MRV -- o que se pode
    defender e o que se mediu -- e e tambem o que faz esta linha caber ao lado
    da linha do AgERA5 para o mesmo instante e a mesma grandeza, em vez de
    colidir com ela na chave de identidade.

    quality_flag e `unchecked`, e nao `valid` como na reanalise. O IPMA publica
    as observacoes em tempo real, sem validacao; o filtro do -99 e a guarda de
    intervalo fisico nao sao controlo de qualidade -- so impedem o absurdo --
    e carimbar `valid` era afirmar uma verificacao que ninguem fez.

    plot_id fica a None: a serie e do sitio. Uma estacao a 5 km nao distingue
    duas parcelas separadas por 200 m, e atribui-la a uma delas seria inventar
    resolucao que a fonte nao tem.

    A distancia NAO vem por argumento: a `proveniencia_de_estacao` recebe as
    duas posicoes e calcula-a por dentro. Uma linha meteorologica sem
    proveniencia concreta e o defeito mais grave possivel neste projecto -- a
    base ja recusa um valor sem `evidence`, mas nao verifica se o `evidence`
    diz alguma coisa.
    """
    # nome proprio, e nao `proveniencia` como no caminho da reanalise: as duas
    # funcoes ficariam com a mesma linha `**proveniencia,` e uma ancora
    # ambigua e uma mutacao que se aplica ao sitio errado sem ninguem dar por isso
    proveniencia_da_estacao = proveniencia_de_estacao(
        estacao["station_id"], estacao["station_name"],
        estacao["lat"], estacao["lon"], lat_sitio, lon_sitio,
    )
    return Observation(
        site_id=site.id,
        plot_id=None,
        observed_at=quando,
        metric=metrica,
        unit=_unidade(metrica, linha),
        value_numeric=linha["value"],
        value_qualifier=ValueQualifier.exact,
        source_type=SourceType.weather_observed,
        quality_flag=QualityFlag.unchecked,
        source_collection=linha["dataset"],
        processing_version=PROCESSING_VERSION_IPMA,
        evidence={
            "site_code": site.code,
            "aoi_code": aoi.code,
            # as quatro coordenadas ficam gravadas para a distancia se poder
            # refazer sem ir buscar a geometria da AOI de hoje nem o
            # stations.json de hoje -- as duas podem mudar depois da linha
            "site_lat": lat_sitio,
            "site_lon": lon_sitio,
            "station_lat": estacao["lat"],
            "station_lon": estacao["lon"],
            # o campo do feed de onde o valor saiu: e o que permite refazer a
            # conversao de unidade sem adivinhar qual dos dois campos de vento
            # (m/s ou km/h) foi lido
            "field": linha["field"],
            "source_url": URL_OBSERVACOES,
            "request_hash": pedido,
            # a politica de escolha, ao lado do resultado dela: "a mais
            # proxima" nao se verifica depois sem o tecto que estava em vigor
            # quando a escolha foi feita, e o tecto e agora do chamador.
            "station_search_radius_km": raio_maximo_km,
            # e o tamanho da lista de onde ela saiu: 5,34 km entre 222 estacoes
            # e outra coisa do que 5,34 km entre duas. O numero vem do
            # `nearest_station`, que e quem ordenou a lista -- uma segunda
            # leitura do stations.json aqui podia estar a contar outra coisa.
            # `[...]` e nao `.get(...)`: um cliente que nao diga de quantas
            # estacoes escolheu nao pode afirmar "a mais proxima" por omissao,
            # e um `null` gravado em silencio nao se distingue de uma linha
            # antiga. Sem a chave, o job falha e diz porque.
            "stations_considered": estacao["stations_considered"],
            # quantas leituras de radiacao desta estacao foram descartadas por
            # o sol estar abaixo do horizonte nesta execucao. Zero e uma
            # afirmacao e nao a ausencia da chave: quem auditar a tabela daqui
            # a um ano nao tem o log, e sem isto nao ha nenhuma forma de saber
            # que houve leituras que a origem publicou e nos nao gravamos.
            "night_radiation_dropped": descartes_de_radiacao,
            # station_id, station_name, distance_km e measured_at_site=False
            **proveniencia_da_estacao,
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


def _hash_do_pedido(material: dict) -> str:
    """Identidade do pedido: mesmo material, mesmo hash.

    E o que liga cada observacao a execucao que a produziu, e o que permite
    reconhecer duas execucoes do mesmo pedido sem repetir o pedido. O material
    e construido por quem chama porque as duas fontes nao pedem a mesma coisa:
    a reanalise identifica-se pela janela, pelas variaveis e pela caixa; o
    IPMA nao tem parametros nenhuns (o URL e fixo e devolve sempre as ultimas
    24 horas), e identifica-se pelo sitio e pelo dia em que se la foi buscar.
    """
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def _como_data(valor) -> date:
    """Aceita `date` ou texto ISO. O job guarda Date; o cliente quer texto."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _momento(valor) -> datetime:
    """O instante de uma linha, sempre consciente do fuso.

    Duas formas, uma por fonte. O AgERA5 agrega por DIA e a linha traz texto:
    gravar meia-noite UTC e o unico instante honesto, porque inventar uma hora
    seria precisao que o dado nao tem. O IPMA mede a cada HORA e a linha traz
    ja um datetime com fuso, resolvido em `weather.ipma` -- e la que esta a
    prova de que os carimbos daquele feed sao UTC, e nao aqui.

    Um datetime sem fuso e recusado em vez de assumido: a coluna e timestamptz
    e o Postgres aplicaria o fuso da sessao, portanto a mesma linha dava
    instantes diferentes conforme a maquina que a ingerisse.
    """
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            raise ValueError(
                f"o instante {valor.isoformat()} vem sem fuso horario. Quem le a fonte e que "
                "sabe em que fuso ela carimba; assumi-lo aqui era decidir isso a distancia.")
        return valor.astimezone(timezone.utc)
    dia = date.fromisoformat(str(valor)[:10])
    return datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)


def _texto_do_erro(erro: Exception) -> str:
    detalhe = str(erro).strip()
    texto = f"{type(erro).__name__}: {detalhe}" if detalhe else type(erro).__name__
    return texto[:_LIMITE_ERRO]


def _agora() -> datetime:
    return datetime.now(timezone.utc)
