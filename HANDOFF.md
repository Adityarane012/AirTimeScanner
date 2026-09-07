# Session Handoff — AirTimeScanner / APIx

> **Last updated:** 2026-09-03 ~23:00 IST
> **Purpose:** Everything the next coding session needs to pick up without re-reading the entire codebase.

---

## 1. What this project is (one paragraph)

**APIx** is an automated airfare price-collection and index-construction platform for Indian domestic routes, designed to augment CPI published by MoSPI/NSO. It collects fare data daily from legally mandated airline tariff-sheet disclosures (Tier 1), normalises quotes into a comparable schema, computes a Jevons/Lowe-Young price index with vintage stamping and sensitivity bands, and exposes results via a FastAPI REST API. The repo name is `AirTimeScanner`, the Python package is `apix`.

---

## 2. Where we are in the build

### Phase completion status

| Phase | Status | Notes |
|---|---|---|
| **0 — Setup & recon** | ⚠️ Partly invalid | Supabase live, tariff URLs found — but the robots.txt verdicts were reached by grepping for path substrings, which **missed a `Disallow: *.pdf` rule and produced a false "allowed" for IndiGo**. See the Correction section in `docs/06-recon-log.md`. Air India / Akasa / SpiceJet verdicts are unverified for the same reason |
| **1 — Vertical slice** | ⚠️ Built, then blocked | Adapter is real and works; the source is robots.txt-disallowed, so it now correctly refuses to collect. Four silent defects found and fixed — see `IMPLEMENTATION.md §5b` |
| **2 — Multi-source** | 🛑 Blocked on a decision | Cannot proceed as written: there is currently **no compliant automated Tier-1 source**. Needs an operator decision before code |
| **3 — Cleaning & index engine** | ❌ Pending | Unblocked-ish — can be built against fixtures without live collection |
| **4 — API & dashboard** | ❌ Pending | |
| **5 — Docs & validation** | ❌ Pending | |

### The headline: there is no live data collection right now

`fare_quote` holds **2 rows**, both flagged `exclusion_reason` and excluded from
any index computation. They are the de-duplicated remains of the 6 rows that
were there, and they were collected via a fetch robots.txt disallows. **The
daily series has not started.** Per `IMPLEMENTATION.md §0` that clock is
wall-clock bound and cannot be backfilled, so this is the single most urgent
thing in the project.

### What changed in the 2026-09-07 review session

Full write-up in `IMPLEMENTATION.md §5b`. Summary:

1. **Found: IndiGo's tariff PDF is robots.txt-disallowed** (`Disallow: *.pdf`,
   line 225 of the only `User-Agent: *` group). Phase 0's "CONFIRMED ALLOWED"
   was wrong. Surfaced the moment `PoliteFetcher` was wired in — the control
   worked on its first live exercise. **No bypass was built.**
2. **Fixed: the collector produced zero new information per run.**
   `collection_ts` was the PDF's issue timestamp, not the fetch time, so every
   daily run wrote identical rows. Now the real fetch time;
   `CollectionResult.source_document_ts` carries the document's own timestamp.
3. **Fixed: `advance_purchase_days` was false on every row** (T+30 label on a
   T-121 row) — same root cause.
4. **Fixed: the scheduled task was silently failing.** Battery settings caused
   outright refusal (`0x800710E0`); 3 of the first 4 days collected nothing.
   Task corrected and now reproducible via the new `scripts/register_task.ps1`.
5. **Fixed: compliance module was never connected.** Adapter now fetches through
   `PoliteFetcher`; `collection_run.robots_checked_at` is finally written.
6. **Added** `sql/0002` — de-duplication + a unique index at the daily-observation
   grain, so a same-day re-run is idempotent instead of duplicating.
7. **Added** `tests/test_tier1_indigo.py` (8 tests) covering the adapter seam
   that all four defects hid in. 41/41 green, ruff clean.

## 3. Uncommitted work

Everything below is working-tree only, on branch
`claude/airfare-price-index-india-saqd83` (in sync with origin).

