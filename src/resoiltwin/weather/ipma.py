"""Cliente das observacoes de estacao do IPMA (api.ipma.pt/open-data).

E a outra fonte da camada meteorologica, e a unica das duas que e mesmo uma
medicao: por tras de cada valor esta um instrumento numa estacao real, nao a
saida de um modelo. Em troca, tem tres propriedades que decidem tudo o que
esta escrito neste modulo:

1. **So existem as ultimas 24 horas.** Nao ha arquivo, nao ha parametro de
   data, nao ha paginacao para tras -- o observations.json e uma janela
   deslizante de 24 instantes horarios. Isto nao e uma limitacao a contornar:
   e o que a fonte e. O historico constroi-se a partir do dia em que a
   sincronizacao comecar a correr, e e a desduplicacao que permite corre-la de
   hora a hora sem duplicar as 23 horas que se repetem de cada vez.

2. **O valor em falta e -99, nao `null`.** Uma temperatura de -99 graus passa
   em qualquer validacao de tipo, uma humidade de -99 por cento tambem, e uma
   precipitacao de -99 mm entra num total acumulado como chuva negativa. A
   leitura de 29/08/2026 tinha 5985 celulas a -99 em sete campos diferentes
   (e 675 registos inteiros a `null`), portanto o filtro nao e sobre a
   temperatura: e sobre todos os campos.

3. **Nem tudo o que a origem publica foi medido.** O `-99` e o caso declarado;
   ha outro que nao se declara. A 29/08/2026, 23 estacoes reportavam radiacao
   solar positiva de madrugada, quatro delas com centenas de kJ/m2 -- e 680
   kJ/m2 dao 188,89 W/m2, um numero perfeitamente plausivel se ninguem olhar
   para a hora. Por isso a radiacao leva uma guarda propria, de altura solar,
   em `_apagar_radiacao_impossivel`: e a unica das cinco metricas cujo limite
   depende do instante e da posicao, e os dois estao no feed.

Uma consequencia de ser append-only, que nao e defeito mas convem estar
escrita: se a origem CORRIGIR um valor dentro das 24 horas (mesmo instante,
mesma metrica, numero diferente), a desduplicacao descarta a correccao em
silencio -- a identidade ja existe na base. A saida e subir a
`PROCESSING_VERSION_IPMA`, que faz a serie corrigida entrar ao lado da antiga
em vez de colidir com ela; nunca apagar a linha antiga.

Tudo o que esta aqui codificado sobre o formato foi medido contra o feed real
a 29/08/2026, nao lido da documentacao:

- os dois ficheiros respondem 200 sem credencial nenhuma;
- stations.json e uma lista de features GeoJSON, com `geometry.coordinates`
  em [lon, lat] e `idEstacao` como INTEIRO;
- observations.json e {instante: {id_estacao_em_TEXTO: registo | null}}, com
  24 instantes e 222 estacoes;
- os carimbos vem sem fuso e sao UTC (ver `_instante_utc`);
- `radiacao` vem em kJ/m2 acumulados na hora, nao em W/m2.
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from resoiltwin.weather.metrics import UNIDADE_POR_METRICA, WeatherMetric, proveniencia_de_estacao

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ipma.pt/open-data/observation/meteorology/stations"
URL_ESTACOES = f"{BASE_URL}/stations.json"
URL_OBSERVACOES = f"{BASE_URL}/observations.json"

COLECCAO_IPMA = "ipma-stations-observations"

# Versao do NOSSO processamento, nao do feed: o IPMA nao versiona nada. E o
# que distingue estas linhas de um reprocessamento futuro com outro mapa de
# campos ou outra conversao de unidades -- muda-la reescreve a serie ao lado
# da antiga em vez de colidir com ela, porque entra na chave de identidade.
VERSAO_IPMA = "1"

# O sentinela de "em falta". Numero, nao `null`: e todo o problema.
VALOR_EM_FALTA = -99.0

# tolerancia da comparacao com o sentinela. O JSON traz -99.0 exacto, mas
# comparar floats por igualdade e uma armadilha que so custa a descobrir no
# dia em que a origem passar a mandar -98.99999.
_TOLERANCIA_EM_FALTA = 1e-6

# Tecto de proximidade. Nao e uma lei da fisica, e uma politica: a rede do
# IPMA no continente tem ~120 estacoes e a mais proxima de Turcifal fica a
# 5,3 km. Uma estacao a 250 km nao e a meteorologia daquele campo, e atribuir
# essa serie ao sitio -- com proveniencia impecavel, distancia gravada e tudo
# -- era dar ar de dado local a uma coisa que nao o e. Quem tiver um caso
# legitimo passa o raio por argumento e fica escrito na chamada.
RAIO_MAXIMO_KM = 50.0

_TIMEOUT_S = 30.0

# Atraso minimo entre o instante mais recente do feed e o momento em que a
# origem o publicou. E a guarda de fuso horario, e o numero vem de duas
# medicoes contra a rede, nao de uma impressao:
#
#   Last-Modified: Sat, 29 Aug 2026 17:35:03 GMT
#   instante mais recente do ficheiro: 2026-08-29T17:00
#   -> atraso de PUBLICACAO = 35 min
#
# O atraso de LEITURA e outra coisa: quem leu o mesmo ficheiro as 18:02 mediu
# 1h02, que e o atraso de publicacao mais o tempo desde ela. A primeira versao
# desta guarda tomou uma leitura unica (1h06) por propriedade da fonte e pos o
# minimo em 30 minutos -- cinco minutos de margem contra os 35 reais. Se a
# origem acelerasse seis minutos, TODOS os jobs horarios passavam a falhar,
# a acusar a origem de ter mudado de fuso; e como o feed e uma janela
# deslizante de 24 h e ninguem olha para `ingestion_jobs.status`, isso nao e
# "uma hora perdida", e perda definitiva de tudo o que saisse da janela.
#
# 10 minutos, com o argumento a vista:
#
#   - contra uma aceleracao da origem: 25 minutos de folga (35 -> 10), cinco
#     vezes a de antes;
#   - contra o caso que a guarda existe para apanhar: com a origem a carimbar
#     em hora local de Lisboa, o mesmo ficheiro daria 17:35 - 18:00 = -25 min
#     de atraso aparente, 35 minutos ABAIXO do piso. Qualquer piso acima de
#     -25 min apanha o caso; este apanha-o com folga dos dois lados.
#
# ATENCAO ao que esta guarda NAO faz: so apanha um deslocamento para a FRENTE.
# Uma origem que passasse a carimbar em UTC-1 daria instantes ainda mais
# antigos e passaria aqui sem nada a assinalar. Nao ha, do lado do consumidor,
# maneira barata de apanhar isso -- fica dito para nao parecer mais forte do
# que e.
ATRASO_MINIMO_DA_PUBLICACAO = timedelta(minutes=10)

# Quanto o Last-Modified pode divergir do nosso relogio antes de deixar de
# servir como referencia. Sao dois relogios diferentes e nenhum deles e nosso,
# por isso o cabecalho e util mas nao e de confianca cega:
#
#   - a frente do nosso relogio: 5 minutos de desvio entre maquinas e normal;
#     mais do que isso e um cabecalho que nao descreve o passado, e um atraso
#     medido contra ele seria maior do que o real -- exactamente o erro que a
#     guarda existe para apanhar, produzido pela guarda;
#   - atras: o ficheiro e reescrito de hora a hora, portanto o cabecalho anda
#     sempre a menos de duas horas do agora. Seis horas e o triplo disso. Um
#     cabecalho preso no passado (uma cache mal configurada, um relogio da
#     origem atrasado dias) daria um atraso enorme e a guarda aceitava tudo
#     para sempre -- ou, se fosse pelo outro lado, recusava tudo para sempre
#     com a mensagem a acusar a origem de ter mudado de fuso.
#
# Nos dois casos a saida e a mesma e nao e falhar: e voltar ao relogio local,
# que e uma referencia pior mas nossa, e deixar dito no log qual foi usada.
TOLERANCIA_DE_ADIANTAMENTO = timedelta(minutes=5)
TECTO_DE_ANTIGUIDADE_DO_CABECALHO = timedelta(hours=6)

# Altura do sol abaixo da qual nao ha radiacao solar nenhuma para medir. -6
# graus e o crepusculo civil, e nao o horizonte geometrico: entre os dois ha
# luz difusa a valer alguns W/m2, e usar o zero apagaria leituras verdadeiras
# de amanhecer. A escolha e conservadora de proposito -- prefere-se deixar
# passar uma falsidade nos vinte minutos de crepusculo a apagar uma medicao.
ALTURA_SOLAR_DE_NOITE_GRAUS = -6.0

# `radiacao` e uma ACUMULACAO da hora e o carimbo e um instante: a hora que o
# carimbo fecha (ou abre -- a origem nao o diz) pode ter tido sol mesmo com o
# sol ja posto no instante do carimbo. Por isso a pergunta nao e "estava de
# noite no carimbo", e "esteve de noite em toda a hora a que este valor pode
# corresponder". Sem isto, o balde que atravessa o por do sol era apagado --
# 44 estacoes do feed real de 29/08/2026, todas com uma medicao verdadeira de
# crepusculo.
JANELA_DE_ACUMULACAO = timedelta(hours=1)

# Abaixo disto, de noite, a leitura diz o que um sensor a funcionar diz: nada.
# Uma leitura de 0,1 kJ/m2 (0,03 W/m2) as duas da manha e o zero do
# instrumento, nao uma falsidade, e apaga-la era mexer na serie sem ganho
# nenhum. Acima disto, de noite, o numero nao pode ter sido medido.
TECTO_RADIACAO_DE_NOITE_WM2 = 1.0

CAMPO_RADIACAO = "radiacao"

# epoca de referencia da astronomia moderna: 1 de Janeiro de 2000, meio-dia UTC
_J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def _sem_conversao(valor: float) -> float:
    return valor


def _kilojoule_por_hora_para_watt(valor: float) -> float:
    """kJ/m2 acumulados numa hora para W/m2: 3600 kJ/m2 numa hora sao 1000 W/m2.

    Confirmado contra o feed real: o percentil 90 das estacoes ao meio-dia
    solar de 29/08/2026 dava 3373 kJ/m2/h, ou seja 937 W/m2 -- o valor certo
    para um dia limpo de agosto em Portugal continental. Lido como se ja
    fosse W/m2, o mesmo numero seria tres vezes a constante solar.
    """
    return valor / 3.6


# campo do feed -> (metrica do vocabulario, conversao para a unidade canonica).
#
# `pressao` e `idDireccVento` ficam de fora: nao ha metrica para nenhuma das
# duas em weather.metrics, e acrescentar `air_pressure` aqui era alargar o
# vocabulario pela porta das traseiras, numa tarefa que nao e a dele.
#
# `intensidadeVentoKM` tambem fica de fora, mas por outra razao: e a MESMA
# grandeza que `intensidadeVento`, em km/h. Gravar as duas dava duas linhas
# de wind_speed para o mesmo instante, e a chave de identidade so admite uma.
_CAMPOS: dict[str, tuple[WeatherMetric, object]] = {
    "temperatura": (WeatherMetric.air_temperature, _sem_conversao),
    "humidade": (WeatherMetric.relative_humidity, _sem_conversao),
    "precAcumulada": (WeatherMetric.precipitation, _sem_conversao),
    "intensidadeVento": (WeatherMetric.wind_speed, _sem_conversao),
    "radiacao": (WeatherMetric.solar_radiation, _kilojoule_por_hora_para_watt),
}

# Intervalo fisicamente possivel de cada metrica, ja na unidade canonica.
#
# Nao e controlo de qualidade -- e a rede de seguranca para o sentinela que
# ainda nao vimos. O -99 esta filtrado pelo nome; se o IPMA passar a usar
# outro codigo (-990, -9999), sem esta guarda ele entrava na serie como um
# valor, com proveniencia de estacao real e tudo.
#
# Cada limite e cerca do DOBRO do extremo alguma vez registado no continente,
# e nao um numero redondo confortavel. A diferenca importa: um tecto de 250 mm
# numa acumulacao horaria era cinco vezes o recorde, ou seja decoracao -- a
# guarda so disparava para um sentinela na casa das centenas, e um na casa das
# dezenas entrava como chuva torrencial. Com o dobro do recorde, o que passa
# ainda e concebivel e o que e recusado nao e.
#
# Extremos usados (continente): -16 C e 47,4 C de temperatura, ~50 mm de chuva
# numa hora, ~40 m/s de vento medio, ~1400 W/m2 de irradiancia com reforco de
# nuvem. Nenhum limite apanha um sentinela que caia dentro da banda plausivel
# -- 99 mm de chuva passaria -- e isso e o que uma guarda de intervalo pode
# dar, nao um defeito por corrigir.
_LIMITES_FISICOS: dict[WeatherMetric, tuple[float, float]] = {
    WeatherMetric.air_temperature: (-30.0, 55.0),
    WeatherMetric.relative_humidity: (0.0, 100.0),   # limite fisico, nao estatistico
    WeatherMetric.precipitation: (0.0, 100.0),
    WeatherMetric.wind_speed: (0.0, 80.0),
    WeatherMetric.solar_radiation: (0.0, 1500.0),
}


class IPMAClient:
    """Fala HTTP com o open-data do IPMA. Nao sabe nada da base de dados.

    Sem credencial nenhuma, ao contrario do CDS e do CDSE: os dois ficheiros
    sao publicos e respondem 200 a um GET simples. Nao ha token para guardar
    nem para renovar, e por isso nao ha nada aqui que se pareca com o
    `token()` dos outros dois clientes.
    """

    def __init__(self, transport=None, timeout: float = _TIMEOUT_S, relogio=None):
        # nao ha `base_url`: os dois URL sao constantes de modulo e e de la que
        # `ingest` le o `source_url` que fica no evidence de cada linha. Um
        # parametro aqui construia um cliente apontado a um espelho cujas
        # linhas continuavam a declarar o URL canonico -- proveniencia a
        # divergir do que foi mesmo lido. Se um dia houver espelho, entra pelos
        # dois sitios ao mesmo tempo ou nao entra.
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)
        # relogio injectavel so para a guarda de fuso: um teste tem de poder
        # dizer "agora" sem depender do dia em que a suite corre
        self._relogio = relogio or (lambda: datetime.now(timezone.utc))
        self._estacoes: list[dict] | None = None
        # leituras de radiacao nocturna descartadas na ultima chamada a
        # `observations()`, por estacao. Publico de proposito: e o unico
        # caminho por onde o numero chega ao `evidence` das linhas.
        self.descartes_por_estacao: dict[str, int] = {}

    def close(self) -> None:
        """Fecha a ligacao. A ingestao vai correr de hora a hora durante meses:
        um cliente por execucao deixado ao GC sao sockets abandonados."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def stations(self) -> list[dict]:
        """A rede de estacoes, ja com as coordenadas na ordem certa.

        Devolve dicionarios normalizados (station_id, station_name, lat, lon)
        e nao as features cruas de proposito: a traducao de [lon, lat] para
        (lat, lon) e a conversao do idEstacao para texto acontecem UMA vez,
        aqui, e nao em cada sitio que consome estacoes. Cada copia dessa
        traducao era mais um sitio onde a ordem se podia trocar.

        A rede fica em cache na instancia, e nao entre execucoes: o
        `observations()` precisa das coordenadas de todas as estacoes e sem
        isto uma so sincronizacao ia buscar o mesmo ficheiro duas vezes. Um
        cliente vive uma execucao, portanto a cache nunca envelhece mais do
        que isso.
        """
        if self._estacoes is not None:
            return list(self._estacoes)
        dados = self._json(URL_ESTACOES)
        if not isinstance(dados, list):
            raise RuntimeError(
                f"IPMA: {URL_ESTACOES} devolveu {type(dados).__name__} e nao a lista de "
                "features esperada. Um 200 com HTML de proxy nao e uma rede sem estacoes.")
        estacoes = []
        for feature in dados:
            estacao = _estacao_da_feature(feature)
            if estacao is None:
                # uma feature partida nao pode derrubar a rede toda: sao 222 e
                # a que interessa e a mais proxima do sitio
                logger.warning("IPMA: feature de estacao ignorada por estar incompleta: %r", feature)
                continue
            estacoes.append(estacao)
        if not estacoes:
            raise RuntimeError(
                f"IPMA: {URL_ESTACOES} nao trouxe nenhuma estacao utilizavel "
                f"({len(dados)} features lidas).")
        self._estacoes = estacoes
        return list(estacoes)

    def nearest_station(self, lat: float, lon: float,
                        raio_maximo_km: float = RAIO_MAXIMO_KM) -> dict:
        """A estacao mais proxima de um ponto, com a distancia ja calculada.

        A distancia sai da `proveniencia_de_estacao` da Task 1 -- a mesma
        funcao que depois grava a distancia em cada linha. Uma segunda formula
        aqui, so para ordenar, podia divergir da que fica gravada: a estacao
        escolhida por um criterio e a distancia declarada por outro.

        O desempate e pelo id, para que duas estacoes a igual distancia nao
        troquem de lugar entre execucoes e a serie do sitio nao mude de
        instrumento sem nada a assinalar.

        Devolve tambem `stations_considered`: quantas estacoes entraram na
        ordenacao. "Esta e a mais proxima" e uma afirmacao sobre uma lista, e
        sem o tamanho dela nao se verifica nada -- 5,34 km entre 222 estacoes e
        outra coisa do que 5,34 km entre duas. Sai daqui, e nao de uma segunda
        leitura do stations.json em quem grava, porque so aqui se sabe que foi
        ESTA a lista usada.
        """
        candidatas = sorted(
            (dict(estacao, **{"distance_km": _distancia_km(estacao, lat, lon)})
             for estacao in self.stations()),
            key=lambda estacao: (estacao["distance_km"], estacao["station_id"]),
        )
        proxima = dict(candidatas[0], stations_considered=len(candidatas))
        if proxima["distance_km"] > raio_maximo_km:
            raise ValueError(
                f"a estacao do IPMA mais proxima de ({lat}, {lon}) e '{proxima['station_name']}' "
                f"a {proxima['distance_km']:.1f} km, acima do tecto de {raio_maximo_km:.0f} km. "
                "Uma serie dessa distancia nao e a meteorologia deste sitio; se for mesmo para "
                "usar, o raio passa-se por argumento e fica escrito na chamada.")
        return proxima

    def observations(self) -> dict:
        """As ultimas 24 horas de todas as estacoes, com duas guardas de feed.

        A forma e a da origem (instante -> id -> registo) e nao uma serie
        normalizada, porque a normalizacao depende da estacao escolhida, que
        este metodo nao sabe qual e; quem a faz e `linhas_da_estacao`.

        As duas guardas estao aqui, e nao la, porque so aqui existe o que elas
        precisam. A do fuso precisa do instante mais recente do FEED INTEIRO, e
        nao so das horas em que uma estacao aparece. A da radiacao nocturna
        precisa das COORDENADAS de cada estacao, que vivem no outro ficheiro do
        feed e que so o cliente vai buscar -- `linhas_da_estacao` recebe um id,
        nao uma posicao.
        """
        dados, resposta = self._ler(URL_OBSERVACOES)
        if not isinstance(dados, dict):
            raise RuntimeError(
                f"IPMA: {URL_OBSERVACOES} devolveu {type(dados).__name__} e nao o mapa de "
                "instantes esperado.")
        referencia, origem = self._momento_de_referencia(resposta)
        _garantir_feed_no_passado(dados, referencia, origem)
        self.descartes_por_estacao = _apagar_radiacao_impossivel(
            dados, {e["station_id"]: e for e in self.stations()})
        return dados

    def _momento_de_referencia(self, resposta) -> tuple[datetime, str]:
        """Contra que instante se mede o atraso do feed.

        O `Last-Modified` da resposta e quando a ORIGEM reescreveu o ficheiro,
        e e a referencia certa: com ele o atraso medido e o atraso de
        publicacao (35 min medidos), constante, e nao o atraso de leitura, que
        varia entre ~35 e ~95 minutos consoante a hora a que calhe correr. Com
        a referencia fixa a guarda decide sempre igual; com o relogio, o
        deslocamento para UTC+1 so era apanhado nas execucoes que calhassem na
        primeira parte do ciclo (o atraso aparente de -25 a +35 min cruza o
        piso a meio), ou seja em pouco mais de metade delas.

        O relogio injectado fica como recurso para quando o cabecalho nao vier
        -- um proxy que o retire, uma pagina servida de cache sem ele. Nesse
        caso a guarda continua a valer, so que probabilistica por execucao:
        a correr de hora a hora, dispara nas primeiras horas.

        O cabecalho e confrontado com o nosso relogio antes de ser aceite. Nao
        e desconfianca decorativa: sem isto, um Last-Modified no futuro era
        aceite em silencio e um preso muito no passado dava recusa PERMANENTE,
        com a mensagem a acusar a origem de ter mudado de fuso -- a mesma falha
        catastrofica que esta guarda ja teve uma vez, por uma via que nao
        controlamos.

        O confronto fecha tambem um buraco que a mudanca para o cabecalho
        abriu: se o relogio da PROPRIA origem adiantar, os carimbos do conteudo
        e o Last-Modified deslizam juntos, o atraso entre eles nao muda e a
        guarda ficaria cega -- coisa que a referencia antiga, o nosso relogio,
        apanhava. Com o confronto, um cabecalho adiantado deixa de servir, a
        referencia volta a ser o nosso relogio, e os instantes adiantados sao
        recusados na mesma.
        """
        agora = self._relogio()
        cabecalho = resposta.headers.get("Last-Modified")
        if not cabecalho:
            return agora, "relogio local (a resposta nao trouxe Last-Modified)"
        try:
            publicado = parsedate_to_datetime(cabecalho)
        except (TypeError, ValueError):
            logger.warning("IPMA: Last-Modified ilegivel (%r); a usar o relogio", cabecalho)
            return agora, "relogio local (Last-Modified ilegivel)"
        if publicado.tzinfo is None:
            # `-0000` e sintaxe legal e quer dizer "sem fuso conhecido", e o
            # parser devolve um naive. Sem este ramo, a subtraccao la a frente
            # rebentava -- ou, pior, se alguem a "arranjasse" assumindo o fuso
            # local da maquina, o erro era de UMA HORA na propria grandeza que
            # aqui se mede.
            publicado = publicado.replace(tzinfo=timezone.utc)
        publicado = publicado.astimezone(timezone.utc)
        desvio = agora - publicado
        if desvio < -TOLERANCIA_DE_ADIANTAMENTO:
            logger.warning(
                "IPMA: Last-Modified (%s) esta %s a frente do nosso relogio (%s); a usar o relogio",
                publicado.isoformat(), -desvio, agora.isoformat())
            return agora, "relogio local (Last-Modified no futuro)"
        if desvio > TECTO_DE_ANTIGUIDADE_DO_CABECALHO:
            logger.warning(
                "IPMA: Last-Modified (%s) esta %s atras do nosso relogio (%s), mais do que o "
                "tecto de %s; a usar o relogio",
                publicado.isoformat(), desvio, agora.isoformat(),
                TECTO_DE_ANTIGUIDADE_DO_CABECALHO)
            return agora, "relogio local (Last-Modified velho de mais)"
        return publicado, "Last-Modified da origem"

    def _json(self, url: str):
        return self._ler(url)[0]

    def _ler(self, url: str):
        """Corpo em JSON e a resposta inteira: os cabecalhos tambem sao dados.

        O `Last-Modified` do observations.json e o unico sitio onde a origem
        diz quando publicou, e sem ele a guarda de fuso mede contra o relogio
        de quem le, que e outra grandeza.
        """
        try:
            r = self._client.get(url)
        except httpx.HTTPError as erro:
            raise RuntimeError(f"IPMA: falhou o pedido a {url}: {erro}") from erro
        if r.status_code >= 400:
            raise RuntimeError(
                f"IPMA: {url} respondeu {r.status_code} - {r.text[:200] or '(corpo vazio)'}")
        try:
            return r.json(), r
        except ValueError as erro:
            # um 200 com HTML (portal, proxy, pagina de manutencao) e o caso
            # real: sem isto vinha um JSONDecodeError sem dizer de que URL
            raise RuntimeError(
                f"IPMA: {url} respondeu {r.status_code} com um corpo que nao e JSON: "
                f"{r.text[:200] or '(corpo vazio)'}") from erro


