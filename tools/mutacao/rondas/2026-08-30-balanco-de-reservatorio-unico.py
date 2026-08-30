"""Ronda sobre o balanco hidrico de reservatorio unico (Fase D, Task 2).

O balanco e aritmetica de escola: soma a chuva, subtrai a ET0, limita o
resultado. Precisamente por isso e um sitio perigoso -- todas as versoes
erradas produzem uma serie de numeros com o aspecto certo, na ordem certa e
na unidade certa. Um reservatorio sem tecto, um reservatorio com divida
acumulada, e um reservatorio que atravessa dez dias em falta como se fossem
dez dias secos dao os tres uma serie diaria plausivel, e nenhuma das tres se
denuncia no grafico.

Os mutantes abaixo dividem-se em quatro familias:

- **o reservatorio** (t1, t2, t3, a1, a2): o tecto, o piso e as duas parcelas
  da conta diaria;
- **o buraco** (b1, b2): o corte do segmento, e o controlo negativo dele --
  cortar sempre e tao errado como nunca cortar;
- **o estado inicial** (i1, i2, i3): o envelope que substitui o numero que
  ninguem mediu, pelos dois lados, e a marca que diz quando ele colapsou;
- **o que a linha declara e o que ela recusa** (c1, v1, v2, v3): a capacidade
  que tem de viajar na saida, e as tres guardas de entrada.
"""

_LINHA_DO_LIMITE = "    return min(max(bruto, 0.0), capacidade_mm), escoamento_mm"
_LINHA_DO_BRUTO = (
    "    bruto = agua_mm + entrada.precipitacao_mm - entrada.evapotranspiracao_referencia_mm"
)
_LINHA_DO_CORTE = (
    "        if data_anterior is None or entrada.data != data_anterior + timedelta(days=1):"
)
_LINHA_DOS_EXTREMOS = "            agua_min_mm, agua_max_mm = 0.0, capacidade_mm"

MUTANTES = [
    ("t1",
     "src/resoiltwin/water/balance.py",
     _LINHA_DO_LIMITE,
     "    return max(bruto, 0.0), escoamento_mm",
     "_passo",
     "o transbordo fica no reservatorio em vez de sair da conta"),

    ("t2",
     "src/resoiltwin/water/balance.py",
     _LINHA_DO_LIMITE,
     "    return min(bruto, capacidade_mm), escoamento_mm",
     "_passo",
     "o piso do zero desaparece: o reservatorio pode ficar negativo"),

    ("t3",
     "src/resoiltwin/water/balance.py",
     "    escoamento_mm = max(0.0, bruto - capacidade_mm)",
     "    escoamento_mm = 0.0",
     "_passo",
     "o que transborda deixa de ser contado e a perda fica invisivel"),

    ("a1",
     "src/resoiltwin/water/balance.py",
     _LINHA_DO_BRUTO,
     "    bruto = agua_mm + entrada.precipitacao_mm",
     "_passo",
     "a evapotranspiracao deixa de descer do reservatorio"),

    ("a2",
     "src/resoiltwin/water/balance.py",
     _LINHA_DO_BRUTO,
     "    bruto = agua_mm - entrada.evapotranspiracao_referencia_mm",
     "_passo",
     "a precipitacao deixa de entrar no reservatorio"),

    ("b1",
     "src/resoiltwin/water/balance.py",
     _LINHA_DO_CORTE,
     "        if data_anterior is None:",
     "balanco_diario",
     "o buraco na serie passa por dia normal: o estado atravessa-o intacto"),

    ("b2",
     "src/resoiltwin/water/balance.py",
     _LINHA_DO_CORTE,
     "        if True:",
     "balanco_diario",
     "todos os dias cortam o segmento: o reservatorio deixa de ter memoria"),

    ("b3",
     "src/resoiltwin/water/balance.py",
     "            dias_desde_o_reinicio += 1",
     "            dias_desde_o_reinicio += 0",
     "balanco_diario",
     "a contagem de dias desde o reinicio fica parada no zero"),

    ("i1",
     "src/resoiltwin/water/balance.py",
     _LINHA_DOS_EXTREMOS,
     "            agua_min_mm, agua_max_mm = capacidade_mm, capacidade_mm",
     "balanco_diario",
     "o estado inicial passa a ser assumido cheio, e o envelope desaparece"),

    ("i2",
     "src/resoiltwin/water/balance.py",
     _LINHA_DOS_EXTREMOS,
     "            agua_min_mm, agua_max_mm = 0.0, 0.0",
     "balanco_diario",
     "o estado inicial passa a ser assumido vazio, e o envelope desaparece"),

    ("i3",
     "src/resoiltwin/water/balance.py",
     "                determinado=agua_min_mm == agua_max_mm,",
     "                determinado=True,",
     "balanco_diario",
     "todo o dia se declara determinado, mesmo antes de os extremos se encontrarem"),

    ("c1",
     "src/resoiltwin/water/balance.py",
     "                capacidade_utilizavel_mm=capacidade_mm,",
     "                capacidade_utilizavel_mm=0.0,",
     "balanco_diario",
     "a capacidade usada deixa de viajar na saida"),

    ("v1",
     "src/resoiltwin/water/balance.py",
     "        if data_anterior is not None and entrada.data <= data_anterior:",
     "        if data_anterior is not None and entrada.data < data_anterior:",
     "balanco_diario",
     "um dia repetido deixa de ser recusado e conta duas vezes"),

    ("v2",
     "src/resoiltwin/water/balance.py",
     "        if self.capacidade_utilizavel_mm <= 0:",
     "        if self.capacidade_utilizavel_mm < 0:",
     "__post_init__",
     "uma capacidade de zero mm passa a ser aceite como reservatorio"),

    ("v3",
     "src/resoiltwin/water/balance.py",
     "    if valor < 0:",
     "    if False:",
     "_exigir_nao_negativo",
     "chuva ou evapotranspiracao negativas passam a ser aceites"),

    ("v4",
     "src/resoiltwin/water/balance.py",
     "        if data_anterior is not None and entrada.data <= data_anterior:",
     "        if False:",
     "balanco_diario",
     "a ordem da serie deixa de ser verificada"),

    ("c2",
     "src/resoiltwin/water/balance.py",
     "    capacidade_utilizavel_mm: float",
     "    capacidade_utilizavel_mm: float = 100.0",
     "Solo",
     "a capacidade ganha um valor por omissao: um numero inventado a fingir de medicao"),

    ("c3",
     "src/resoiltwin/water/balance.py",
     "def balanco_diario(dias: list[DiaDeEntrada], solo: Solo) -> list[DiaDeSaida]:",
     "def balanco_diario(dias: list[DiaDeEntrada], solo: Solo = Solo(100.0)) -> list[DiaDeSaida]:",
     "balanco_diario",
     "chamar o balanco sem solo passa a ser legal, com uma capacidade inventada"),
]
