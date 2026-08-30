"""Ronda sobre a guarda que exige que a variavel lida seja a que foi pedida.

A divida numero 2 da Fase C. O leitor do NetCDF ficava com a PRIMEIRA variavel
tridimensional do ficheiro, e o `variable` que vai para o `evidence` vem do
PEDIDO -- portanto uma divergencia entre o que se pediu e o que o ficheiro
trazia gravava um valor de uma grandeza sob o nome de outra, ja convertido
pela formula da grandeza errada, com proveniencia completa e ar de correcto.

Cada mutante afirma uma coisa falsa sobre esta guarda. Se sobreviver, ha um
pedaco da guarda que nenhum teste esta a defender.
"""

MUTANTES = [
    ("v1",
     "src/resoiltwin/weather/cds.py",
     "        if nome_variavel not in ds.variables:",
     "        if False:",
     "_ler_netcdf_solto",
     "um ficheiro que nao traz a variavel pedida e lido na mesma"),

    ("v2",
     "src/resoiltwin/weather/cds.py",
     "        var = ds.variables[nome_variavel]",
     "        var = ds.variables[tridimensionais[0]]",
     "_ler_netcdf_solto",
     "a variavel lida volta a ser a primeira que aparecer, e nao a pedida"),

    ("v3",
     "src/resoiltwin/weather/cds.py",
     "        if var.ndim != 3:",
     "        if False:",
     "_ler_netcdf_solto",
     "uma variavel com o nome certo e outra forma passa por serie diaria"),

    ("v4",
     "src/resoiltwin/weather/cds.py",
     "                        ficheiro, lat_sitio, lon_sitio, nome_no_ficheiro)",
     "                        ficheiro, lat_sitio, lon_sitio, variavel)",
     "agera5_diario",
     "o nome esperado dentro do ficheiro e o nome com que se pede ao CDS"),

    ("v5",
     "src/resoiltwin/weather/cds.py",
     '    "2m_temperature": ("24_hour_mean", "Temperature_Air_2m_Mean_24h",',
     '    "2m_temperature": ("24_hour_mean", "Precipitation_Flux",',
     "(modulo)",
     "a temperatura procura-se no ficheiro pelo nome da precipitacao"),
]