def linhas_da_estacao(observacoes: dict, station_id: str) -> list[dict]:
    """Serie normalizada de UMA estacao, a partir do feed cru das 24 horas.

    Uma linha por instante e por metrica, com o valor ja na unidade do
    vocabulario. O que nao produz linha nenhuma: os campos a -99, os registos
    a `null` e os campos sem metrica (pressao, direccao do vento, vento em
    km/h).

    A estacao ausente do feed nao da uma serie vazia -- da erro. Zero linhas e
    indistinguivel de "a estacao existe e nao mediu nada", e um job succeeded
    com zero linhas por causa de um id que nunca bateu certo e exactamente o
    tipo de sucesso vazio que nao se descobre a olhar para o estado.
    """
    identificador = str(station_id)
    linhas: list[dict] = []
    aparece = False
    for instante in sorted(observacoes):
        registos = observacoes[instante] or {}
        if identificador not in registos:
            continue
        aparece = True
        registo = registos[identificador]
        if registo is None:
            # hora sem leitura nenhuma: acontece no feed real (675 casos em
            # 5328 a 29/08/2026) e nao e erro, e ausencia
            continue
        quando = _instante_utc(instante)
        for campo, (metrica, converte) in _CAMPOS.items():
            bruto = registo.get(campo)
            if bruto is None:
                continue
            bruto = float(bruto)
            if _em_falta(bruto):
                continue
            valor = converte(bruto)
            _garantir_plausivel(metrica, valor, campo, bruto, identificador, instante)
            linhas.append({
                "date": quando,
                "metric": metrica,
                "value": valor,
                "unit": UNIDADE_POR_METRICA[metrica],
                "field": campo,
                "dataset": COLECCAO_IPMA,
            })
    if not aparece:
        raise ValueError(
            f"a estacao '{identificador}' nao aparece em nenhum dos {len(observacoes)} instantes "
            "do feed do IPMA. Isto nao e uma estacao sem leituras: e um id que nunca bateu certo "
            "-- provavelmente por o stations.json o dar como inteiro e o observations.json o usar "
            "como chave de texto.")
    if not linhas:
        # a estacao esta la e nao deu um unico valor utilizavel em 24 horas.
        # Devolver [] daria um job succeeded com zero linhas -- o mesmo sucesso
        # vazio da estacao ausente, por outra porta: nada no estado do job
        # distingue "a estacao esta avariada ha um dia" de "correu bem". Um
        # falso positivo aqui custa uma hora, e a hora seguinte volta a tentar,
        # porque a janela do feed e deslizante.
        raise ValueError(
            f"a estacao '{identificador}' aparece no feed mas nao deu um unico valor utilizavel "
            f"em {len(observacoes)} instantes: ou os registos vem todos a null, ou os campos vem "
            f"todos a {VALOR_EM_FALTA}. Escolher outra estacao ou esperar que a origem recupere.")
    linhas.sort(key=lambda linha: (linha["date"], linha["metric"]))
    return linhas


