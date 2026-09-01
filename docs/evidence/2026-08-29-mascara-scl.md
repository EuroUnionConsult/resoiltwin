# Evidence — per-pixel SCL mask, and what it says about 24/08 (29/08/2026)

> *Written in Portuguese on 29–30/08/2026, translated into English on 01/09/2026. The
> English text is the normative version of this note; the Portuguese original stands
> unchanged in the repository history at commit `bf3fd90`. The retractions in this note
> are translated as retractions: nothing that was wrong has been quietly tidied away.*

This note answers a question left open on 28/08/2026: **were the anomalous indices of 24
August over Campo Real cloud contamination, or were they signal?**

The Phase B note (`docs/evidence/2026-08-29-fase-b.md`) left the question open
deliberately — *"the values are anomalous; neither of the two explanations has been
excluded; excluding one of them requires a pixel-level cloud mask, which this pipeline
does not apply"*. The pipeline now applies it. This note brings the numbers.

**This note supersedes the provisional formulation of 28/08, and there is an earlier
record to correct.** See the final section.

Every number below was collected on 29/08/2026, between **12:06 and 13:15 UTC**, against
the local `resoiltwin` database and against the Copernicus Data Space Ecosystem. Nothing
was carried over from the Phase B note except, where it is said so, the `v1` values that
are still stored in the database and were re-read from there.

> **Reproducibility warning.** The development database was deleted by accident later the
> same day and restored from scratch. **Every value in this note was reconfirmed on the
> restored database, number by number.** The identifiers were not: the job and
> area-of-interest UUIDs quoted below, and the `started_at`/`finished_at` marks, belong to
> the original 12:06 run and do not come back. See *"The database was restored — what
> reproduces and what does not"*, at the end.

---

## The short answer

**On 24/08/2026, 57 432 of the 62 750 pixels over Campo Real — 91.5% of the area of
interest — were excluded by the SCL mask as cloud, shadow or cirrus.** The pixels
producing the drop were identified **one by one** by the scene classification, and
removing them moves the indices strongly in the expected direction: NDVI rises from
0.2111 to 0.4130, NDRE from 0.1531 to 0.3018. **The drop in NDVI and NDRE on 24/08 was
cloud: that is confirmed.**

**What is not confirmed is the value that remains.** The 5 318 remaining pixels are
**8.5% of the area**, and they are not a random sample of it: they are exactly the
windows that happened to be clear in a landscape 92% covered. And that holds for all
three indices at once — 0.4130, 0.3018 and 0.2313 are **the same average over the same
5 318 pixels**. None of the three is an estimate of the true index over the area of
interest on 24/08, and none of the three compares with the whole-area averages of the
other days.

**The two claims are kept separate on purpose, and the note of 28/08 did not separate
them.** One is about the *cause* of the drop and is demonstrated by the per-pixel count;
the other would be about the *level* of the index that day, and it is not. **24/08 can be
explained, but it cannot be measured.**

One further observation is recorded that concerns the same day and survives this caveat
intact, because it compares 24/08 with itself: on the other three partially covered
dates, removing cloud *lowered* NDMI; here it **raised** it, from 0.1847 to 0.2313. This
is recorded, not explained.

And, on the way to this answer, the reason this task exists is demonstrated with numbers:
**the scene cloud percentage does not decide whether the area of interest is
contaminated.** There is an association between the two — it is not noise — but it breaks
down in exactly the cases where we would need it.

---

## What was run

Two real `sync` calls, one per area of interest, through the HTTP routes, with the mask
on (`scl_mask` defaults to `true`), over the window **2026-08-01 to 2026-08-29**.

```bash
cd <repository root> && source .venv/bin/activate
set -a && . ./.env && set +a
alembic upgrade head
uvicorn resoiltwin.main:app --host 127.0.0.1 --port 8031 &

API=http://127.0.0.1:8031/api/v1
curl -X POST $API/sites/EUC-TUR-01/eo/sync -H 'Content-Type: application/json' \
  -d '{"aoi_code":"EUC-TUR-EO1","date_from":"2026-08-01","date_to":"2026-08-29","scl_mask":true}'
curl -X POST $API/sites/EUC-PTO-01/eo/sync -H 'Content-Type: application/json' \
  -d '{"aoi_code":"EUC-PTO-EO1","date_from":"2026-08-01","date_to":"2026-08-29","scl_mask":true}'
```

