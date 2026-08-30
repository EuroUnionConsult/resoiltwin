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

Four paths, one table.

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

Filtering by how cloudy a *scene* is does not protect the area of interest — a scene
covers a wide swath of ground, and a parcel is a small fraction of it. A scene can be
mostly clear while the parcel underneath it sits entirely under cloud, or mostly clouded
while the parcel is clear. Cloud cover at the scene level is only useful for skipping
scenes that are unusable everywhere; it says nothing about what is happening over any one
polygon.

So the exclusion happens **per pixel**, using the Sentinel-2 scene classification band,
rather than by discarding — or accepting — whole acquisitions. What survives the mask is
counted, and every value is recorded together with how many pixels actually contributed
to it, so an average built from a handful of surviving pixels is visible as such rather
than looking the same as one built from the whole parcel.

**Two versions of the processing script coexist.** Cloud masking was added after the
connector already had readings in production, and the new version does not replace the
old one — both are requested through the same route, selected by a flag on the sync
request, and every value declares which script produced it through its
`processing_version`. Reprocessing with a new method does not erase what the old method
produced; it sits alongside it. That is what makes changing the method auditable instead
of invisible — the two versions of the same acquisition can be compared directly, instead
of trusting that the newer one is better.

The connector requests aggregated statistics over the parcel rather than downloading
imagery — faster, cheaper, and it keeps the pipeline reproducible. Each synchronisation is
recorded as a job: what was requested, when, how many rows it wrote, which script version
it ran with, and the error if it failed. Re-running a synchronisation writes nothing new.

> **What satellites do not do.** They see the surface. They do **not** measure soil
> moisture. Soil moisture comes from probes in the ground. The two scales complement each
> other and neither substitutes the other. Any radar-derived "surface soil moisture" is a
> landscape-scale contextual signal, never ground truth.

> **Known limitation, on the pixel count itself.** The field stored as `valid_pixels`
> records the total number of pixels sampled, not the number that actually contributed to
> the value — the number that matters is `sampled − excluded`, and today that subtraction
> has to be done by the reader, not by the pipeline. Cloud masking made this more visible
> than it used to be: `no_data_pixels` now sums two different things — pixels that fall
> outside the parcel's polygon, and pixels excluded by the cloud mask — without telling
> them apart. The two are only separable today by coincidence, because one parcel in
> production happens to have zero of the first kind and another happens to have zero of
> the second. An irregular parcel with partial cloud on the same acquisition would make
> the two indistinguishable. Recording them as two separate counts is open work.

### Weather — a station and a reanalysis grid

Two sources, one route, and neither of them measures anything inside the parcel:

```http
POST /api/v1/sites/{code}/weather/sync
```

With `source: "ipma"` the connector reads the Portuguese meteorological institute's
open-data feed, picks the station nearest the site, and writes its hourly readings as
`weather_observed`. With `source: "reanalysis"` it asks the Copernicus Climate Data Store
for the AgERA5 daily fields over the requested window and writes the grid cell containing
the site as `reanalysis` — a model output, never a measurement.

**The distance is the point, and it travels in every row.** The nearest station to the
Turcifal site is 5.34 km away; the reanalysis cell containing it is 11.1 km north–south by
8.6 km east–west, and its centre sits 5.41 km from the site. Every value carries the
station identity or the cell coordinates, the distance, the cell footprint in both
directions, and `measured_at_site: false`. A grid value or a value from a station some
kilometres away is context for the parcel, not a reading taken in it, and the row says so
rather than leaving it to be inferred.

Two ways this can mislead, both handled where they can be and declared where they cannot:

- **A station can report solar radiation at night.** Readings taken when the sun is more
  than 6° below the horizon are dropped, and how many were dropped for that station is
  recorded on every row the run wrote. Twilight, between −6° and 0°, is deliberately not
  guarded.
- **The feed has no archive.** It publishes the last 24 hours and nothing else, so the
  observed series begins the day the sync first runs and grows an hour at a time. Nothing
  schedules it yet, so it will have gaps.

The reanalysis has its own lag: the archive trails the present by roughly a week, so a
window asked for up to today comes back ending earlier. That is not an error and the job
does not fail for it — but the job narrows its declared window to the days it actually
covered, so a short series is visible in the job rather than hidden behind the window that
was requested.

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