def _garantir_feed_no_passado(observacoes: dict, referencia: datetime, origem: str) -> None:
    """O instante mais recente do feed tem de estar bem antes de ter sido publicado.

    E a guarda de fuso horario. Os carimbos do IPMA vem sem fuso e sao UTC (ver
    `_instante_utc`), mas isso e uma leitura da origem, nao um contrato: se ela
    passar a carimbar em hora local de Lisboa, "15:00" passa a significar 14:00
    UTC e a serie fica uma hora adiantada, MISTURADA com as horas correctas que
    ja la estao. Nada rebentaria -- a desduplicacao veria apenas uma hora nova.

    O que se observa de fora e o atraso entre o instante mais recente e a
    publicacao: 35 minutos medidos. Em hora local de Lisboa o mesmo ficheiro
    daria -25 minutos, e e isso que esta comparacao apanha.

    `referencia` e `origem` vem de `_momento_de_referencia`: ou o Last-Modified
    da origem (fixo, e o que torna a decisao igual em todas as execucoes) ou o
    relogio local (variavel, recurso para quando o cabecalho falta). A origem
    entra na mensagem porque a mesma folga significa coisas diferentes conforme
    o que esta do outro lado da subtraccao.

    So apanha o deslocamento para a FRENTE. Uma origem que passasse a carimbar
    em UTC-1 daria instantes ainda mais antigos e passava aqui em silencio.
    """
    if not observacoes:
        raise ValueError("o feed do IPMA veio sem nenhum instante.")
    recente = _instante_utc(max(observacoes))
    atraso = referencia - recente
    if atraso < ATRASO_MINIMO_DA_PUBLICACAO:
        raise ValueError(
            f"o instante mais recente do feed ({recente.isoformat()}) esta a {atraso} de "
            f"{referencia.isoformat()} ({origem}), menos do que os "
            f"{ATRASO_MINIMO_DA_PUBLICACAO} de atraso minimo de publicacao. Medido contra a "
            "rede, o IPMA publica cada ficheiro 35 minutos depois do instante mais recente que "
            "ele traz; um atraso perto de zero (ou negativo) quer dizer que a origem deixou de "
            "carimbar em UTC. Gravar assim punha a serie uma hora adiantada, misturada com as "
            "horas correctas anteriores.")


