# The rule the repository did not keep

**3 September 2026.** On 31 August the approved area geometries were moved to a
private repository, `EuroUnionConsult/resoiltwin-internal`, so that the parcel
locations would not circulate. The evidence notes were written to the same rule:
publish distances and cell sizes, never the polygons.

While auditing the evidence package before delivery, the rule was checked against
the repository rather than against the notes. It does not hold, and it never did.

## What is public, and since when

Seventeen tracked files carry real coordinates. Sixteen are tests; one is an
evidence note.

| What | Value | Where |
|---|---|---|
| Canonical site point, Turcifal | `39.037317, -9.240247` | 10 test files |
| Canonical site point, Porto | `41.177928, -8.641731` | 4 test files |
| `EUC-TUR-EO1` area box | `[-9.2547, 39.0261] … [-9.2258, 39.0485]` | 4 test files |
| A ~15 m plot polygon at the Turcifal point | `[-9.24034, 39.03725] …` | 4 test files |
| Station coordinates and the distance to the site | `39.04389444, -9.179`, 5.34 km | 5 files, one of them an evidence note |

The canonical point entered in commit `e9ccc7e` — **the first commit of the
repository**, 28 August. It has been readable by anyone for the whole life of
the project, and it is in the history of all 102 commits, not only in the
current tree.

## Why the private repository did not prevent this

Because the decision moved a *file* and the location was never only in that
file. It was in the fixtures the tests were written against, where a real
coordinate is convenient precisely because the assertions around it are real:
the distance to the station is 5.34 km because the station is where it is, the
grid cell is 11.1 × 8.6 km because the site is at 39° north, and the UTM zone is
29N because the site is west of 6° W. Those numbers are the evidence. Replacing
the coordinate changes every one of them.

That is also why the guard did not catch it. The console has a redaction guard,
and it works — it inspects *values* leaving the API. Nothing inspects the
repository, and a fixture is not a value leaving anything.

## Two claims that were false, now corrected

The note `2026-08-29-fase-c.md` said that what it published carried the argument
"without locating the parcel". It does locate it, twice over: a named public
station plus a distance places `EUC-PTO-01` on a circle of 0.89 km radius, and
the fixtures give the point outright.

The section `fase-e-decisoes-pendentes.md` gave the private repository as the
reason the API stopped serving geometry. The decision stands; the premise that
the rest of the repository already kept the rule does not.

Both were corrected in place rather than deleted, in the same commit as this note.

## What was not done, and why it is a decision and not an oversight

**The fixtures were left alone.** Moving them to a synthetic location is a real
refactor, not a search and replace: every derived expectation above has to be
recomputed, across 16 files and roughly 1 100 tests, and a test that silently
stops asserting what it used to assert is worse than a published coordinate.

**The history was left alone.** Rewriting it would not undo publication — the
repository has been public since 28 August, and clones, forks and provider-side
copies are outside anyone's reach — while it would break every existing clone.

So there are three honest positions, and choosing between them is a company
decision about the data, not a coding one:

1. **Accept it.** The site is a research micro-site, the coordinate is already
   out, and the documentation now says so plainly instead of implying otherwise.
   Cost: nothing new is protected.
2. **Refactor the fixtures to a synthetic site** and keep the real coordinates
   only in the private repository, so that nothing *new* is published. Cost: a
   few days, and the history still holds the old values.
3. **Refactor and rewrite history.** Cost: everything in 2, plus broken clones,
   and still no guarantee against copies already taken.

Until that is decided, the position is 1 — stated, not assumed.