```
 M IMPLEMENTATION.md                     # §5b post-mortem; Phase 1 status corrected
 M docs/03-architecture.md               # "x 5 windows" -> "x 4 windows"
 M docs/06-recon-log.md                  # IndiGo robots verdict CORRECTED + lesson
 M pyproject.toml                        # + protego; ruff per-file-ignore for B008
 M scripts/run_collection.py             # robots_checked_at, warnings, idempotent insert
 M scripts/sql/0001_init.sql             # stale ~3k/day figure -> ~2.4k/day
 M src/apix/acquisition/base.py          # + robots_checked_at, source_document_ts, warnings, notes
 M src/apix/acquisition/compliance.py    # noqa reason on the deliberate blind except
 M src/apix/acquisition/tier1_indigo.py  # collection_ts fix, PoliteFetcher, staleness alarm
?? HANDOFF.md
?? scripts/register_task.ps1             # NEW: reproducible task registration
?? scripts/sql/0002_fare_quote_dedupe_and_uniqueness.sql   # NEW: applied to Supabase already
?? src/apix/acquisition/compliance.py    # NEW: the four docs/01 controls
?? tests/test_compliance.py              # NEW: 18 tests
?? tests/test_tier1_indigo.py            # NEW: 8 regression tests
```

> [!IMPORTANT]
> `sql/0002` has **already been applied** to the live Supabase database, and the
> 2 surviving rows already carry their `exclusion_reason`. The file is committed
> for the record; do not re-run it expecting it to do work.

## 4. Codebase map

```
AirTimeScanner/
├── .env                          # REAL credentials (gitignored) — Supabase connection
├── .gitignore
├── pyproject.toml                # deps: fastapi, sqlalchemy, psycopg, scrapling[fetchers], pdfplumber, pandera, etc.
├── env.example                   # Template — points at Supabase by default
├── README.md                     # Project overview + reading order
├── IMPLEMENTATION.md             # THE key doc — compressed solo build plan, what's done/pending, open questions
│
├── docs/
│   ├── 00-scope.md               # Problem restatement, in/out of scope, success criteria
│   ├── 01-data-acquisition.md    # Four-tier source ladder, legal posture, what we refuse to build
│   ├── 02-methodology.md         # Product spec, Jevons/Lowe-Young, booking-curve gap, day-of-week artefact
│   ├── 03-architecture.md        # Stack, data model, pipeline stages, API surface, Scrapling rationale
│   ├── 04-delivery-plan.md       # Original 16-week plan (now compressed to ~1 week solo)
│   ├── 05-open-questions.md      # 8 sponsor decisions with recommended defaults
│   ├── 06-recon-log.md           # Phase 0 findings — real URLs, live robots.txt verdicts
│   └── 07-dgca-outreach-draft.md # Draft letters to DGCA TMU and MoSPI (not sent yet)
│
├── config/
│   ├── routes.yaml               # PLACEHOLDER 10-route basket (needs real DGCA data in Phase 2)
│   ├── booking_curve.yaml        # Assumed curve: T1=0.08, T7=0.27, T15=0.35, T30=0.30 + sensitivity alternates
│   └── suppression.yaml          # Coverage floors: 60% stratum, 75% headline
│
├── scripts/
│   ├── bootstrap_db.sql          # NOT in use — local Postgres fallback only
│   ├── sql/0001_init.sql         # Full schema: 6 tables (route, collection_run, selector_confirmation, fare_quote, stratum_panel, index_value)
│   ├── seed_routes.py            # Loads routes.yaml into DB (idempotent upsert)
│   ├── run_collection.py         # Daily entrypoint — registers adapters, persists quotes (inline mini-NORMALISE)
│   ├── run_collection.bat        # Task Scheduler wrapper
│   └── check_secrets.py          # Pre-commit guard (this repo is PUBLIC)
│
├── src/apix/
│   ├── __init__.py               # v0.1.0
│   ├── settings.py               # Pydantic-settings, reads .env
│   ├── db/
│   │   ├── models.py             # SQLAlchemy models mirroring 0001_init.sql
│   │   └── engine.py             # create_engine + SessionLocal
│   ├── contracts/
│   │   └── fare_quote.py         # Pydantic FareQuote + Pandera FareQuoteBatchSchema
│   ├── storage/
│   │   └── object_store.py       # Content-hashed immutable local store (MinIO stand-in)
│   ├── acquisition/
│   │   ├── base.py               # SourceAdapter ABC + CollectionResult
│   │   ├── compliance.py         # ⚠️ UNCOMMITTED — RobotsGate, RateLimiter, CircuitBreaker, PoliteFetcher
│   │   ├── pdf_tariff.py         # Shared parser for space-delimited tariff-band PDFs
│   │   ├── tier1_indigo.py       # REAL working IndiGo adapter (tariff PDF → FareQuote)
│   │   └── tier1_tariff_stub.py  # Template adapter for the next carrier
│   ├── index/
│   │   └── jevons.py             # Elementary Jevons aggregation (pure, deterministic)
│   └── api/
│       └── main.py               # FastAPI: /healthz, /v1/index, /v1/index/{series}/latest, /v1/routes, /v1/quotes, /v1/coverage, /v1/methodology, /v1/sdmx/data/{flow}
│
├── tests/
│   ├── test_jevons.py            # 9 golden-fixture tests (ILO-style)
│   ├── test_pdf_tariff.py        # 6 fixture-based parser tests
│   └── test_compliance.py        # ⚠️ UNCOMMITTED — 18 tests for compliance module
│
├── data/raw/                     # Content-hashed raw payloads (gitignored)
├── logs/collection.log           # Task Scheduler output
└── .scratch/                     # Scratch inspection files (gitignored)
```