def _apagar_radiacao_impossivel(observacoes: dict, estacoes_por_id: dict) -> dict:
    """Radiacao solar nocturna nao e uma medicao. Sai do feed antes de virar linha.

    No feed real de 29/08/2026, 23 estacoes reportavam radiacao positiva entre
    as 23h e as 4h, quatro delas com centenas de kJ/m2 -- 680 kJ/m2 dao
    188,89 W/m2, dentro do intervalo fisico, portanto a guarda de intervalo nao
    lhes toca. Gravadas, ficavam na serie como `weather_observed` com
    proveniencia completa, que e a pior forma de um numero falso existir.

    A radiacao e a unica das cinco metricas cujo limite depende do INSTANTE e
    da POSICAO -- e os dois estao aqui. Nao e preciso controlo de qualidade
    nenhum, e preciso altura solar: sem sol em toda a hora acumulada, o tecto
    e ~0. "Em toda a hora" e nao "no carimbo" -- ver `_sol_ausente_na_janela`;
    a versao ingenua apagava a medicao de crepusculo de 44 estacoes.

    O valor apagado passa a ser o sentinela de "em falta", que e exactamente o
    que ele e, e desaparece pelo mesmo caminho ja testado dos -99 -- a linha
    nao chega a existir. `quality_flag=unchecked` nao servia: diz "ninguem
    verificou", nao "isto e falso".

    O feed e alterado no sitio. E o dicionario que acabou de sair do
    `r.json()`, ninguem mais lhe pegou, e copiar 5000 registos para mudar
    algumas dezenas de campos era trabalho sem leitor.
    """
    apagados: dict[str, int] = {}
    exemplos: dict[str, tuple[str, float]] = {}
    sem_coordenadas: set[str] = set()
    for instante, registos in observacoes.items():
        if not registos:
            continue
        quando = _instante_utc(instante)
        for identificador, registo in registos.items():
            if not registo:
                continue
            bruto = registo.get(CAMPO_RADIACAO)
            if bruto is None:
                continue
            valor = _kilojoule_por_hora_para_watt(float(bruto))
            # sem `or _em_falta(bruto)`: era inalcancavel. O sentinela -99 da
            # -27,5 W/m2, que ja satisfaz o `<=` acima, portanto o segundo
            # termo nunca podia ser o decisivo -- codigo que corre sem fazer
            # nada, e que nenhum teste podia cobrir.
            if valor <= TECTO_RADIACAO_DE_NOITE_WM2:
                continue
            estacao = estacoes_por_id.get(str(identificador))
            if estacao is None:
                # esta no observations.json e nao no stations.json: sem
                # coordenadas nao ha altura solar, e inventar uma posicao para
                # poder aplicar a guarda era pior do que nao a aplicar
                sem_coordenadas.add(str(identificador))
                continue
            if not _sol_ausente_na_janela(quando, estacao["lat"], estacao["lon"]):
                continue
            registo[CAMPO_RADIACAO] = VALOR_EM_FALTA
            apagados[str(identificador)] = apagados.get(str(identificador), 0) + 1
            # guarda-se um exemplo por estacao: sem o instante e o valor, o
            # aviso diz que houve descartes e nao da por onde comecar a olhar
            exemplos.setdefault(str(identificador), (instante, valor))
    for identificador, quantos in sorted(apagados.items()):
        instante, valor = exemplos[identificador]
        logger.warning(
            "IPMA: %d leituras de radiacao com o sol abaixo de %.0f graus na estacao %s "
            "descartadas (p.ex. %s = %.1f W/m2) -- radiacao nocturna nao e uma medicao",
            quantos, ALTURA_SOLAR_DE_NOITE_GRAUS, identificador, instante, valor)
    if sem_coordenadas:
        logger.warning(
            "IPMA: %d estacoes do observations.json nao estao no stations.json (%s...): a guarda "
            "de radiacao nocturna nao lhes foi aplicada",
            len(sem_coordenadas), ", ".join(sorted(sem_coordenadas)[:5]))
    # a contagem sobe para quem chama porque tem de chegar ao `evidence` de
    # cada linha: quem auditar a tabela daqui a um ano nao tem outra forma de
    # saber que houve leituras descartadas nesta estacao -- o log ja se foi
    return apagados


