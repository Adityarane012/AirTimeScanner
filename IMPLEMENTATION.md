# Implementation Guide — APIx, compressed to a solo full-time build

This turns `docs/00-05` (a 16-week, 2.6-FTE prototype plan) into a build one
person can execute full-time in about a week of engineering, with an honest
note on the one thing that timeline *cannot* compress: the collection window.

## 0. The one thing that doesn't compress

**docs/04-delivery-plan.md is explicit: "the validation window is wall-clock
bound, not effort-bound."** You cannot collect airfare data retroactively.
Whatever day you get one adapter writing to the database daily, that's day
zero of the collection window — no amount of additional coding pulls that
date earlier.

Consequence for a 1-week solo build: **finishing every phase below in a week
gets you a complete, tested pipeline with a live daily collector — not a
validated statistic.** Q3 in the open questions (below) already flags that
even 30 days of collection yields exactly one DGCA monthly comparison point.
So: engineering can be "done" in a week; the statistical validation output
accrues afterward, one day at a time, regardless of further coding. Get the
first Tier-1 adapter running on day 1–2, not day 6, so that clock starts
early.

## 1. What's cut from the original stack, and why

Compressing 2.6 FTE × 16 weeks into 1 FTE × ~1 week means cutting real scope,
not just working faster. Cut deliberately, documented here so it's a decision,
not a silent gap:

| docs/03 target | Cut to, for week 1 | Why this is an acceptable prototype cut |
|---|---|---|
| Prefect 3 orchestration | A plain Python script (`scripts/run_collection.py`) run via Windows Task Scheduler | At one run/day, an orchestrator adds ops overhead with no benefit yet. Adapter logic is orchestrator-agnostic, so swapping in Prefect later touches one script, not the adapters |
| MinIO / S3 | Local content-hashed filesystem store (`apix.storage.object_store`) | Same guarantee (immutable, content-addressed); no Docker available on this machine anyway. One-file swap to real S3 later |
| PostgreSQL + **TimescaleDB** | Plain **Postgres 17, Supabase-hosted** (`apix-airfare-index` project, `ap-south-1`, free tier) | docs/03 itself says "no part of this project is a scale problem" at ~3k rows/day. A hypertable buys nothing yet. Supabase over the local PostgreSQL 18 install: no local admin/superuser password handling needed, provisioned entirely via tool calls |
| Parquet + DuckDB analytics layer | Deferred; pandas directly against Postgres | Not needed until back-testing needs to iterate faster than SQL allows |
| dbt | Deferred; SQL written directly in `scripts/sql/` | Revisit once there's a silver/gold split worth tracking lineage on |
| Next.js + ECharts dashboard | Streamlit only for week 1 | One surface, fast to build; swap/add Next.js once the API is stable |
| SDMX-JSON/ML | Stretch goal, Phase 4, after plain JSON/CSV works | High-value but not blocking; `/v1/sdmx/data/{flow}` is stubbed as `501` rather than faked |
| Tier 3 (booking-engine) adapters | Deferred past week 1 | Tier 1 alone gets a real daily series running; Tier 3 is the least stable, most legally exposed source — build it once Tier 1 is proven, not before |

Kept as-is because they're cheap and high-value from day one: **Scrapling**,
**Pandera** contracts, **pure-Python Jevons index engine with golden
fixtures**, **FastAPI**, the **adapter-isolation** architecture, the
**immutable raw-payload + config_hash** audit trail.

## 2. Environment — what's already true

Checked/set up this session, all independently verified (not just asserted):

- **Database: Supabase-hosted Postgres 17**, project `apix-airfare-index` (id
  `criogqvlhfzpazgtipwa`, region `ap-south-1`, free tier — $0/month confirmed
  before creation). Schema applied, all 6 tables live, 10 placeholder routes
  seeded. **Connection verified end-to-end**: SQLAlchemy → Postgres →
  FastAPI `GET /v1/routes` → real 10-row JSON response. A local
  **PostgreSQL 18** service also exists on this machine (unused for now);
  `scripts/bootstrap_db.sql` is kept as a fallback if you ever want to move
  back to fully local Postgres — see the note at its top.
