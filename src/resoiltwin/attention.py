"""O que, numa tabela de execucoes, precisa de um humano a olhar.

**Porque e que isto existe.** A camada meteorologica inteira esta desenhada em
volta de "a falha e visivel": um valor absurdo do IPMA derruba o job de
proposito em vez de ser descartado em silencio, a mudanca de estacao debaixo da
mesma identidade derruba o job, a guarda de fuso derruba o job, a variavel
errada no ficheiro derruba o job. Todas essas decisoes foram tomadas com o
argumento de que falhar alto e melhor do que perder em silencio. Sem ninguem a
ler `ingestion_jobs.status`, "falhar alto" e tao silencioso como o `succeeded`
enganador que substituiu -- a diferenca e so que fica gravado.

Isto e a peca que faltava para o argumento se aguentar: a definicao, num sitio
so, do que conta como "precisa de atencao", legivel pela rota `GET /jobs`.

**O que conta, e porque cada um conta.**

- `failed` -- a execucao declarou que correu mal. E o caso facil, e a restricao
  `ck_failed_job_needs_an_error` garante que traz o erro com ela;
- `never_finished` -- ficou em `pending` ou `running` sem `finished_at`. E o
  unico estado que o desenho de "falhar alto" NAO consegue gravar: um processo
  abatido a meio nao chega a escrever `failed`, e a linha fica para sempre a
  dizer que esta a correr, com `error: null`. Hoje a ingestao e sincrona,
  portanto uma linha destas lida depois do facto e sempre um processo que
  morreu -- com a ressalva de que um pedido em voo neste preciso momento tem o
  mesmo aspecto. Nao ha aqui limite de tempo nenhum, de proposito: qualquer
  numero de minutos seria inventado, e quem le tem o `started_at` a frente;
- `succeeded_without_writing` -- disse que correu bem e nao escreveu linha
  nenhuma, **e nenhuma outra execucao do mesmo pedido escreveu tambem**. Esta
  segunda metade nao e um afinamento: sem ela, a lista enchia-se de repeticoes
  legitimas. Uma segunda execucao do mesmo pedido escreve zero porque a
  desduplicacao ja tem as linhas -- e correcto e nao interessa a ninguem. O
  `request_hash` existe exactamente para "reconhecer duas execucoes do mesmo
  pedido sem repetir o pedido em si", e e essa a distincao que se usa aqui.
  Nos 15 jobs da base a 30/08/2026, as tres execucoes com zero linhas sao todas
  repeticoes de pedidos que ja tinham escrito: sem esta metade, tres quintos da
  lista eram ruido, e uma lista que grita por nada deixa de ser lida -- que e a
  doenca que isto veio curar.

**O que NAO conta, e porque nao.**

O caso de 29/08 -- dois jobs `succeeded` que esconderam a perda de 96% da
serie, 6 linhas onde havia 159 -- **nao aparece nesta lista, e nao ha maneira
honesta de o fazer aparecer**. Nao ha "esperado" gravado em lado nenhum, e
todas as formas de o derivar sao circulares ou inventadas:

- `rows_written` contra os dias da janela declarada assume uma cadencia diaria
  que so a reanalise tem. O satelite escreve ao ritmo da revisita do Sentinel:
  21 linhas numa janela de 29 dias e um resultado perfeitamente normal, e uma
  regra dessas marcava-o;
- `rows_written` contra a janela *pedida* deixou de ser possivel desde que o
  job passou a declarar a janela que **cobriu**: os dois lados da comparacao
  passaram a vir da mesma execucao, e uma fronteira derivada da propria
  constante nao mede nada;
- "uma execucao posterior do mesmo pedido escreveu linhas, logo a anterior
  estava incompleta" e verdade, mas so dispara depois de alguem ja ter voltado
  a correr e ter obtido mais -- ou seja, depois de ja se saber. E o atraso de
  publicacao do AgERA5 fa-la disparar rotineiramente sem defeito nenhum.

Uma heuristica inventada seria pior do que nada: daria confianca falsa. O que
se ganha aqui e mais modesto e verdadeiro -- os estados que **estao** gravados
passam a ter quem os leia.
"""

from enum import StrEnum

from sqlalchemy import and_, case, exists, select
from sqlalchemy.orm import aliased

from resoiltwin.enums import JobStatus
from resoiltwin.models import IngestionJob


class AttentionReason(StrEnum):
    """Porque e que este job esta na lista. Nunca "porque sim"."""

    failed = "failed"                                        # declarou que correu mal
    never_finished = "never_finished"                        # ficou a correr e nunca acabou
    succeeded_without_writing = "succeeded_without_writing"  # disse que sim e nao escreveu nada


# outra execucao do MESMO pedido que tenha escrito alguma coisa. Correlacionada
# com a linha de fora: e o que separa uma repeticao legitima (a desduplicacao
# ja tem as linhas, logo esta escreve zero) de um pedido que nunca produziu
# nada. Nao se exige que seja anterior: a pergunta que a lista responde e o que
# precisa de atencao AGORA, e um pedido que entretanto produziu linhas ja nao
# precisa, tenha isso acontecido antes ou depois.
#
# `_OUTRA.id != IngestionJob.id` e, hoje, redundante: este `exists` so se
# avalia sobre linhas com `rows_written = 0`, e procura linhas com
# `rows_written > 0`, portanto a propria nunca se encontraria a si mesma. Fica
# na mesma, e a razao nao e defensiva no vago -- e para que as duas condicoes
# nao fiquem caladamente presas uma a outra. Sem ela, relaxar o
# `rows_written = 0` la em baixo fazia cada linha passar a satisfazer o seu
# proprio `exists`, e a regra deixava de marcar seja o que for sem que nada no
# codigo mudasse de aspecto. Uma delas tem de ser redundante; esta e a que se
# le como o que quer dizer ("outra execucao").
_OUTRA = aliased(IngestionJob)
_OUTRA_EXECUCAO_DO_MESMO_PEDIDO_ESCREVEU = exists(
    select(1).where(
        _OUTRA.request_hash == IngestionJob.request_hash,
        _OUTRA.id != IngestionJob.id,
        _OUTRA.rows_written > 0,
    )
)

# a ordem dos ramos e a ordem de leitura: um job `failed` que tambem nunca
# tenha registado o fim continua a ser, antes de tudo, um job que falhou.
ATTENTION_REASON = case(
    (IngestionJob.status == JobStatus.failed, AttentionReason.failed.value),
    (
        and_(
            IngestionJob.status.in_((JobStatus.pending, JobStatus.running)),
            IngestionJob.finished_at.is_(None),
        ),
        AttentionReason.never_finished.value,
    ),
    (
        and_(
            IngestionJob.status == JobStatus.succeeded,
            IngestionJob.rows_written == 0,
            ~_OUTRA_EXECUCAO_DO_MESMO_PEDIDO_ESCREVEU,
        ),
        AttentionReason.succeeded_without_writing.value,
    ),
    else_=None,
).label("attention")