def _sol_ausente_na_janela(quando: datetime, lat: float, lon: float) -> bool:
    """O sol esteve abaixo do crepusculo civil em toda a hora deste valor?

    Testa as duas pontas da janela (uma hora para tras e uma para a frente) e
    nao so o instante do carimbo, porque a origem nao diz se o carimbo abre ou
    fecha a hora acumulada -- as duas pontas cobrem as duas convencoes. Ao fim
    da noite a altura solar e monotona entre as pontas, portanto o maximo do
    intervalo esta sempre numa delas: testar as duas chega.
    """
    return all(
        altura_solar_graus(quando + desvio, lat, lon) <= ALTURA_SOLAR_DE_NOITE_GRAUS
        for desvio in (-JANELA_DE_ACUMULACAO, JANELA_DE_ACUMULACAO)
    )


def altura_solar_graus(quando: datetime, lat: float, lon: float) -> float:
    """Altura do sol acima do horizonte, em graus, para um instante e um ponto.

    Algoritmo de baixa precisao do NOAA (o mesmo do Astronomical Almanac),
    ~0,01 grau de erro no seculo XXI -- tres ordens de grandeza melhor do que o
    que esta pergunta precisa, e sem dependencia nenhuma.

    Nao ha correccao de refraccao: o disco solar ainda se ve com o centro
    geometrico a -0,833 graus. Nao interessa aqui, porque o limiar usado e o
    crepusculo civil (-6 graus), muito abaixo desse efeito.

    Aferido contra duas identidades que se conhecem sem calcular nada:

    - ao meio-dia solar do solsticio de Inverno em Lisboa da 27,84 graus, e o
      valor geometrico e 90 - 38,7223 - 23,44 = 27,8377;
    - no equinocio de Marco de 2026 (20/03, 14:46 UTC) a declinacao solar e
      zero, e no polo a altura do sol E a declinacao: da 0,002 graus.

    A segunda ancora existe porque a primeira, sozinha, nao afere quase nada.
    O solsticio de Inverno cai a duas semanas do perielio, onde a equacao do
    centro -- a maior correccao periodica deste algoritmo, ate 1,9 graus -- e
    quase nula: apaga-la mexe 0,002 graus no valor do solsticio e 0,74 graus no
    do equinocio.

    O que NAO serve como afericao: comparar estes cruzamentos do zero com as
    horas de nascer e por do sol publicadas. As publicadas sao do limbo
    superior e com refraccao (-0,833 graus), portanto estao sistematicamente
    4 a 5 minutos afastadas do cruzamento geometrico de cada lado. Uma versao
    anterior deste docstring apresentava a concordancia ao minuto como
    confirmacao; era coincidencia, e uma afericao que parece mais apertada do
    que e vale menos do que nenhuma.
    """
    if quando.tzinfo is None:
        raise ValueError("a altura solar precisa de um instante com fuso horario")
    quando = quando.astimezone(timezone.utc)
    dias = (quando - _J2000).total_seconds() / 86400.0
    longitude_media = math.radians((280.460 + 0.9856474 * dias) % 360)
    anomalia = math.radians((357.528 + 0.9856003 * dias) % 360)
    eclitica = (longitude_media + math.radians(1.915) * math.sin(anomalia)
                + math.radians(0.020) * math.sin(2 * anomalia))
    obliquidade = math.radians(23.439 - 0.0000004 * dias)
    declinacao = math.asin(math.sin(obliquidade) * math.sin(eclitica))
    ascensao_recta = math.atan2(math.cos(obliquidade) * math.sin(eclitica), math.cos(eclitica))
    # tempo sideral de Greenwich em horas, depois local em graus
    sideral_greenwich = (18.697374558 + 24.06570982441908 * dias) % 24
    sideral_local = math.radians((sideral_greenwich * 15 + lon) % 360)
    angulo_horario = sideral_local - ascensao_recta
    fi = math.radians(lat)
    seno = (math.sin(fi) * math.sin(declinacao)
            + math.cos(fi) * math.cos(declinacao) * math.cos(angulo_horario))
    return math.degrees(math.asin(max(-1.0, min(1.0, seno))))