The real response of both:

```
HTTP 202
{"id":"66a47279-1757-42ca-a385-a07b8f4f3a68","aoi_id":"352d4000-ff52-459a-ad30-07a9c1279431",
 "job_type":"eo_sync","status":"succeeded","date_from":"2026-08-01","date_to":"2026-08-29",
 "request_hash":"0a4bb5ac47a3e414703d16fb7dd96bc9ee69abc665f760b8b968c8a2ddbbd50b",
 "started_at":"2026-08-29T12:06:14.795521Z","finished_at":"2026-08-29T12:06:18.398835Z",
 "rows_written":33,"error":null}

HTTP 202
{"id":"b0edfb53-acc5-4e1a-ae02-d8958e9be2ff","aoi_id":"b93ce717-a8fa-4f3a-a8df-76e7debce3e7",
 "job_type":"eo_sync","status":"succeeded","date_from":"2026-08-01","date_to":"2026-08-29",
 "request_hash":"9489a99418a19be61f5bb9d1b14e4cb397a8910c12f54f74dda360add41e6ac3",
 "started_at":"2026-08-29T12:06:27.891775Z","finished_at":"2026-08-29T12:06:29.336565Z",
 "rows_written":21,"error":null}
```

**Both came back `succeeded`, and it is the `status` that says so, not the 202.**
`sync_aoi()` does not propagate failures: a job that blows up in the Statistical API also
comes out with 202 and with `status: "failed"`. It was the `status` field that was read,
in both.

33 rows = 11 dates × 3 indices. 21 = 7 × 3. The same totals as Phase B, because the same
dates still have acquisitions — the mask does not eliminate dates, it changes values.

**The window was extended to 29/08 on purpose**, one day past the end of Phase B. No new
date appeared: the last usable Turcifal acquisition is still 24/08. The Catalog explains
why — see the cloudiness table further down.

### `v1` was left intact

```
$ count by source_type and processing_version
('derived',             'vpd-tetens-v1',                     4)
('observed_screening',  'field-campaign-v1',                27)
('satellite_observed',  's2-ndvi-ndmi-ndre-scl-v2+9d560fddf3f1', 54)
('satellite_observed',  's2-ndvi-ndmi-ndre-v1+f03f9beed32d',     54)
total 139
```

The 54 original rows are still there, with the old `processing_version`
(`s2-ndvi-ndmi-ndre-v1+f03f9beed32d`), and the 54 new ones sit beside them with
`s2-ndvi-ndmi-ndre-scl-v2+9d560fddf3f1`. 85 → 139. **The two series coexist, which is
what makes this comparison possible at all:** the `processing_version` is part of the
observation's identity (`uq_observation_identity`), so the masked series neither replaces
nor erases the unmasked one.

This count describes the state of the database at 12:06. After the database was deleted
and restored, still on 29/08, the count is the same — 139, with the same breakdown — but
the 54 `v1` rows are no longer the originals from 28/08: they were re-ingested. See the
final section.

---

## The comparison, date by date — `EUC-TUR-01` / Campo Real

The **contrib** column is `sampleCount − noDataCount`, not the `valid_pixels` field of the
`evidence` — which, despite the name, holds the `sampleCount` and includes the discarded
pixels. It is the trap already recorded in Phase B.

> **Corrected on 30/08/2026, after this note.** The field was renamed `sampled_pixels`,
> which is what it always held, and the new rows carry `contributing_pixels` beside it —
> the subtraction done by the pipeline, per index, rather than by the reader. The 108 rows
> already stored were renamed in a migration (`0010`) without the number changing; they did
> not receive `contributing_pixels`, because only an upper bound survives for them and
> inventing an exact value here would have repeated the original defect. In the same
> migration, the satellite rows stopped declaring `quality_flag = 'valid'` — a literal with
> no condition behind it — and became `unchecked`: it is this note that declares 24/08
> unusable, and until that day the code did not know it. No number in this table changed.

