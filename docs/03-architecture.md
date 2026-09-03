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
| Acquisition | **Scrapling** | One framework, three fetchers spanning the tier ladder — see below. Free, BSD-3-Clause, no hosted tier or usage cost |
| Raw landing | **MinIO / S3**, content-hashed, immutable | The audit trail. Non-negotiable |
| Warehouse | **PostgreSQL + TimescaleDB** | Hypertable on collection timestamp; one dependency, well understood, easy to hand over |
| Analytics | **Parquet + DuckDB** | Fast local index computation and back-testing without loading the warehouse |
| Transform | **dbt** | Testable, documented, lineage-tracked SQL for silver/gold |
| Data contracts | **Pandera** | Schema and constraint enforcement at pipeline boundaries |
| Index engine | Pure-Python library, **polars/pandas** | Deterministic, side-effect-free, unit-testable |
| API | **FastAPI**, OpenAPI 3.1 | With SDMX output — see below |
| Dashboard | **Next.js + ECharts** (deliverable); Streamlit (internal QA) | Two surfaces, different audiences |

### Acquisition: Scrapling across the tier ladder

**Decision: [Scrapling](https://github.com/D4Vinci/Scrapling)** (~77k★, BSD-3-Clause,
pip-installable, no hosted service or usage cost) is the single acquisition
dependency, in place of the httpx/Scrapy/Playwright combination named in earlier
scoping notes. It was chosen over Scrapy, Crawlee, Firecrawl and crawl4ai for
three reasons:

- **The tier ladder in [`01-data-acquisition.md`](01-data-acquisition.md#the-four-tier-source-ladder)
  maps directly onto Scrapling's three fetchers.** Escalating from a static tariff
  sheet to a JS-rendered booking page is a class swap, not a rewrite:

  | Source tier | Fetcher | Notes |
  |---|---|---|
  | Tier 1 — tariff sheets | `Fetcher` | Plain HTTP; static pages, no JS |
  | Tier 2 — licensed/API | `Fetcher` | Same class; just a different base URL and auth |
  | Tier 3 — booking engines, low protection | `Fetcher` with `impersonate=` | TLS/JA3 impersonation before reaching for a browser at all |
  | Tier 3 — booking engines, hostile | `StealthyFetcher` → `DynamicFetcher` | Escalate only as far as the source requires |

- **This project does not crawl.** The route basket is fixed and enumerated from
  config (~50 pairs × 2 directions × 5 windows); no link discovery, no frontier,
  no URL dedup at scale. Scrapy's and Crawlee's core value — crawling machinery —
  solves a problem this project doesn't have. Scrapling's request volume (a few
  hundred to ~3,000 fetches/day) plays to its strength instead.

- **Adaptive selectors directly target risk #7 in the delivery plan** (parser rot
  from site redesigns) — see the quarantine rule below, which is the one governing
  constraint on how this feature is used.

**Probe before escalating**, for every new Tier 3 source: capture the fare
response in a browser's network tab, replay it with `Fetcher(impersonate="chrome")`
first. Most fare endpoints are gated at the TLS layer alone, and a plain
impersonated request is ~50× cheaper than a browser session. Only escalate to
`StealthyFetcher` or `DynamicFetcher` when the cheaper tier is actually blocked —
confirmed per source during Phase 0 reconnaissance, not assumed upfront.

**The adaptive-selector quarantine rule.** Adaptive relocation is convenient and
dangerous in the same breath: when a page changes, Scrapling can silently
re-target a selector onto a *similar-looking but wrong* element — a strikethrough
price, a per-passenger subtotal, a different fare bucket — and return a plausible
number with no error. That is worse than a crash, because it corrupts the index
input without tripping anything, and it defeats the `config_hash` reproducibility
guarantee in [`02-methodology.md`](02-methodology.md#9-vintages-and-revisions) by
changing what a selector *means* without changing the config.

So relocation is treated as an **alarm, not a repair**:

1. Run every adapter with `adaptive=True`.
2. A relocation event is logged with the old and new element, and that source's
   slots for the run are written as `observation_status = collection_failed`,
   never as a normal observation.
3. The run is excluded from the index build until a human confirms the new
   selector is correct — logged as a `selector_confirmation` record against the
   adapter, referenced from `collection_run`.
4. Only after confirmation does the adapter's config change, under its own
   `config_hash`, and subsequent runs resume as `observed`.

This keeps the actual benefit — finding out within hours that a source changed,
instead of discovering it a week later from a coverage hole — without letting the
feature quietly redefine what is being measured.

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
- An adapter's selector relocating (see
  [the quarantine rule above](#acquisition-scrapling-across-the-tier-ladder)) is
  handled the same way as any other adapter failure: caught, quarantined, and
  never propagated into the index build unreviewed.

## Core data model

```
route                 origin, destination, direction, stage_length_km,
                      stratum_class (metro-metro / metro-nonmetro / rcs),
                      dgca_pax_weight

collection_run        run_id, started_at, source, status, robots_checked_at,
                      config_hash, selector_relocated (bool)

selector_confirmation adapter, detected_at, old_selector, new_selector,
                      confirmed_by, confirmed_at, resulting_config_hash

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
| Regression | Adaptive selectors | Replay each adapter's fixture set with `adaptive=True` and assert zero relocation events on unchanged fixtures — a relocation here means the matcher itself drifted, not the site |
| Property | Cleaning pipeline | Invariants: no negative fares, totals ≥ component sums, status transitions legal, imputation never invents observations |
| Integration | Stage boundaries | Synthetic run end-to-end through all six stages |
| Regression | Published values | Recompute a frozen vintage and assert bit-identical output. Catches accidental methodology drift, which is the failure mode that destroys trust in a statistical series |
| Monitoring (not a test) | Live sources | Separate scheduled canary job, alerting on yield collapse. Kept out of CI on purpose |

## Observability

- Per-source yield and latency; alert on collapse rather than on individual failures
- Stratum coverage vs the suppression floor, tracked daily
- Parse-error rate by source — the leading indicator of a site redesign
- **Selector relocation events — alert immediately, one per event.** Never
  auto-promote a relocated selector into production; see the quarantine rule above
- Index revision monitor — alert if a recomputed vintage differs unexpectedly
- robots.txt change detection per source, alerting on any change to a path we use
