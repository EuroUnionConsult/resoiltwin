"""Ronda sobre a entrada da evapotranspiracao de referencia no AgERA5.

A Task 1 da Fase D acrescentou uma quarta variavel a `_VARIAVEIS_AGERA5`, e
uma entrada dessa tabela sao quatro decisoes independentes: que estatistica
vai no pedido, com que nome a variavel aparece dentro do ficheiro, que metrica
do vocabulario ela e, e que conversao de unidade se lhe aplica. Nenhuma das
quatro se ve na linha gravada -- uma errada produz uma serie com proveniencia
completa e ar de correcto.

A ET0 e o caso em que isso custa mais caro: e a entrada que domina qualquer
balanco hidrico, e um valor errado so aparece no resultado do balanco, nunca
na coluna que o produziu.

Cada mutante muda UMA das quatro decisoes. Se sobreviver, essa decisao nao
esta a ser defendida por teste nenhum.
"""

_LINHA_CABECA = ('    "reference_evapotranspiration": (None, "ReferenceET_PenmanMonteith_FAO56",')

MUTANTES = [
    ("e1",
     "src/resoiltwin/weather/cds.py",
     _LINHA_CABECA,
     '    "reference_evapotranspiration": (None, "reference_evapotranspiration",',
     "(modulo)",
     "o nome procurado dentro do ficheiro passa a ser o nome com que se pede"),

    ("e2",
     "src/resoiltwin/weather/cds.py",
     _LINHA_CABECA,
     '    "reference_evapotranspiration": ("24_hour_mean", "ReferenceET_PenmanMonteith_FAO56",',
     "(modulo)",
     "o pedido da ET0 passa a levar `statistic`, que o CDS recusa"),

    ("e3",
     "src/resoiltwin/weather/cds.py",
     "                                     WeatherMetric.reference_evapotranspiration,",
     "                                     WeatherMetric.precipitation,",
     "(modulo)",
     "a ET0 e gravada com o nome de metrica da precipitacao"),

    ("e4",
     "src/resoiltwin/weather/cds.py",
     "                                     _sem_conversao),",
     "                                     _joule_por_dia_para_watt),",
     "(modulo)",
     "os milimetros por dia da ET0 passam por uma conversao de radiacao"),
]
