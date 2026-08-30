import pytest

from resoiltwin.weather.metrics import (
    UNIDADE_POR_METRICA,
    AggregationOperator,
    WeatherMetric,
    proveniencia_de_agregacao,
    proveniencia_de_celula,
    proveniencia_de_estacao,
)

# coordenadas do sitio de Turcifal, as mesmas usadas em tests/test_geo.py
TURCIFAL_LAT, TURCIFAL_LON = 39.037317, -9.240247


def test_every_metric_has_a_unit():
    for m in WeatherMetric:
        assert UNIDADE_POR_METRICA[m], f"{m} sem unidade"


def test_metrics_reuse_the_names_already_in_the_database():
    """air_temperature e relative_humidity ja existem como observed_screening.
    A mesma grandeza tem de ter o mesmo nome, seja qual for a fonte — quem as
    distingue e o source_type, nao o nome da metrica."""
    assert WeatherMetric.air_temperature == "air_temperature"
    assert WeatherMetric.relative_humidity == "relative_humidity"


def test_station_provenance_computes_the_distance():
    """A API do IPMA nao devolve distancia, so coordenadas -- por isso a
    funcao recebe coordenadas e calcula, tal como proveniencia_de_celula.
    Coordenadas da estacao (1210739, Torres Vedras/Dois Portos) verificadas
    em api.ipma.pt/open-data/observation/meteorology/stations/stations.json."""
    p = proveniencia_de_estacao(
        "1210739",
        "Torres Vedras, Dois Portos",
        39.04389444,
        -9.179,
        TURCIFAL_LAT,
        TURCIFAL_LON,
    )
    assert p["station_id"] == "1210739"
    assert p["distance_km"] == pytest.approx(5.340, abs=0.05)
    assert p["measured_at_site"] is False


def test_a_station_on_top_of_the_site_is_still_not_at_the_site():
    """S. Gens fica a ~0,9 km do sitio do Porto -- perto, mas nao no sitio.
    A distincao e binaria de proposito: ou o instrumento esta na parcela, ou
    nao esta."""
    p = proveniencia_de_estacao(
        "1210649",
        "S. Gens",
        41.1848,
        -8.6350,
        41.177928,
        -8.641731,
    )
    assert p["distance_km"] == pytest.approx(0.949, abs=0.05)
    assert p["measured_at_site"] is False


def test_cell_provenance_computes_the_distance_to_the_site():
    # celula centrada a 0,05 grau a norte do sitio, mesma longitude -> ~5,56 km
    p = proveniencia_de_celula(39.087, -9.240, 39.037, -9.240, 0.1)
    assert p["distance_km"] == pytest.approx(5.560, abs=0.05)
    assert p["cell_size_deg"] == 0.1
    assert p["measured_at_site"] is False


def test_cell_provenance_reports_the_footprint_in_km():
    """A pegada e dada nas DUAS direccoes. Um so `cell_size_km` era o valor
    norte-sul apresentado como se fosse o lado da celula, e a celula nao e
    quadrada em nenhuma latitude que nao seja o equador."""
    p = proveniencia_de_celula(39.087, -9.240, 39.037, -9.240, 0.1)
    assert p["cell_size_km_ns"] == pytest.approx(11.120, abs=0.05)
    assert p["cell_size_km_ew"] == pytest.approx(8.635, abs=0.05)
    assert "cell_size_km" not in p, "o nome ambiguo nao pode voltar a aparecer"


def test_the_cell_is_narrower_east_west_at_portuguese_latitudes():
    """Um grau de longitude nao vale 111 km fora do equador: vale 111 x cos(lat).

    Turcifal (39 graus): 0,1 grau da 11,1 km norte-sul e 8,6 km este-oeste --
    22% de diferenca. Porto (41,2): 8,4 km, 25%. Este projecto ja publicou uma
    distancia 28% acima do real por tratar um grau de longitude como se
    valesse o mesmo que um grau de latitude; um numero unico na proveniencia
    era o mesmo erro, gravado em cada linha.
    """
    turcifal = proveniencia_de_celula(39.0, -9.2, 39.037317, -9.240247, 0.1)
    porto = proveniencia_de_celula(41.2, -8.6, 41.177928, -8.641731, 0.1)

    assert turcifal["cell_size_km_ns"] == pytest.approx(porto["cell_size_km_ns"], abs=1e-9)
    assert turcifal["cell_size_km_ew"] == pytest.approx(8.643, abs=0.02)
    assert porto["cell_size_km_ew"] == pytest.approx(8.368, abs=0.02)
    # a diferenca e grande de mais para ser arredondamento: >20% nos dois casos
    for p in (turcifal, porto):
        encolhimento = 1 - p["cell_size_km_ew"] / p["cell_size_km_ns"]
        assert encolhimento > 0.20
    # e o encolhimento aumenta com a latitude: o Porto e mais estreito
    assert porto["cell_size_km_ew"] < turcifal["cell_size_km_ew"]