| date | NDVI v1 | NDVI v2 | Δ | NDMI v1 | NDMI v2 | Δ | NDRE v1 | NDRE v2 | Δ | contrib v1 | contrib v2 | excluded pixels | % of the area |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-01 | 0.4851 | 0.4852 | +0.0001 | 0.0543 | 0.0543 | +0.0000 | 0.3395 | 0.3395 | +0.0001 | 62 750 | 62 702 | 48 | **0.08%** |
| 2026-08-04 | 0.3966 | 0.4848 | +0.0882 | 0.0748 | 0.0591 | −0.0157 | 0.2847 | 0.3455 | +0.0608 | 62 750 | 32 253 | 30 497 | **48.60%** |
| 2026-08-06 | 0.4657 | 0.4658 | +0.0001 | 0.0278 | 0.0279 | +0.0001 | 0.2999 | 0.3000 | +0.0000 | 62 750 | 62 702 | 48 | 0.08% |
| 2026-08-08 | 0.4338 | 0.4338 | +0.0000 | 0.0248 | 0.0248 | +0.0000 | 0.3072 | 0.3072 | +0.0000 | 62 750 | 62 734 | 16 | 0.03% |
| 2026-08-09 | 0.3485 | 0.4380 | +0.0895 | 0.0768 | 0.0584 | −0.0184 | 0.2268 | 0.2948 | +0.0680 | 62 750 | 24 449 | 38 301 | **61.04%** |
| 2026-08-11 | 0.4749 | 0.4750 | +0.0001 | 0.0311 | 0.0312 | +0.0001 | 0.3321 | 0.3321 | +0.0000 | 62 750 | 62 698 | 52 | 0.08% |
| 2026-08-16 | 0.4611 | 0.4611 | +0.0000 | 0.0139 | 0.0140 | +0.0001 | 0.3028 | 0.3028 | −0.0000 | 62 750 | 62 706 | 44 | 0.07% |
| 2026-08-18 | 0.4415 | 0.4415 | +0.0000 | 0.0108 | 0.0109 | +0.0001 | 0.3111 | 0.3111 | +0.0000 | 62 750 | 62 718 | 32 | 0.05% |
| 2026-08-19 | 0.4107 | 0.4431 | +0.0324 | 0.0373 | 0.0317 | −0.0056 | 0.2733 | 0.2948 | +0.0216 | 62 750 | 45 015 | 17 735 | **28.26%** |
| 2026-08-21 | 0.4641 | 0.4641 | +0.0001 | 0.0303 | 0.0303 | +0.0000 | 0.3256 | 0.3257 | +0.0000 | 62 750 | 62 706 | 44 | 0.07% |
| **2026-08-24** | **0.2111** | **0.4130** | **+0.2019** | **0.1847** | **0.2313** | **+0.0465** | **0.1531** | **0.3018** | **+0.1486** | **62 750** | **5 318** | **57 432** | **91.53%** |

Two sanity readings before any conclusion:

- **On the clear days, v2 reproduces v1 to the third decimal place.** That is what you
  want from a mask: where there is no cloud, nothing changes. It is not a *no-op*, though
  — 16 to 52 pixels (0.03–0.08%) are always excluded, scattered, and the effect on the
  averages is of the order of 0.0001.
- **On the partially masked days, the mask always moves the three indices in the same
  direction:** NDVI and NDRE **rise**, NDMI **falls** (04/08, 09/08, 19/08). That is the
  expected direction — cloud lowers NDVI/NDRE and raises NDMI, so removing it does the
  reverse. **24/08 is the only date that breaks this pattern:** NDVI and NDRE rise as on
  the others, but NDMI **rises too**. This is recorded, not explained.

---

## The concrete question: 24 August

**How many pixels were excluded:** 57 432 of 62 750, that is **91.53% of the area of
interest**. **5 318 pixels** remain — 8.47% of the area, about 53 ha of Campo Real's
623.6 ha.

There are **two** possible comparisons with these numbers, and only one of them is
legitimate.

**The comparison that holds is `v1` against `v2` on the same day.** Same date, same area,
same acquisition: the only difference between the two averages is the removal of the
pixels the SCL classified as cloud, shadow or cirrus. What it measures is the effect of
the contamination, and it measures it well.

| index | v1 (24/08) | v2 (24/08) | Δ | what the difference shows |
|---|---|---|---|---|
| NDVI | 0.2111 | 0.4130 | **+0.2019** | the removed pixels were pulling NDVI down — the expected direction for cloud |
| NDRE | 0.1531 | 0.3018 | **+0.1486** | the same, and it is the largest NDRE jump of the whole series |
| NDMI | 0.1847 | 0.2313 | **+0.0465** | it **rises**, unlike the other three masked dates, where removing cloud lowered NDMI |