**Three origins can answer the same question, and the route keeps them apart.** Ask
`metric=air_temperature` of the Turcifal site and one response carries a screening probe
held in the parcel, a station 5.34 km away, and a reanalysis cell 11.1 by 8.6 km — as
`observed_screening`, `weather_observed` and `reanalysis`, each point saying which it is.
Nothing merges them, averages them, or prefers one. That is the whole point: the reader
decides what a given number is worth, and cannot do that if the provenance was resolved
before they saw it.

### Which runs need a human

Every ingestion leaves a row in `ingestion_jobs`, and several deliberate design decisions
lean on that row being read: an absurd station value brings the job down instead of being
dropped in silence, so does a station swapped under the same identity, so does a wrong
timezone. Failing loudly is only better than losing data quietly if somebody looks.

```http
GET /api/v1/jobs?needs_attention=true
GET /api/v1/jobs?status=failed&job_type=reanalysis_sync
```

Every row carries an `attention` verdict — `failed`, `never_finished`, or
`succeeded_without_writing` — and `null` when there is nothing to flag. `GET /jobs/{id}`
carries the same verdict, so the job handed back by a `sync` call can be checked without
knowing the listing exists.

**What the verdict cannot see is written down too.** A run that reported success while
writing far fewer rows than it should have is not on this list, because no expectation is
recorded anywhere and every way of deriving one is either circular or invented — a
satellite job writing 21 rows over a 29-day window is perfectly normal. A repeat of a
request that already wrote its rows is deliberately quiet: deduplication means it writes
zero, and flagging that would fill the list with noise. The reasoning is in
`src/resoiltwin/attention.py`.

Interactive API documentation is generated from the code and served at `/docs`.

---

## Architecture

```
  field readings   ─┐
  Copernicus       ─┤
                    ├─→  ReSoilTwin API  ─→  PostgreSQL + PostGIS
  weather stations ─┤          │
  climate archive  ─┘          └─→  ingestion jobs (idempotent, auditable)
```

| | |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 with PostGIS |
| Schema | Alembic migrations, versioned and reversible |
| Geometry | stored in EPSG:4326, computed in UTM 29N |
| Earth observation | Copernicus Data Space, OAuth 2.0 |
| Weather | Copernicus Climate Data Store (AgERA5) and the Portuguese open-data station feed |

Seven tables: sites, areas of interest, plots, observation points, instruments,
observations, ingestion jobs. Every rule described above is a database constraint, not a
convention — the schema refuses the bad row rather than trusting the caller to avoid it.
The migrations rebuild this schema exactly, verified against the models by a test that
fails if the two ever drift apart.

---

## Running it locally

Requires Docker and Python 3.12.

```bash
git clone https://github.com/EuroUnionConsult/resoiltwin.git
cd resoiltwin

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env          # required: the app will not start without it
docker compose up -d db
alembic upgrade head

uvicorn resoiltwin.main:app --reload
```

The API is then at `http://127.0.0.1:8000`, with documentation at `/docs`.

**The `.env` step is not optional.** `DATABASE_URL` has no default value — `Settings`
raises `MissingDatabaseUrlError` and refuses to start without it, naming the variable and
pointing back at this section. That is deliberate: a misconfigured environment must fail
loudly instead of silently falling back to some other database.

