from fastapi import FastAPI

from resoiltwin.api import health, observations, sites, timeseries


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReSoilTwin API",
        version="0.1.0",
        description=(
            "Soil digital twin platform. Every value carries an explicit source_type, "
            "quality_flag and processing_version. Screening-grade readings are never "
            "presented as calibrated measurements."
        ),
    )
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(sites.router, prefix="/api/v1")
    app.include_router(observations.router, prefix="/api/v1")
    app.include_router(timeseries.router, prefix="/api/v1")
    return app


app = create_app()