---

## 5. Key architectural decisions & gotchas

### The `fare_class='tier1_tariff_floor'` fork
IndiGo's tariff sheet gives a **filed floor/ceiling fare band per city-pair**, not a per-departure-date offer, and it's **non-directional** (symmetric). These rows are written to `fare_quote` tagged `fare_class='tier1_tariff_floor'` with `departure_date` conventionally anchored to `collection_ts + 30 days`. **Phase 3's index engine MUST filter these out of the headline series** — they're validation/anchor data, not live index inputs. See `IMPLEMENTATION.md §5a`.

### The compliance module is wired in — and it immediately blocked the only source
`tier1_indigo.py` now fetches through `PoliteFetcher.get()`. Every new adapter must do the same; never call `Fetcher.get()` directly from an adapter. The first live run through the gate failed with `RobotsDisallowed` on IndiGo's tariff PDF, which is the correct behaviour, not a bug to work around.

### `protego` dependency
`compliance.py` imports `protego` for robots.txt parsing. **Now added to `pyproject.toml`.** Note it was working only because it happened to be present in `.venv`; a clean install would have failed.

### The MINUS SIGN gotcha
IndiGo's tariff PDF uses U+2212 MINUS SIGN (`−`), not ASCII hyphen (`-`), as the route separator. `pdf_tariff.py` handles this, but any new carrier adapter parsing similar PDFs must be aware.

### Supabase, not local Postgres
The live DB is Supabase-hosted Postgres 17, connection string in `.env`. `bootstrap_db.sql` is a kept-but-unused local fallback. RLS is enabled on all 6 tables with no policies (intentional — app connects as `postgres` role which bypasses RLS; closes anonymous REST access).

### Advance-purchase windows are T+1, T+7, T+15, T+30 only
T+45 was removed. This is consistent across: `config/routes.yaml`, `config/booking_curve.yaml`, `contracts/fare_quote.py` (`AdvancePurchaseDays` type), `0001_init.sql` (CHECK constraint), and most docs.

> [!NOTE]
> **`docs/03-architecture.md` previously said "× 5 windows" in two places** (lines 8 and 53). Fixed this session to "× 4 windows" with recalculated estimates (~2,400/day). This fix is uncommitted.

### The booking-curve gap
The composite index relies on assumed booking-curve weights (Q1 in open questions). Every composite value MUST carry a sensitivity band showing the result under `front_loaded` and `back_loaded` alternate curves from `config/booking_curve.yaml`. Never publish a bare point estimate.

---

## 6. Environment

| Item | Value |
|---|---|
| Python | 3.11.15 |
| Package manager | `uv 0.11.19` |
| Venv | `.venv/` (in project root) |
| DB | Supabase Postgres 17 (see `.env` for connection string) |
| Local Postgres | PostgreSQL 18 installed but unused |
| OS | Windows |
| Docker | Not available |
| Task Scheduler | `APIx-DailyCollection` registered, daily 06:00, runs `run_collection.bat` |

### Quick start
```
.venv\Scripts\python.exe -m pytest -q          # 41 tests, no DB needed
uvicorn apix.api.main:app --reload --app-dir src   # http://127.0.0.1:8000/docs
python scripts/run_collection.py               # manual collection run
```

---

## 7. What to do next

### The one blocking decision (yours, not code's)

There is **no compliant automated Tier-1 source** right now. IndiGo is blocked by
`Disallow: *.pdf`; Air India Express by `/content/dam`. The realistic options,
none of which a coding session should pick unilaterally:

1. **Send the DGCA/MoSPI letter** (`docs/07-dgca-outreach-draft.md`, still
   unsent). It is now the highest-value unblocked action in the project — it
   asks the regulator for the filings directly, sidestepping the carriers'
   crawl rules entirely.
