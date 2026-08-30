"""Balanco hidrico diario de reservatorio unico.

Funcao pura: entra uma serie diaria, sai outra. Sem base de dados e sem rede.
A agua disponivel sobe com a precipitacao, desce com a evapotranspiracao de
referencia, e fica limitada entre zero e a capacidade utilizavel. O que
transborda e escoamento e sai da conta.

**Fora de ambito, declarado:** coeficiente cultural (Kc) e qualquer distincao
entre evapotranspiracao de referencia e real. Sem Kc medido no terreno,
aplica-lo era inventar um numero -- por isso a procura de cada dia e a ET0 tal
como ela vem da origem, e a unica coisa que a limita e o reservatorio nao ter
mais agua para dar.

**A capacidade utilizavel nao e conhecida para estes sitios.** Nao ha analise
de solo destes terrenos neste projecto: nem capacidade de agua utilizavel, nem
profundidade radicular, nem textura. E o parametro que domina o resultado, e
por isso entra como argumento obrigatorio -- sem valor por omissao, que seria
um numero inventado a fingir de medicao -- e viaja em cada dia da saida, para
que a linha que vier a ser gravada o declare.

Duas decisoes que esta forma "simples" ainda assim obriga a tomar, e que nao
tem resposta obvia:

**O buraco na serie.** A serie real tem buracos -- a reanalise chega com
atraso -- e um dia em falta e um dia sobre o qual nao se sabe nada. Contar-lhe
zero de chuva inventa um deficit: a ET0 continuava a esvaziar o reservatorio
com base num numero que ninguem observou. Atravessar o buraco de estado
intacto tambem inventa, ao contrario: afirma que o reservatorio ficou onde
estava durante dias que nao se viram. As duas invencoes ficam gravadas na
serie sem deixar marca. A escolha aqui e a terceira: **o buraco corta o
segmento**. Nao se inventam linhas para os dias em falta, os dias que existem
saem todos, e cada um diz em que segmento esta e quantos dias leva desde o
reinicio -- e quem ler a serie ve o corte.

**O estado inicial.** Nao ha medicao dele em lado nenhum. Recebe-lo por
argumento era acrescentar um segundo numero que ninguem mediu; assumi-lo
(cheio a capacidade de campo, ou vazio) era inventa-lo. Aqui nao se faz nem
uma coisa nem outra: cada segmento e corrido **duas vezes**, a partir dos dois
unicos extremos que o reservatorio admite -- vazio e cheio -- e o que sai e o
intervalo entre as duas trajectorias. E um intervalo honesto: o passo diario e
monotono no estado de partida, logo qualquer estado inicial possivel produz
uma trajectoria contida entre estas duas. O intervalo estreita sozinho e
colapsa por completo no dia em que o reservatorio toca um dos limites, porque
a partir dai as duas trajectorias sao a mesma; `determinado` marca esse dia e
os seguintes. Antes dele, o que o modelo sabe e um intervalo, e o que ele
devolve e um intervalo.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

METODO_DO_BALANCO = "single-reservoir-daily-water-balance"
VERSAO_DO_BALANCO = "water-balance-single-reservoir-v1"


def _exigir_nao_negativo(nome: str, valor: float) -> None:
    if not math.isfinite(valor):
        raise ValueError(f"{nome} tem de ser um numero finito: {valor}")
    if valor < 0:
        raise ValueError(f"{nome} nao pode ser negativo: {valor}")


@dataclass(frozen=True)
class Solo:
    """Os parametros de solo do sitio. Hoje so um, e nenhum tem omissao.

    Nao ha analise de solo destes terrenos: este valor e escolha de quem
    chama, e a saida declara-o em cada dia para que nunca passe por medicao.
    """

    capacidade_utilizavel_mm: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.capacidade_utilizavel_mm):
            raise ValueError(
                f"capacidade utilizavel tem de ser um numero finito: {self.capacidade_utilizavel_mm}"
            )
        if self.capacidade_utilizavel_mm <= 0:
            raise ValueError(
                f"capacidade utilizavel tem de ser positiva: {self.capacidade_utilizavel_mm}. "
                "Um reservatorio de zero mm nao e um reservatorio."
            )


@dataclass(frozen=True)
class DiaDeEntrada:
    """Um dia de entradas. Ambas em mm; a ET0 e a de referencia, sem Kc."""

    data: date
    precipitacao_mm: float
    evapotranspiracao_referencia_mm: float

    def __post_init__(self) -> None:
        _exigir_nao_negativo("precipitacao_mm", self.precipitacao_mm)
        _exigir_nao_negativo("evapotranspiracao_referencia_mm", self.evapotranspiracao_referencia_mm)


@dataclass(frozen=True)
class DiaDeSaida:
    """Um dia de balanco.

    A agua e o escoamento saem como intervalo porque o estado inicial do
    segmento nao e conhecido -- ver o docstring do modulo. `determinado` e
    True quando os dois limites se encontraram e o valor ja nao depende dele.
    """

    data: date
    agua_disponivel_min_mm: float
    agua_disponivel_max_mm: float
    escoamento_min_mm: float
    escoamento_max_mm: float
    determinado: bool
    capacidade_utilizavel_mm: float  # o valor com que ESTE dia foi produzido
    segmento: int
    dias_desde_o_reinicio: int


def _passo(agua_mm: float, entrada: DiaDeEntrada, capacidade_mm: float) -> tuple[float, float]:
    """Um dia: entra chuva, sai ET0, e o resultado fica dentro do reservatorio.

    Devolve (agua no fim do dia, escoamento do dia). O tecto e o piso nao sao
    o mesmo tipo de limite: o que passa do tecto **existiu** e perdeu-se, e por
    isso sai contado como escoamento; o que faltava para chegar ao piso nunca
    existiu -- e procura de ET0 que o solo nao tinha para satisfazer -- e por
    isso nao deixa divida nenhuma para o dia seguinte pagar.
    """
    bruto = agua_mm + entrada.precipitacao_mm - entrada.evapotranspiracao_referencia_mm
    escoamento_mm = max(0.0, bruto - capacidade_mm)
    return min(max(bruto, 0.0), capacidade_mm), escoamento_mm


def balanco_diario(dias: list[DiaDeEntrada], solo: Solo) -> list[DiaDeSaida]:
    """Corre o balanco sobre uma serie diaria ordenada e devolve outra serie.

    A serie de entrada tem de vir por ordem crescente de data e sem dias
    repetidos; buracos sao permitidos e cortam o segmento. Sai exactamente um
    dia por cada dia de entrada -- os dias em falta nao ganham linha.
    """
    capacidade_mm = solo.capacidade_utilizavel_mm
    saida: list[DiaDeSaida] = []
    data_anterior: date | None = None
    segmento = -1
    dias_desde_o_reinicio = 0
    agua_min_mm = agua_max_mm = 0.0

    for entrada in dias:
        if data_anterior is not None and entrada.data <= data_anterior:
            raise ValueError(
                f"a serie tem de vir por ordem crescente de data e sem dias repetidos: "
                f"{entrada.data} veio depois de {data_anterior}"
            )
        if data_anterior is None or entrada.data != data_anterior + timedelta(days=1):
            # buraco (ou primeiro dia): o estado nao atravessa, recomeca-se dos
            # dois extremos admissiveis em vez de fingir que se sabe onde ficou
            segmento += 1
            dias_desde_o_reinicio = 0
            agua_min_mm, agua_max_mm = 0.0, capacidade_mm
        else:
            dias_desde_o_reinicio += 1

        agua_min_mm, escoamento_min_mm = _passo(agua_min_mm, entrada, capacidade_mm)
        agua_max_mm, escoamento_max_mm = _passo(agua_max_mm, entrada, capacidade_mm)

        saida.append(
            DiaDeSaida(
                data=entrada.data,
                agua_disponivel_min_mm=agua_min_mm,
                agua_disponivel_max_mm=agua_max_mm,
                escoamento_min_mm=escoamento_min_mm,
                escoamento_max_mm=escoamento_max_mm,
                # as duas trajectorias so ficam iguais quando ambas tocaram o
                # mesmo limite; dai em diante seguem juntas, bit a bit
                determinado=agua_min_mm == agua_max_mm,
                capacidade_utilizavel_mm=capacidade_mm,
                segmento=segmento,
                dias_desde_o_reinicio=dias_desde_o_reinicio,
            )
        )
        data_anterior = entrada.data

    return saida
