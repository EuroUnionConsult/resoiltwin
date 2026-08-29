# ReSoilTwin

A soil digital twin backend. It brings field readings, satellite imagery and derived
indicators into a single time series, and it never lets a value forget where it came from.

[![tests](https://github.com/EuroUnionConsult/resoiltwin/actions/workflows/tests.yml/badge.svg)](https://github.com/EuroUnionConsult/resoiltwin/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-proprietary-lightgrey)](#license)

---

## The idea

Soil monitoring mixes measurements of very different quality. A handheld probe, a
calibrated sensor, a laboratory assay and a satellite index are not the same kind of
number — but most systems store them in the same column and lose the distinction.

ReSoilTwin refuses to. Every value carries an explicit source type, a quality flag and a
processing version, and the database enforces it: you cannot insert a reading without
saying where it came from. An indicator on a dashboard can be traced back to the
measurement that produced it.

**This matters more than it sounds.** A screening probe reading `>=2000` because the
instrument saturated is not the number `2000`. A pH noted as `7–8` is not `7.5`. A
vegetation index averaged over a cloudy pixel is not a measurement of the ground. Each of
those distinctions is a column, a constraint, or both.

---

## How data gets in

Three paths, one table.

### Field observations

Manual readings and sensor telemetry are posted to the API with their instrument, their
plot, and an honest description of what kind of value they are:

```http
POST /api/v1/observations
```

A reading that saturated at the top of its scale is stored as a **censored value** — the
number, plus the fact that the real value is somewhere above it. A reading noted as a
range is stored as a range, not as its midpoint. The database rejects any combination
where the flag and the value disagree.

### Satellite imagery — Copernicus

The connector talks to the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/),
the European Union's Earth observation programme. Sentinel-2 passes over the same ground
every few days and the data is free.

```http
POST /api/v1/sites/{code}/eo/sync
```

Three indices are computed per acquisition, aggregated over the area of interest:

| Index | What it measures | What it is used for |
|---|---|---|
| **NDVI** | vegetation vigour and cover | whether the canopy is growing or declining |
| **NDMI** | water content in the canopy | water stress before it becomes visible |
| **NDRE** | chlorophyll, dense vegetation | condition of vines and orchards |

Cloudy pixels are excluded **per pixel**, using the Sentinel-2 scene classification band,
rather than by discarding whole acquisitions. What survives the mask is counted and
recorded, so every value comes with the number of pixels that actually contributed to it.

The connector requests aggregated statistics over the parcel rather than downloading
imagery — faster, cheaper, and it keeps the pipeline reproducible. Each synchronisation is
recorded as a job: what was requested, when, how many rows it wrote, and the error if it
failed. Re-running a synchronisation writes nothing new.

> **What satellites do not do.** They see the surface. They do **not** measure soil
> moisture. Soil moisture comes from probes in the ground. The two scales complement each
> other and neither substitutes the other. Any radar-derived "surface soil moisture" is a
> landscape-scale contextual signal, never ground truth.

### Derived variables

Values computed from other values — vapour pressure deficit from air temperature and
humidity, for example — are stored alongside the measurements, marked as derived, with a
record of how they were produced. They are never presented as observations.

---

## Provenance

Every row declares its origin. This is the vocabulary:

| Source type | Meaning |
|---|---|
| `observed_screening` | Screening-grade instrument, **not calibrated** |
| `observed_reference` | Calibrated, traceable sensor |
| `observed_lab` | Laboratory analysis |
| `satellite_observed` | Derived from a satellite acquisition |
| `weather_observed` | Weather station |
| `reanalysis` | Climate reanalysis — a model, not a measurement |
| `simulated` | Emulator output — **not a measurement** |
| `derived` | Computed from the layers above |

There is no value called `observed`, and its absence is deliberate. It was ambiguous
between a retail probe and a calibrated instrument, and that ambiguity is exactly what
destroys auditability. Being forced to choose is the point.

The database enforces this with check constraints, not conventions. Among other things it
refuses to store a value with no origin, to mark a reading as saturated while storing it as
exact, to approve an area of interest whose geometry was never confirmed, or to record a
failed job with no error message.

---

## Reading data out

One route serves every source. The provenance travels **inside each point**, not in a
footer:

```http
GET /api/v1/sites/{code}/timeseries?metric=ndvi
GET /api/v1/sites/{code}/timeseries?metric=soil_moisture_screening
```

```json
{
  "site_code": "...",
  "metric": "ndvi",
  "point_count": 11,
  "source_types": ["satellite_observed"],
  "points": [
    {
      "observed_at": "2026-08-21T00:00:00Z",
      "value": 0.4641,
      "value_qualifier": "exact",
      "unit": "index",
      "source_type": "satellite_observed",
      "quality_flag": "valid",
      "plot_code": null,
      "processing_version": "s2-ndvi-ndmi-ndre-scl-v2+..."
    }
  ]
}
```

Whoever reads a chart can see, point by point, where the number came from and how much it
is worth. Filter by plot, by source type, or by date window.

Interactive API documentation is generated from the code and served at `/docs`.

---

## Architecture

```
  field readings ─┐
                  ├─→  ReSoilTwin API  ─→  PostgreSQL + PostGIS
  Copernicus     ─┘         │
                            └─→  ingestion jobs (idempotent, auditable)
```

| | |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 with PostGIS |
| Schema | Alembic migrations, versioned and reversible |
| Geometry | stored in EPSG:4326, computed in UTM 29N |
| Earth observation | Copernicus Data Space, OAuth 2.0 |

Seven tables: sites, areas of interest, plots, observation points, instruments,
observations, ingestion jobs. Fourteen check constraints. The migrations rebuild this
schema exactly — verified byte for byte against the models.

---

## Running it locally

Requires Docker and Python 3.12.

```bash
git clone https://github.com/EuroUnionConsult/resoiltwin.git
cd resoiltwin

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env          # then fill in your own credentials
docker compose up -d db
alembic upgrade head

uvicorn resoiltwin.main:app --reload
```

The API is then at `http://127.0.0.1:8000`, with documentation at `/docs`.

Earth observation requires credentials from the
[Copernicus Data Space](https://dataspace.copernicus.eu/) — create an OAuth client in the
Sentinel Hub dashboard and put the id and secret in `.env`. Everything else runs without
them.

### Running the tests

```bash
source .venv/bin/activate
pytest -q
ruff check .
```

No test reaches the network. Every external call is mocked.

---

## Development

**Commits follow [Conventional Commits](https://www.conventionalcommits.org/).** The prefix
determines the next version:

| Prefix | Effect |
|---|---|
| `fix:` | patch — `0.1.0 → 0.1.1` |
| `feat:` | minor — `0.1.0 → 0.2.0` |
| `feat!:` or `BREAKING CHANGE:` | major — `0.1.0 → 1.0.0` |
| `docs:` `test:` `chore:` `refactor:` | no release |

Releases and the changelog are produced by
[release-please](https://github.com/googleapis/release-please), which opens a release pull
request as commits land and tags the version when it is merged. `CHANGELOG.md` is generated
— do not edit it by hand.

---

## Status

The observation model, the API and the Copernicus connector are implemented and tested.
The weather layer, the water-balance emulator and the web interface are not.

**What this project does not claim.** No agronomic validation has been performed. No
calibrated field sensors are installed. Screening-grade readings are never presented as
reference measurements, and simulated values are never presented as observations. Anything
this system asserts can be traced to the row that supports it — and where it cannot, it
says so.

---

## License

Proprietary. © Euro Union Consult, Lda.
