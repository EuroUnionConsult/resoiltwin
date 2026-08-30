"""Vocabulario de metricas meteorologicas e a disciplina do "nao e local".

Nenhuma das duas fontes desta camada mede na parcela: a estacao IPMA mais
proxima fica a alguns km, e a celula de reanalise AgERA5 cobre ~9 km. As duas
funcoes abaixo produzem o dicionario de proveniencia que vai para o `evidence`
de cada observacao, para que essa distancia nunca se perca.
"""

import math
from enum import StrEnum

# raio medio da terra, usado no haversine e na conversao grosseira de graus para km
EARTH_RADIUS_KM = 6371.0088


class WeatherMetric(StrEnum):
    """Metricas meteorologicas partilhadas pelas duas fontes (IPMA e AgERA5).

    air_temperature e relative_humidity reusam exactamente os nomes que ja
    existem na base como observed_screening (campanha de campo). Quem separa
    as tres proveniencias da mesma grandeza e o source_type, nao o nome da
    metrica -- por isso nao ha aqui `ipma_air_temperature` nem `era5_temperature`.
    """

    precipitation = "precipitation"
    air_temperature = "air_temperature"
    relative_humidity = "relative_humidity"
    solar_radiation = "solar_radiation"
    wind_speed = "wind_speed"
    reference_evapotranspiration = "reference_evapotranspiration"


UNIDADE_POR_METRICA: dict[WeatherMetric, str] = {
    WeatherMetric.precipitation: "mm",
    WeatherMetric.air_temperature: "degC",
    WeatherMetric.relative_humidity: "percent",
    WeatherMetric.solar_radiation: "W/m2",
    WeatherMetric.wind_speed: "m/s",
    WeatherMetric.reference_evapotranspiration: "mm",
}


class AggregationOperator(StrEnum):
    """Como e que o numero de uma linha resume o periodo que ele cobre.

    Nao e o campo `statistic` do pedido ao CDS, e a distincao e o achado
    inteiro. O AgERA5 aceita `statistic` para umas variaveis e RECUSA-O
    noutras (a precipitacao e a evapotranspiracao ja sao diarias por
    definicao) -- mas essas continuam a ser agregados de 24 horas. Copiar o
    campo do pedido para o `evidence` gravava `null` em tres das quatro
    variaveis da reanalise, e um leitor que lesse esse `null` concluia o
    CONTRARIO do que e verdade: que a chuva de um dia inteiro e uma leitura
    instantanea. O que a linha tem de dizer e o que o numero E, e isso e
    conhecimento nosso sobre a fonte, nao um eco do corpo do pedido.

    `undeclared` nao e uma falta de preenchimento -- e uma afirmacao: "a
    origem nao declara o que este numero resume". O IPMA documenta a
    acumulacao da chuva (`precAcumulada`) e a da radiacao (kJ/m2 na hora), e
    nao documenta nada sobre a temperatura, a humidade ou o vento: dizer
    `mean` nesses tres era inventar. A diferenca entre "nao ha agregacao a
    declarar" e "ninguem preencheu" e o que a `proveniencia_de_agregacao`
    resolve -- ver la.
    """

    mean = "mean"
    total = "total"
    undeclared = "undeclared"


def proveniencia_de_agregacao(operador, periodo_horas: float | None) -> dict:
    """As duas chaves que dizem o que o numero da linha resume.

    O achado que isto fecha: o mesmo sitio tem `air_temperature` em `degC`
    tres vezes (campo, estacao, reanalise) e `solar_radiation` em `W/m2` duas
    vezes -- a reanalise entre 185 e 350 (media de 24 h) e a estacao entre 0 e
    872 (media de 1 h). **Mesma metrica, mesma unidade, uma ordem de grandeza
    de diferenca ao meio-dia**, e nao havia nada na linha por onde aprender a
    diferenca dela. E a mesma classe do `cell_size_km` unico que ja foi
    corrigido: um valor descrito por um rotulo que e verdadeiro de outra coisa.

    **As duas chaves existem sempre e nas duas fontes.** Marcar so um dos
    lados era pior do que nao marcar nenhum: quem lesse o grafico da Fase F
    ficava a comparar uma serie etiquetada com outra por etiquetar e nao tinha
    como saber se a segunda era a mesma coisa.

    **O `null` do periodo nunca e ambiguo, e e essa a razao de haver duas
    chaves e nao uma.** Uma chave unica a `null` diz ao mesmo tempo "esta
    variavel nao tem agregacao" e "ninguem preencheu isto", e as duas leituras
    sao incompativeis: a primeira convida a comparar, a segunda proibe-o. Aqui
    o `null` do periodo so e legal com o operador `undeclared` a nomea-lo, e
    so com ele -- as duas direccoes sao verificadas. "Ninguem preencheu" deixa
    de ser representavel: a chave nao tem omissao e quem constroi a linha tem
    de a pedir a esta funcao, que recusa qualquer combinacao que nao seja uma
    afirmacao.
    """
    try:
        operador = AggregationOperator(operador)
    except ValueError:
        raise ValueError(
            f"operador de agregacao desconhecido: {operador!r}. Os que existem sao "
            f"{[o.value for o in AggregationOperator]} -- inventar um terceiro rotulo aqui "
            "poe na base uma palavra que ninguem sabe ler."
        ) from None

    if operador is AggregationOperator.undeclared:
        if periodo_horas is not None:
            raise ValueError(
                f"o operador 'undeclared' veio com um periodo de {periodo_horas} h. Se a origem "
                "nao declara o que o numero resume, tambem nao declara sobre quanto tempo: "
                "escrever um periodo ao lado era dar-lhe a precisao que ele nao tem."
            )
    else:
        if periodo_horas is None:
            raise ValueError(
                f"o operador '{operador.value}' veio sem periodo. Uma media sem o intervalo que "
                "ela cobre nao se compara com nada: e exactamente a linha que este par de "
                "chaves existe para nao voltar a haver."
            )
        periodo_horas = float(periodo_horas)
        if not (periodo_horas > 0 and math.isfinite(periodo_horas)):
            raise ValueError(
                f"periodo de agregacao invalido: {periodo_horas}. Tem de ser um numero finito "
                "e positivo -- um periodo de zero ou negativo nao descreve intervalo nenhum."
            )

    return {
        "aggregation_operator": operador.value,
        "aggregation_period_hours": periodo_horas,
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia em linha reta entre dois pontos lat/lon, em km.

    Escolhida em vez da reprojeccao para UTM 29N de resoiltwin.geo porque o
    que ha aqui e a distancia entre dois pontos, nao a area de um poligono --
    nao ha vantagem em construir uma geometria e reprojecta-la so para medir
    um segmento. O haversine erra por defeito (assume esfera, nao elipsoide)
    numa fraccao de porcento, muito abaixo dos ~100 m de precisao pedidos a
    esta escala de poucos km.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _validar_lat_lon(lat: float, lon: float) -> None:
    """Recusa coordenadas fora do intervalo fisicamente possivel.

    Guarda mantida depois de a distancia deixar de ser um argumento directo:
    ja nao ha "distancia negativa" para recusar (o haversine nunca devolve
    uma), mas uma latitude ou longitude invalida produzia uma distancia
    calculada sobre lixo, em silencio. Isto apanha esse caso mais cedo.
    """
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"latitude fora do intervalo valido: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude fora do intervalo valido: {lon}")


