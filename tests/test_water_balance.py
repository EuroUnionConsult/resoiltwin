"""Testes do balanco hidrico diario de reservatorio unico.

Tres decisoes de desenho ficam aqui presas, e nenhuma delas se ve olhando
para um numero da serie de saida:

1. **A capacidade utilizavel nao tem valor por omissao e viaja em cada dia.**
   E o parametro que domina o resultado e nao foi medido em nenhum destes
   sitios. Um valor por omissao seria um numero inventado a fingir de medicao.
2. **Um buraco na serie corta o segmento.** Dias em falta nao sao dias de zero
   chuva -- sao dias sobre os quais nao se sabe nada -- e tambem nao se
   atravessa o buraco a fingir que o reservatorio ficou onde estava.
3. **O estado inicial nao e recebido nem assumido.** Cada segmento corre a
   partir dos dois extremos admissiveis (vazio e cheio) e o que sai e o
   intervalo entre eles, que colapsa sozinho no dia em que o reservatorio
   toca um dos limites.
"""

import inspect
from datetime import date, timedelta

import pytest

from resoiltwin.water.balance import DiaDeEntrada, Solo, balanco_diario


def _dia(d: date, precipitacao: float = 0.0, et0: float = 0.0) -> DiaDeEntrada:
    return DiaDeEntrada(
        data=d,
        precipitacao_mm=precipitacao,
        evapotranspiracao_referencia_mm=et0,
    )


def _serie(inicio: date, entradas: list[tuple[float, float]]) -> list[DiaDeEntrada]:
    """Serie contigua a partir de `inicio`: uma entrada por dia, sem buracos."""
    return [_dia(inicio + timedelta(days=i), p, e) for i, (p, e) in enumerate(entradas)]


# --- o estado inicial ---------------------------------------------------------


def test_the_first_day_says_only_that_the_water_is_somewhere_in_the_reservoir():
    """Ninguem mediu o estado inicial destes sitios. O modelo nao o recebe por
    argumento (era mais um numero por medir) nem o assume (era invencao): corre
    o segmento a partir dos dois extremos admissiveis e devolve o intervalo."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(0.0, 0.0)]),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert len(saida) == 1
    assert saida[0].agua_disponivel_min_mm == 0.0
    assert saida[0].agua_disponivel_max_mm == 100.0
    assert saida[0].determinado is False


def test_a_day_is_only_determined_once_the_two_extremes_have_met():
    """Com 100 mm de capacidade e 30 mm de ET0 por dia, uma trajectoria que
    comece cheia leva quatro dias a encontrar-se com a que comecou vazia. So
    a partir dai o valor deixa de depender do que ninguem mediu."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(0.0, 30.0)] * 5),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert [d.determinado for d in saida] == [False, False, False, True, True]


def test_the_envelope_contains_every_initial_state_it_could_have_started_from():
    """A afirmacao que o intervalo faz e verificavel: qualquer trajectoria que
    comece dentro do reservatorio fica dentro do intervalo, todos os dias. O
    oraculo esta escrito aqui e nao chama o codigo de producao."""
    capacidade = 100.0
    entradas = [
        (0.0, 4.0), (12.0, 3.0), (0.0, 6.0), (40.0, 2.0), (0.0, 5.0),
        (0.0, 5.0), (90.0, 1.0), (0.0, 7.0), (3.0, 3.0), (0.0, 9.0),
    ]
    saida = balanco_diario(
        _serie(date(2026, 7, 1), entradas),
        Solo(capacidade_utilizavel_mm=capacidade),
    )
    for inicial in (0.0, 17.5, 50.0, 82.3, 100.0):
        agua = inicial
        for dia, (p, e) in zip(saida, entradas, strict=True):
            agua = min(max(agua + p - e, 0.0), capacidade)
            assert dia.agua_disponivel_min_mm - 1e-9 <= agua
            assert agua <= dia.agua_disponivel_max_mm + 1e-9


# --- o dia parado, o transbordo e o piso do zero ------------------------------


def test_a_day_without_rain_or_et_does_not_move_a_determined_reservoir():
    """O primeiro dia satura o reservatorio pelos dois lados; os dois seguintes
    nao tem entradas nenhumas e por isso nao lhe podem mexer."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(300.0, 0.0), (0.0, 0.0), (0.0, 0.0)]),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert saida[0].determinado is True
    assert [d.agua_disponivel_min_mm for d in saida] == [100.0, 100.0, 100.0]
    assert [d.agua_disponivel_max_mm for d in saida] == [100.0, 100.0, 100.0]


def test_rain_above_the_capacity_leaves_the_reservoir_as_runoff():
    """O excedente e escoamento e sai da conta. Fica registado -- sem ele, um
    dia cheio e um dia em que se perderam 150 mm sao a mesma linha -- mas nunca
    volta a entrar: o dia seguinte gasta ET sobre o que cabe, nao sobre o que
    choveu."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(300.0, 0.0), (150.0, 0.0), (0.0, 20.0)]),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert saida[1].agua_disponivel_min_mm == 100.0
    assert saida[1].agua_disponivel_max_mm == 100.0
    assert saida[1].escoamento_min_mm == 150.0
    assert saida[1].escoamento_max_mm == 150.0
    assert saida[2].agua_disponivel_min_mm == 80.0
    assert saida[2].agua_disponivel_max_mm == 80.0


