"""Rotas HTTP da sincronizacao meteorologica.

Uma porta, duas fontes. `POST /sites/{code}/weather/sync` com
`source: "reanalysis"` corre a reanalise AgERA5 do Climate Data Store; com
`source: "ipma"` corre as ultimas 24 horas da estacao do IPMA mais proxima do
sitio. As duas escrevem na mesma tabela de observacoes e deixam o mesmo tipo
de rasto -- uma linha em `ingestion_jobs` -- que continua a ser lido pelo
`GET /api/v1/jobs/{id}` que a Fase B ja criou. Esta rota nao duplica essa
leitura.

**Duas recusas diferentes, e nao se podem confundir.**

O que se sabe ANTES de a execucao comecar sobe como excepcao dos
sincronizadores e sai como erro HTTP: o sitio nao existe (404), o sitio nao
tem exactamente uma AOI aprovada (409). Nao ha job nenhum na base, porque nao
houve execucao nenhuma.

O que corre mal DEPOIS de o job existir nao sobe: fica gravado no job com
`status = failed` e o erro, e a rota devolve 202 com esse job no corpo. E
deliberado, e e por isso que o `status` esta no corpo da resposta e nao so no
codigo HTTP: um pedido aceite e processado continua a ser 202 mesmo quando o
resultado e mau, e quem chama tem de olhar para o `status`. Este projecto ja
pagou por essa distincao -- o `restore_dev_data.py` teve de passar a ler o
`status` de cada job porque um 202 nao e sucesso.

Nao ha aqui `except IntegrityError` a distinguir UNIQUE de CHECK como em
`api/observations.py`, e a ausencia e uma decisao, nao um esquecimento: esta
rota nao escreve nada por sua mao. Toda a escrita acontece dentro de
`sync_reanalysis`/`sync_ipma`, debaixo de um `except Exception` que ja faz
rollback e marca o job como falhado -- uma violacao de restricao chega ao
cliente como um job `failed` com o nome da restricao no `error`, que e o que o
teste `test_a_row_the_database_refuses_becomes_a_failed_job` fixa. Um bloco
`except IntegrityError` aqui nunca correria, e um caminho de excepcao que
nunca corre e uma afirmacao por verificar disfarcada de cuidado.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from resoiltwin.config import Settings, get_settings
from resoiltwin.api.auth import EXIGE_CHAVE_DE_ESCRITA
from resoiltwin.db import get_session
from resoiltwin.models import Site
from resoiltwin.schemas.job import IngestionJobRead
from resoiltwin.schemas.weather import WeatherSource, WeatherSyncRequest
from resoiltwin.weather.cds import CDSClient
from resoiltwin.weather.ingest import sync_ipma, sync_reanalysis
from resoiltwin.weather.ipma import IPMAClient

router = APIRouter(tags=["weather"])


def _fabrica_de_cliente(construir):
    """Gestor de contexto que adia a construcao do cliente para quem o pedir.

    As dependencias do FastAPI resolvem-se TODAS antes do corpo da rota, e esta
    rota serve duas fontes: com as dependencias a construir os clientes, um
    pedido `source: "ipma"` construia na mesma um `CDSClient` -- e vice-versa --
    que nunca chegava a servir para nada. Nao custa rede (o `httpx.Client` so
    liga no primeiro pedido) mas e trabalho por pedido que nao serve ninguem,
    e um `close()` a fechar uma ligacao que nunca existiu.

    O que a dependencia cede e por isso uma FABRICA: quem precisar do cliente
    chama-a, e so ai ele nasce. A fabrica memoriza, portanto duas chamadas no
    mesmo pedido dao o mesmo cliente; e o que for construido e fechado aqui, no
    fim do pedido, que e a razao de isto ser um gerador e nao um `return`.
    """
    construidos = []

    def fabrica():
        if not construidos:
            construidos.append(construir())
        return construidos[0]

    try:
        yield fabrica
    finally:
        for cliente in construidos:
            if cliente is not None:
                cliente.close()


def get_cds_client(settings: Settings = Depends(get_settings)):
    """Fabrica do cliente do Climate Data Store. Devolve None se faltarem credenciais.

    A fabrica devolve None em vez de recusar, ao contrario do `get_cdse_client`
    do satelite: recusar aqui fazia um `source: "ipma"` -- que nao toca no CDS
    e nao precisa de credencial nenhuma -- responder 503 por falta de uma
    credencial que nao ia usar. A recusa continua a existir, so que no ramo que
    precisa dela.
    """
    def construir():
        if not settings.cds_api_url or not settings.cds_api_key:
            return None
        return CDSClient(settings.cds_api_url, settings.cds_api_key)

    yield from _fabrica_de_cliente(construir)


def get_ipma_client():
    """Fabrica do cliente do open-data do IPMA. Sem credencial: os ficheiros sao publicos.

    Um cliente por pedido HTTP deixado ao colector de lixo era o defeito que a
    Task 4 ja fechou dentro do cliente; nao o fechar aqui seria desfaze-lo.
    """
    yield from _fabrica_de_cliente(IPMAClient)


def _garantir_que_o_sitio_existe(session: Session, code: str) -> None:
    """404 para um sitio que nao existe, antes de qualquer trabalho.

    Os sincronizadores ja recusam um sitio desconhecido -- tem de recusar, sao
    chamados tambem de fora do HTTP -- mas recusam com ValueError, que aqui e
    indistinguivel da recusa por falta de AOI aprovada. As duas nao sao a mesma
    coisa para quem chama: um sitio que nao existe e 404 e um sitio que existe
    mas nao esta em condicoes e 409. Ler a mensagem da excepcao para as separar
    era pendurar o codigo HTTP num texto em portugues.
    """
    if session.scalar(select(Site).where(Site.code == code)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Site '{code}' not found")


@router.post(
    "/sites/{code}/weather/sync",
    response_model=IngestionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=EXIGE_CHAVE_DE_ESCRITA,
)
def sync_weather(
    code: str,
    payload: WeatherSyncRequest,
    session: Session = Depends(get_session),
    # fabricas, e nao clientes: so nasce o cliente da fonte que este pedido
    # escolheu. Ver `_fabrica_de_cliente`.
    construir_cds: Callable[[], CDSClient | None] = Depends(get_cds_client),
    construir_ipma: Callable[[], IPMAClient] = Depends(get_ipma_client),
):
    _garantir_que_o_sitio_existe(session, code)
    try:
        if payload.source is WeatherSource.reanalysis:
            cds = construir_cds()
            if cds is None:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "CDS credentials not configured: set cds_api_url and cds_api_key via "
                    "environment variables or .env before syncing reanalysis. The 'ipma' "
                    "source does not need them.",
                )
            job = sync_reanalysis(session, cds, code, payload.date_from, payload.date_to)
        else:
            # sem janela, de proposito: `sync_ipma` nao a aceita porque a
            # origem nao a tem. O corpo do pedido tambem nao a deixa passar --
            # `WeatherSyncRequest` recusa-a com 422 em vez de a ignorar aqui em
            # silencio, que era prometer um arquivo que nao existe.
            job = sync_ipma(session, construir_ipma(), code)
    except ValueError as exc:
        # a esta altura o sitio ja existe: o que os sincronizadores ainda podem
        # recusar antes de haver job e o estado das AOI -- nenhuma aprovada,
        # mais do que uma, ou uma sem geometria. 409 porque o pedido esta bem
        # formado e e o estado do recurso que o impede; nao e um erro do
        # cliente (422) nem um recurso em falta (404).
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return job