def _em_falta(valor: float) -> bool:
    """-99 e o "em falta" do IPMA, em qualquer campo."""
    return abs(valor - VALOR_EM_FALTA) <= _TOLERANCIA_EM_FALTA


def _garantir_plausivel(metrica: WeatherMetric, valor: float, campo: str, bruto: float,
                        station_id: str, instante: str) -> None:
    minimo, maximo = _LIMITES_FISICOS[metrica]
    if minimo <= valor <= maximo:
        return
    raise ValueError(
        f"a estacao '{station_id}' deu {campo}={bruto} em {instante}, que da "
        f"{valor:.3f} {UNIDADE_POR_METRICA[metrica]} -- fora do intervalo fisicamente possivel "
        f"[{minimo}, {maximo}]. O sentinela conhecido do IPMA e {VALOR_EM_FALTA}; um valor "
        "absurdo diferente desse quer dizer que a origem mudou de convencao, e grava-lo era "
        "por na serie um numero que ninguem mediu.")


def _instante_utc(texto: str) -> datetime:
    """O carimbo do IPMA para um instante consciente do fuso.

    O feed escreve "2026-08-29T14:00", sem fuso, e e UTC. Medido, nao
    assumido: a 29/08/2026, com o ficheiro lido as 15:21 UTC, o instante mais
    recente era o das 14:00 (uma hora de atraso de publicacao, nao duas e
    meia), e o percentil 90 da radiacao das 125 estacoes caia no bloco das
    13:00, que e o meio-dia solar em Portugal continental. Lido como hora
    local de Lisboa (UTC+1 em agosto), o pico de radiacao ficava uma hora
    antes do meio-dia solar.

    Gravar isto como naive era pior do que errar o fuso: a coluna e
    timestamptz e o Postgres aplicaria o fuso da sessao, portanto o mesmo
    ficheiro dava instantes diferentes conforme a maquina que o ingerisse.
    """
    quando = datetime.fromisoformat(str(texto))
    if quando.tzinfo is not None:
        return quando.astimezone(timezone.utc)
    return quando.replace(tzinfo=timezone.utc)