def test_before_the_state_is_determined_the_runoff_is_a_range_too():
    """Num dia cujo estado ainda nao esta determinado, tambem nao se sabe
    quanto transbordou: 150 mm sobre um reservatorio vazio perdem 50, sobre um
    reservatorio cheio perdem 150."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(150.0, 0.0)]),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert saida[0].escoamento_min_mm == 50.0
    assert saida[0].escoamento_max_mm == 150.0


def test_a_long_dry_spell_never_takes_the_reservoir_negative():
    """Um reservatorio a -200 mm nao e uma coisa."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(0.0, 5.0)] * 60),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert all(d.agua_disponivel_min_mm >= 0.0 for d in saida)
    assert saida[-1].agua_disponivel_min_mm == 0.0
    assert saida[-1].agua_disponivel_max_mm == 0.0
    assert saida[-1].determinado is True


def test_the_dry_spell_leaves_no_debt_for_the_next_rain_to_pay():
    """Sessenta dias a 5 mm dao 300 mm de procura sobre um reservatorio de 100.
    Os 200 mm que o solo nao tinha para dar nao existem: a chuva a seguir enche
    o que chove, nao o que chove menos uma divida acumulada."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(0.0, 5.0)] * 60 + [(30.0, 0.0)]),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert saida[-1].agua_disponivel_min_mm == 30.0
    assert saida[-1].agua_disponivel_max_mm == 30.0


# --- o buraco na serie --------------------------------------------------------


def test_a_missing_day_is_not_a_day_without_rain():
    """A serie real tem buracos: a reanalise chega com atraso. Um dia em falta
    e um dia sobre o qual nao se sabe nada -- nao se inventa uma linha para ele,
    nao se conta como seco, e nao se atravessa o buraco a fingir que o
    reservatorio ficou onde estava. O segmento recomeca e diz que recomecou."""
    dias = [_dia(date(2026, 7, 1), precipitacao=300.0), _dia(date(2026, 7, 11))]
    saida = balanco_diario(dias, Solo(capacidade_utilizavel_mm=100.0))
    assert [d.data for d in saida] == [date(2026, 7, 1), date(2026, 7, 11)]
    assert saida[0].segmento == 0
    assert saida[0].determinado is True
    assert saida[0].agua_disponivel_min_mm == 100.0
    assert saida[1].segmento == 1
    assert saida[1].dias_desde_o_reinicio == 0
    assert saida[1].determinado is False
    assert saida[1].agua_disponivel_min_mm == 0.0
    assert saida[1].agua_disponivel_max_mm == 100.0


def test_a_contiguous_series_is_one_single_segment():
    """Controlo negativo do teste acima: sem buracos nao ha reinicio nenhum, e
    a memoria do reservatorio atravessa a serie toda."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(0.0, 0.0)] * 5),
        Solo(capacidade_utilizavel_mm=100.0),
    )
    assert [d.segmento for d in saida] == [0, 0, 0, 0, 0]
    assert [d.dias_desde_o_reinicio for d in saida] == [0, 1, 2, 3, 4]


def test_a_repeated_day_is_refused():
    with pytest.raises(ValueError):
        balanco_diario(
            [_dia(date(2026, 7, 1)), _dia(date(2026, 7, 1))],
            Solo(capacidade_utilizavel_mm=100.0),
        )


def test_a_series_out_of_order_is_refused():
    with pytest.raises(ValueError):
        balanco_diario(
            [_dia(date(2026, 7, 2)), _dia(date(2026, 7, 1))],
            Solo(capacidade_utilizavel_mm=100.0),
        )


def test_an_empty_series_gives_an_empty_series():
    assert balanco_diario([], Solo(capacidade_utilizavel_mm=100.0)) == []


# --- a capacidade utilizavel --------------------------------------------------


def test_the_capacity_used_travels_with_every_day():
    """A capacidade domina o resultado e ninguem a mediu nestes sitios: a linha
    que vier a ser gravada tem de declarar o valor com que foi produzida."""
    saida = balanco_diario(
        _serie(date(2026, 7, 1), [(0.0, 12.0), (0.0, 3.0)]),
        Solo(capacidade_utilizavel_mm=137.0),
    )
    assert [d.capacidade_utilizavel_mm for d in saida] == [137.0, 137.0]


def test_the_capacity_has_no_default_value():
    """Um valor por omissao seria um numero inventado a fingir de medicao."""
    assert (
        inspect.signature(Solo).parameters["capacidade_utilizavel_mm"].default
        is inspect.Parameter.empty
    )
    assert inspect.signature(balanco_diario).parameters["solo"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        Solo()


def test_a_capacity_that_is_not_a_reservoir_is_refused():
    for valor in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            Solo(capacidade_utilizavel_mm=valor)


def test_negative_or_non_finite_inputs_are_refused():
    for precipitacao, et0 in (
        (-1.0, 0.0),
        (0.0, -1.0),
        (float("nan"), 0.0),
        (0.0, float("inf")),
    ):
        with pytest.raises(ValueError):
            _dia(date(2026, 7, 1), precipitacao, et0)
