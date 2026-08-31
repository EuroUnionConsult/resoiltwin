# ReSoilTwin

A soil digital twin backend. It brings field readings, satellite imagery, weather, and the
values modelled from them into a single time series, and it never lets a value forget where
it came from.

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

Five paths, one table.

**Every route on this page needs a key.** The `http` blocks below name the route and
omit the header for readability, but none of them answers without one — see
[Every route needs a key](#every-route-needs-a-key) before you try any of them.

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

> **How many pixels a satellite value rests on, and what the row claims about it.** Every
> satellite row records three counts: `sampled_pixels` (how many the API sampled),
> `no_data_pixels` (how many it excluded), and `contributing_pixels` (how many actually
> fed the mean, subtracted within each index before the worst of the three is taken).
> Until 30/08/2026 only the first was recorded, and it was stored under the name
> `valid_pixels` — a label that was true of something else: on the 24/08/2026 acquisition
> it read 62 750 where 5 318 pixels contributed, and it was identical with and without the
> cloud mask on all 18 acquisitions. Rows written before that date were renamed in place
> (migration `0010`); they carry no `contributing_pixels`, and the absence of that key is
> how you tell them apart — for those, `sampled − no_data` is a bound, not the count.
>
> **Satellite rows are `unchecked`, never `valid`.** Nothing in this pipeline checks the
> quality of a spectral index, so no row claims it was checked. There is no coverage
> threshold, because nothing here would justify one — the counts are on the row so that a
> reader can apply their own. Before 30/08/2026 the flag was a literal `valid` with no
> condition behind it, which put a mean taken over 8,47% of a parcel into every query that
> filtered on `quality_flag = 'valid'`.
>
> **Still open.** `no_data_pixels` sums two different things — pixels that fall outside the
> parcel's polygon, and pixels excluded by the cloud mask — without telling them apart. The
> two are only separable today by coincidence, because one parcel in production happens to
> have zero of the first kind and another happens to have zero of the second. An irregular
> parcel with partial cloud on the same acquisition would make the two indistinguishable.
> Recording them as two separate counts is open work.

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

**Four variables by default, and the fourth is there on purpose.** Air temperature,
precipitation, solar radiation and — since 30/08/2026 — **reference evapotranspiration**,
which is the input that dominates the [water balance](#water-balance--a-model-over-the-series-already-stored).
It is a default rather than something to remember to ask for, because a variable that only
arrives when somebody names it is a variable missing from the archive on the day it is
needed, and the archive does not fill in the past for free.

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

### Water balance — a model over the series already stored

The fifth path contacts nothing. It reads two series that are already in the database —
daily precipitation and daily reference evapotranspiration — runs a single-reservoir
daily balance over them, and writes a third series back as `simulated`:

```http
POST /api/v1/sites/{code}/water/sync
{"date_from": "2026-07-01", "date_to": "2026-08-29", "available_water_capacity_mm": 100}
```

**The soil's available water capacity is a required argument with no default, and that is
the whole design.** Nobody has measured it on this ground, and it is the parameter that
dominates the result. A default would be an invented number quietly deciding the output of
every run by whoever did not type one. So it must be written by the caller, it travels in
the `processing_version` — which means two capacities are two series side by side, not two
runs of the same one — and it travels again in each row's `evidence` next to
`capacity_is_measured: false`. Being forced to write it does not make it true; it makes it
**attributable**, which is all that can be done until somebody measures it.

**The output is an interval, not a number, for as long as the ignorance lasts.** A
reservoir balance needs to know how much water was in the ground on the first day, and
nobody knows. Rather than receive that as a second unmeasured argument or assume it, each
series is run **twice**, from the only two states the reservoir admits — empty and full —
and what is stored is the band between the two trajectories. Any true initial state lies
between them. The band closes on its own: once both trajectories hit the same bound they
are the same series from then on, and the value stops depending on what nobody measured.
Those days come out as `value_qualifier: 'exact'`; the earlier ones as `'range'`, with
`value_min`/`value_max` filled and `value_numeric` null.

**A `202` is not success.** The route answers 202 when the request was accepted and
processed; whether it worked is the `status` in the body. A window with no input rows, two
input series that share no day, an input in the wrong unit, or an hourly series where the
balance needs daily totals all bring the job down with the reason written out — none of
them writes zero rows and claims success. What is refused *before* a job exists rises as an
HTTP error instead and leaves no trace: 422 for an impossible capacity or an inverted
window, 404 for an unknown site, 409 for a site without exactly one approved AOI.

> **It has run for real, and what came out is the point.** On 30/08/2026 it wrote **318
> rows** — 53 days × 2 sites × 3 declared capacities — across six `succeeded` jobs.
> **Every determined value in all of them is `0.0000 mm`**, and every lower bound is `0.0`.
> It did not rain: over those 53 days Turcifal received **3.48 mm** of precipitation
> against **303.95 mm** of reference evapotranspiration, 1.1 %, and the wettest single day
> never reached the least thirsty one. The trajectory starting from an empty reservoir
> never left zero, so every collapse of the band was on the floor and none on the ceiling.
> **That run exercised the plumbing, not the model** — the overflow branch and the
> gap-in-the-series cut were never touched by real data, and remain defended by tests and
> mutants only. The full account, including what the interval table looks like to someone
> who reads it without this paragraph, is in
> [`docs/evidence/2026-08-30-fase-d.md`](docs/evidence/2026-08-30-fase-d.md).

### Every route needs a key

Every route — reading as well as writing — requires a shared key in an `X-API-Key`
header, checked against `WRITE_API_KEY`.

```http
GET  /api/v1/sites
POST /api/v1/observations
X-API-Key: <the key>
```

**`GET /api/v1/health` is the first of two exceptions.** The platform health probe calls it
with no credential at all, and a revision that never becomes healthy never starts — so a
guard there would take the system down rather than protect it. What it returns was checked
before it was left open: a status, the application name and the environment tag. It does
not touch the database, does not report a version, and does not say where `DATABASE_URL`
points.

**`GET /console/…` is the second, and it exists for the opposite reason** — see
[The layer that holds the key](#the-layer-that-holds-the-key) below.

**Why reading needs a key too.** Plot geometries and field readings are not public, and
that was already decided twice elsewhere: the approved polygons live in a **private**
repository, and the published evidence notes state distances and cell sizes but never the
polygons themselves. An API that handed the same geometries and the same readings to
anyone who asked contradicted both. Satellite and weather series do come from open
sources, but they are served by the same routes as everything else, and splitting the
boundary by row rather than by route is a larger piece of work than this is.

**The documentation is behind the key as well** — `/openapi.json`, `/docs`,
`/docs/oauth2-redirect` and `/redoc`. The schema holds no data, but it holds the map:
route names, body shapes, which fields are free text. The cost is real and worth stating —
a browser cannot put a header on an address bar, so `/docs` no longer opens by typing the
URL. The schema is still served to whoever presents the key, and reads well in a local
Swagger UI or client generator:

```bash
curl -H "X-API-Key: <the key>" "$URL/openapi.json"
```

**Be clear about what this is.** It is a fence, not an identity. All valid requests are
equivalent to each other, and `approved_by` is still a text field the client fills in —
an approval can still claim any name. There is no per-person revocation either: removing
one holder's access means generating a new key and redistributing it to everyone else.
What changed is that none of it can be reached by someone who does not hold the key.
Attaching a real user to each approval means putting an identity provider in front of the
API, and that is a separate, larger step.

Two consequences worth knowing before you deploy:

- **The key has no default value.** A default in a public repository is the same key
  everywhere, which is a painted-on lock. Generate one per installation:
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- **A missing key closes the API rather than opening it.** Every route except `/health`
  answers 503, and the application still starts — so the probe still answers and the log
  still names the missing variable, which is how you tell "the secret never arrived" from
  "my key is wrong". That is deliberate: the dangerous failure would be the mirror image —
  "no key is configured, so let everything through" — which is exactly what the obvious way
  of writing the check produces.

Requests without the header and requests with the wrong key get the same 401, the same
body and the same headers. The difference between the two goes to the server log, where
whoever operates the system can see it and whoever is guessing cannot.

The variable is still called `WRITE_API_KEY`, which now says less than the key does. The
name is the deployment contract — it is the `write-api-key` secret in the vault and the
variable `infra/modules/app.bicep` carries into the container — and renaming it is a
change with a redeployment attached, not a widening of scope. It is recorded as a naming
debt rather than left to pass as an oversight.

### The layer that holds the key

A frontend running in a browser cannot hold that key. Anything in its code, its
configuration or one of its responses is visible to whoever opens the developer tools —
and from there, writable straight into the production database. So the console has a
server layer of its own, which holds the key and talks to the API; the browser never sees
it.

```
browser  ->  this layer  ->  ReSoilTwin API
                  ^
             holds the key
```

It is the same Python application and the same image — a router
(`src/resoiltwin/api/console.py`), not a second runtime to build, publish, update and
secure. Its request to the API is a real HTTP request, carrying the key and passing
through the same guard as any other client's, but it travels over an in-process ASGI
transport rather than over the network. That is not an optimisation: it is what makes
"this layer talks only to the API" structural. There is no configurable address anyone
could point at the database, at Copernicus, or at a third party.

**What it forwards, and what that costs.**

- **Reads only.** The route is registered with a single method, so a write verb is refused
  by the router before any of our code runs. The console shows data; it does not trigger
  syncs or approve areas of interest. Whoever reaches the layer cannot write, even with the
  whole layer in front of them. When the console does need to trigger a sync, this has to
  be changed on purpose, with the decision written down.
- **Only paths this application serves as `GET` under `/api/v1`, asked of the router
  itself.** No hand-written route list — one of those ages in silence, which this project
  has already been caught by three times. A read route added tomorrow becomes reachable
  with nobody editing a list; a write route never does. The cost is real: a new read route
  becomes readable through the console without anyone deciding that it should.
- **No geometries.** `GET /sites/{code}/aois` returns the polygon next to the area in m²;
  the area passes, the polygon is replaced by a marker. The cut is by the *shape* of the
  value, not the field name, so renaming `geometry` does not get around it.
- **No coordinates either**, which is the other half of the same rule. A polygon has a
  GeoJSON shape and falls to the cut above; a centroid does not — it is a `float` called
  `site_lat` inside a row's evidence, or a pair written into a sentence in an area's
  provenance note. Three rules, each with its price written in the module header: by
  *name* for bare numbers (`lat`, `lon`, and anything ending in `_lat`/`_lon`), by *shape*
  for bounding boxes (an area-ish key holding a list of numbers — `area_m2` and
  `area_expanded` still pass), and by *pattern* for prose (a pair of decimals with four or
  more places, or a lone one with six or more). Renaming `site_lat` to `y` would get
  around the first, which is why the console draws only what comes out of here rather than
  keeping an exception list of its own.
- **Nothing of the browser's reaches the API, and nothing of the API's envelope reaches the
  browser.** Both header sets are built from scratch. A body that is not JSON does not pass,
  and neither does one that contains the key.

⚠️ **What it does not do.** Whoever reaches this layer reads the API's data without
presenting any credential. Reads were closed on 31/08 precisely because this data is not
public, and this layer reopens them to whoever reaches the address. What the fence protects
is what is left: the credential does not leave, and nothing that goes through it writes.
Putting a real identity in front is the same conversation as per-person revocation, and it
is not this step — until it happens, the console should not be published at a public
address.

### The console

Three read-only views, served by the same application under `/console`, rendered on the
server and carrying **no JavaScript at all**. What the browser receives is the finished
HTML, and the finished HTML has already been through the filter above; with no script
there is nothing in the browser that could go and fetch more than it was handed. The only
request the page makes is for its own stylesheet, which we serve. That also means the
container needs no route to the internet: nothing comes from a CDN, and the type is
whatever the reader's system already has.

```
Observations      table filtered by site, metric and origin, with a provenance panel
Synchronisations  what ran, what failed, and what needs a human
Sites             both of them, their areas of interest, and what each one holds
```

Four design rules are binding, and each is pinned by a test in `tests/test_consola.py`:

- **Solid means measured in the parcel; hatched means it was not.** A station 5.34 km away
  and a ~9 km cell are not measurements on site, and the hatch says so without a legend.
  It is a channel *independent of colour* on purpose — around 8% of men have difficulty
  with red/green, and this is the distinction the whole product exists not to erase. Every
  row also says it in words, so it survives a stylesheet that never loads.
- **A range is drawn as a range.** The water balance returns `value_min`/`value_max` while
  it does not know; the midpoint of 0 to 93.12 mm is a number nobody measured and reads as
  "about half the reservoir". Neither the text nor the bar ever draws it.
- **A saturated reading shows as `≥ value`,** never as the value. 2000 on a scale that
  saturates at 2000 is a lower bound, not a measurement.
- **The frame is neutral and cold; the colour is only in the data,** and it comes from the
  domain: provenance in the **10YR** hue of Munsell soil charts, varying in value from the
  most direct measurement to the most distant; vegetation brown to green (*browning* /
  *greening*); water dry to wet. **Never a rainbow.** Light and dark themes, both of them
  cared for.

A row whose provenance was never recorded structurally **says so** rather than showing an
empty panel — the 27 field readings are in that position, having been written before the
field existed, and an empty panel reads as "there is nothing to say about this" when the
truth is the opposite.

**There are no charts, and the absence is deliberate.** A chart can imply what a text does
not state: a continuous line between a field reading and a reanalysis cell says "this is
one series", and it is not. Exactly one day in the production database carries two
provenances and none carries three. There is one bar per row, and only where the domain is
not invented — normalised indices live between -1 and 1 by construction, and available soil
water between zero and the capacity written in the row's own evidence. A bar joins no
points, and the bar of a range draws the whole band.

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
| `simulated` | [Water-balance](#water-balance--a-model-over-the-series-already-stored) output — a model, **not a measurement** |
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
GET /api/v1/sites/{code}/timeseries?metric=soil_available_water
```

```json
{
  "site_code": "EUC-TUR-01",
  "metric": "ndvi",
  "point_count": 22,
  "source_types": ["satellite_observed"],
  "points": [
    {
      "observed_at": "2026-08-01T00:00:00Z",
      "value": 0.48520387152697747,
      "value_min": null,
      "value_max": null,
      "value_qualifier": "exact",
      "unit": "index",
      "source_type": "satellite_observed",
      "quality_flag": "unchecked",
      "plot_code": null,
      "processing_version": "s2-ndvi-ndmi-ndre-scl-v2+9d560fddf3f1"
    }
  ]
}
```

**Twenty-two points for eleven acquisitions, and that is not a duplicate.** The masked and
unmasked scripts both produced a value for each acquisition and both are stored; the
`processing_version` is what tells them apart, and the route hands back the pair rather
than choosing between them. Nor is a satellite point ever `valid` — nothing here checks the
quality of a spectral index, so the flag says `unchecked` and the pixel counts on the row
are left for the reader to threshold.

**A point can be a band instead of a number.** `value_min`/`value_max` are filled and
`value` is null wherever the value is only known to lie between two bounds — which is what
the water balance produces for every day before its interval collapses:

```json
{
  "observed_at": "2026-07-01T00:00:00Z",
  "value": null,
  "value_min": 0.0,
  "value_max": 93.121741771698,
  "value_qualifier": "range",
  "unit": "mm",
  "source_type": "simulated",
  "quality_flag": "unchecked",
  "plot_code": null,
  "processing_version": "water-balance-single-reservoir-v1+awc100mm"
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

**But the three do not yet meet on a single day, and the response does not say so.** In the
production database the screening readings run 22–24/08, the reanalysis ends on 22/08 and
the station series begins on 28/08. **Exactly one day carries two provenances — 22/08, the
probe and the reanalysis cell — and no day carries all three.** The route puts them in the
same response because they are the same metric at the same site, not because they can be
compared; a reader who takes that response as a field-against-model comparison is looking
at one day of overlap. Widening it is a matter of running the syncs on a clock and going
back to the ground, not of changing the route.

**And one route answers "what does this site have, and where did each row come from".**

```http
GET /api/v1/sites/{code}/observations
GET /api/v1/sites/{code}/observations?metric=ndvi&source_type=satellite_observed&limit=50
```

The time series route needs a metric, so it only answers whoever already knows the name of
what they want; there was no question of the form "what is in here". Any client wanting to
show a table had to carry the list of metrics inside itself, and a list like that ages in
silence. This one returns the site's inventory — every metric, its unit, which origins
answer it, how many rows and over what span — **always for the whole site, never for the
filter**, so a filter cannot erase its own options. Alongside it come the matching rows,
each carrying `evidence`, `method`, `source_collection` and `notes`: the structured
provenance the series route deliberately leaves out, because a point on a series is a
time/value pair. `total` counts what matches and `returned` what came back, so a truncated
listing cannot be read as the whole list. `limit=0` returns the inventory with no rows.

### Which runs need a human

Every ingestion leaves a row in `ingestion_jobs`, and several deliberate design decisions
lean on that row being read: an absurd station value brings the job down instead of being
dropped in silence, so does a station swapped under the same identity, so does a wrong
timezone. Failing loudly is only better than losing data quietly if somebody looks.

```http
GET /api/v1/jobs?needs_attention=true
GET /api/v1/jobs?status=failed&job_type=reanalysis_sync
GET /api/v1/jobs?min_uncovered_days=30
```

Every row carries an `attention` verdict — `failed`, `never_finished`, or
`succeeded_without_writing` — and `null` when there is nothing to flag. `GET /jobs/{id}`
carries the same verdict, so the job handed back by a `sync` call can be checked without
knowing the listing exists. There are four job types — `eo_sync`, `ipma_sync`,
`reanalysis_sync` and `water_balance_sync` — and the production database currently holds
**25 jobs**, three of them `failed`. One of those three was made to fail on purpose, so
that a `202` carrying a failure exists in the database as evidence rather than as a claim.

**Two windows, not one.** Each job records the window it *asked for* next to the window it
*covered*, and `uncovered_days` counts the days of the first that fall outside the second.
Without the pair the job was always right: both sides of any comparison came from the same
run. With it, a run that asked for 60 days and covered 2 says so in its own row — which is
exactly what two reanalysis runs did on 29 August 2026 while reporting success, having
written 6 rows where there were 159.

**That difference is reported, never judged.** An archive that publishes with a delay, and
a winter month with no usable acquisition at all, produce the same shape as a series that
was genuinely lost — they differ only in magnitude, and any boundary drawn between them
would be invented. So the count is on the row and the threshold belongs to whoever asks:
`min_uncovered_days` has no default that judges, and a job with no recorded requested
window reports `null` rather than zero. The same restraint applies to the rest of the
verdict — a repeat of a request that already wrote its rows is deliberately quiet, because
deduplication means it writes zero and flagging that would fill the list with noise. The
reasoning, including what the pair still cannot see, is in `src/resoiltwin/attention.py`.

Interactive API documentation is generated from the code and served at `/docs`, behind
the same key as everything else — see [Every route needs a key](#every-route-needs-a-key).

---

## Architecture

```
  field readings   ─┐
  Copernicus       ─┤
                    ├─→  ReSoilTwin API  ─→  PostgreSQL + PostGIS
  weather stations ─┤          ↑  │                 │
  climate archive  ─┘          │  │                 │
                               │  │     water balance (no external call:
  browser ─→ console ─→ layer ─┘  │     reads the stored series, writes
             (3 views) (holds     │     `simulated` back beside them)
                        the key)  │
                                  │
                                  └─→  ingestion jobs (idempotent, auditable)
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

# WRITE_API_KEY arrives empty and there is no default. Generate one and write it
# into .env, or nothing but /health will answer:
python -c "import secrets; print(secrets.token_urlsafe(32))"

docker compose up -d db
alembic upgrade head

uvicorn resoiltwin.main:app --reload
```

The API is then at `http://127.0.0.1:8000`. **Every route wants an `X-API-Key` header**,
`/docs` included, except `GET /api/v1/health` and the console layer under `/console`
(which puts the header on for you — see
[The layer that holds the key](#the-layer-that-holds-the-key)). The two calls that tell
you the installation is alive are these:

```bash
curl "http://127.0.0.1:8000/api/v1/health"                            # no header, 200
curl -H "X-API-Key: <the key>" "http://127.0.0.1:8000/api/v1/sites"   # header, 200
```

A 401 from the second means the key is wrong or missing from the request; a 503 means
`WRITE_API_KEY` never reached the process. The distinction is deliberate — see
[Every route needs a key](#every-route-needs-a-key).

**The `.env` step is not optional.** `DATABASE_URL` has no default value — `Settings`
raises `MissingDatabaseUrlError` and refuses to start without it, naming the variable and
pointing back at this section. That is deliberate: a misconfigured environment must fail
loudly instead of silently falling back to some other database.

**`WRITE_API_KEY` has no default either**, but its absence does not stop the application:
it closes every route except `/api/v1/health` (503), which keeps the installation
diagnosable — the probe answers and the log names the variable. Set it in `.env` before
you use the API at all; `scripts/restore_dev_data.py` drives the HTTP routes and refuses
to start without it.

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
seconds: the Climate Data Store takes one request per variable per month, so each
reanalysis sync over that window is now **eight** of them — it was six before the
reference evapotranspiration was added.

**Only part of the end state has a number to check against, and the script says which.**
The reproducible part is **139 observations** — 27 field readings, 4 derived VPD, 54 `v1`
and 54 `v2` — and the script fails if that count comes out different. That number is about
the reproducible set and nothing else; it is not, and never was, the size of the database.
The two weather series are reported next to it but not demanded:

- the **reanalysis** is short until the archive publishes the whole window. A complete
  60-day window is now **480 rows** — 60 days × **4** metrics × 2 sites — because the
  reference evapotranspiration joined the three default variables on 30/08/2026, so that
  the water balance would find its dominant input already there. (The target the script
  prints alongside is still `360`, counting three: a constant left behind when the fourth
  arrived, and worth knowing before you read its output as a shortfall.) The run of
  29/08/2026 wrote 318 over three variables, ending on 22/08; the 30/08 run added the
  missing 106 and brought the series to 424;
- the **station** series has no expected number at all. The feed publishes the last 24
  hours, so what lands depends on when the script runs; the run of 29/08/2026 wrote 240.

**The restore does not run the water balance, and that is not an oversight.** The balance
needs a capacity that nobody has measured, and there is no honest default to bake into a
restore script — so its 318 rows are produced by calling the route by hand, with the
capacities written out, exactly as the Fase D note records. A restored database is
therefore a *smaller* thing than the production one: the run of 29/08/2026 that the Fase C
evidence note describes ended at **697 observations** — the 139, plus 318 reanalysis and
240 station rows — while the production database today holds **1121**, the 697 plus 106
evapotranspiration rows and 318 simulated ones. Anyone re-running the script later will get
the same 139, more reanalysis rows, different station rows, and no simulated ones, and none
of those differences means anything went wrong.

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

No test reaches the network. Every external call is mocked. At `HEAD` on 31/08/2026 that
is **808 tests**, all green, with `ruff check .` clean.

Passing is not the same as covering; what the suite would actually have *caught* is
measured separately — see
[Measuring what the tests actually catch](#measuring-what-the-tests-actually-catch).

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

## Deploying

The Azure infrastructure is written as Bicep templates in
[`infra/`](infra/), and the step-by-step guide is
[`docs/deployment.md`](docs/deployment.md).

**None of it has been deployed.** The templates exist so that whoever has the
authority to create resources can run them; no resource was created and no
subscription was authenticated against while they were written.

A container image is built from the [`Dockerfile`](Dockerfile) at the root. It
is Debian-based and that is not a style choice: four of this project's
dependencies are native extensions that ship the system library inside the
wheel — shapely carries GEOS, pyproj carries PROJ, netCDF4 carries HDF5 and
netcdf-c, psycopg carries libpq. Those wheels are manylinux, which is glibc. On
a musl base none of them apply and pip falls back to compiling all four from
source. On glibc the image needs no `apt` package at all.

Before deploying, read
[`docs/fase-e-decisoes-pendentes.md`](docs/fase-e-decisoes-pendentes.md). It is
the register of what only the project owner can decide, and it records the
answer next to the reasoning rather than replacing one with the other.

**Five of those decisions were taken on 31/08/2026**, and none of them
provisioned anything:

| | Decision | Answer |
|---|---|---|
| 1 | region | **West Europe** — applied when the resource group is created, not written into any template |
| 2 | public surface | **nothing public**, which is what widened the key from the write routes to all of them |
| 5 | environments | **development only, for now** — a second one is the same deployment with another tag |
| 7 | authentication | **a shared key on every route**, `GET /api/v1/health` excepted so the platform probe can reach it |
| 8 | how secrets reach the app | the variant a *Contributor* can run end to end — **accepted technical debt**, not the right answer |

Decision 7 is the one that changes how anybody uses this system; see
[Every route needs a key](#every-route-needs-a-key) for what it does and, just as
importantly, what it does not do. `WRITE_API_KEY` is a Key Vault secret like the
others and the deployment guide creates it.

Decision 8 is the one to read before trusting the deployment with anything real.
Binding the application to the Key Vault through a managed identity needs two
role assignments, and creating role assignments is outside what a *Contributor*
can do — so the templates default to handing the secrets over at deployment time
instead. That means a copy of every secret outside the vault, a long-lived
registry admin account nothing rotates, and a rotation that requires
redeploying. The privileged half is isolated in a single file that takes two
minutes to run on the day somebody with the authority exists, and the guide
writes both variants side by side.

**Eight decisions are still open**, and the file names them rather than guessing:
where the official copy of the parcel geometries lives and who answers for it,
who holds the external credentials, what the first real case to demonstrate is,
which database user the API runs as, what schedules the ingestion, how long
backups are kept, who answers for the bill, and whether the telemetry resource
gets instrumented or stays empty.

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

### Measuring what the tests actually catch

A green suite says the tests pass, not that they would have noticed. The mutation harness
in [`tools/mutacao/`](tools/mutacao/) answers the second question: it copies the repository
to a temporary tree, changes one line of production code there so that it states something
false about the domain, runs the whole suite, and asks whether any test fell over. A
survivor is behaviour nobody is defending.

```sh
python tools/mutacao/arnes.py tools/mutacao/rondas/<round>.py
```

**It has found more real defects in this project than any other check**, including tests
that could not fail and two bugs in production code — and it is worth knowing that the
harness itself lied three different ways on its first day, each lie now held down by a
guard with a test that makes the guard fire. A round is a throwaway file listing the
mutants for one piece of work; each is committed next to the work it measured, so the
rounds in `tools/mutacao/rondas/` are the record of what was checked and when. The design,
the twelve guards and what each one was born from are documented in
[`tools/mutacao/README.md`](tools/mutacao/README.md), which is in Portuguese like the rest
of the internal record.

---

## Status

The observation model, the API, the Copernicus connector, the weather layer and the
water-balance model are implemented, tested and have each run against real data. **The web
console exists and has never been published** — it is three read-only views over what is
in the database, described in [The console](#the-console), and it has only ever been
opened against a local database. The Azure infrastructure exists as templates that have
never been run — see [Deploying](#deploying).

Every phase that ran left a dated note, and those notes are the primary record; this file
summarises them and they win wherever the two disagree:

| Note | What it records |
|---|---|
| [`2026-08-28-fase-a.md`](docs/evidence/2026-08-28-fase-a.md) | the schema and the API, verified end to end from an empty database |
| [`2026-08-29-fase-b.md`](docs/evidence/2026-08-29-fase-b.md) | the first real Copernicus series — and the warning that three of them are contaminated by cloud |
| [`2026-08-29-mascara-scl.md`](docs/evidence/2026-08-29-mascara-scl.md) | per-pixel cloud masking, and three wrong claims made and retracted along the way |
| [`2026-08-29-fase-c.md`](docs/evidence/2026-08-29-fase-c.md) | the first real weather ingestion, station and reanalysis |
| [`2026-08-30-fase-d.md`](docs/evidence/2026-08-30-fase-d.md) | the first real water-balance run, and why nothing but zero came out of it |

The production database holds **1121 observations** across six provenances and **25
ingestion jobs**, at migration `0011`.

**The weather layer has run for real twice** — on 29/08/2026, written up in
[`docs/evidence/2026-08-29-fase-c.md`](docs/evidence/2026-08-29-fase-c.md), and again on
30/08/2026 to fetch the reference evapotranspiration the water balance needed, which added
106 rows and wrote nothing else, because deduplication refused the three variables that
were already there. Two things from the first run it is important not to read past. The station series has **no history before
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

Four things have been learned since that paragraph was first written, and each of them
makes it narrower rather than wider:

- **The water balance ran, and every determined value it produced is zero.** Over the 53
  days it covered, Turcifal received 3.48 mm of precipitation against 303.95 mm of
  reference evapotranspiration — 1.1 % — and the wettest day never reached the least
  thirsty one, so the trajectory starting from an empty reservoir never left the floor.
  Every collapse of the interval was on the floor and none on the ceiling. **That run
  exercised the path through the system, not the model.** Overflow and the cut across a
  gap in the series are still held up by tests and mutants alone. "We have a water
  balance" and "the water balance has been shown to work on real data" are different
  sentences, and only the first is true.
- **The soil's available water capacity has never been measured on this ground.** There is
  not one soil analysis of these sites in this project, and that parameter dominates the
  output. Making it mandatory, putting it in the row's identity and recording
  `capacity_is_measured: false` beside it made the result **auditable, not true**. No
  amount of work in the code substitutes for a soil analysis.
- **Field and reanalysis have met on exactly one day.** The screening campaign ran 22–24/08
  and the reanalysis archive, publishing about a week behind, reached 22/08 — so a single
  day carries both, and **no day carries all three provenances**, because the station
  series only begins on 28/08. Nothing here has been validated against anything; there has
  not yet been enough overlap to try.
- **None of the model's inputs is measured in the parcel.** They come from a reanalysis
  cell roughly 9 km across, which means two parcels inside the same cell receive exactly
  the same rain and the same evapotranspiration.

---

## License

Proprietary. © Euro Union Consult, Lda.