**The comparison that does not hold is 24/08 against the rest of the series.** The other
days' averages are over the 623.6 ha of the area; 24/08's is over a ~53 ha cut-out chosen
by the geometry of the clouds. They are different quantities with the same name. The table
below stands as description — **not as a verdict** — and it holds equally for all three
indices:

| index | v2 (24/08) | range of the v2 series without 24/08 | descriptive reading |
|---|---|---|---|
| NDVI | 0.4130 | 0.4338 – 0.4852 | **falls below the minimum of the range**, not inside it |
| NDRE | 0.3018 | 0.2948 – 0.3455 | falls inside the range |
| NDMI | 0.2313 | 0.0109 – 0.0591 | 3.9× the maximum of the range (0.2313 / 0.0591 = 3.91) |

**None of those three rows is a verdict on 24/08**, and this is where the previous version
of this note contradicted itself: it used the 8.47% argument to void NDMI while at the
same time accepting NDVI and NDRE as values comparable with the other days. It is the same
average over the same 5 318 pixels. Either all three count as an estimate for the area, or
none does — and none does.

That said, what follows:

1. **The drop in NDVI and NDRE was cloud, and that is confirmed.** It is not inference:
   the pixels producing it were identified one by one by the SCL as cloud, shadow or
   cirrus, and removing them moves the two indices +0.2019 and +0.1486 in the expected
   direction. The "contamination" hypothesis is confirmed **as the explanation of the
   drop**.

2. **What is confirmed is the explanation, not the level.** That the drop was cloud does
   not make 0.4130 the NDVI of Campo Real on 24/08. And in fact 0.4130 does **not** come
   back into the range of the series: it stays below the minimum (0.4338). NDRE returns to
   the range; NDVI approaches it without entering.

3. **The rise in NDMI is not explained by cloud removal — on the contrary, it is made
   worse.** On the other three partially covered dates, removing cloud *lowered* NDMI.
   Here it raised it. This is a comparison of direction, between days, about which way the
   mask pushes — not about the level — and it therefore survives the sampling caveat.

4. **And none of the three values supports or denies the soil hypothesis.** With 8.47% of
   the area surviving, the v2 average for 24/08 **is not the same quantity** as the
   averages of the other days. There is also a concrete mechanism of residual
   contamination: our mask **keeps** SCL class 7 (*unclassified*), and in a scene 92%
   covered the surviving pixels are disproportionately adjacent to cloud, where the SCL is
   less reliable and where thin cirrus and penumbra get through.

**Conclusion on 24/08:** the date **can be explained** — the drop was cloud, demonstrated
pixel by pixel — and **cannot be measured**: too few pixels remain, and they are chosen in
too biased a way, for any of the three masked values to be the index of the landscape that
day. It serves to say that the landscape was covered and that this is what produced the
anomaly; it does not serve to say anything about the water in the landscape, neither to
confirm nor to deny what the probe read in the soil.

### The criterion, stated — and it is not only 24/08

The previous version of this note drew the line at 8.47% without ever stating it, and by
omission blessed the other partially masked dates. That does not hold: if the argument is
that the surviving pixels are chosen by the geometry of the clouds, it applies with almost
full force to 09/08, whose `v2` is an average over **39% of the area**.

**Criterion adopted, and it is a declared convention and not a discovery:** a date is used
for a landscape-level statement about `EUC-TUR-EO1` only when **at least two thirds of the
area contributes to the average**. Below that, the average describes a cut-out selected by
the cloud, and the value can only be quoted with the masked fraction glued to it. The two
thirds do not come out of the data — what comes out of the data is the ordering; the
cut-off is a choice, and it is written down so that it can be contested.

| date | % of the area masked | % contributing | status |
|---|---|---|---|
| 2026-08-19 | 28.26% | 71.74% | above the cut-off; usable, **but always quote it with the 28% masked** |
| 2026-08-04 | 48.60% | 51.40% | **below the cut-off** — not usable for a landscape-level statement |
| 2026-08-09 | 61.04% | 38.96% | **below the cut-off** — not usable |
| 2026-08-24 | 91.53% | 8.47% | far below the cut-off — not usable, and it is the case of this note |

