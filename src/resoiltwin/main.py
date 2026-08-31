from fastapi import FastAPI

from resoiltwin.api import (
    PREFIXO_DA_API,
    console,
    docs,
    eo,
    health,
    jobs,
    observations,
    sites,
    timeseries,
    water,
    weather,
)
from resoiltwin.api.auth import EXIGE_CHAVE


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReSoilTwin API",
        version="0.1.0",
        description=(
            "Soil digital twin platform. Every value carries an explicit source_type, "
            "quality_flag and processing_version. Screening-grade readings are never "
            "presented as calibrated measurements."
        ),
        # As tres a None desligam as rotas de documentacao do FastAPI, que ele
        # regista como rotas do Starlette e que por isso NAO passariam por
        # dependencia nenhuma. As mesmas quatro sao registadas por nos, com
        # guarda, em `api/docs.py` -- e o argumento para as fechar esta la.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    # A politica de acesso inteira le-se nestas dez linhas, e e essa a razao de
    # ela estar aqui e nao espalhada pelas rotas: TODAS pedem a chave, menos o
    # `/health`. A excepcao e visivel por ser a unica linha sem `dependencies=`.
    #
    # O `/health` fica aberto porque a sonda de saude da plataforma o chama sem
    # credencial nenhuma, e uma revisao que nunca fica saudavel nao arranca. O
    # que ele devolve foi conferido: estado, nome e etiqueta do ambiente.
    app.include_router(docs.router, dependencies=EXIGE_CHAVE)
    app.include_router(health.router, prefix=PREFIXO_DA_API)
    app.include_router(sites.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)
    app.include_router(observations.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)
    app.include_router(timeseries.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)
    app.include_router(eo.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)
    app.include_router(jobs.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)
    app.include_router(weather.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)
    app.include_router(water.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)

    # A segunda linha sem `dependencies=`, e a segunda excepcao a politica. A
    # razao e outra: o `/health` fica aberto porque a sonda nao tem onde por um
    # cabecalho; a consola fica aberta porque o NAVEGADOR nao tem chave nenhuma
    # -- e nao pode ter, que e a razao de esta camada existir.
    #
    # O que ela deixa fazer sem credencial esta estreitado no proprio modulo, e
    # e ai que esta escrito o custo: so `GET`, so caminhos que esta aplicacao
    # serve como leitura sob o `PREFIXO_DA_API`, sem geometrias, e com a chave
    # a nunca voltar para tras. Escreve-se, por aqui, nada.
    app.include_router(console.router)
    return app


app = create_app()