The external credentials are the only genuinely optional part of `.env`, and each one gates
exactly one connector. Earth observation needs an OAuth client created in the Sentinel Hub
dashboard of the [Copernicus Data Space](https://dataspace.copernicus.eu/); the reanalysis
needs a personal access token from the
[Copernicus Climate Data Store](https://cds.climate.copernicus.eu/). Ask for a reanalysis
sync without the second pair and the route answers 503 naming the two variables — it does
not fail the station sync, which needs no credential at all because the feed is public.
Everything else runs without any of them.

### Restoring the development data

A fresh database has the schema and no rows. To load the reference dataset the evidence
notes are written against — the Turcifal field campaign, the two AOI, both Copernicus
series, and both weather series — run:

```bash
python scripts/restore_dev_data.py --yes
```

It seeds the field campaign, then starts a temporary `uvicorn` on a free port and drives
the **HTTP routes** for everything else: the Porto site, both AOI (geometry, provenance
and source note read from the GeoJSON files in `resoiltwin-internal/aoi-final/`), the
approvals, four Copernicus syncs — each AOI with and without the SCL mask, which rebuilds
the `v1` and `v2` series side by side — and then, per site, a reanalysis sync over
01/07–29/08/2026 and a station sync. It reads the `status` of every job and stops if one
comes back `failed`; a `202` is not success. Expect it to take minutes rather than
seconds: each reanalysis sync is six separate requests to the Climate Data Store.

**Only part of the end state has a number to check against, and the script says which.**
The reproducible part is **139 observations** — 27 field readings, 4 derived VPD, 54 `v1`
and 54 `v2` — and the script fails if that count comes out different. The two weather
series are reported next to it but not demanded:

- the **reanalysis** converges to 360 rows (60 days × 3 metrics × 2 sites) and is short
  until the archive publishes the whole window. The run of 29/08/2026 wrote 318, ending
  on 22/08;
- the **station** series has no expected number at all. The feed publishes the last 24
  hours, so what lands depends on when the script runs; the run of 29/08/2026 wrote 240.

The run this repository's evidence note describes ended at **697 observations** — the 139,
plus 318 reanalysis and 240 station rows. Anyone re-running it later will get the same
139, more reanalysis rows, and different station rows, and neither of those two
differences means anything went wrong.

**It prints the database it is about to write to, and refuses to run without either a
terminal to confirm at or an explicit `--yes`.** That guard is there because this database
has already been wiped twice by a command aimed somewhere else. Before running anything
that writes, check where the connection actually points:

```bash
python -c "from resoiltwin.config import get_settings; from scripts.restore_dev_data import url_sem_segredo; print(url_sem_segredo(get_settings().database_url))"
```

`Settings` has no `env_prefix`, so the variable is `DATABASE_URL` and nothing else. It was
a misnamed variable (`RESOILTWIN_DATABASE_URL` instead of `DATABASE_URL`) that caused the
second wipe: silently ignored, it fell back to a hardcoded default that happened to point
at this real database, and an `alembic downgrade base` run against it in that state took
the 139 observations with it. `database_url` now has no default at all — get the name
wrong, or leave it unset, and `Settings` raises `MissingDatabaseUrlError` before anything
can connect to the wrong place.

The satellite values are reproducible; the job and AOI UUIDs and the timestamps are not,
because they are generated per run.

### Running the tests

```bash
source .venv/bin/activate
pytest -q
ruff check .
```

No test reaches the network. Every external call is mocked.

**Each run gets its own database.** The suite creates `resoiltwin_test_<pid>_<random>`,
builds the schema through the migrations, and drops it at the end — so two runs never
collide, and a mutation round (which runs the suite inside a copy of the tree) can run
while you work. Nothing to set: `pytest -q` derives it.

The drop is guarded by what created the database, not by what it is called. `CREATE
DATABASE` runs with no `IF NOT EXISTS` and no preceding drop, so a name already taken is
refused by the server itself; and the drop refuses to run unless the create succeeded in
this same run, against the name the create actually accepted. A real database is not
protected by our getting the name right — it is protected by already existing.

Databases left behind by other runs are **listed as a warning, never dropped**: one of them
may belong to a run happening right now, and the name alone does not prove otherwise.

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

The observation model, the API, the Copernicus connector and the weather layer are
implemented and tested. The water-balance emulator and the web interface are not.

**The weather layer has run for real once**, on 29/08/2026, and what that run found is
written up in [`docs/evidence/2026-08-29-fase-c.md`](docs/evidence/2026-08-29-fase-c.md).
Two things it is important not to read past. The station series has **no history before
the day the sync first ran** — the open-data feed publishes the last 24 hours and keeps no
archive — and nothing schedules the sync, so that series will have gaps until something
runs it on a clock. And the reanalysis archive lags behind the present by about a week:
a window asked for up to 29/08 came back ending on 22/08, which is why the field campaign
of 22–24 August is met by a reanalysis value on **one** of its three days.

**What this project does not claim.** No agronomic validation has been performed. No
calibrated field sensors are installed. Screening-grade readings are never presented as
reference measurements, and simulated values are never presented as observations. Anything
this system asserts can be traced to the row that supports it — and where it cannot, it
says so.

---

## License

Proprietary. © Euro Union Consult, Lda.
