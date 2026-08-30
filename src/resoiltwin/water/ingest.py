"""Ingestao do balanco hidrico: le as entradas da BASE, corre o modelo, grava.

E a camada que falta entre `water.balance` (funcao pura, sem base e sem rede) e
a tabela canonica de observacoes. Nao ha aqui cliente nenhum nem rede nenhuma:
as duas series de entrada -- precipitacao e evapotranspiracao de referencia --
ja estao gravadas pela Fase C, e o que sai e uma terceira serie ao lado delas,
com `source_type = simulated`. Um balanco hidrico e exactamente aquilo que essa
coluna foi criada para receber: **nao e uma medicao, e nunca passa por uma**.

Segue a disciplina de `weather.ingest`, e reutiliza-lhe as pecas em vez de as
copiar: a recusa por sitio inexistente, por AOI por aprovar, por janela
invertida ou por capacidade impossivel acontece **antes de o job existir** e
sobe como excepcao -- nao e uma execucao falhada, e uma que nunca comecou;
tudo o que corra mal **depois** fica gravado no job (`failed` + `error`) em vez
de subir para quem chama.

Tres decisoes proprias desta camada, e nenhuma delas e obvia:

**A capacidade utilizavel entra na IDENTIDADE da linha, e nao so no
`evidence`.** E o parametro que domina o resultado e ninguem o mediu nestes
sitios. Se ficasse so no `evidence`, uma segunda corrida sobre a mesma janela
com outra capacidade batia na identidade da primeira, escrevia zero linhas e
respondia `succeeded` -- e a serie da segunda capacidade nunca tinha existido.
E por isso que a `processing_version` a leva: duas capacidades sao duas series
lado a lado, nao duas execucoes da mesma.

**Uma serie de entrada tem UMA proveniencia na janela inteira, escolhida por
uma precedencia fixa e declarada, nunca ao dia.** A precipitacao existe hoje na
base como `reanalysis` E como `weather_observed`. Escolher a melhor de cada dia
produzia uma serie de agua cujo numero do dia N depende de uma cadeia de dias
de proveniencias diferentes, sem que nenhuma linha o diga -- e o estado do
reservatorio tem memoria, portanto a mistura contamina para a frente e nao
fica confinada ao dia em que aconteceu. A precedencia esta em
`PRECEDENCIA_DAS_ENTRADAS`, a escolha vai no `evidence` de cada linha **ao lado
das proveniencias que estavam disponiveis e nao foram usadas**, e os dias que a
escolhida nao tem ficam por balancar (buraco, que o modelo trata cortando o
segmento) em vez de serem preenchidos pela outra.

A precedencia poe a reanalise a frente da estacao, e isso **nao e "o modelo
vale mais do que a medicao"**. E que o balanco e DIARIO e a grandeza de que
precisa e um total de 24 horas: a serie da reanalise ja e isso
(`aggregation_operator = total`, `aggregation_period_hours = 24`), e a da
estacao e horaria. Transforma-la num total diario e uma segunda decisao -- o
que fazer com um dia de cinco horas das 24 -- e um dia incompleto lido como dia
seco e exactamente a forma de defeito que este projecto persegue. Enquanto essa
decisao nao for tomada com dados, uma serie de entrada com mais do que um valor
por dia e **recusada** em vez de somada em silencio. Fica dito o que isto NAO
resolve: um balanco com chuva de estacao e ET0 de reanalise continuaria a ser
um balanco de duas proveniencias, porque o IPMA nao publica ET0 nenhuma -- a
ET0, que e a entrada que domina o resultado, so existe como reanalise.

**O que o modelo devolve como intervalo grava-se como intervalo.** O estado
inicial do reservatorio nao e conhecido, e o modelo corre cada segmento dos
dois extremos admissiveis; `determinado` marca o dia em que as duas
trajectorias colapsam. Dai em diante o valor ja nao depende do que ninguem
mediu e sai como `exact`; antes disso sai como `range`, em `value_min`/
`value_max`, com `value_numeric` a NULL. **Gravar `exact` com o minimo, com o
maximo ou com a media do intervalo era reinventar o estado inicial pela porta
de tras**, depois de todo o trabalho do modelo para o nao fazer. E se o
intervalo nunca colapsar -- o que acontece com capacidades grandes sobre uma
serie curta -- a serie e gravada na mesma, toda como intervalo: "esta algures
entre estes dois numeros" e informacao verdadeira, e recusar perdia o que se
sabe de facto.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta, timezone

from sqlalchemy import select

from resoiltwin.enums import JobStatus, QualityFlag, SourceType, ValueQualifier
from resoiltwin.models import IngestionJob, Observation
from resoiltwin.water.balance import (
    METODO_DO_BALANCO,
    VERSAO_DO_BALANCO,
    DiaDeEntrada,
    Solo,
    balanco_diario,
)

# As pecas da ingestao meteorologica sao IMPORTADAS e nao copiadas. Sao
# privadas ao modulo delas, e isso e deliberado -- nao sao superficie publica --
# mas duplicar a resolucao do sitio, a desduplicacao pela chave de seis colunas
# ou o corte do texto do erro criava duas copias que divergiriam no dia em que
# uma delas fosse corrigida. A alternativa era promove-las a publicas, o que
# obrigava a mexer em `weather/ingest.py` para nao ganhar nada.
from resoiltwin.weather.ingest import (
    _agora,
    _como_data,
    _garantir_janela_valida,
    _gravar,
    _hash_do_pedido,
    _momento,
    _sitio_e_aoi_aprovada,
    _texto_do_erro,
)
from resoiltwin.weather.metrics import WeatherMetric

JOB_TYPE = "water_balance_sync"

# A grandeza que sai daqui. Nome novo e nao um dos do vocabulario
# meteorologico: nenhuma das duas fontes de meteorologia mede agua no solo, e
# reusar um nome delas poria tres series incomparaveis debaixo da mesma
# etiqueta. A unidade e a mesma das entradas, porque o reservatorio conta-se em
# lamina de agua (mm) como a chuva e a ET0.
METRICA_DA_AGUA = "soil_available_water"
UNIDADE_DA_AGUA = "mm"

# As duas series que o modelo consome, e a unidade em que as duas tem de vir.
# Nao ha conversao nenhuma aqui de proposito: um valor em metros gravado como
# milimetros continua plausivel e ninguem volta a olhar para ele, portanto a
# discordancia derruba a corrida em vez de ser adivinhada.
METRICAS_DE_ENTRADA = (
    WeatherMetric.precipitation,
    WeatherMetric.reference_evapotranspiration,
)
UNIDADE_DAS_ENTRADAS = "mm"

# A ordem por que se escolhe a proveniencia de CADA serie de entrada, para a
# janela inteira. Ver o docstring do modulo para o argumento -- em duas linhas:
# o balanco e diario, a reanalise ja e diaria, a estacao e horaria, e agregar
# horas em dias e uma decisao que esta camada nao tem mandato para tomar em
# silencio. Uma proveniencia que nao esteja nesta lista nao alimenta o balanco.
PRECEDENCIA_DAS_ENTRADAS = (SourceType.reanalysis, SourceType.weather_observed)

# Vai no `evidence` ao lado da escolha. Sem o nome da regra, quem ler a linha
# daqui a um ano ve "reanalysis" e nao sabe se foi escolhida, se foi a unica, ou
# se alguem a escreveu a mao.
REGRA_DE_ESCOLHA = "single-provenance-per-input-series-by-fixed-precedence"

# A `processing_version` cabe em String(80) nas duas tabelas (migracao 0008).
_LIMITE_DA_VERSAO = 80


def processing_version_do_balanco(capacidade_utilizavel_mm: float) -> str:
    """A versao de processamento desta serie: o modelo E a capacidade usada.

    A capacidade entra aqui, e nao apenas no `evidence`, porque entra na chave
    de identidade da observacao. Duas capacidades diferentes produzem duas
    series diferentes sobre os mesmos dias: com a versao a ignora-las, a
    segunda corrida encontrava as identidades todas presentes, escrevia zero
    linhas e respondia `succeeded` -- a forma exacta do defeito que ja custou a
    este projecto a perda silenciosa de uma serie. Assim, ficam lado a lado.

    O formato `%g` e canonico: 100 e 100.0 sao a mesma capacidade e tem de dar
    a mesma versao, senao a mesma corrida escrita de duas maneiras produzia
    duas series.
    """
    return f"{VERSAO_DO_BALANCO}+awc{capacidade_utilizavel_mm:g}mm"


@dataclass(frozen=True)
class _EntradaEscolhida:
    """Uma serie de entrada depois de escolhida a proveniencia dela."""

    metrica: str
    source_type: str
    processing_version: str
    source_collection: str | None
    proveniencias_disponiveis: tuple[str, ...]
    valor_por_dia: dict[date, float]
    id_por_dia: dict[date, uuid.UUID]


def sync_water_balance(session, site_code, date_from, date_to, capacidade_mm) -> IngestionJob:
    """Corre o balanco hidrico de um sitio sobre uma janela e devolve o job.

    `capacidade_mm` e a capacidade de agua utilizavel do solo, em mm, e **nao
    tem valor por omissao**: nao ha analise de solo destes terrenos, e um valor
    por omissao seria um numero inventado a dominar o resultado de todas as
    corridas. Viaja na `processing_version` e no `evidence` de cada linha.

    Quatro recusas acontecem ANTES de o job existir e sobem como excepcao: o
    sitio nao existe, o sitio nao tem exactamente uma AOI aprovada, a janela
    esta invertida, e a capacidade nao descreve um reservatorio. Nenhuma delas
    precisa de ler uma linha de dados para se decidir, e um `failed` na base
    para uma execucao que nunca devia ter comecado e rasto a mais.

    A partir do `session.add(job)` nada sobe: quem chama tem de olhar para o
    `status` do job devolvido.
    """
    site, aoi = _sitio_e_aoi_aprovada(session, site_code)
    inicio, fim = _como_data(date_from), _como_data(date_to)
    _garantir_janela_valida(inicio, fim)
    # a validacao da capacidade e a do modelo, e nao uma segunda escrita aqui:
    # duas guardas sobre o mesmo numero divergem no dia em que uma mudar
    solo = Solo(capacidade_utilizavel_mm=float(capacidade_mm))
    versao = processing_version_do_balanco(solo.capacidade_utilizavel_mm)
    _garantir_que_a_versao_cabe(versao)

    pedido = _hash_do_pedido({
        "site_code": site.code,
        "aoi_code": aoi.code,
        "date_from": inicio.isoformat(),
        "date_to": fim.isoformat(),
        "method": METODO_DO_BALANCO,
        "processing_version": versao,
        # a capacidade ja esta dentro da versao, e vai tambem por extenso: o
        # hash e o que liga a linha a execucao que a produziu, e quem o refizer
        # a mao nao tem de saber decompor o texto da versao para o reproduzir.
        "available_water_capacity_mm": solo.capacidade_utilizavel_mm,
        "inputs": [str(metrica) for metrica in METRICAS_DE_ENTRADA],
        "input_precedence": [fonte.value for fonte in PRECEDENCIA_DAS_ENTRADAS],
    })

    job = IngestionJob(
        aoi_id=aoi.id, job_type=JOB_TYPE, status=JobStatus.pending,
        date_from=inicio, date_to=fim, request_hash=pedido,
        processing_version=versao,
    )
    session.add(job)
    session.commit()

    job.status = JobStatus.running
    session.commit()

    try:
        escolhas = {
            str(metrica): _entrada_escolhida(session, site.id, str(metrica), inicio, fim)
            for metrica in METRICAS_DE_ENTRADA
        }
        dias, sem_a_outra = _dias_com_todas_as_entradas(escolhas, inicio, fim)
        _garantir_que_as_entradas_nao_mudaram(session, site.id, versao, dias, escolhas)

        saida = balanco_diario(
            [
                DiaDeEntrada(
                    data=dia,
                    precipitacao_mm=escolhas[str(WeatherMetric.precipitation)].valor_por_dia[dia],
                    evapotranspiracao_referencia_mm=escolhas[
                        str(WeatherMetric.reference_evapotranspiration)
                    ].valor_por_dia[dia],
                )
                for dia in dias
            ],
            solo,
        )

        def construir(quando, metrica, linha):
            return _observacao_de_agua(
                site, aoi, quando, linha["dia_de_saida"], versao, escolhas, sem_a_outra, pedido,
            )

        linhas = [{"date": dia.data, "metric": METRICA_DA_AGUA, "dia_de_saida": dia}
                  for dia in saida]
        escritas = _gravar(session, site, linhas, SourceType.simulated, versao, construir)

        # a janela que foi mesmo balancada, e nao a que foi pedida: o job e a
        # unica linha que alguem le para saber o que uma corrida trouxe, e
        # declarar dez dias por causa de dois e afirmar uma cobertura que a
        # serie desmente. Mesma regra do `_janela_coberta_por_todas` da
        # reanalise, com a diferenca de que aqui a interseccao ja foi feita.
        job.date_from, job.date_to = dias[0], dias[-1]
        job.status = JobStatus.succeeded
        job.rows_written = escritas
        job.finished_at = _agora()
        session.commit()
    except Exception as erro:
        # mesma disciplina das duas ingestoes de meteorologia: o rollback vem
        # primeiro, para nao ficarem linhas meio-escritas, e so depois o job
        # (confirmado antes de qualquer leitura, portanto sobrevivente do
        # rollback) e marcado como falhado com o motivo por extenso.
        session.rollback()
        job.status = JobStatus.failed
        job.rows_written = 0
        job.error = _texto_do_erro(erro)
        job.finished_at = _agora()
        session.commit()
    return job


def _garantir_que_a_versao_cabe(versao: str) -> None:
    """A versao leva a capacidade dentro, portanto pode crescer com o argumento.

    As duas colunas que a guardam sao String(80). Uma capacidade absurdamente
    longa produzia uma versao que o job (gravado primeiro) aceitava e a tabela
    de observacoes recusava a meio da escrita -- e falhar depois do job, por um
    limite que se conhece antes dele, e deixar rasto de uma execucao que nunca
    devia ter comecado.
    """
    if len(versao) > _LIMITE_DA_VERSAO:
        raise ValueError(
            f"The processing version built from this capacity is {len(versao)} characters long "
            f"and the column holds {_LIMITE_DA_VERSAO}: '{versao}'. The capacity travels inside "
            "the version because it is part of the row identity, so an unreasonable capacity is "
            "refused before the run starts."
        )


def _entrada_escolhida(session, site_id, metrica: str, inicio: date, fim: date) -> _EntradaEscolhida:
    """A serie de uma metrica na janela, com UMA proveniencia para tudo.

    Cinco recusas, e cada uma existe porque a alternativa e um numero errado com
    ar de certo: nenhuma linha; nenhuma proveniencia na precedencia; mais do que
    uma versao de processamento na proveniencia escolhida; unidade que nao e a
    esperada; mais do que um valor para o mesmo dia.
    """
    filas = session.execute(
        select(
            Observation.id,
            Observation.observed_at,
            Observation.value_numeric,
            Observation.unit,
            Observation.source_type,
            Observation.processing_version,
            Observation.source_collection,
        ).where(
            Observation.site_id == site_id,
            Observation.plot_id.is_(None),
            Observation.metric == metrica,
            Observation.observed_at >= _momento(inicio),
            Observation.observed_at < _momento(fim + timedelta(days=1)),
        )
    ).all()

    disponiveis = tuple(sorted({str(fila.source_type) for fila in filas}))
    if not disponiveis:
        raise ValueError(
            f"Nao ha uma unica linha de '{metrica}' para este sitio em "
            f"[{inicio.isoformat()}, {fim.isoformat()}]. O balanco precisa das duas series de "
            "entrada; tratar a que falta como zero era afirmar que nao choveu nada, ou que nao "
            "houve procura de agua nenhuma, em dias que ninguem observou. Uma corrida sem "
            "entradas nao e uma corrida com zero linhas escritas -- e uma corrida que nao pode "
            "acontecer, e diz-se."
        )

    escolhida = next(
        (fonte.value for fonte in PRECEDENCIA_DAS_ENTRADAS if fonte.value in disponiveis), None,
    )
    if escolhida is None:
        raise ValueError(
            f"A serie de '{metrica}' existe na janela com as proveniencias "
            f"{list(disponiveis)}, e nenhuma delas esta na precedencia declarada "
            f"({[fonte.value for fonte in PRECEDENCIA_DAS_ENTRADAS]}). Alimentar o balanco com "
            "uma proveniencia que ninguem declarou aceitavel era decidir aqui, as escuras, o "
            "que a serie de saida significa."
        )

    filas = [fila for fila in filas if str(fila.source_type) == escolhida]

    versoes = sorted({fila.processing_version for fila in filas})
    if len(versoes) > 1:
        raise ValueError(
            f"A serie de '{metrica}' com proveniencia '{escolhida}' esta gravada em mais do que "
            f"uma versao de processamento nesta janela: {', '.join(versoes)}. Sao dois valores "
            "possiveis para o mesmo dia, e escolher um pela ordem da consulta era escolher ao "
            "acaso e nao deixar rasto da escolha. Quem quiser uma delas tem de a pedir."
        )

    unidades = sorted({fila.unit for fila in filas})
    if unidades != [UNIDADE_DAS_ENTRADAS]:
        raise ValueError(
            f"A serie de '{metrica}' vem em {', '.join(repr(unidade) for unidade in unidades)} e "
            f"o balanco conta em '{UNIDADE_DAS_ENTRADAS}'. Converter aqui era adivinhar; gravar "
            "assim era pior, porque o numero continua plausivel e ninguem volta a olhar para ele."
        )

    valor_por_dia: dict[date, float] = {}
    id_por_dia: dict[date, uuid.UUID] = {}
    for fila in filas:
        dia = fila.observed_at.astimezone(timezone.utc).date()
        if fila.value_numeric is None:
            # uma entrada que ja e ela propria um intervalo (ou um valor
            # textual) nao alimenta este modelo, que soma escalares. Nao se
            # escolhe um extremo dela em silencio.
            raise ValueError(
                f"A linha de '{metrica}' de {dia.isoformat()} nao tem valor escalar "
                "(value_numeric a NULL). O modelo soma milimetros; escolher um extremo de um "
                "intervalo de entrada era inventar o numero que falta."
            )
        if dia in valor_por_dia:
            raise ValueError(
                f"A serie de '{metrica}' com proveniencia '{escolhida}' traz mais do que um valor "
                f"para {dia.isoformat()}. O balanco e diario e esta serie nao e: somar as "
                "leituras num total diario e uma segunda decisao -- o que fazer com um dia de "
                "cinco horas das 24 -- e um dia incompleto lido como dia seco e exactamente o "
                "defeito que este projecto persegue. Enquanto essa decisao nao for tomada com "
                "dados, isto recusa-se em vez de somar em silencio."
            )
        valor_por_dia[dia] = float(fila.value_numeric)
        id_por_dia[dia] = fila.id

    coleccoes = sorted({fila.source_collection for fila in filas if fila.source_collection})
    return _EntradaEscolhida(
        metrica=metrica,
        source_type=escolhida,
        processing_version=versoes[0],
        source_collection=", ".join(coleccoes) if coleccoes else None,
        proveniencias_disponiveis=disponiveis,
        valor_por_dia=valor_por_dia,
        id_por_dia=id_por_dia,
    )


def _dias_com_todas_as_entradas(escolhas, inicio: date, fim: date):
    """Os dias em que TODAS as entradas existem, e quantos ficaram de fora.

    Um dia com chuva mas sem ET0 (ou ao contrario) nao e balancado. Nao se
    completa a entrada em falta com zero -- era afirmar que nao houve procura de
    agua nenhuma num dia que ninguem observou -- e o dia fica como buraco na
    serie, que o modelo trata cortando o segmento e dizendo que o cortou.

    A contagem do que ficou de fora vai para o `evidence`. Sem ela, a serie
    encurta e nada na base diz que encurtou: e a mesma razao das contagens de
    descarte da camada de meteorologia. Zero e uma afirmacao ("nao faltou um
    unico dia") e nao a ausencia da chave.
    """
    conjuntos = {nome: set(escolha.valor_por_dia) for nome, escolha in escolhas.items()}
    comuns = set.intersection(*conjuntos.values())
    dias = sorted(comuns)
    if not dias:
        detalhe = "; ".join(
            f"{nome}: {len(conjunto)} dia(s)" for nome, conjunto in sorted(conjuntos.items())
        )
        raise ValueError(
            f"As series de entrada deste sitio nao partilham um unico dia em "
            f"[{inicio.isoformat()}, {fim.isoformat()}] ({detalhe}). Nao ha um so dia que possa "
            "ser balancado, e escrever zero linhas a dizer sucesso era esconder isso."
        )
    sem_a_outra = {nome: len(conjunto - comuns) for nome, conjunto in conjuntos.items()}
    return dias, sem_a_outra


def _garantir_que_as_entradas_nao_mudaram(session, site_id, versao, dias, escolhas) -> None:
    """Reescrever a janela com OUTRA proveniencia de entrada e perda silenciosa.

    A proveniencia das entradas nao cabe na `processing_version` (as duas
    series juntas nao cabem em 80 caracteres) e por isso nao entra na
    identidade da linha. A consequencia e a mesma que a guarda da estacao do
    IPMA descreve: mudada a precedencia, a re-execucao encontra as identidades
    todas presentes, escreve zero linhas, responde `succeeded` -- e a serie
    nova, alimentada por outra coisa, nunca chega a existir.

    Um `failed` com as duas proveniencias nomeadas nao recupera a serie nova,
    mas tira-lhe o silencio. E falhar nao custa nada aqui: as entradas estao na
    base, nao numa janela deslizante que se esvazia -- a corrida repete-se
    quando alguem decidir subir a versao, e nao se perde uma linha.
    """
    gravadas = session.execute(
        select(Observation.evidence["inputs"]).where(
            Observation.site_id == site_id,
            Observation.plot_id.is_(None),
            Observation.metric == METRICA_DA_AGUA,
            Observation.source_type == SourceType.simulated,
            Observation.processing_version == versao,
            Observation.observed_at >= _momento(dias[0]),
            Observation.observed_at <= _momento(dias[-1]),
        ).distinct()
    ).scalars().all()

    for anteriores in gravadas:
        for nome, escolha in escolhas.items():
            anterior = (anteriores or {}).get(nome, {})
            antes = (anterior.get("source_type"), anterior.get("processing_version"))
            agora = (escolha.source_type, escolha.processing_version)
            if antes != agora:
                raise ValueError(
                    f"As linhas de balanco ja gravadas nesta janela foram produzidas com "
                    f"'{nome}' vinda de {antes[0]} / {antes[1]}, e esta execucao escolheu "
                    f"{agora[0]} / {agora[1]}. A proveniencia das entradas nao entra na "
                    "identidade da linha, portanto a serie nova passaria por duplicado da "
                    "antiga e desaparecia sem deixar rasto. Po-las lado a lado exige subir a "
                    "versao do balanco."
                )


def _observacao_de_agua(site, aoi, quando, dia, versao, escolhas, sem_a_outra, pedido):
    """Uma linha de agua disponivel, com tudo o que a torna auditavel.

    `source_type` e `simulated` e nao `derived` nem `observed_*`: nao ha
    instrumento nenhum por tras deste numero, e `SourceType.is_measurement`
    confirma-o. Nao e `derived` porque `derived` e um produto calculado sobre
    as camadas de observacao -- uma conta sobre numeros medidos, como o VPD --
    e isto e a saida de um MODELO com estado, com um parametro que ninguem
    mediu a dominar o resultado. As duas coisas nao se defendem da mesma
    maneira num sistema MRV, e o dia em que se confundirem ninguem as separa.

    `quality_flag` e `unchecked` nas duas formas de linha, e nao `range_value`
    nos dias indeterminados. `value_qualifier` ja diz que o valor e um
    intervalo; a bandeira de qualidade e um eixo ortogonal -- e sobre o valor
    ter sido verificado, e nenhum destes foi.

    `plot_id` fica a None: a serie e do sitio. As entradas vem de uma celula de
    ~9 km e a capacidade e um so numero para o sitio inteiro; atribuir isto a
    uma parcela era inventar resolucao que nada aqui tem.
    """
    determinado = dia.determinado
    return Observation(
        site_id=site.id,
        plot_id=None,
        observed_at=quando,
        metric=METRICA_DA_AGUA,
        unit=UNIDADE_DA_AGUA,
        # o dia determinado sai como escalar; o indeterminado sai como
        # intervalo, e NUNCA como escalar. Ver o docstring do modulo.
        value_numeric=dia.agua_disponivel_min_mm if determinado else None,
        value_min=None if determinado else dia.agua_disponivel_min_mm,
        value_max=None if determinado else dia.agua_disponivel_max_mm,
        value_qualifier=ValueQualifier.exact if determinado else ValueQualifier.range,
        source_type=SourceType.simulated,
        quality_flag=QualityFlag.unchecked,
        source_collection=None,
        processing_version=versao,
        method=METODO_DO_BALANCO,
        # a cadeia fecha-se ate as linhas exactas que produziram este dia, e
        # nao apenas ate a proveniencia delas em texto: com os ids, quem
        # auditar refaz a conta sem depender de o `evidence` estar certo.
        derived_from=[escolha.id_por_dia[dia.data] for escolha in escolhas.values()],
        evidence={
            "site_code": site.code,
            "aoi_code": aoi.code,
            "method": METODO_DO_BALANCO,
            "model_version": VERSAO_DO_BALANCO,
            "request_hash": pedido,
            # ⚠️ o parametro que DOMINA o resultado, e que ninguem mediu nestes
            # sitios. Sem ele na linha, a linha nao e auditavel: o numero nao se
            # refaz nem se contesta. A segunda chave impede-o de passar por
            # medido -- um numero sozinho num campo de proveniencia le-se como
            # se tivesse sido observado.
            "available_water_capacity_mm": dia.capacidade_utilizavel_mm,
            "capacity_is_measured": False,
            "input_selection_rule": REGRA_DE_ESCOLHA,
            "inputs": {
                nome: _evidencia_da_entrada(escolha, dia.data, sem_a_outra[nome])
                for nome, escolha in escolhas.items()
            },
            # o que o modelo diz sobre o troco a que este dia pertence. Sem
            # isto, dois pontos separados por um buraco de dez dias parecem
            # contiguos, e o `determined` explica porque e que a linha e um
            # intervalo em vez de um numero.
            "segment": dia.segmento,
            "days_since_restart": dia.dias_desde_o_reinicio,
            "determined": determinado,
            # o que transbordou e saiu da conta. Sem ele, um dia em que o
            # reservatorio esta cheio e um dia em que se perderam 200 mm sao a
            # mesma linha, e nada explica porque e que um dia de chuva forte
            # nao subiu a agua.
            "runoff_min_mm": dia.escoamento_min_mm,
            "runoff_max_mm": dia.escoamento_max_mm,
            # a serie de saida herda o "isto nao foi medido aqui" das entradas,
            # e acrescenta-lhe o seu proprio: nada disto e uma leitura.
            "measured_at_site": False,
        },
    )


def _evidencia_da_entrada(escolha: _EntradaEscolhida, dia: date, dias_sem_a_outra: int) -> dict:
    """A proveniencia de uma serie de entrada, e o valor que este dia usou.

    As proveniencias DISPONIVEIS vao ao lado da escolhida de proposito. Com so
    a escolhida, quem ler a linha ve "reanalysis" e nao sabe se houve escolha
    nenhuma -- e a precipitacao deste projecto existe hoje nas duas
    proveniencias, ainda que ate 30/08/2026 em dias DISJUNTOS (a reanalise de
    01/07 a 22/08, as estacoes so a 28-29/08). O par (escolhida, disponiveis) e o que
    torna a escolha visivel em vez de implicita.
    """
    return {
        "source_type": escolha.source_type,
        "processing_version": escolha.processing_version,
        "source_collection": escolha.source_collection,
        "provenances_available": list(escolha.proveniencias_disponiveis),
        # o valor que ESTE dia usou, para a conta se poder refazer a partir da
        # propria linha
        "value_mm": escolha.valor_por_dia[dia],
        # quantos dias desta serie ficaram por balancar por a outra entrada
        # nao existir nesse dia
        "days_without_the_other_input": dias_sem_a_outra,
    }