2. **Ask IndiGo for written permission** to fetch the one tariff sheet. A
   blanket `*.pdf` rule is near-certainly aimed at search-engine indexing, not
   at a research collector; permission makes that explicit and auditable.
3. **Look for a non-PDF representation** of the same filing — an HTML tariff
   page is not covered by `*.pdf`, and non-PDF paths on that host are allowed.
4. **Treat it as a manual, human-download source** — monthly, by a person, not
   an automated adapter.

### Before any Phase 2 code

- **Re-check Air India, Akasa and SpiceJet robots.txt with `protego`**, not
  substring search. Their current verdicts were reached the way IndiGo's wrong
  one was, so treat all three as unverified. This is cheap and should happen
  first — it may reveal the same `*.pdf` pattern industry-wide, which would
  change the whole acquisition strategy.
- **Enable the Task Scheduler operational log** (needs an elevated shell):
  `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`. Without it
  a scheduled-task failure leaves no diagnosable trace — which is exactly how
  three missed collection days went unnoticed.

### Work that is genuinely unblocked

**Phase 3 (cleaning & index engine)** does not need live collection to be
built — outlier flagging, imputation, Lowe/Young upper-level aggregation and
vintage stamping can all be developed and tested against fixtures, the same way
`jevons.py` already is. If the acquisition decision takes days to resolve, this
is the productive place to spend them. Remember the `fare_class` filter from
§5a: `tier1_tariff_floor` rows must be excluded from the headline series.

## 8. Open questions status (from `docs/05-open-questions.md`)

| # | Question | Status |
|---|---|---|
| Q1 | Booking-curve weights | Assumed curve in `config/booking_curve.yaml`, sensitivity band required |
| Q2 | "PSD" meaning | Adopted: DGCA passenger/revenue shares |
| Q3 | Back-test | Forward validation + pursue historical archive via DGCA |
| Q4 | DGCA/MoSPI engagement | Draft letter in `docs/07-dgca-outreach-draft.md` — **not sent yet** (user's action) |
| Q5 | Offered vs transaction price | Accepted: offered prices, stated in metadata |
| Q6 | Tier 2 budget | Assumed: no budget |
| Q7 | Anti-bot evasion exclusion | Accepted |
| Q8 | COICOP 2018 code | Deferred as config value |

---

## 9. Files NOT to touch / gotchas

- **`.env`** — contains real Supabase credentials. Never commit. `check_secrets.py` guards against this.
- **`bootstrap_db.sql`** — local-Postgres fallback, not in active use. Password is `CHANGE_ME` (placeholder).
- **`IMPLEMENTATION.md`** — the central build plan; Phases 0 and 1 are marked done there. Update it as phases complete.
- **`config/booking_curve.yaml`** — weights must sum to 1.0. Currently T+45 entry has already been removed (it was never there — the YAML was created after the T+45 removal from docs).
- **`scripts/sql/0002` is already applied** to the live Supabase DB — committed for the record, not to be re-run.

---

## 10. Database state

- **6 tables** created via `0001_init.sql`: `route`, `collection_run`, `selector_confirmation`, `fare_quote`, `stratum_panel`, `index_value`
- **10 placeholder routes** seeded (5 metro-metro pairs × 2 directions)
- **2 fare_quote rows**, both flagged `exclusion_reason` and `outlier_flag` — legacy, compliance-tainted, excluded from all index computation. Effectively the table is empty for index purposes
- **Unique index `uq_fare_quote_daily_observation`** enforces one observation per (source, carrier, route, departure date, window, fare class) per collection day
- **RLS enabled on all tables**, no policies (by design — see §5)
- `stratum_panel` and `index_value` are **empty** — populated in Phase 3

---

## 11. Test inventory

| File | Count | What |
|---|---|---|
| `test_jevons.py` | 9 | Golden-fixture Jevons tests (ILO-style worked examples) |
| `test_pdf_tariff.py` | 6 | Fixture-based parser tests (section tracking, NA handling, multi-section guard) |
| `test_compliance.py` | 18 | Robots enforcement, rate limiting, circuit breaking, composed PoliteFetcher |
| `test_tier1_indigo.py` | 8 | Adapter seam: collection_ts is fetch time, staleness warning, robots timestamp propagation, PoliteFetcher routing |
| **Total** | **41** | All pass in ~1s, no DB needed |
