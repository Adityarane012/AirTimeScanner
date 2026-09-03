# 03 — Architecture

## Sizing first

Worth establishing up front, because it changes what the hard problems are.

```
50 city-pairs × 2 directions × 5 windows × ~6 carriers ≈ 3,000 headline quote-slots/day
With full fare ladders retained:                        ≈ 15,000–30,000 rows/day
Annual:                                                 ≈ 5–11 million rows/year
```

This is a small dataset. It fits comfortably in a single PostgreSQL instance for
years. **No part of this project is a scale problem.** The hard problems are source
fragility, statistical correctness, and auditability — and the architecture should
spend its complexity budget there, not on distributed processing.

## Stack

| Layer | Choice | Rationale |
|---|---|---|
| Orchestration | **Prefect 3** (prototype) → Airflow (institutional production) | Prefect gives far less ops burden for a prototype; Airflow is the safe long-term choice inside a government estate. Keep DAG logic in plain Python so the migration is mechanical |
| HTTP acquisition | **httpx** / Scrapy | Tier 1 tariff sheets and Tier 2 APIs |
| Browser acquisition | **Playwright** | Genuinely JS-rendered pages only. Preferred over Selenium: better async model, more reliable waits, first-class network interception |
| Raw landing | **MinIO / S3**, content-hashed, immutable | The audit trail. Non-negotiable |
| Warehouse | **PostgreSQL + TimescaleDB** | Hypertable on collection timestamp; one dependency, well understood, easy to hand over |
| Analytics | **Parquet + DuckDB** | Fast local index computation and back-testing without loading the warehouse |
| Transform | **dbt** | Testable, documented, lineage-tracked SQL for silver/gold |
| Data contracts | **Pandera** | Schema and constraint enforcement at pipeline boundaries |
| Index engine | Pure-Python library, **polars/pandas** | Deterministic, side-effect-free, unit-testable |
| API | **FastAPI**, OpenAPI 3.1 | With SDMX output — see below |
| Dashboard | **Next.js + ECharts** (deliverable); Streamlit (internal QA) | Two surfaces, different audiences |

### Why SDMX matters

**SDMX (Statistical Data and Metadata eXchange) is the standard by which national
statistical offices and central banks exchange statistical series.** NSO and RBI
consume SDMX. An API that emits only bespoke JSON asks a statistical agency to
write a custom adapter for a series they are being invited to trust.

Exposing **SDMX-JSON and SDMX-ML** alongside plain JSON and CSV is a small amount
of work and is one of the highest-leverage credibility signals available to this
project. It converts "an interesting dashboard" into "a series our systems can
already ingest".

## Pipeline stages

```
  ┌──────────────────────────────────────────────────────────────────┐
  │ ACQUIRE   per-source adapters, robots.txt check, rate limiting   │
  │           └─> raw payload → object store (immutable, hashed)     │
  ├──────────────────────────────────────────────────────────────────┤
  │ PARSE     source-specific parser → FareQuote contract            │
  │           └─> bronze: one row per observed offer, status-coded   │
  ├──────────────────────────────────────────────────────────────────┤
  │ NORMALISE fare decomposition, currency, carrier/airport codes,    │
  │           de-duplication across sources, observation status      │
  │           └─> silver: canonical quote table                      │
  ├──────────────────────────────────────────────────────────────────┤
  │ CLEAN     within-stratum outlier flagging, imputation,            │
  │           coverage assessment, suppression rules                 │
  │           └─> gold: index-ready stratum panel                    │
  ├──────────────────────────────────────────────────────────────────┤
  │ INDEX     Jevons elementary → Lowe/Young upper → multilateral    │
  │           monthly; vintage stamp + config hash                   │
  ├──────────────────────────────────────────────────────────────────┤
  │ PUBLISH   SDMX / JSON / CSV API  +  dashboard  +  QA report      │
  └──────────────────────────────────────────────────────────────────┘
```

