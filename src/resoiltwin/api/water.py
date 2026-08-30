"""Rota HTTP do balanco hidrico.

`POST /sites/{code}/water/sync` corre o balanco de reservatorio unico sobre as
series que ja estao na base e grava uma terceira serie ao lado delas, com
`source_type = simulated`. Deixa o mesmo rasto das outras duas ingestoes -- uma
linha em `ingestion_jobs` -- que continua a ser lida pelo `GET /api/v1/jobs/{id}`
da Fase B. Esta rota nao duplica essa leitura.

**Nao ha cliente nenhum, e a ausencia e o ponto.** As rotas de meteorologia e de
satelite recebem por dependencia um cliente HTTP e recusam com 503 quando falta
a credencial dele; esta nao tem 503 nenhum porque nao ha origem externa a
contactar. As duas series de entrada -- precipitacao e evapotranspiracao de
referencia -- ja estao gravadas, e o que corre aqui e uma funcao pura sobre
elas. Uma dependencia de credencial neste modulo seria uma recusa por uma coisa
que este caminho nunca usa.

**Duas recusas diferentes, e nao se podem confundir** -- a mesma disciplina de
`api/weather.py`:

O que se sabe ANTES de a execucao comecar sai como erro HTTP e nao deixa job
nenhum na base, porque nao houve execucao nenhuma. Sao tres, e cada uma tem o
seu codigo: o corpo do pedido nao se aguenta -- janela invertida, ou uma
capacidade que nao descreve um reservatorio -- e 422, decidido em
`schemas/water.py` sem tocar na base; o sitio nao existe e 404; o sitio existe
mas nao tem exactamente uma AOI aprovada e 409.

O que corre mal DEPOIS de o job existir nao sobe: fica gravado no job com
`status = failed` e o erro, e a rota devolve **202 com esse job no corpo**. E
deliberado, e e por isso que o `status` esta no corpo e nao so no codigo HTTP:
um pedido aceite e processado continua a ser 202 mesmo quando o resultado e
mau, e quem chama tem de olhar para o `status`. Este projecto ja pagou por essa
distincao -- o `restore_dev_data.py` teve de passar a ler o `status` de cada job
porque um 202 nao e sucesso.

Aqui essa segunda familia e maior do que na meteorologia, e vale a pena
nomea-la: uma serie de entrada sem uma unica linha na janela, as duas series
sem um dia em comum, mais do que uma versao de processamento na mesma
proveniencia, uma entrada numa unidade que nao e o milimetro, uma serie horaria
onde o balanco precisa de totais diarios, ou uma janela ja escrita a partir de
outra proveniencia. **Nenhuma delas escreve zero linhas a dizer `succeeded`** --
todas derrubam o job com o motivo por extenso. Um cliente que receba 202 e
assuma sucesso perde exactamente isso.

Como em `api/weather.py`, nao ha aqui `except IntegrityError`: esta rota nao
escreve nada por sua mao. Toda a escrita acontece dentro de
`sync_water_balance`, debaixo de um `except Exception` que ja faz rollback e
marca o job como falhado -- uma violacao de restricao chega ao cliente como um
job `failed` com o nome da restricao no `error`. Um bloco `except IntegrityError`
aqui nunca correria, e um caminho de excepcao que nunca corre e uma afirmacao
por verificar disfarcada de cuidado.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from resoiltwin.api.weather import _garantir_que_o_sitio_existe
from resoiltwin.db import get_session
from resoiltwin.schemas.job import IngestionJobRead
from resoiltwin.schemas.water import WaterSyncRequest
from resoiltwin.water.ingest import sync_water_balance

router = APIRouter(tags=["water"])


@router.post(
    "/sites/{code}/water/sync",
    response_model=IngestionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_water(
    code: str,
    payload: WaterSyncRequest,
    session: Session = Depends(get_session),
):
    # a guarda do 404 e IMPORTADA de `api/weather.py`, e nao copiada, pela
    # mesma razao por que `water/ingest.py` importa as pecas de
    # `weather/ingest.py`: duas copias da mesma pergunta divergem no dia em que
    # uma for corrigida. `sync_water_balance` tambem recusa um sitio
    # desconhecido -- tem de recusar, e chamado tambem de fora do HTTP -- mas
    # recusa com ValueError, indistinguivel aqui da recusa por falta de AOI
    # aprovada sem ler a mensagem da excepcao, que era pendurar o codigo HTTP
    # num texto em portugues.
    _garantir_que_o_sitio_existe(session, code)
    try:
        job = sync_water_balance(
            session, code, payload.date_from, payload.date_to,
            payload.available_water_capacity_mm,
        )
    except ValueError as exc:
        # a esta altura o sitio ja existe e o corpo do pedido ja passou pelo
        # validador, portanto a janela nao esta invertida e a capacidade e um
        # reservatorio. O que sobra e o estado das AOI: nenhuma aprovada, mais
        # do que uma, ou uma sem geometria. 409 porque o pedido esta bem
        # formado e e o estado do recurso que o impede; nao e um erro do
        # cliente (422) nem um recurso em falta (404).
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return job