**19/08 is close to the line.** The cut-off is two thirds (66.7%) and 19/08 contributes
71.74% — about **5 percentage points above**, the narrowest margin of all the dates
assessed. A cut-off at 75%, equally defensible as a convention, would move it to the
unusable side. The status of 19/08 depends on the choice of cut-off more than any other
date in this table.

The remaining seven Turcifal dates have 0.03–0.08% masked and are unaffected.

**Consequence for what has already been published:** the NDVI values for 04/08, 09/08 and
19/08 went out in the Phase B note as values of the series, with no caveat at all, and
**all three are contaminated** — 0.3966, 0.3485 and 0.4107 are averages with 48.60%,
61.04% and 28.26% of cloud inside them. The Phase B note now carries a warning at the top
naming all three.

---

## The counter-example: 1 August, and the demonstration that motivates the task

Phase B raised the right suspicion: the cloudiness of the **scene** does not let you
decide whether the **area of interest** is contaminated. With the per-pixel mask that
stops being an argument and becomes a measurement. Copernicus Catalog query made on
29/08/2026, with no cloud filter, for the same area and window, beside the fraction of the
area the SCL masked:

**How to read the middle column, and it has to be stated:** four dates have **two
scenes**, and the table shows both separated by `/`. Where a single number per date is
used further down — in the ordering and in the coefficients — that number is the
**maximum** of the two. It is the conservative choice for the question at hand (we want to
know whether the scene metric *lets contamination through*), but it is a choice, and it
changes the results: see the note on the coefficients.

| date | **scene** cloud (`eo:cloud_cover`) | % of the **area** masked | |
|---|---|---|---|
| 2026-08-01 | 15.50 / **29.13** | **0.08%** | ← scene almost at the threshold, area clean |
| 2026-08-04 | 24.54 | 48.60% | |
| 2026-08-06 | 0.04 | 0.08% | |
| 2026-08-08 | 0.46 | 0.03% | |
| 2026-08-09 | **7.24** | **61.04%** | ← scene almost clear, area mostly covered |
| 2026-08-11 | 5.86 / 11.44 | 0.08% | |
| 2026-08-16 | 2.16 | 0.07% | |
| 2026-08-18 | 18.03 | 0.05% | |
| 2026-08-19 | 17.82 | 28.26% | |
| 2026-08-21 | 0.12 / 0.50 | 0.07% | |
| 2026-08-24 | 29.94 | 91.53% | |

**The two flagged cases kill the scene metric as an indicator for deciding date by date —
not as an indicator in general, see the set-level association further down:**

- **01/08 has a scene at 29.13%** — by the maximum criterion, the second cloudiest of the
  window, a step away from the 30% threshold that would have excluded it — **and 0.08% of
  the area masked.** The cloud was entirely outside Campo Real. It was the highest NDVI of
  the whole series, and it still is after masking (0.4852). **This case depends on the
  criterion:** 01/08 has two scenes, 15.50 and 29.13; by the minimum it would be the 5th
  cloudiest and would stop being spectacular. The next case depends on no criterion at
  all.
- **09/08 has a scene at 7.24%** — among the cleanest — **and 61.04% of the area masked.**
  A date any scene filter would have accepted without hesitation had nearly two thirds of
  our area under cloud. The NDVI Phase B published for that day (0.3485, the lowest of the
  series after 24/08) was an average with 61% cloud inside it. **09/08 has a single
  scene**, so this counter-example is immune to the criterion of the previous paragraph
  and carries the argument on its own.

Over the two 11-point series, the correlation between scene cloudiness and masked fraction
of the area is, **by the maximum**, **r = 0.511** (Pearson) and **ρ = 0.520** (Spearman,
mid-ranks for ties, as in `scipy.stats.spearmanr`). By the **minimum** it gives **r =
0.681** and **ρ = 0.543**. All four values are computed over the "% of the area masked"
column **as the table shows it**, rounded to two decimal places; over the excluded-pixel
counts, unrounded, the minimum's ρ gives **0.548** — the difference is the rounding
deciding ties that do not exist in the raw data (see next), not a correction to the number.

**Correction to an earlier version of this note, which quoted ρ = 0.473.** That value
comes from **ordinal** ranks, with ties broken by sort order. With the standard definition
the coefficient is 0.520. The correction changes nothing in the conclusion, and that is
exactly why it is being made: the number was wrong and correcting it cost nothing.

