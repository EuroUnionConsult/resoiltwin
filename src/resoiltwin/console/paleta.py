"""A cor da consola, e de onde cada uma vem.

A regra que manda: **a moldura e neutra e fria, e a cor esta so nos dados.**
Nada que seja estrutura -- fundo, fio, tipo, cabecalho -- tem saturacao. Assim,
qualquer mancha de cor que apareca no ecra e um valor, e nao decoracao; e quando
tudo o resto e cinzento, uma mancha pequena chega.

E a cor dos dados vem do dominio, e nao do gosto:

- **proveniencia na matiz 10YR** das cartas de solo Munsell. E o hue que a
  pedologia usa para descrever solo -- o castanho-amarelado das cartas de
  campo --, portanto quem le solo ja o conhece. Aqui usa-se uma so matiz e
  varia-se o **valor** (a claridade), que e como uma carta de solo tambem
  ordena: e uma escala ordinal, do mais directo ao mais distante da parcela;
- **vegetacao de castanho para verde.** A literatura de deteccao remota chama-lhe
  *browning* / *greening*, e a direccao e a mesma que os artigos usam;
- **agua de seco para humido**, laranja em seco e azul em humido, como os mapas
  de humidade do solo da NASA.

⛔ **Nunca arco-iris.** Ha um artigo de hidrologia de 2021 que mede a distorcao
que uma rampa arco-iris introduz na leitura precisamente neste campo: o salto de
luminancia no amarelo inventa uma fronteira onde os dados nao tem nenhuma. As
rampas deste ficheiro andam numa direccao so, entre dois ancoradouros, e o teste
`test_nenhuma_rampa_e_um_arco_iris` recusa qualquer uma que inverta o sentido.
"""

from resoiltwin.enums import SourceType

# ---------------------------------------------------------------------------
# A moldura
# ---------------------------------------------------------------------------

# Croma = distancia entre o canal mais alto e o mais baixo, em 0-255. Usa-se
# isto e nao a saturacao HSL porque a saturacao HSL de um cinzento quase branco
# dispara para valores altos por causa do denominador -- e um limite escrito
# sobre ela recusava a moldura inteira sem existir cor nenhuma.
CROMA_MAXIMO_DA_MOLDURA = 12

# Cinzentos frios: o azul um pouco acima do vermelho em todos eles. E o
# "instrumento" e nao o "papel" -- e deixa o 10YR dos dados, que e quente, a
# destacar-se sem precisar de saturacao.
MOLDURA_CLARA = {
    "fundo": "#FBFCFD",
    "fundo-fraco": "#F2F5F7",
    "superficie": "#FFFFFF",
    "tinta": "#16191C",
    "tinta-media": "#4C5257",
    "tinta-fraca": "#70777C",
    "fio": "#DEE4E8",
    "fio-forte": "#C8CED2",
    "realce": "#E8EEF2",
}

MOLDURA_ESCURA = {
    "fundo": "#121517",
    "fundo-fraco": "#181B1E",
    "superficie": "#1D2124",
    "tinta": "#E7EBEE",
    "tinta-media": "#A9B0B5",
    "tinta-fraca": "#7C8388",
    "fio": "#2C3135",
    "fio-forte": "#3D4348",
    "realce": "#232A2E",
}

# ---------------------------------------------------------------------------
# A proveniencia, na matiz 10YR
# ---------------------------------------------------------------------------

# A janela de matiz que conta como 10YR depois de a converter para sRGB. Nao e
# um numero redondo escolhido a olho: o 10YR das cartas de solo cai entre os
# ~25 e os ~48 graus da roda HSL conforme o valor e o croma da amostra, e e essa
# a janela que as duas rampas abaixo tem de respeitar.
MATIZ_10YR = (25.0, 48.0)

# ⭐ A ordem, e ela e o significado da escala: do mais directo ao mais distante
# de uma medicao desta parcela. Nao e uma ordem estetica -- e a mesma pergunta
# que o `source_type` responde, posta por graus.
#
# ⚠️ Isto e uma escala de DISTANCIA a medicao, e nao de qualidade. Uma linha de
# reanalise nao e pior do que uma de laboratorio: e outra coisa. O que a escala
# impede e que as tres proveniencias de uma mesma metrica se leiam como
# comparaveis, que e a leitura que este produto nao pode deixar acontecer.
ORDEM_DA_PROVENIENCIA = (
    SourceType.observed_lab,
    SourceType.observed_reference,
    SourceType.observed_screening,
    SourceType.satellite_observed,
    SourceType.weather_observed,
    SourceType.reanalysis,
    SourceType.simulated,
    SourceType.derived,
)