def _estacao_da_feature(feature) -> dict | None:
    """Uma feature do stations.json normalizada, ou None se estiver incompleta."""
    if not isinstance(feature, dict):
        return None
    propriedades = feature.get("properties") or {}
    coordenadas = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coordenadas) < 2 or propriedades.get("idEstacao") is None:
        return None
    # GeoJSON e [lon, lat] -- longitude PRIMEIRO. Trocar os dois nao rebenta
    # (-9,179 e uma latitude valida e 39,04 uma longitude valida): poe Dois
    # Portos na Tanzania e devolve uma distancia com ar plausivel para o sitio
    # errado. E a mesma familia de defeito da distancia 28% acima do real que
    # este projecto ja publicou uma vez.
    lon, lat = float(coordenadas[0]), float(coordenadas[1])
    return {
        # inteiro no stations.json, chave de TEXTO no observations.json: sem
        # esta conversao a procura da serie nao encontra nada, e nao encontrar
        # nada e silencioso
        "station_id": str(propriedades["idEstacao"]),
        "station_name": str(propriedades.get("localEstacao") or ""),
        "lat": lat,
        "lon": lon,
    }


def _distancia_km(estacao: dict, lat: float, lon: float) -> float:
    return proveniencia_de_estacao(
        estacao["station_id"], estacao["station_name"], estacao["lat"], estacao["lon"], lat, lon,
    )["distance_km"]
