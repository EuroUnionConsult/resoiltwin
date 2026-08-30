# Imagem de execucao da API ReSoilTwin.
#
# Debian e nao Alpine, e a escolha nao e estilistica. Quatro dependencias deste
# projecto sao extensoes nativas que trazem a biblioteca de sistema embutida na
# propria wheel: shapely traz o GEOS, pyproj traz o PROJ, netCDF4 traz o HDF5 e
# o netcdf-c, psycopg[binary] traz o libpq. Essas wheels sao manylinux, que e
# glibc; numa base musl (Alpine) nenhuma delas se aplica e o pip cai para
# compilar as quatro a partir do codigo-fonte, o que exige toda a cadeia de
# compilacao e as bibliotecas de sistema correspondentes. Em glibc nao e
# preciso um unico pacote apt para alem do que a imagem ja traz.
#
# A consequencia pratica: nao trocar a base por uma variante Alpine sem
# reescrever esta imagem por inteiro.

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Ambiente virtual proprio para o poder copiar inteiro para a fase de execucao,
# sem levar o pip nem os metadados de compilacao para a imagem final.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# O pyproject e o codigo sao copiados juntos porque o setuptools precisa de
# encontrar src/ para resolver o pacote. Nao ha ficheiro de dependencias
# separado a que se pudesse dar cache antes do codigo.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install .


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Utilizador sem privilegios. A aplicacao nao escreve no sistema de ficheiros
# em nenhum caminho de execucao: o unico ficheiro que chega a existir e o
# NetCDF que o cliente do Climate Data Store transfere, e esse vive num
# TemporaryDirectory que e apagado a seguir.
RUN useradd --create-home --uid 10001 resoiltwin

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# alembic.ini e migrations/ vao na imagem de proposito: e a mesma imagem que
# corre a API e que corre `alembic upgrade head` no job de migracao. Duas
# imagens diferentes podiam divergir, e o schema deixaria de corresponder ao
# codigo que o le.
COPY alembic.ini ./
COPY migrations/ ./migrations/

USER resoiltwin

EXPOSE 8000

# Sem valores por omissao para DATABASE_URL nem para as credenciais externas.
# `Settings` levanta MissingDatabaseUrlError e recusa arrancar sem DATABASE_URL,
# e e isso que se quer: um ambiente mal configurado tem de falhar a vista em vez
# de se ligar em silencio a outra base.
ENV ENVIRONMENT=production

CMD ["uvicorn", "resoiltwin.main:app", "--host", "0.0.0.0", "--port", "8000"]
