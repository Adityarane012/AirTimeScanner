# AirTimeScanner — Real-time Airfare Price Index for India (APIx)

Automated airfare price-collection and index-construction platform intended to
augment the Consumer Price Index published by the National Statistical Office
(NSO), MoSPI.

**Status: scaffolded and running.** Schema live on a Supabase-hosted Postgres
instance, FastAPI skeleton serving the full documented `/v1` surface, index
engine unit-tested against golden fixtures. No adapter has a real target URL
wired in yet — that's the current work. See [`IMPLEMENTATION.md`](IMPLEMENTATION.md)
for the compressed solo build plan and exactly what's done vs. pending.

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
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | **Start here to build.** Compresses docs/00-05 into a ~week-long solo build: environment, resources needed, phase-by-phase plan, committed answers to the open questions |

## Quick start

```
uv venv --python 3.11 .venv
uv pip install -e ".[dev]" --python .venv
cp env.example .env   # fill in DATABASE_URL — see IMPLEMENTATION.md §2/§3
pytest -q             # 9 golden-fixture tests, no DB needed
uvicorn apix.api.main:app --reload --app-dir src   # http://127.0.0.1:8000/docs
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