def proveniencia_de_estacao(
    station_id: str,
    station_name: str,
    lat_estacao: float,
    lon_estacao: float,
    lat_sitio: float,
    lon_sitio: float,
) -> dict:
    """Proveniencia de um valor vindo de uma estacao meteorologica (IPMA).

    A API do IPMA nao devolve a distancia da estacao ao sitio -- so as
    coordenadas da estacao (idEstacao, localEstacao, geometry.coordinates).
    Por isso esta funcao recebe coordenadas e calcula a distancia com o
    mesmo haversine de proveniencia_de_celula, em vez de confiar num numero
    que quem chama teria de calcular por fora -- exactamente o erro
    silencioso que a proveniencia da celula ja evitava. measured_at_site e
    sempre False -- a distincao e binaria de proposito, ou o instrumento
    esta na parcela ou nao esta, e nenhuma estacao do IPMA fica na parcela,
    mesmo quando a distancia e pequena.
    """
    _validar_lat_lon(lat_estacao, lon_estacao)
    _validar_lat_lon(lat_sitio, lon_sitio)
    distancia_km = _haversine_km(lat_estacao, lon_estacao, lat_sitio, lon_sitio)
    return {
        "station_id": station_id,
        "station_name": station_name,
        "distance_km": distancia_km,
        "measured_at_site": False,
    }


def proveniencia_de_celula(
    lat_celula: float,
    lon_celula: float,
    lat_sitio: float,
    lon_sitio: float,
    resolucao_graus: float,
) -> dict:
    """Proveniencia de um valor vindo de uma celula de reanalise (AgERA5).

    Recebe as coordenadas da celula e do sitio e calcula a distancia entre
    elas -- nao a recebe por argumento, para que a conta nao fique a cargo
    de quem chama. measured_at_site e sempre False: uma grelha de ~9 km nunca
    e uma medicao no sitio.

    A pegada da celula sai em DUAS dimensoes, e nao num `cell_size_km` unico.
    A conversao `graus * (pi * R / 180)` so vale na direccao norte-sul; a
    este-oeste um grau encolhe com o cosseno da latitude, e a celula do
    AgERA5 nao e quadrada em nenhuma latitude que nao seja o equador:

        Turcifal (39,0)   0,1 grau = 11,1 km NS  x  8,6 km EW   (-22%)
        Porto    (41,2)   0,1 grau = 11,1 km NS  x  8,4 km EW   (-25%)

    Um numero unico era o valor norte-sul apresentado como se fosse o lado da
    celula -- o mesmo erro que ja custou a este projecto uma distancia 28%
    acima do real, desta vez gravado em cada linha da serie. O cosseno e o da
    latitude da CELULA, que e o objecto que a pegada descreve.
    """
    if resolucao_graus <= 0:
        raise ValueError("resolucao_graus tem de ser positiva")
    _validar_lat_lon(lat_celula, lon_celula)
    _validar_lat_lon(lat_sitio, lon_sitio)
    distancia_km = _haversine_km(lat_celula, lon_celula, lat_sitio, lon_sitio)
    km_por_grau = resolucao_graus * (math.pi * EARTH_RADIUS_KM / 180)
    return {
        "cell_lat": lat_celula,
        "cell_lon": lon_celula,
        "distance_km": distancia_km,
        "cell_size_deg": resolucao_graus,
        "cell_size_km_ns": km_por_grau,
        "cell_size_km_ew": km_por_grau * math.cos(math.radians(lat_celula)),
        "measured_at_site": False,
    }
