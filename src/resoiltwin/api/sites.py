from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resoiltwin.db import get_session
from resoiltwin.enums import AoiStatus, GeometryProvenance
from resoiltwin.geo import area_m2, geojson_to_wkt_element, wkb_to_geojson
from resoiltwin.models import Aoi, Plot, Site
from resoiltwin.schemas.site import AoiApprove, AoiCreate, AoiRead, PlotCreate, PlotRead, SiteCreate, SiteRead

router = APIRouter(prefix="", tags=["sites"])


def _is_duplicate_of(exc: IntegrityError, unique_index: str) -> bool:
    """True apenas quando a violacao foi o indice unico do codigo.

    O except generico devolvia 409 "... already exists" para QUALQUER
    IntegrityError. Com os CHECK de dominio das migracoes 0004, um payload
    incoerente passaria a receber "AOI 'X' already exists" sobre uma AOI que
    nao existe -- e uma ingestao automatica que faca retry-on-409 nunca
    resolveria, porque nao ha duplicado nenhum. O duplo getattr com default
    None degrada para o raise generico se o driver nao expuser `diag`, em vez
    de rebentar com AttributeError.
    """
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == unique_index


def _get_site(session: Session, code: str) -> Site:
    site = session.scalar(select(Site).where(Site.code == code))
    if site is None:
        raise HTTPException(404, f"Site '{code}' not found")
    return site


def _aoi_read(aoi: Aoi) -> AoiRead:
    geometry = wkb_to_geojson(aoi.geometry)
    return AoiRead(
        id=aoi.id, code=aoi.code, purpose=aoi.purpose, geometry=geometry,
        geometry_provenance=aoi.geometry_provenance,
        geometry_source_note=aoi.geometry_source_note, status=aoi.status,
        approved_by=aoi.approved_by, approved_at=aoi.approved_at,
        area_m2=round(area_m2(geometry), 2),
    )


@router.post("/sites", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
def create_site(payload: SiteCreate, session: Session = Depends(get_session)):
    site = Site(**payload.model_dump())
    session.add(site)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_duplicate_of(exc, "ix_sites_code"):
            raise HTTPException(409, f"Site '{payload.code}' already exists")
        raise
    session.refresh(site)
    return site


@router.get("/sites", response_model=list[SiteRead])
def list_sites(session: Session = Depends(get_session)):
    return session.scalars(select(Site).order_by(Site.code)).all()


@router.get("/sites/{code}", response_model=SiteRead)
def read_site(code: str, session: Session = Depends(get_session)):
    return _get_site(session, code)


@router.post("/sites/{code}/aois", response_model=AoiRead, status_code=status.HTTP_201_CREATED)
def create_aoi(code: str, payload: AoiCreate, session: Session = Depends(get_session)):
    site = _get_site(session, code)
    aoi = Aoi(
        site_id=site.id, code=payload.code, purpose=payload.purpose,
        geometry=geojson_to_wkt_element(payload.geometry),
        geometry_provenance=payload.geometry_provenance,
        geometry_source_note=payload.geometry_source_note,
    )
    session.add(aoi)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_duplicate_of(exc, "ix_aois_code"):
            raise HTTPException(409, f"AOI '{payload.code}' already exists")
        raise
    session.refresh(aoi)
    return _aoi_read(aoi)


@router.get("/sites/{code}/aois", response_model=list[AoiRead])
def list_aois(code: str, session: Session = Depends(get_session)):
    site = _get_site(session, code)
    aois = session.scalars(select(Aoi).where(Aoi.site_id == site.id).order_by(Aoi.code)).all()
    return [_aoi_read(a) for a in aois]


@router.post("/aois/{code}/approve", response_model=AoiRead)
def approve_aoi(code: str, payload: AoiApprove, session: Session = Depends(get_session)):
    aoi = session.scalar(select(Aoi).where(Aoi.code == code))
    if aoi is None:
        raise HTTPException(404, f"AOI '{code}' not found")
    if aoi.geometry_provenance == GeometryProvenance.provisional_pending_kml:
        raise HTTPException(
            409,
            "AOI has provisional geometry and cannot be approved. Confirm the boundary "
            "and update its provenance before approving.",
        )
    aoi.status = AoiStatus.approved
    aoi.approved_by = payload.approved_by
    aoi.approved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(aoi)
    return _aoi_read(aoi)


@router.post("/sites/{code}/plots", response_model=PlotRead, status_code=status.HTTP_201_CREATED)
def create_plot(code: str, payload: PlotCreate, session: Session = Depends(get_session)):
    site = _get_site(session, code)
    plot = Plot(site_id=site.id, **payload.model_dump())
    session.add(plot)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_duplicate_of(exc, "ix_plots_code"):
            raise HTTPException(409, f"Plot '{payload.code}' already exists")
        raise
    session.refresh(plot)
    return plot


@router.get("/sites/{code}/plots", response_model=list[PlotRead])
def list_plots(code: str, session: Session = Depends(get_session)):
    site = _get_site(session, code)
    return session.scalars(select(Plot).where(Plot.site_id == site.id).order_by(Plot.code)).all()
