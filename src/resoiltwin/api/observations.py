from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resoiltwin.api.auth import EXIGE_CHAVE_DE_ESCRITA
from resoiltwin.db import get_session
from resoiltwin.models import Instrument, Observation, ObservationPoint, Plot, Site
from resoiltwin.schemas.observation import ObservationCreate, ObservationRead

router = APIRouter(tags=["observations"])


def _resolve(session: Session, payload: ObservationCreate) -> dict:
    site = session.scalar(select(Site).where(Site.code == payload.site_code))
    if site is None:
        raise HTTPException(404, f"Site '{payload.site_code}' not found")
    ids = {"site_id": site.id, "plot_id": None, "observation_point_id": None, "instrument_id": None}
    if payload.plot_code:
        plot = session.scalar(select(Plot).where(Plot.code == payload.plot_code))
        if plot is None:
            raise HTTPException(404, f"Plot '{payload.plot_code}' not found")
        ids["plot_id"] = plot.id
    if payload.observation_point_code:
        pt = session.scalar(
            select(ObservationPoint).where(ObservationPoint.code == payload.observation_point_code)
        )
        if pt is None:
            raise HTTPException(404, f"Observation point '{payload.observation_point_code}' not found")
        ids["observation_point_id"] = pt.id
    if payload.instrument_code:
        inst = session.scalar(select(Instrument).where(Instrument.code == payload.instrument_code))
        if inst is None:
            raise HTTPException(404, f"Instrument '{payload.instrument_code}' not found")
        ids["instrument_id"] = inst.id
    return ids


@router.post(
    "/observations",
    response_model=ObservationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=EXIGE_CHAVE_DE_ESCRITA,
)
def create_observation(payload: ObservationCreate, session: Session = Depends(get_session)):
    ids = _resolve(session, payload)
    data = payload.model_dump(
        exclude={"site_code", "plot_code", "observation_point_code", "instrument_code"}
    )
    obs = Observation(**ids, **data)
    session.add(obs)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # o except generico apanhava tanto o UNIQUE de duplicado como
        # qualquer CHECK que escapasse a validacao do pydantic, e mentia
        # "already exists" para os dois casos. so o UNIQUE de identidade
        # e um duplicado genuino; qualquer outra violacao (por exemplo um
        # CHECK que a validacao devia ter apanhado) e um erro real do
        # servidor e tem de aparecer como tal, nao disfarcado de 409.
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_observation_identity":
            raise HTTPException(
                409,
                "An observation already exists for this site, plot, timestamp, metric, "
                "source type and processing version",
            )
        raise
    session.refresh(obs)
    return obs