**A note on the ties, because the earlier description was wrong.** "0.08%" appears three
times in the rounded column (01/08, 06/08, 11/08) and "0.07%" twice (16/08, 21/08) — but
that is an effect of the rounding, not of the pixel count: in raw terms those three dates
have 48, 48 and 52 excluded pixels. The genuine ties are **48/48** (01/08 and 06/08) and
**44/44** (16/08 and 21/08); 11/08 (52 pixels) comes close but is not tied. The argument
about the fragility of the scene metric holds either way — the rank ordering is practically
the same with or without the pseudo-ties — but the description of the ties was wrong and is
corrected here.

**How to read those four numbers:** with n = 11 and a distribution like this one they are
descriptive and nothing more, and the difference between 0.511 and 0.681 depending on
whether you take the maximum or the minimum shows how much freedom there is in the choice.
What can be said is that **there is a positive, moderate association** — more cloud in the
scene tends to go with more cloud over the area — and that this association **is no use for
deciding date by date**, which is what the two cases above show. What supports the
conclusion is the cases, not the coefficient.

**Practical consequence, and it holds beyond this window:** `maxCloudCoverage` at the scene
level is not a quality control for the area of interest. **It is not useless, and one
should not say it predicts nothing** — the association is there, and the filter avoids
spending requests on entirely covered scenes. What it does not do is say what is happening
over our polygons on a given day, which is the decision we have to make. Only the per-pixel
count says that.

### Why no new date appeared up to 29/08

The Catalog, queried with no cloud filter, shows three overpasses the `sync` did not use,
all of them above the 30% threshold:

```
2026-08-14  cloud_cover=[80.40]   above the threshold
2026-08-26  cloud_cover=[73.82]   above the threshold
2026-08-28  cloud_cover=[33.52]   above the threshold, only just
```

So: extending the window to 29/08 picked up two new overpasses (26 and 28), and neither
entered. The one on 28/08, at 33.52%, misses the threshold by 3.5 points — and, in the
light of the table above, **it cannot be said whether the area was covered that day or
not**: the scene percentage does not say. Repeating that day with a higher threshold and
reading the per-pixel count is what would answer it, and it has not been done.

---

## `EUC-PTO-01` / Requesende park — the mask changes nothing

| date | NDVI v1 | NDVI v2 | NDMI v1 | NDMI v2 | NDRE v1 | NDRE v2 | contrib v1 | contrib v2 | excluded |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-06 | 0.4074 | 0.4074 | 0.0207 | 0.0207 | 0.2683 | 0.2683 | 1 095 | 1 095 | 0 |
| 2026-08-08 | 0.4041 | 0.4041 | 0.0171 | 0.0171 | 0.2851 | 0.2851 | 1 095 | 1 095 | 0 |
| 2026-08-09 | 0.4091 | 0.4091 | 0.0112 | 0.0112 | 0.2817 | 0.2817 | 1 095 | 1 095 | 0 |
| 2026-08-11 | 0.3393 | 0.3393 | 0.0047 | 0.0047 | 0.2456 | 0.2456 | 1 095 | 1 095 | 0 |
| 2026-08-16 | 0.4377 | 0.4377 | 0.0045 | 0.0045 | 0.2916 | 0.2916 | 1 095 | 1 095 | 0 |
| 2026-08-18 | 0.4072 | 0.4072 | 0.0131 | 0.0131 | 0.2931 | 0.2931 | 1 095 | 1 095 | 0 |
| 2026-08-21 | 0.4135 | 0.4135 | 0.0204 | 0.0204 | 0.2983 | 0.2983 | 1 095 | 1 095 | 0 |

**Zero pixels excluded on all seven dates, and the values identical to the fourth decimal
place.** The seven dates Porto has are the seven on which the scene was clear over it; the
cloudy dates (1, 4, 19 and 24 August, all above 30% at Porto) never entered at all. It is a
useful control: it shows that v2 introduces no systematic drift, and that what is seen at
Turcifal on 24/08 is localised cloud, not an artefact of the new script.

Porto's 1 406 `no_data_pixels` are still geometry — pixels of the bounding box outside the
park's irregular polygon — and not cloud.