- **Python 3.11.15** and **uv 0.11.19** available on PATH; `.venv` created,
  `pytest -q` green (9/9 golden-fixture tests).
- **Scrapling requires its `[fetchers]` extra** (`curl_cffi`, `playwright`,
  `patchright`, `browserforge`) — bare `scrapling` cannot even import
  `Fetcher`. Fixed in `pyproject.toml` (`scrapling[fetchers]>=0.4.15`) and
  verified with a real `Fetcher.get()` call against a live URL (200 OK).
  Browser binaries (`playwright install` / Scrapling's own installer) are
  **not** needed yet — Tier 1 targets are static pages fetched via plain
  `Fetcher`, no browser. Only pull those in if/when Tier 3 (StealthyFetcher/
  DynamicFetcher) actually starts, per "probe before escalating."
- **No Docker.**
- Raw shell network egress (`curl` etc.) is sandboxed in this session, but
  `uv`/`pip`, live HTTP fetches from Python (`Fetcher.get`, `urllib`), and the
  Supabase MCP tools all work fine — those are the paths actually used.
- **Known gap, not fixed, your call:** Supabase reports Row Level Security
  disabled on all 6 tables. Low-risk in this design (FastAPI talks to
  Postgres directly, no Supabase anon key is planned to reach a browser) but
  flagged, not silently fixed — the remediation SQL is sitting in this
  session's history if you want it applied.

## 3. Resources needed from you

Concrete, in the order they're needed:

1. ~~Nothing to start coding~~ / ~~Supabase database password~~ — **both done.**
   The app connects end-to-end; see §2.
2. **DGCA domestic passenger-traffic data** (needed by end of Phase 1 to replace the 10-route placeholder in `config/routes.yaml` with the real ~50-pair, weighted basket). Published by DGCA (dgca.gov.in, "Traffic Statistics" / monthly domestic reports). If you have a copy or a subscription source, send it; otherwise I'll attempt to fetch it via web search/fetch when we reach that step — flag now if you already know this site is awkward to reach.
3. **Real Tier-1 tariff-sheet URLs**, one per carrier (IndiGo, Air India, Air India Express, Akasa, SpiceJet). I'll attempt to locate and probe these myself in Phase 0/1 (that's genuine reconnaissance work, not something to hand you), but if you already have any bookmarked, they save time.
4. **No repo cloning needed.** Scrapling installs via `pip`/`uv` — it's not vendored. Nothing else in the stack requires a source checkout. If a specific Tier-3 target later needs Camoufox as a stealth-browser fallback (see docs/03-architecture.md "Known limitation"), that's a `pip install camoufox` away too, not a clone.
5. **A decision on Q6 (Tier 2 budget)** — see open questions below. Default assumption going in: **no budget**, Tier 1 + Tier 3 only. Tell me if that's wrong.
6. Nothing else blocks starting. Everything else in the open questions has a stated default good enough to build against.

### Phase 0 dependency checklist

Everything the code actually needs to run, confirmed present or fixed this
session — kept here so Phase 0 is the single place this gets checked, not
rediscovered mid-Phase-1:

