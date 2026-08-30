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
serie, 6 linhas onde havia 159 -- **continua a nao entrar nesta lista**. O que
mudou a 30/08 foi que ele deixou de ser invisivel; o que nao mudou foi que
nao ha maneira honesta de o julgar.

Ate a migracao 0011 nao havia sequer com que o comparar. As tres derivacoes de
um "esperado" que se consideraram na altura eram todas circulares ou
inventadas:

- `rows_written` contra os dias da janela declarada assume uma cadencia diaria
  que so a reanalise tem. O satelite escreve ao ritmo da revisita do Sentinel:
  21 linhas numa janela de 29 dias e um resultado perfeitamente normal, e uma
  regra dessas marcava-o;
- `rows_written` contra a janela *pedida* era impossivel desde que o job passou
  a declarar a janela que **cobriu** (68d09d7): os dois lados da comparacao
  passaram a vir da mesma execucao, e uma fronteira derivada da propria
  constante nao mede nada;
- "uma execucao posterior do mesmo pedido escreveu linhas, logo a anterior
  estava incompleta" e verdade, mas so dispara depois de alguem ja ter voltado
  a correr e ter obtido mais -- ou seja, depois de ja se saber. E o atraso de
  publicacao do AgERA5 fa-la disparar rotineiramente sem defeito nenhum.

A migracao 0011 fecha o buraco da segunda: o job passou a guardar **as duas**
janelas, a pedida e a coberta, e a comparacao voltou a ser possivel. Nao e um
"esperado" derivado -- e o que o chamador pediu, observado no momento em que a
execucao comecou.

**E mesmo assim nao vira alarme.** Nao por prudencia vaga: porque as duas
situacoes tem exactamente a mesma forma e so diferem em magnitude.

    defeito de 29/08     pediu 01/07-29/08  ·  cobriu 01/07-02/07   (58 dias fora)
    atraso do AgERA5     pediu 01/07-29/08  ·  cobriu 01/07-22/08   ( 7 dias fora)

Nos dois casos a cobertura comeca no dia pedido e acaba antes do fim. Nenhuma
regra que olhe so para a forma os separa, e toda a regra que olhe para a
magnitude tem de trazer um numero -- "abaixo de 80% avisa" -- que nada neste
projecto sustenta. Um numero inventado da confianca falsa e e pior do que
nenhum: um aviso que dispare com o atraso de publicacao do arquivo, ou com um
mes de Inverno sem aquisicao nenhuma, deixa de ser lido, que e a doenca que
isto veio curar.

**O que se faz em vez disso: mostrar o par, e deixar o limiar a quem le.** Cada
linha leva as duas janelas e `uncovered_days`, a contagem dos dias da janela
pedida que ficaram fora da coberta. "Pediu 60 dias e cobriu 2" nao precisa de
regra nenhuma para saltar a vista com os dois numeros lado a lado. Quem quiser
filtrar traz o SEU limiar em `?min_uncovered_days=`; o codigo nao tem nenhum, e
nao tem valor por omissao que julgue. E a mesma postura que
`eo/ingest.py::_observacao` ja tomou com `contributing_pixels`: poe-se na linha
a contagem real, e o criterio e de quem le a serie, nao de quem a grava.

**O que isto ainda nao ve, e vale a pena estar escrito.** O par
pedido/coberto estreita o buraco, nao o fecha. O que distinguiria mesmo os dois
casos acima nao e a janela: e que a 29/08 a origem ENTREGOU os 159 dias e nos
guardamos 6, enquanto no atraso do arquivo os dias nunca chegaram. Nenhuma das
duas colunas sabe isso, porque as duas descrevem o que ficou gravado. Fechar
esse buraco obriga o cliente a declarar o que recebeu -- e trabalho por fazer,
e nao uma regra que se possa inferir daqui.
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


# Os dias da janela PEDIDA que ficaram de fora da COBERTA: o que falta ao
# inicio mais o que falta ao fim. Nao e um veredicto -- e uma contagem, pela
# razao que esta no topo deste ficheiro.
#
# Duas coisas que este numero NAO diz, e que quem o ler tem de saber:
#
# - nao conta buracos DENTRO da cobertura. A janela coberta e o primeiro e o
#   ultimo dia que a execucao gravou; um dia sem linhas la pelo meio nao
#   aparece aqui. Contar esses obrigava a saber a cadencia esperada de cada
#   origem, que e precisamente a derivacao inventada que este ficheiro recusa;
# - da NULL, e nao zero, quando a janela pedida nao esta registada -- os 25
#   jobs anteriores a migracao 0011 e todas as corridas do IPMA, que nao
#   pedem janela nenhuma. Zero diria "cobriu tudo o que pediu", que e uma
#   afirmacao que nenhuma dessas linhas suporta.
#
# `date - date` da um inteiro de dias no PostgreSQL, e a aritmetica com NULL
# propaga NULL sozinha: nao ha aqui COALESCE nenhum de proposito.
DIAS_FORA_DA_COBERTURA = (
    IngestionJob.date_from - IngestionJob.requested_date_from
) + (IngestionJob.requested_date_to - IngestionJob.date_to)

UNCOVERED_DAYS = DIAS_FORA_DA_COBERTURA.label("uncovered_days")