**A new limitation, and it needs recording:** in v2, `no_data_pixels` starts to add two
different things — pixels outside the polygon **and** pixels excluded by the SCL — without
distinguishing them. At Turcifal they are separable because v1 gives 0 outside the polygon;
at Porto they are separable because the SCL excluded 0. On an irregular area with partial
cloud they would stop being separable. Storing the two counts separately is left as
technical debt.

---

## What changed in the code

**`processing_version` on the `IngestionJobRead`.** Until now, through the API, there was
no way to tell whether a job had run with the mask without going to the observations table
— and a job that wrote zero rows had nowhere to be read from at all. The column was added
to `ingestion_jobs` (migration `0007`), is filled at the moment the job is created (before
the network, so that a failed job also declares it) and comes out in the response of both
routes.

The column is **nullable and there is no backfill**. Jobs predating the migration —
including the two in this note, which ran before the column existed — read `null`, and
`null` means *"not recorded"*, not *"no mask"*. Filling them with the version they are
presumed to have used would be writing provenance nobody observed, which is the opposite of
what this column exists to allow:

```
$ curl -s $API/jobs/66a47279-1757-42ca-a385-a07b8f4f3a68
{"id":"66a47279-...","job_type":"eo_sync","status":"succeeded",
 "request_hash":"0a4bb5ac...","processing_version":null,
 "rows_written":33,"error":null}
HTTP 200
```

The version of these two jobs is recoverable from the rows they wrote
(`s2-ndvi-ndmi-ndre-scl-v2+9d560fddf3f1`), which is exactly the manual work the field
spares from now on.

Four new tests cover it: the version declared by the job matches the one that ended up on
the observations; the two mask choices are distinguishable from the route alone; **a
`failed` job still declares the version it tried to run with** — the case that justifies
storing it on the job rather than deducing it from the observations; and `GET /jobs/{id}`
returns the same as the `POST`.

---

## Earlier record to correct

