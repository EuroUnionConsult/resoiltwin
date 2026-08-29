"""Rotas HTTP da sincronizacao Copernicus.

sync_aoi() nao propaga falhas de execucao -- devolve o job com status
'failed' e o erro gravado. So a guarda da AOI nao aprovada levanta
ValueError. E por isso que esta rota le o `status` do job em vez de assumir
que correu: um pedido aceite e processado, mesmo que o resultado seja mau,
continua a ser 202 -- o cliente le o status para saber o que aconteceu.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from resoiltwin.config import Settings, get_settings
from resoiltwin.db import get_session
from resoiltwin.eo.cdse import CDSEClient
from resoiltwin.eo.ingest import sync_aoi
from resoiltwin.models import Aoi, IngestionJob, Site
from resoiltwin.schemas.eo import EoSyncRequest
from resoiltwin.schemas.job import IngestionJobRead

router = APIRouter(tags=["eo"])


def get_cdse_client(settings: Settings = Depends(get_settings)) -> CDSEClient:
    """Constroi o cliente CDSE a partir das settings.

    Se faltar client_id ou client_secret, recusa aqui com uma mensagem que
    diz exactamente o que falta -- este projecto ja perdeu tempo com
    credenciais ambiguas, e um 500 opaco repetia o problema. 503 porque o
    pedido em si esta bem formado: e o servico que nao esta pronto para o
    atender.
    """
    em_falta = [
        nome
        for nome, valor in (
            ("cdse_client_id", settings.cdse_client_id),
            ("cdse_client_secret", settings.cdse_client_secret),
        )
        if not valor
    ]
    if em_falta:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CDSE credentials not configured: missing "
            f"{', '.join(em_falta)}. Set them via environment variables or .env before syncing.",
        )
    return CDSEClient(settings.cdse_client_id, settings.cdse_client_secret)


def _get_site(session: Session, code: str) -> Site:
    site = session.scalar(select(Site).where(Site.code == code))
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Site '{code}' not found")
    return site


def _get_aoi_for_site(session: Session, site: Site, aoi_code: str) -> Aoi:
    """AOI tem de existir E pertencer a este site.

    O codigo da AOI e unico globalmente na tabela, mas cada AOI pertence
    sempre a um unico site. Uma AOI que existe, so que noutro site, tem de
    parecer inexistente aqui: nada nesta rota deve confirmar a um cliente que
    um codigo existe algures fora do site que ele pediu.
    """
    aoi = session.scalar(select(Aoi).where(Aoi.code == aoi_code))
    if aoi is None or aoi.site_id != site.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"AOI '{aoi_code}' not found for site '{site.code}'",
        )
    return aoi


@router.post(
    "/sites/{code}/eo/sync",
    response_model=IngestionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_eo(
    code: str,
    payload: EoSyncRequest,
    session: Session = Depends(get_session),
    client: CDSEClient = Depends(get_cdse_client),
):
    site = _get_site(session, code)
    _get_aoi_for_site(session, site, payload.aoi_code)
    try:
        job = sync_aoi(
            session, client, payload.aoi_code, payload.date_from, payload.date_to,
            com_mascara_scl=payload.scl_mask,
        )
    except ValueError as exc:
        # a esta altura ja confirmamos que a AOI existe e pertence ao site;
        # a unica coisa que sync_aoi ainda pode recusar e o estado de
        # aprovacao. 409 porque o pedido esta bem formado mas o estado do
        # recurso impede-o -- nao e um erro do cliente (422) nem um recurso
        # em falta (404).
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return job


@router.get("/jobs/{job_id}", response_model=IngestionJobRead)
def read_job(job_id: uuid.UUID, session: Session = Depends(get_session)):
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job '{job_id}' not found")
    return job
