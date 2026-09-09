# AirTimeScanner — Real-time Airfare Price Index for India (APIx)

Automated airfare price-collection and index-construction platform intended to
augment the Consumer Price Index published by the National Statistical Office
(NSO), MoSPI.

**Status: collecting daily.** Schema live on a Supabase-hosted Postgres
instance, FastAPI serving the full documented `/v1` surface, index engine
unit-tested against golden fixtures, and a real Tier-1 adapter writing quotes
every morning since **9 September 2026** — Air India's filed tariff sheet, ten
routes a day with the full fare decomposition (base fare, UDF, ASF, RCS/CUTE,
fuel surcharge, GST).

The headline index is still empty, and that is correct rather than broken:
every quote collected so far is a **filed tariff band**, not an offered price,
and the engine deliberately excludes those from the headline. Publishing a
series needs a Tier-3 offer source. See [`IMPLEMENTATION.md`](IMPLEMENTATION.md)
for the build plan and exactly what's done vs. pending, and
[`HANDOFF.md`](HANDOFF.md) for the current state in detail.

## What this is

Design documents that turn the problem statement into a buildable, defensible
project — what gets built, what deliberately does not, which statistical
choices determine credibility, which questions must be answered before
engineering starts — plus a working scaffold implementing them.

## Read in this order

| Doc | What it settles |
|---|---|
| [`docs/00-scope.md`](docs/00-scope.md) | Problem restatement against the **CPI 2024 series**, in/out of scope, success criteria, the honest value proposition |
| [`docs/01-data-acquisition.md`](docs/01-data-acquisition.md) | The four-tier source ladder, the statutory sources most teams miss, legal posture, what we refuse to build |
| [`docs/02-methodology.md`](docs/02-methodology.md) | Product specification, elementary aggregation, weighting, chain drift, imputation, the day-of-week artefact |
| [`docs/03-architecture.md`](docs/03-architecture.md) | Stack, data model, pipeline stages, API surface, testing strategy |
| [`docs/04-delivery-plan.md`](docs/04-delivery-plan.md) | The original 16-week, 2.6-FTE phased plan: risk register, effort estimate, wall-clock critical path |
| [`docs/05-open-questions.md`](docs/05-open-questions.md) | Eight decisions needed from the sponsor, with recommended defaults |
| [`docs/06-recon-log.md`](docs/06-recon-log.md) | Phase 0 findings: real tariff-sheet URLs and live robots.txt verdicts per carrier, not estimates — including the two verdicts that were wrong and how |
| [`docs/07-dgca-outreach-draft.md`](docs/07-dgca-outreach-draft.md) | Draft letters to DGCA/MoSPI requesting the filings directly (not yet sent) |
| [`docs/08-methodology-sources.md`](docs/08-methodology-sources.md) | Citations for the index formulas, and the build-vs-borrow decision on existing index libraries |
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | **Start here to build.** Compresses docs/00-05 into a ~week-long solo build: environment, resources needed, phase-by-phase plan, committed answers to the open questions, and post-mortems on every defect found so far |
| [`HANDOFF.md`](HANDOFF.md) | **Start here to continue.** Current state, what changed when, and the next task |

## Quick start

```
uv venv --python 3.11 .venv
uv pip install -e ".[dev]" --python .venv
cp env.example .env   # fill in DATABASE_URL — see IMPLEMENTATION.md §2/§3
pytest -q             # 119 tests, no DB and no network needed
uvicorn apix.api.main:app --reload --app-dir src   # http://127.0.0.1:8000/docs
```

Then, against a configured database:

```
python scripts/check_robots.py       # re-verify every source's robots.txt
python scripts/run_collection.py     # one collection run
python scripts/run_index.py --dry-run   # compute the index, write nothing
```

## The three findings that reshape this project

1. **The CPI 2024 base-year series went live on 12 February 2026** (HCES 2023–24
   weights, COICOP 2018, 358 items) and explicitly commits to *"inclusion of
   alternative data sources"*. The problem statement was written against the 2012
   series. The pitch changes from *replace manual collection* to *supply the
   alternative-data pipeline MoSPI has already committed to*.

2. **Scheduled domestic airlines are legally required to publish route-wise tariff
   sheets on their websites** (Rule 135(2), Aircraft Rules 1937; DGCA Air Transport
   Circular 02 of 2010), and DGCA's Tariff Monitoring Unit already collects fares
   from airline websites on ~78 routes monthly. There is a mandated, public,
   low-hostility data source that sits below the booking engines everyone tries to
   scrape first.

3. **The "30 days of back-tested results against DGCA monthly data" deliverable is
   internally inconsistent** — 30 days of forward collection produces one monthly
   comparison point, and scraped fares cannot be collected retrospectively. See
   [`docs/05-open-questions.md`](docs/05-open-questions.md#q3) for three ways out.

## Non-goals

This project will not build CAPTCHA-solving, residential-proxy IP rotation, or
other anti-bot evasion. The reasoning — which is operational, not just ethical —
is in [`docs/01-data-acquisition.md`](docs/01-data-acquisition.md#what-we-do-not-build).