def test_invalid_coordinates_are_refused():
    """Ja nao ha "distancia negativa" para recusar -- a distancia passou a
    ser sempre calculada, e o haversine nunca devolve um valor negativo.
    O que continua a poder vir errado e a coordenada: uma latitude fora de
    [-90, 90] produzia, antes desta guarda, uma distancia calculada sobre
    lixo, em silencio."""
    with pytest.raises(ValueError):
        proveniencia_de_estacao("x", "y", 999.0, 0.0, TURCIFAL_LAT, TURCIFAL_LON)


# --------------------------------------------------- o que o numero resume


def test_an_operator_outside_the_vocabulary_is_refused():
    """Um rotulo inventado no `evidence` e uma palavra que ninguem sabe ler.

    E pior do que a chave em falta: a chave em falta ve-se, e um `"hourly"`
    escrito a mao ao lado de tres `"mean"` parece informacao e nao e.
    """
    with pytest.raises(ValueError, match="operador de agregacao desconhecido"):
        proveniencia_de_agregacao("hourly", 1)


def test_a_real_operator_without_a_period_is_refused():
    """Uma media sem o intervalo que ela cobre nao se compara com nada.

    E literalmente a linha que existia antes deste par de chaves: `mean` sem
    periodo diz tanto como nao dizer nada, porque a pergunta que o leitor tem
    e "media de quanto tempo".
    """
    with pytest.raises(ValueError, match="sem periodo"):
        proveniencia_de_agregacao(AggregationOperator.mean, None)
    with pytest.raises(ValueError, match="sem periodo"):
        proveniencia_de_agregacao(AggregationOperator.total, None)


def test_undeclared_is_the_only_operator_that_carries_a_null_period():
    """O `null` do periodo nunca e ambiguo, e e por isto que ha duas chaves.

    Uma chave unica a `null` diz ao mesmo tempo "esta variavel nao tem
    agregacao nenhuma" e "ninguem preencheu isto", e as duas leituras sao
    incompativeis: a primeira convida a comparar a serie com outra, a segunda
    proibe-o. Aqui o `null` so e legal com o operador `undeclared` a nomea-lo,
    e o `undeclared` so e legal COM ele -- as duas direccoes sao verificadas,
    e e a segunda que impede uma linha de dizer "nao sei o que isto resume,
    mas resume uma hora".
    """
    sem_declaracao = proveniencia_de_agregacao(AggregationOperator.undeclared, None)
    assert sem_declaracao["aggregation_operator"] == "undeclared"
    assert sem_declaracao["aggregation_period_hours"] is None

    with pytest.raises(ValueError, match="veio com um periodo"):
        proveniencia_de_agregacao(AggregationOperator.undeclared, 1)


def test_a_period_that_is_not_a_positive_interval_is_refused():
    """Zero horas nao e um intervalo, e negativo tambem nao."""
    for periodo in (0, -1, float("inf")):
        with pytest.raises(ValueError, match="periodo de agregacao invalido"):
            proveniencia_de_agregacao(AggregationOperator.mean, periodo)


def test_the_operator_is_written_as_text_and_not_as_the_enum():
    """O `evidence` vai para JSONB: um StrEnum serializa, mas o que la fica
    tem de ser a palavra e nao a repr do membro. Fixado porque a chave e lida
    por quem monta os graficos da Fase F, nao por Python."""
    valor = proveniencia_de_agregacao(AggregationOperator.mean, 24)
    assert valor == {"aggregation_operator": "mean", "aggregation_period_hours": 24.0}
    assert type(valor["aggregation_operator"]) is str
