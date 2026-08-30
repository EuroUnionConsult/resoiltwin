"""satellite rows stop asserting a quality nobody checked, and the pixel count stops lying

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-30 18:00:00.000000

Escrita a mao, como as 0001-0009, e sem importar nada de `resoiltwin`: uma
migracao e um artefacto congelado e tem de correr no dia em que os modulos da
aplicacao mudarem de nome ou de sitio.

PORQUE. Duas afirmacoes falsas nas 108 linhas de satelite ja gravadas, e o
codigo sozinho nao chega a nenhuma delas: uma re-execucao sobre uma janela ja
sincronizada encontra as identidades presentes, escreve zero linhas e responde
`succeeded`. Sem esta migracao, corrigir o codigo deixava as linhas como
estao -- para sempre.

1. `quality_flag = 'valid'` era um LITERAL em `eo/ingest.py`, sem uma unica
   condicao por tras. Todas as linhas de satelite eram `valid` por construcao,
   incluindo a de 24/08/2026 sobre Campo Real, que e a media do NDVI sobre
   8,47% da parcela -- 57 432 dos 62 750 pixeis excluidos pela mascara SCL --
   e que `docs/evidence/2026-08-29-mascara-scl.md` ja tinha declarado
   explicavel mas NAO mensuravel. Um `WHERE quality_flag = 'valid'`, que e o
   filtro obvio, devolvia-a ao lado das aquisicoes de ceu limpo.

   Passa a `unchecked`, que e a unica coisa verdadeira: nada nesta ingestao
   verifica a qualidade de um indice espectral. Nao se inventa limiar nenhum
   -- ver o comentario em `eo/ingest.py::_observacao` para as duas fronteiras
   que foram consideradas e porque nenhuma serve.

2. A chave `valid_pixels` do `evidence` guarda `min(sampleCount)`, que conta
   os pixeis AMOSTRADOS e nao os validos: dizia 62 750 na linha de 24/08
   quando os que contribuiram foram 5 318, e era identica com e sem mascara
   nas 18 aquisicoes. Passa a chamar-se `sampled_pixels`, que e o que sempre
   guardou. O NUMERO nao muda -- a renomeacao e sem perda, e e por isso que se
   aplica tambem as linhas antigas em vez de deixar 108 linhas com um rotulo
   falso a conviver com as novas debaixo da mesma chave.

   `contributing_pixels` NAO e escrita aqui. Nas linhas novas e
   `min(sampleCount - noDataCount)` por indice; das linhas antigas so sobra
   `min(sampleCount)` e `max(noDataCount)`, cuja diferenca e um MAJORANTE do
   erro e nao a contagem. Inventar aqui um numero exacto era repetir o defeito
   que esta migracao fecha. A ausencia da chave e o que distingue as linhas
   antigas: quem as ler sabe que tem de fazer a subtraccao e que o resultado e
   um limite, nao a contagem.

CONTAGEM. Nada aqui apaga nem cria linhas: sao dois UPDATE sobre colunas de
linhas existentes. A tabela tinha 1121 observacoes antes desta migracao, 108
delas `satellite_observed`.

REVERSIVEL sem adivinhar. O `downgrade` repoe `valid` em TODAS as linhas de
satelite, e nao apenas nas que esta migracao mexeu, porque antes dela nao
havia nenhuma outra: o valor era um literal no codigo. A renomeacao da chave
faz-se ao contrario pelo mesmo caminho, e a `contributing_pixels` das linhas
escritas depois desta migracao e retirada -- deixa-la seria devolver a base a
um estado que nunca existiu.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# jsonb_exists(...) e nao o operador `?`: o `?` e o marcador de parametro do
# driver e um SQL literal com ele nao chega inteiro ao PostgreSQL.
_RENOMEAR = """
UPDATE observations
   SET evidence = (evidence - '{antiga}')
                  || jsonb_build_object('{nova}', evidence -> '{antiga}')
 WHERE source_type = 'satellite_observed'
   AND evidence IS NOT NULL
   AND jsonb_exists(evidence, '{antiga}')
"""

_MARCAR = """
UPDATE observations
   SET quality_flag = '{para}'
 WHERE source_type = 'satellite_observed'
   AND quality_flag = '{de}'
"""


def upgrade() -> None:
    op.execute(_RENOMEAR.format(antiga="valid_pixels", nova="sampled_pixels"))
    op.execute(_MARCAR.format(de="valid", para="unchecked"))


_APAGAR_CHAVE = """
UPDATE observations
   SET evidence = evidence - '{chave}'
 WHERE source_type = 'satellite_observed'
   AND evidence IS NOT NULL
   AND jsonb_exists(evidence, '{chave}')
"""


def downgrade() -> None:
    op.execute(_MARCAR.format(de="unchecked", para="valid"))
    op.execute(_APAGAR_CHAVE.format(chave="contributing_pixels"))
    op.execute(_RENOMEAR.format(antiga="sampled_pixels", nova="valid_pixels"))
