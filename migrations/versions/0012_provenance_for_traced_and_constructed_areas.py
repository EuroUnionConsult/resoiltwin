"""geometry provenance gains a word for traced and for constructed areas

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-01 18:40:00.000000

Escrita a mao, como as 0001-0011, e sem importar nada de `resoiltwin`: uma
migracao e um artefacto congelado e tem de correr no dia em que os modulos da
aplicacao mudarem de nome ou de sitio. O autogenerate do Alembic 1.13 tambem
nao veria isto -- nao compara CheckConstraints -- e na imagem PostGIS afogaria
o sinal em ruido das ~40 tabelas de tiger_geocoder e topology. A paridade com o
modelo e verificada por `tests/test_schema_parity.py`.

PORQUE. As duas AOI em producao declaravam `geometry_provenance = 'surveyed'`,
que neste vocabulario quer dizer levantado em campo com GNSS. Nenhuma das duas
foi ao terreno, e as proprias notas de origem gravadas ao lado dizem-no: uma e
uma caixa construida a volta de um ponto conhecido, a outra um contorno tracado
sobre mapa base a seguir os limites visiveis. O erro nao estava so nas duas
linhas -- estava no vocabulario, que nao tinha palavra nenhuma para o modo como
a maior parte das AOI deste mundo e feita. Escolher o menos errado dos quatro
valores antigos punha o mesmo defeito noutra palavra.

DOIS VALORES E NAO UM. `digitised_from_basemap` afirma que o poligono e o
limite de uma feicao que existe, tal como o mapa base a mostra -- verificavel
por quem reabrir o mapa. `constructed_extent` nao afirma limite nenhum: e um
recorte de analise escolhido, e a pergunta "que exactidao tem esta fronteira?"
nao lhe faz sentido porque nao ha fronteira no terreno com que a comparar. Uma
so entrada a cobrir os dois casos voltava a por uma palavra sobre duas
verdades, que e o defeito que esta migracao existe para fechar.

`surveyed` FICA no dominio. Continua a ser o valor certo no dia em que alguem
levar um receptor GNSS ao terreno; o que estava errado era a linha, nao a
palavra.

A GUARDA DE APROVACAO NAO MUDA. `ck_aoi_provisional_never_approved` continua a
nomear so `provisional_pending_kml`, e os dois valores novos podem ser
aprovados de proposito: o que aquela guarda recusa nao e geometria pouco
exacta, e geometria cuja POSICAO e inventada. Um contorno tracado esta onde se
ve que esta; uma caixa construida a volta de um ponto documentado e
reproduzivel ao metro. O raciocinio inteiro esta em `models/site.py`, ao lado
da constraint.

CONTAGEM. Nada aqui cria nem apaga linhas. A tabela `aois` tinha 2 linhas, a
`observations` 1121 e a `ingestion_jobs` 25 antes desta migracao, e tem o mesmo
depois. O UPDATE toca em duas linhas, nomeadas pelo codigo, e so as toca se
ainda disserem `surveyed` -- numa base onde alguem ja tenha corrigido a mao, ou
numa base vazia (a que a suite de testes constroi), nao escreve nada.

REVERSIVEL, mas com uma perda que se declara: o downgrade repoe `surveyed` nas
duas linhas porque o dominio antigo nao tem outra palavra que lhes sirva, ou
seja repoe a afirmacao falsa. E o proprio motivo de esta migracao existir. Se
entretanto houver outras linhas com os valores novos, o downgrade falha ao
recriar a constraint antiga -- falha alto, que e o que se quer: reduzir dez
areas tracadas a "levantadas em campo" em silencio seria pior do que nao
reverter.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DOMINIO = "ck_aoi_geometry_provenance_domain"

# congelados em 2026-09-01. A ordem e a mesma da declaracao do enum: o teste de
# paridade compara o que o PostgreSQL entendeu de cada lado, e a ordem da lista
# sobrevive a `pg_get_constraintdef`.
_DOMINIO_ANTIGO = (
    "geometry_provenance IN ('documented_exact', 'surveyed', 'derived_from_metrics',"
    " 'provisional_pending_kml')"
)
_DOMINIO_NOVO = (
    "geometry_provenance IN ('documented_exact', 'surveyed', 'digitised_from_basemap',"
    " 'constructed_extent', 'derived_from_metrics', 'provisional_pending_kml')"
)

# O codigo da AOI e um identificador de negocio, nao uma coordenada: nenhuma
# geometria entra nesta migracao. As geometrias vivem fora deste repositorio.
_CORRECCOES = {
    "EUC-TUR-EO1": "constructed_extent",
    "EUC-PTO-EO1": "digitised_from_basemap",
}


def _corrigir(de: str, para: dict[str, str]) -> None:
    """Troca a proveniencia das AOI nomeadas, e so se ela ainda for `de`.

    O `AND geometry_provenance = :de` nao e decoracao. Sem ele, esta migracao
    reescrevia por cima de qualquer valor que alguem tivesse posto entretanto
    nestas duas linhas -- incluindo o valor certo -- e uma escrita dessas nao
    deixa rasto nenhum de que aconteceu.
    """
    for codigo, valor in para.items():
        op.get_bind().execute(
            text(
                "UPDATE aois SET geometry_provenance = :valor"
                " WHERE code = :codigo AND geometry_provenance = :de"
            ),
            {"valor": valor, "codigo": codigo, "de": de},
        )


def upgrade() -> None:
    # a constraint primeiro: sem o dominio alargado o UPDATE seguinte era
    # recusado pela propria guarda que ele vem satisfazer.
    op.drop_constraint(_DOMINIO, "aois", type_="check")
    op.create_check_constraint(_DOMINIO, "aois", _DOMINIO_NOVO)
    _corrigir("surveyed", _CORRECCOES)


def downgrade() -> None:
    # as linhas primeiro, a constraint depois: recriar o dominio antigo com uma
    # linha ainda em `constructed_extent` seria recusado pelo proprio PostgreSQL.
    for codigo, valor_novo in _CORRECCOES.items():
        op.get_bind().execute(
            text(
                "UPDATE aois SET geometry_provenance = 'surveyed'"
                " WHERE code = :codigo AND geometry_provenance = :valor"
            ),
            {"codigo": codigo, "valor": valor_novo},
        )
    op.drop_constraint(_DOMINIO, "aois", type_="check")
    op.create_check_constraint(_DOMINIO, "aois", _DOMINIO_ANTIGO)