# A matiz nao muda com o tema; o valor muda. E tem de mudar: a escala e lida
# pelo CONTRASTE contra o fundo (mais directo = mais contraste), e num fundo
# escuro o extremo mais contrastado e o claro. Inverter as duas rampas mantinha
# a matiz e destruia a leitura.
PROVENIENCIA_CLARA = {
    SourceType.observed_lab: "#33281E",
    SourceType.observed_reference: "#4A3928",
    SourceType.observed_screening: "#63492C",
    SourceType.satellite_observed: "#7E6440",
    SourceType.weather_observed: "#9A8058",
    SourceType.reanalysis: "#B69C76",
    SourceType.simulated: "#CDB998",
    SourceType.derived: "#E0D3BC",
}

PROVENIENCIA_ESCURA = {
    SourceType.observed_lab: "#F0E4CC",
    SourceType.observed_reference: "#DFCEAF",
    SourceType.observed_screening: "#CBB68F",
    SourceType.satellite_observed: "#B49C74",
    SourceType.weather_observed: "#9C845E",
    SourceType.reanalysis: "#836E4C",
    SourceType.simulated: "#6B583C",
    SourceType.derived: "#55452F",
}

# ---------------------------------------------------------------------------
# As rampas de valor
# ---------------------------------------------------------------------------

# Percurso maximo de matiz que uma rampa pode fazer, em graus. Um arco-iris
# percorre a roda quase toda; uma rampa divergente honesta (seco/humido) passa
# pelo neutro e nao pelo amarelo, e cabe aqui com folga.
PERCURSO_MAXIMO_DE_MATIZ = 200.0

# Castanho -> verde. E a direccao de *browning*/*greening* da literatura, e por
# isso um leitor do dominio ja sabe para que lado e "mais vegetacao" sem olhar
# para legenda nenhuma.
VEGETACAO = ("#7A5A32", "#A08A55", "#B9AE72", "#7E9A4A", "#3D6E2E")

# Seco -> humido. Divergente, com o neutro no meio: e o desenho dos mapas de
# humidade do solo, e o neutro no meio e o que impede que o meio da escala
# pareca uma classe propria.
AGUA = ("#C4622A", "#D9A05C", "#D8CBB0", "#7FA8B8", "#2E6E8E")

RAMPAS_DE_VALOR = {"vegetacao": VEGETACAO, "agua": AGUA}

# Que metrica usa que rampa, e com que dominio. ⚠️ Um dominio inventado e uma
# afirmacao: dizer que 25 graus e "meio" numa barra de temperatura e escolher
# uma escala que nada neste projecto sustenta. Por isso so estao aqui as
# metricas cujo dominio NAO e inventado:
#
# - os indices normalizados vivem, por construcao, entre -1 e 1;
# - a agua disponivel no solo vive entre zero e a capacidade do reservatorio, e
#   a capacidade vem escrita na propria evidencia da linha.
#
# Tudo o resto nao tem barra nenhuma. E melhor nao desenhar do que desenhar
# sobre um eixo que ninguem definiu.
DOMINIOS = {
    "ndvi": ("vegetacao", -1.0, 1.0),
    "ndre": ("vegetacao", -1.0, 1.0),
    "ndmi": ("vegetacao", -1.0, 1.0),
    "soil_available_water": ("agua", 0.0, None),  # o topo vem da evidencia
}

# A chave da evidencia de onde sai o topo do dominio da agua.
CAPACIDADE_NA_EVIDENCIA = "available_water_capacity_mm"

# ---------------------------------------------------------------------------
# Tokens que nao mudam com o tema
# ---------------------------------------------------------------------------

# `test_o_tema_escuro_redefine_todos_os_tokens_do_claro` exige que tudo o que o
# `:root` define seja redefinido no bloco escuro. Estes ficam de fora, e cada um
# por uma razao que se escreve:
#
# - as rampas de valor sao codificadas por MATIZ e nao por claridade. Muda-las
#   com o tema mudava o significado da cor, que e o contrario do que se quer:
#   um azul e "humido" nos dois temas;
# - as duracoes, a curva e o passo da trama sao geometria e tempo, nao cor.
TOKENS_SEM_TEMA = frozenset({
    *(f"--vegetacao-{indice}" for indice in range(len(VEGETACAO))),
    *(f"--agua-{indice}" for indice in range(len(AGUA))),
    "--duracao",
    "--curva",
    "--trama-passo",
    "--trama-largura",
})
