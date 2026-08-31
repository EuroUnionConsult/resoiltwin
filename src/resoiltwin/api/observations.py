from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resoiltwin.db import get_session
from resoiltwin.enums import SourceType
from resoiltwin.models import Instrument, Observation, ObservationPoint, Plot, Site
from resoiltwin.schemas.observation import (
    MetricFacet,
    ObservationCreate,
    ObservationListRead,
    ObservationRead,
    ObservationRowRead,
)

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


def _inventario(session: Session, site: Site) -> list[MetricFacet]:
    """O que este sitio tem, metrica a metrica.

    Sai de um `GROUP BY` sobre a propria tabela e nao de uma lista escrita a
    mao: uma metrica nova aparece sozinha, e uma que deixe de ser gravada
    desaparece sem ninguem vir aqui. Uma lista a mao envelhece em silencio, que
    e um padrao que este projecto ja apanhou tres vezes.

    Agrupa por metrica **e unidade**: a mesma metrica gravada em duas unidades
    sao duas coisas, e junta-las apagava precisamente a diferenca que importa.
    """
    consulta = (
        select(
            Observation.metric,
            Observation.unit,
            func.array_agg(Observation.source_type.distinct()).label("source_types"),
            func.count().label("count"),
            func.min(Observation.observed_at).label("first_observed_at"),
            func.max(Observation.observed_at).label("last_observed_at"),
        )
        .where(Observation.site_id == site.id)
        .group_by(Observation.metric, Observation.unit)
        .order_by(Observation.metric, Observation.unit)
    )
    return [
        MetricFacet(
            metric=linha.metric,
            unit=linha.unit,
            source_types=sorted(SourceType(origem) for origem in linha.source_types),
            count=linha.count,
            first_observed_at=linha.first_observed_at,
            last_observed_at=linha.last_observed_at,
        )
        for linha in session.execute(consulta)
    ]


@router.get("/sites/{code}/observations", response_model=ObservationListRead)
def list_observations(
    code: str,
    session: Session = Depends(get_session),
    metric: str | None = Query(None, description="Only this metric."),
    source_type: SourceType | None = Query(None, description="Only this origin."),
    limit: int = Query(
        100, ge=0, le=500,
        description=(
            "Most recent first. Zero returns the site inventory with no rows, which is "
            "what a view that only needs the catalogue asks for."
        ),
    ),
):
    """As observacoes de um sitio, com a proveniencia de cada uma ao lado.

    **Porque e que a listagem faltava.** Ate aqui a unica leitura de
    observacoes era `GET /sites/{code}/timeseries`, e ela exige uma metrica --
    logo, so responde a quem ja saiba o nome do que quer. Nao havia pergunta
    nenhuma do genero "o que e que este sitio tem", e por isso qualquer cliente
    que quisesse mostrar uma tabela tinha de trazer a lista de metricas escrita
    dentro dele. Uma lista dessas envelhece em silencio, e o cliente passa a
    esconder o que a base tem.

    E a serie temporal nao devolve a proveniencia estruturada -- nem
    `evidence`, nem `method`, nem `source_collection`, nem `notes`. Faz sentido
    onde ela esta: um ponto de uma serie e um par tempo/valor. Mas quem precisa
    de responder "de onde veio este numero" ficava sem ter onde perguntar.

    **Uma rota e nao um alargamento da serie temporal.** Acrescentar `evidence`
    a `TimeseriesPoint` engordava a resposta de todos os leitores de series por
    causa de um caso que nao e o deles, e misturava duas perguntas diferentes:
    "como e que isto evoluiu" e "de onde veio cada linha". Sao duas rotas
    porque sao duas perguntas.

    `total` conta as linhas que casam com o filtro e `returned` as que vao na
    resposta: sem o par, uma listagem truncada le-se como a lista toda -- que e
    a mesma forma de erro que o job que dizia `succeeded` tendo escrito 6 linhas
    onde havia 159.
    """
    site = session.scalar(select(Site).where(Site.code == code))
    if site is None:
        raise HTTPException(404, f"Site '{code}' not found")

    filtros = [Observation.site_id == site.id]
    if metric is not None:
        filtros.append(Observation.metric == metric)
    if source_type is not None:
        filtros.append(Observation.source_type == source_type)

    total = session.scalar(select(func.count()).select_from(Observation).where(*filtros))

    # O desempate por `id` nao significa nada -- serve para que duas linhas com
    # o mesmo `observed_at` saiam sempre na mesma ordem, senao o mesmo pedido
    # devolvia conjuntos diferentes.
    consulta = (
        select(Observation, Plot.code)
        .outerjoin(Plot, Observation.plot_id == Plot.id)
        .where(*filtros)
        .order_by(Observation.observed_at.desc(), Observation.id)
        .limit(limit)
    )
    linhas = [
        ObservationRowRead(
            **ObservationRead.model_validate(observacao).model_dump(),
            plot_code=plot_code,
            source_collection=observacao.source_collection,
            method=observacao.method,
            notes=observacao.notes,
            evidence=observacao.evidence,
        )
        for observacao, plot_code in session.execute(consulta)
    ]
    return ObservationListRead(
        site_code=code,
        metrics=_inventario(session, site),
        total=total or 0,
        returned=len(linhas),
        rows=linhas,
    )