The Phase B note (`docs/evidence/2026-08-29-fase-b.md`, section *"The 2026-08-24 anomaly,
and what cannot be concluded from it"*) says:

> the values for 2026-08-24 are **anomalous** relative to the rest of the series;
> **neither** of the two explanations — real signal or contamination — has been excluded.

**That formulation is superseded.** With the per-pixel mask:

- For the **drop in NDVI and NDRE**, the contamination explanation is **confirmed**, not
  merely not excluded. 91.53% of the area was cloud, shadow or cirrus, and removing it
  moves the two indices +0.2019 and +0.1486 in the expected direction.
- **Confirmed as the explanation of the drop, not as a measurement of what lies beneath.**
  The masked NDRE falls inside the range of the series; the masked **NDVI does not** —
  0.4130 stays below the minimum, 0.4338. And neither of the two is comparable with the
  other days, because it rests on the same 8.47% of the area that disqualifies the NDMI.
- For the **NDMI**, neither of the two explanations has been excluded — and the masked value
  does not help decide, for the same reason and no other.
- The claim that there was **"the project's first soil↔satellite correspondence"** on 24/08
  remains unsupported, and now for a documented reason instead of a suspicion: the value
  quoted came from an area 92% covered.

**And there is a second correction, about the reasoning and not about the conclusion.** The
retraction made on 28/08 attributed the anomaly to cloud. The only measure of cloud that
existed on that date was the 29.94% of the scene — and this note shows that this number did
not support the inference: 01/08, at 29.13%, had 0.08% of the area masked, and 09/08, at
7.24%, had 61%. **The conclusion was right; the indicator it rested on does not decide the
case.** Anyone repeating the argument in the form *"it was cloud, the scene was at 30%"* is
leaning on a metric that, on its own and on a given day, the data in this note shows to be
insufficient. The proof is the per-pixel count, and only that.

---

## What this note still does not confirm

The three caveats of Phase B stand in full, and the mask touches none of them:

1. **The satellite does not measure soil moisture.** NDVI, NDMI and NDRE respond to
   vegetation cover. The project's only soil measurement is still the screening probe.
2. **None of this is agronomic validation.** No calibration, no established correlation,
   over 29 days of August 2026 and two areas.
3. **There is still no weather layer and no Sentinel-1.** Without a water balance, no
   spectral index converts into a statement about water in the soil; and without radar, the
   covered days have no coverage at all — 24/08 is precisely the day on which that would
   have made a difference.

A fourth is added, specific to this phase:

4. **The SCL mask is not absolute truth.** It is the L2A product's own classification, with
   its own false positives and negatives, and we keep class 7 (*unclassified*) because it is
   real surface in the overwhelming majority of cases. In a mostly covered scene that choice
   lets in more doubt than in a clear one.

---

## The database was restored — what reproduces and what does not

After this note was written, still on 29/08/2026, the development `resoiltwin` database was
**deleted by accident**: an `alembic downgrade base` intended for an isolated clone ran
against it, because the environment variable that was exported is not the one `Settings`
reads and the connection fell back to the default — which is the real database. Zero rows in
every table.

The database was restored from scratch by `scripts/restore_dev_data.py`: the field seed, then
the Porto site and the two areas of interest through the HTTP routes with the geometries read
from the same GeoJSON files, then four Copernicus synchronisations over the same window — each
area with and without the mask, which recreates the `v1` and `v2` series side by side. The
four jobs came back `succeeded`, with 33 + 21 + 33 + 21 rows, and the database returned to 139
observations with the same breakdown by `source_type` and `processing_version`.

**What did reproduce, and it is what matters:** *every* value in this note. The three index
tables — Campo Real `v1`/`v2`, the pixel counts, and Porto's seven dates — were recomputed
against the restored database and match **to the fourth decimal place, cell by cell**. In
particular the central numbers: 24/08 with NDVI `v1` 0.2111 and `v2` 0.4130, NDRE 0.1531 →
0.3018, NDMI 0.1847 → 0.2313, and **57 432 pixels excluded of 62 750**. Copernicus returns
today what it returned at 12:06.

**What does not reproduce, and never would:**

- **The job UUIDs.** The two quoted above — `66a47279-1757-42ca-a385-a07b8f4f3a68` and
  `b0edfb53-acc5-4e1a-ae02-d8958e9be2ff` — **no longer exist in the database.** They are keys
  generated on each run. Anyone trying `GET /jobs/66a47279-…` to verify this note gets a
  **404**, and that is not a sign that anything is wrong. The same holds for the
  area-of-interest UUIDs (`352d4000-…`, `b93ce717-…`) quoted in the response bodies.
- **The `started_at` / `finished_at` marks.** The 29/08 12:06 stamps belong to the original
  run.
- **The `created_at`** of every row.

**The `request_hash` values of the two synchronisations in this note do reproduce**, and were
reconfirmed: `0a4bb5ac…` and `9489a994…`, the same ones published above. That is what is
expected — the hash derives from the request (area of interest, window, collection, processing
version, resolution, cloud threshold) and not from the run.

A caveat about the `v1` series: on restore it was re-ingested over the window **01–29/08**, so
as to be level with `v2`, whereas Phase B had run it to **28/08**. The values are exactly the
same — there is no acquisition on 29/08 — but the `request_hash` changes with the window, so
the `v1` hashes the Phase B note publishes (`03c9afcd…`, `efece715…`) no longer exist in the
database. Anyone looking for them will not find them, and that is not a sign that anything is
wrong.

Two consequences are recorded because they are a lesson and not a detail. First: this
project's `Settings` **has no `env_prefix`**, so exporting `RESOILTWIN_DATABASE_URL`
configures nothing and the connection falls silently back to the default database — which is
the development one. Before any command that writes, confirm with `python -c "from
resoiltwin.config import get_settings; print(get_settings().database_url)"`. Second: the
restore became a command, and it is documented in the `README.md`.

---

## Test suite and static analysis

```
$ pytest -q
........................................................................ [ 35%]
........................................................................ [ 71%]
.........................................................                [100%]
201 passed in 4.95s

$ ruff check .
All checks passed!
```

197 tests before this task, 201 after. None touches the network: the Copernicus responses are
simulated by a test HTTP transport. The only real calls were the **two** `sync` runs of this
note and **one** Catalog query for the cloudiness table — and, later the same day, the **four**
`sync` runs of the restore.

After this note the repository went to 203 tests: two new schema-parity tests, which pin the
width of the `VARCHAR` columns between models and migrations. They came from migration `0008`,
which aligned `ingestion_jobs.processing_version` (it was `String(64)`) with
`observations.processing_version` (`String(80)`) — the same processing version stored at two
different widths, which would make a version longer than 64 characters accepted in one table
and refused in the other.