| Dependency | Status |
|---|---|
| Python 3.11, `uv` | ✅ present |
| `fastapi`, `sqlalchemy`, `psycopg[binary]`, `pydantic`, `pandera`, `pandas`, `pyyaml` | ✅ installed, imports verified |
| `scrapling[fetchers]` (curl_cffi, playwright, patchright, browserforge) | ✅ fixed this session — bare `scrapling` was missing `curl_cffi` and couldn't import `Fetcher` at all; extra added to `pyproject.toml`, reinstalled, a live `Fetcher.get()` call verified working |
| Playwright/Camoufox **browser binaries** | ⬜ not installed, **not needed yet** — only required once a Tier-3 target forces `StealthyFetcher`/`DynamicFetcher`; run `playwright install chromium` (or Scrapling's own installer) at that point, not before |
| Supabase Postgres connection | ✅ verified end-to-end (SQLAlchemy → DB → FastAPI response) |
| `pytest`, `ruff`, `streamlit` (dev extras) | ✅ installed |
| Windows Task Scheduler entry for daily collection | ⬜ Phase 1, once an adapter has a real target |

## 4. What's been scaffolded already (this session)

```
pyproject.toml            deps: fastapi, sqlalchemy, psycopg, pydantic, pandera, pandas,
                           pyarrow, pyyaml, apscheduler, scrapling[fetchers], pdfplumber (all MIT/BSD/Apache — checked, see Phase 1 note), pytest, streamlit
env.example                copy to .env — points at Supabase by default now
.gitignore                 now also excludes .scratch/ and logs/
scripts/
  bootstrap_db.sql          NOT in use — local-Postgres fallback path only, see its header
  sql/0001_init.sql         full schema: route, collection_run, selector_confirmation,
                             fare_quote, stratum_panel, index_value — matches docs/03 1:1
  seed_routes.py            loads config/routes.yaml into the route table
  run_collection.py         the daily entrypoint — REAL now: registers Tier1IndiGoTariffAdapter,
                             persists parsed quotes to fare_quote (inline minimal NORMALISE)
  run_collection.bat        Task Scheduler wrapper (sets working dir, logs to logs/)
config/
  routes.yaml               PLACEHOLDER 10-route basket (§3.2 replaces this)
  booking_curve.yaml         Q1's assumed-curve default, versioned, with sensitivity alternates
  suppression.yaml           coverage floors from docs/01 (60%/75%, matches exactly)
src/apix/
  settings.py                 pydantic-settings, reads .env
  storage/object_store.py     content-hashed immutable local store (MinIO stand-in)
  contracts/fare_quote.py     pydantic + Pandera FareQuote contract
  acquisition/base.py         SourceAdapter interface + CollectionResult (isolation boundary)
  acquisition/tier1_tariff_stub.py   generic adapter TEMPLATE for the next carrier (Phase 2)
  acquisition/pdf_tariff.py   REAL, working: parses IndiGo's tariff-band PDF structure —
                             section-tracking, MINUS-SIGN route separator, NA handling
  acquisition/tier1_indigo.py   REAL, first working adapter — see §5a for the honest scope
                             of what its output means
  db/models.py                 SQLAlchemy models mirroring 0001_init.sql
  db/engine.py
  index/jevons.py              elementary aggregation, pure function
  api/main.py                  FastAPI skeleton — full docs/03 surface: /v1/index[/latest],
                             /v1/routes, /v1/quotes, /v1/coverage, /v1/methodology, /v1/sdmx/*
tests/
  test_jevons.py               9 golden-fixture tests (ILO-style worked examples), passing without a DB
  test_pdf_tariff.py           6 more, fixture-based (not live-PDF), covering the section-
                             tracking guard and NA-bucket handling
```

Run the test suite any time with no DB needed:
```
uv venv --python 3.11 .venv
uv pip install -e ".[dev]" --python .venv
pytest -q
```

**Cross-checked this session, fixed where wrong** (so this section stays a
statement of fact, not aspiration): `pyproject.toml`'s Scrapling dependency
was missing the `[fetchers]` extra and couldn't actually run; the adapter
template called `Fetcher.get(..., adaptive=True)`, which doesn't exist on
that method (adaptive belongs on `.css()`/`.xpath()`) — both fixed and
re-verified against the installed package. `api/main.py` was missing
`/v1/quotes` from docs/03's documented surface — added. `README.md` still
said "no implementation code yet" — updated to match reality.

## 5. Phase plan — 2 days or less per phase, full-time solo

Each phase ends with a concrete, checkable Definition of Done, same spirit as
docs/04 but sized for one person. Numbers assume you start today.

| Phase | Days | Goal | Definition of done |
|---|---|---|---|
| **0 — Setup & recon** | 0.5–1 | ✅ **Done and signed off** — see `docs/06-recon-log.md`'s "Phase 0 sign-off" section: real tariff-sheet URLs for 4/5 carriers, IndiGo fully live-verified (robots.txt, T&C, actual fetch), one real conflict found and left unresolved rather than routed around (Air India Express), Q4/Q6/Q7 addressed (Q4 outreach drafted in `docs/07-dgca-outreach-draft.md`, not yet sent — that's yours to do) | See `docs/06-recon-log.md` |
| **1 — Vertical slice** | 1–2 | ✅ **Done.** Real IndiGo adapter (`tier1_indigo.py` + `pdf_tariff.py`): fetches the live tariff PDF, parses its "ONE WAY ECONOMY FARES" section (confirmed via direct inspection: 68 pages, MINUS-SIGN route separator, multiple fare-table sections that must be kept separate, non-directional bands), writes real rows to Supabase. Task Scheduler entry (`APIx-DailyCollection`, daily 06:00, via `run_collection.bat`) registered and manually triggered once to confirm the actual scheduled path works, not just the direct invocation | **Verified**: 4 real rows in `fare_quote` (2 via direct run, 2 via the Task Scheduler path), `observation_status='observed'`, valid `raw_payload_hash`, `fare_class='tier1_tariff_floor'` correctly distinguishing this from a live headline quote (see the honesty note in `tier1_indigo.py`'s docstring — this is a filed floor band, not a per-date offer). 15/15 tests green (6 new, parser-only, fixture-based) |
| **2 — Multi-source** | 1–2 | Remaining Tier-1 adapters (all 5 carriers, or as many as have reachable tariff sheets); real ~50-route basket loaded from actual DGCA data; NORMALISE stage (fare decomposition, de-dup across sources); **resolve the Tier-1-vs-Tier-3 semantics question flagged below before this phase's index-relevant work** | ≥3 sources landing daily; `route` table has the real weighted basket; a NORMALISE unit test per fare-component rule |
| **3 — Cleaning & index engine** | 1–2 | Outlier flagging (MAD, within-stratum, log relatives), stratum-mean imputation, Jevons elementary (done) → Lowe/Young upper level with `booking_curve.yaml`, `config_hash` + vintage stamping, coverage-floor suppression | A `stratum_panel` and `index_value` row computed end-to-end from real collected data; recompute is bit-identical on a second run; sensitivity band present on every composite value |
| **4 — API & dashboard** | 1 | Wire `/v1/index*` to real data (already stubbed); Streamlit dashboard: trend line, coverage panel, at minimum | `GET /v1/index?series=...` returns real numbers; Streamlit page loads and shows the trend and a coverage/suppression indicator |
| **5 — Docs & validation setup** | 0.5–1 | Revision-policy doc; wire the DGCA comparison metric (direction-of-change) so it's ready the moment a DGCA monthly figure is out; open-questions decisions written down as committed, not just recommended | `docs/07-revision-policy.md` exists; validation script runs against whatever data exists, even if thin |

**Total: ~6–9 focused full-time days** for a working end-to-end pipeline —
consistent with "a week or less" if Phase 0 and the DB step happen today.
**Not included in that estimate:** the actual statistical validation, because
per §0 that's wall-clock-bound and keeps accruing after the code is done —
budget for checking back in on it weekly, not finishing it in week 1.

## 5a. A real design fork from Phase 1 — worth your explicit sign-off

Building the IndiGo adapter surfaced something docs/01/02 discuss in the
abstract ("Tier 1 anchors the fare structure... published tariffs are
ranges, not live availability-adjusted prices") but that turned out to have
a concrete, material consequence once real data was in hand:

**IndiGo's tariff sheet gives a filed floor/ceiling fare per city-pair —
not a specific-departure-date offer, and not directional** (confirmed: the
same band applies both ways; no reverse-direction row exists anywhere in the
68-page document). That doesn't match the `fare_quote` product spec in
docs/02 §1 (directional, specific departure date, lowest *available* fare)
in three ways at once.

**Decision made to unblock Phase 1, not hidden in code**: write these rows
into `fare_quote` anyway — `observation_status='observed'` (it is a real,
current, verifiable filing) — but tag them `fare_class='tier1_tariff_floor'`
and anchor `departure_date`/`advance_purchase_days` to a stated convention
(`collection_ts + 30 days`, `30`) rather than inventing false precision.

**What this means for Phase 3 (index engine)**: the Jevons/Lowe-Young
computation must filter on `fare_class` and exclude `tier1_tariff_floor`
rows from the *headline* series — they're validation/anchor data (exactly
docs/01's framing), not inputs to the live index. If Phase 3 is built
without that filter, Tier-1 floor bands would silently contaminate the
headline number with non-directional, non-date-specific data. **Flagging
this now so it's not rediscovered as a bug three phases from now.**

If you'd rather handle Tier-1 data differently — a separate table instead of
overloading `fare_quote`, a fifth `observation_status` value, dropping
Tier-1 from `fare_quote` entirely — that's a reasonable alternative and a
schema change, not a big one. Current choice was made to keep Phase 1
moving without a schema migration; revisit before Phase 3 if it doesn't sit
right.

## 6. Open questions — decisions to make now, not defer

`docs/05-open-questions.md` lists eight sponsor decisions, each with a
recommended default so work isn't blocked. For a solo build with no
separate "sponsor," you're both roles — so these need an actual answer from
you, not just a default sitting on the page. My recommendation on each,
adopted as the working assumption unless you say otherwise:

- **Q1 (booking-curve weights) — adopt.** No real distribution is publicly
  available. `config/booking_curve.yaml` already encodes the assumed curve
  plus sensitivity alternates, per the recommended default. This is the
  single biggest methodological soft spot in the whole project — the
  composite index rests on an assumption, and every composite value must
  carry its sensitivity band rather than being published as a bare number.
- **Q2 ("PSD" meaning) — adopt reading 3: DGCA passenger/revenue shares.**
  It's the only reading that yields CPI-consistent weights, and it's what
  `route.dgca_pax_weight` in the schema already assumes.
- **Q3 (back-test) — adopt (a)+(c), lean into (a) for week 1.** 30 days of
  forward collection gives real engineering/coverage validation and exactly
  one DGCA monthly comparison point — that's honestly all a solo week-one
  build can produce. (c), a historical fare archive, is an institutional ask
  (DGCA TMU records, etc.) — worth a cold email now since it costs you
  nothing to send, but don't plan week 1 around getting a reply.
- **Q4 (DGCA/MoSPI engagement) — send the letter anyway.** Doesn't block any
  phase above; purely upside if it lands.
- **Q5 (offered vs transaction price) — adopt.** Proceed on offered prices;
  it's already baked into the product spec and validation-on-changes-only
  design (docs/02 §3, §10).
- **Q6 (Tier 2 budget) — assume none**, per §3.7 above. Confirm if wrong;
  changes nothing structural if you later add a paid feed — it's just
  another adapter.
- **Q7 (anti-bot evasion exclusion) — accept the exclusion.** No CAPTCHA
  solving, no proxy rotation, no session/credential reuse. This isn't just
  the ethical call — it's the practical one for a solo maintainer: an
  evasion arms race against enterprise bot management (IndiGo, Air India,
  MakeMyTrip) is not a fight one person keeps winning, and losing it takes
  down the whole collector, not just one source. Tier 1 first is what makes
  this affordable to accept.
- **Q8 (COICOP 2018 code/weight) — defer as config.** `mospi.gov.in` was
  reported blocked from this environment when the docs were written; try it
  again in Phase 0 (network access differs by session) or pull it from a
  browser yourself. Doesn't block any phase above — it's a metadata label,
  already designed as a config value, not a schema field.

None of these block starting Phase 0 today. Q1, Q3 and Q7 are the ones
`docs/04-delivery-plan.md` calls out as changing what gets built — and all
three already have a committed answer above.
