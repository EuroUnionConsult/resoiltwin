from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from resoiltwin.db import get_session
from resoiltwin.enums import SourceType
from resoiltwin.models import Observation, Plot, Site
from resoiltwin.schemas.observation import TimeseriesPoint, TimeseriesResponse

router = APIRouter(tags=["timeseries"])


@router.get("/sites/{code}/timeseries", response_model=TimeseriesResponse)
def timeseries(
    code: str,
    metric: str = Query(...),
    plot: str | None = Query(default=None),
    source_type: SourceType | None = Query(default=None),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    session: Session = Depends(get_session),
):
    site = session.scalar(select(Site).where(Site.code == code))
    if site is None:
        raise HTTPException(404, f"Site '{code}' not found")

    stmt = (
        select(Observation, Plot.code)
        .outerjoin(Plot, Observation.plot_id == Plot.id)
        .where(Observation.site_id == site.id, Observation.metric == metric)
        .order_by(Observation.observed_at)
    )
    if plot:
        stmt = stmt.where(Plot.code == plot)
    if source_type:
        stmt = stmt.where(Observation.source_type == source_type)
    if date_from:
        stmt = stmt.where(Observation.observed_at >= date_from)
    if date_to:
        stmt = stmt.where(Observation.observed_at <= date_to)

    rows = session.execute(stmt).all()
    points = [
        TimeseriesPoint(
            observed_at=o.observed_at, value=o.value_numeric, value_min=o.value_min,
            value_max=o.value_max, value_qualifier=o.value_qualifier, unit=o.unit,
            source_type=o.source_type, quality_flag=o.quality_flag,
            plot_code=plot_code, processing_version=o.processing_version,
        )
        for o, plot_code in rows
    ]
    return TimeseriesResponse(
        site_code=code, metric=metric, point_count=len(points),
        source_types=sorted({p.source_type for p in points}), points=points,
    )
