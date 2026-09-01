"""Ronda de 01/09/2026 -- proveniencia das AOI.

Mede duas coisas, e so estas duas:

1. **O dominio.** Os valores `digitised_from_basemap` e `constructed_extent`
   entraram no vocabulario a 01/09/2026 porque nenhum dos quatro anteriores
   descrevia como as duas AOI reais foram feitas. Se um deles desaparecer, algum
   teste tem de cair -- caso contrario o valor novo esta no codigo sem ninguem o
   defender, que e a mesma situacao de antes com outra palavra.

2. **A guarda de aprovacao.** `ck_aoi_provisional_never_approved` continua a
   nomear um so valor, de proposito: recusa geometria cuja POSICAO e inventada,
   nao geometria pouco exacta. Se deixar de distinguir -- na base ou na rota --
   tem de cair o teste que afirma sobre ela.

O mutante `upd` mede uma terceira coisa que so foi defendida DEPOIS de esta
ronda a apanhar: ver a nota no fim deste ficheiro.
"""

MUTANTES = [
    (
        "dom-t",
        "src/resoiltwin/enums.py",
        '    digitised_from_basemap = "digitised_from_basemap"    '
        "# tracado sobre mapa base, a seguir limites visiveis",
        None,
        "GeometryProvenance",
        "o dominio perde a palavra para um contorno tracado sobre mapa base",
    ),
    (
        "dom-c",
        "src/resoiltwin/enums.py",
        '    constructed_extent = "constructed_extent"            '
        "# recorte construido; nao e limite de nada no terreno",
        None,
        "GeometryProvenance",
        "o dominio perde a palavra para um recorte construido a volta de um ponto",
    ),
    (
        "apr-bd",
        "migrations/versions/0001_sites_and_plots.py",
        "            \"NOT (status = 'approved' AND geometry_provenance ="
        " 'provisional_pending_kml')\",",
        '            "1 = 1",',
        "upgrade",
        "a guarda de aprovacao na BASE deixa de distinguir o que nao pode ser aprovado",
    ),
    (
        "apr-api",
        "src/resoiltwin/api/sites.py",
        "    if aoi.geometry_provenance == GeometryProvenance.provisional_pending_kml:",
        "    if False:",
        "approve_aoi",
        "a guarda de aprovacao na ROTA deixa de distinguir o que nao pode ser aprovado",
    ),
    (
        "upd",
        "migrations/versions/0012_provenance_for_traced_and_constructed_areas.py",
        '                " WHERE code = :codigo AND geometry_provenance = :de"',
        '                " WHERE code = :codigo"',
        "_corrigir",
        "a correccao das duas linhas escreve por cima de qualquer valor, nao so de surveyed",
    ),
]

# SOBRE O `upd`. Na primeira passagem desta ronda SOBREVIVEU, com zero testes
# apanhados, e a razao era estrutural e nao um esquecimento pontual: a base que
# a suite constroi nasce vazia, portanto a migracao 0012 corria sobre zero
# linhas de `aois` e o seu UPDATE nao tocava em nada, com guarda ou sem ela.
# Nenhum teste podia distinguir as duas versoes. O comportamento tinha sido
# ensaiado a mao numa base descartavel -- e um ensaio nao e um teste.
#
# `tests/test_migracao_0012_proveniencia.py` fechou o buraco: constroi uma base
# propria, para-a na 0011, poe-lhe linhas dentro e so entao a leva a 0012. Na
# segunda passagem o mutante morre, e morre pelo teste da sua propria guarda.