Each stage reads only the stage before it and writes an addressable artefact.
The index is recomputable from `gold` alone; `gold` is recomputable from the raw
object store alone. That chain is the reproducibility guarantee promised in
[`02-methodology.md`](02-methodology.md#9-vintages-and-revisions).

## Adapter isolation

The most important structural decision, and it follows directly from the source
analysis in [`01-data-acquisition.md`](01-data-acquisition.md#source-by-source-assessment):
**Tier 3 sources will break, individually and without warning.**

Therefore:

- Every source is an **independent adapter** implementing one interface and
  emitting one contract type (`FareQuote`). Nothing else in the system knows which
  source a quote came from except as a metadata field.
- Adapters run in **isolated tasks**. An adapter failure is caught, reason-coded,
  and recorded as `collection_failed` for its slots. It never propagates.
- The index build reads the warehouse and **has no knowledge of adapters at all**.
  A total collection outage produces a suppressed or thin index value with an
  honest coverage figure — never a crash, and never a silently wrong number.
- Adding a source is adding one file plus a fixture set. Removing one is deleting
  them. No other code changes.

## Core data model

```
route                 origin, destination, direction, stage_length_km,
                      stratum_class (metro-metro / metro-nonmetro / rcs),
                      dgca_pax_weight

collection_run        run_id, started_at, source, status, robots_checked_at,
                      config_hash

fare_quote            quote_id, run_id, source, carrier, route_id,
                      departure_date, collection_ts, advance_purchase_days,
                      fare_class, is_nonstop,
                      base_fare, carrier_charges, udf, asf, rcs_levy, gst,
                      convenience_fee, total_fare,
                      observation_status,       -- observed | no_service |
                                                --  collection_failed | imputed
                      outlier_flag, exclusion_reason,
                      raw_payload_hash          -- → object store

stratum_panel         date, route_id, advance_purchase_days,
                      jevons_relative, n_observed, n_imputed, coverage_ratio

index_value           vintage_id, series_id, frequency, period, value,
                      coverage_ratio, suppressed, config_hash,
                      sensitivity_low, sensitivity_high   -- booking-curve band
```

Two fields carry disproportionate weight: `raw_payload_hash` (the audit chain back
to evidence) and `config_hash` (which methodology produced this number). Together
they make any published value fully explicable months later.

## API surface

```
GET /v1/index                    ?series=&freq=daily|weekly|monthly&from=&to=
GET /v1/index/{series}/latest
GET /v1/routes                   basket, weights, stratum classes
GET /v1/quotes                   research access; rate-limited, filtered
GET /v1/coverage                 per-stratum yield and suppression status
GET /v1/methodology              active config, version, revision policy
GET /v1/sdmx/data/{flow}         SDMX-JSON / SDMX-ML content negotiation
```

Every index response carries `coverage_ratio`, `suppressed`, `vintage_id`,
`config_hash`, and the booking-curve sensitivity band. Quality metadata travels
with the number rather than living in a separate document nobody reads.

## Dashboard views

1. **Index trends** — daily (7-day MA), weekly, monthly; sensitivity band shown, not hidden
2. **Sector heatmap** — route × time, price relative
3. **Lead-time elasticity curves** — fare vs advance-purchase days, by route and season.
   The most analytically interesting view and the one that best demonstrates why
   dynamic pricing defeats manual collection
4. **Carrier dispersion** — spread across carriers on a route over time
5. **Tax-and-fee wedge** — administered charges separated from market pricing
6. **Data quality panel** — coverage, yield by source, suppression events,
   parser health. Deliberately visible rather than buried; a statistical product
   that hides its own quality metrics does not get adopted

## Testing strategy

| Test type | Target | Approach |
|---|---|---|
| Unit | Index math | **Golden fixtures with hand-worked expected values**, including examples from the ILO CPI Manual. The index engine is pure and deterministic, so this is cheap and high-value |
| Contract | Parsers | Recorded response fixtures (VCR-style). Parser tests **never hit live sites** — otherwise the test suite becomes a scraper and fails when a site changes |
| Property | Cleaning pipeline | Invariants: no negative fares, totals ≥ component sums, status transitions legal, imputation never invents observations |
| Integration | Stage boundaries | Synthetic run end-to-end through all six stages |
| Regression | Published values | Recompute a frozen vintage and assert bit-identical output. Catches accidental methodology drift, which is the failure mode that destroys trust in a statistical series |
| Monitoring (not a test) | Live sources | Separate scheduled canary job, alerting on yield collapse. Kept out of CI on purpose |

## Observability

- Per-source yield and latency; alert on collapse rather than on individual failures
- Stratum coverage vs the suppression floor, tracked daily
- Parse-error rate by source — the leading indicator of a site redesign
- Index revision monitor — alert if a recomputed vintage differs unexpectedly
- robots.txt change detection per source, alerting on any change to a path we use
