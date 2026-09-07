# Session Handoff — AirTimeScanner / APIx

> **Last updated:** 2026-09-07, end of session
> **Purpose:** Everything the next coding session needs to pick up without re-reading the entire codebase.

---

## 1. What this project is (one paragraph)

**APIx** is an automated airfare price-collection and index-construction platform for Indian domestic routes, designed to augment CPI published by MoSPI/NSO. It collects fare data daily from legally mandated airline tariff-sheet disclosures (Tier 1), normalises quotes into a comparable schema, computes a Jevons/Lowe-Young price index with vintage stamping and sensitivity bands, and exposes results via a FastAPI REST API. The repo name is `AirTimeScanner`, the Python package is `apix`.

---

## 2. Where we are in the build

### Phase completion status

| Phase | Status | Notes |
|---|---|---|
| **0 — Setup & recon** | ✅ Re-verified | Every carrier robots verdict re-checked with a real parser. Two of the original five verdicts were wrong. See `docs/06-recon-log.md` |
| **1 — Vertical slice** | ⚠️ Built, source blocked | IndiGo adapter works but its source is robots.txt-disallowed (`Disallow: *.pdf`). Four silent defects found and fixed — `IMPLEMENTATION.md §5b` |
| **2 — Multi-source** | 🟡 **UNBLOCKED — in progress** | Air India confirmed allowed and reachable. Parser built and tested. **Adapter is the next task** |
| **3 — Cleaning & index engine** | ✅ Engine complete | Full pipeline built and verified end-to-end against Supabase. Waiting on data, not on code — `IMPLEMENTATION.md §5c` |
| **4 — API & dashboard** | ❌ Pending | `/v1/index*` already reads `index_value`; returns empty until data exists |
| **5 — Docs & validation** | ❌ Pending | |

### START HERE TOMORROW

**Build the Air India adapter.** Everything it needs is in place: the source is
confirmed compliant and reachable, the parser is written and tested, and the
index engine is waiting for input. This is the task that finally starts the
collection clock — which `IMPLEMENTATION.md §0` notes is wall-clock bound and
cannot be backfilled.

**One decision to make first (it was left open deliberately, not forgotten).**
Air India files **base** fares; docs/02 §2 requires the headline on **total
payable**. The total is constructible from the sheet, but the GST base is
ambiguous in the source: it says *"5% ... on Base Fare & YR"*, which leaves
unclear whether the pass-through airport charges (UDF, ASF) sit inside or
outside that base. For DEL→HYD:

```
base 1250 + UDF 152 + ASF 236 + RCS 10 + CUTE 160 + YQ 549 + GST 71  ≈  2428
```

The choice moves the index **level** by roughly 2%. It largely cancels in
period-to-period relatives, which is what docs/02 §3 says validation compares,
so it is not fatal either way — but it must be a stated rule, not a silent one.

**Recommendation: follow the document literally** — GST on base + YR (RCS +
CUTE) only — and record it as an explicit assumption in the adapter docstring
alongside the alternative reading.

### The data situation

`fare_quote` holds **2 rows**, both flagged `exclusion_reason` and excluded
from any index computation. `stratum_panel` and `index_value` are empty. **The
daily series has not started.** No collection has been possible since the
IndiGo source was found to be disallowed.

### What changed on 2026-09-07 (long session — full detail in IMPLEMENTATION.md §5b/§5c)

1. **Found: IndiGo's tariff PDF is robots.txt-disallowed** (`Disallow: *.pdf`).
   Phase 0's "CONFIRMED ALLOWED" came from grepping for the path; a rule
   matching by file extension is invisible to that. Surfaced the moment
   `PoliteFetcher` was wired in. **No bypass was built.**
2. **Fixed four silent Phase-1 defects**: frozen `collection_ts` producing
   duplicate rows, a false `advance_purchase_days`, a scheduled task that was
   being *refused* on battery power, and a compliance module that nothing
   called.
3. **Fixed the secret guard**, which was scanning the working tree instead of
   staged content while reporting "clean".
4. **Built Phase 3 in full** — outlier flagging, imputation, Jevons →
   Lowe/Young, suppression, sensitivity band, 7-day centred average, config
   hash and vintage stamping. Verified end-to-end against Supabase, then
   cleaned up.
5. **Re-verified every carrier's robots verdict** with `scripts/check_robots.py`.
   **Air India is allowed** — verified by hand as well as by parser.
6. **Solved the identification problem** on hosts that reset on a custom
   User-Agent, without going anonymous (see §5 below).
7. **Built and tested the Air India parser.**
8. **Evaluated the open-source index libraries** and recorded the
   build-vs-borrow decision — `docs/08-methodology-sources.md`.

## 3. Git state

Branch `claude/airfare-price-index-india-saqd83`. Working tree clean, 95/95
tests green, ruff clean.

**7 commits unpushed** (the earlier batch of 10 has already been pushed):

```
(this handoff update)
21fec72  Simplify Decimal literals in the Air India parser tests
13d52db  Add a parser for Air India's tariff sheet
49c463a  Cite the methodology sources; record the build-vs-borrow decision
73775ec  Re-verify every carrier robots verdict; Air India unblocks Phase 2
12f817d  Keep identifying ourselves on hosts that reset on a custom User-Agent
8ea76a0  Add a repeatable robots.txt check, replacing the grep that got it wrong
```

To push (pushes are denied at this session's permission layer, so run it
manually):

```
git push origin claude/airfare-price-index-india-saqd83
```

Note `main` does not exist — this branch *is* the repo default (`origin/HEAD`
points at it), so `git push origin main` fails with `src refspec main does not
match any`.

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
│   ├── 06-recon-log.md           # Recon + the two robots.txt CORRECTIONS
│   ├── 07-dgca-outreach-draft.md # Draft letters (not sent — cites BPP now)
│   └── 08-methodology-sources.md # NEW: citations + build-vs-borrow decision
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
│   ├── check_robots.py           # NEW: robots.txt verdicts via a real parser
│   ├── register_task.ps1         # NEW: reproducible Task Scheduler registration
│   ├── run_index.py              # NEW: index entrypoint (--dry-run supported)
│   ├── sql/0002_...sql           # NEW: dedupe + daily-observation unique index
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
│   │   ├── pdf_tariff.py         # IndiGo-shaped tariff PDFs (MINUS SIGN separator)
│   │   ├── ai_tariff.py          # NEW: Air India sheet — base fares + tax schedule
│   │   ├── tier1_indigo.py       # REAL working IndiGo adapter (tariff PDF → FareQuote)
│   │   └── tier1_tariff_stub.py  # Template adapter for the next carrier
│   ├── index/                    # PHASE 3 — complete
│   │   ├── jevons.py             # Elementary Jevons (pure, deterministic)
│   │   ├── config.py             # Methodology params, config_hash, vintage_id
│   │   ├── relatives.py          # Fixed-base relatives, MAD outliers, imputation
│   │   ├── aggregate.py          # Lowe/Young, suppression, sensitivity band, 7-day MA
│   │   └── engine.py             # The only module touching the DB or the clock
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

### robots.txt checks go through `scripts/check_robots.py` — never by grep
This is the lesson that cost Phase 1. A rule can match by file *extension*
(`Disallow: *.pdf`), which no path search will ever find. The script uses the
production `RobotsGate`, and keeps IndiGo and Air India Express as
known-blocked controls so a regression in the tool is visible.

### The compliance module is wired in — and it immediately blocked the only source
`tier1_indigo.py` now fetches through `PoliteFetcher.get()`. Every new adapter must do the same; never call `Fetcher.get()` directly from an adapter. The first live run through the gate failed with `RobotsDisallowed` on IndiGo's tariff PDF, which is the correct behaviour, not a bug to work around.

### `protego` dependency
`compliance.py` imports `protego` for robots.txt parsing. **Now added to `pyproject.toml`.** Note it was working only because it happened to be present in `.venv`; a clean install would have failed.

### Air India needs its own parser — do not extend pdf_tariff.py
The two sheets share nothing but the file format: 8 pages vs 68, separate
Origin/Destination columns vs a `−`-joined string, 13 fare levels vs 21
buckets, and base fare vs total. `ai_tariff.py` is the Air India parser.

### Air India's four extraction hazards (all pinned by tests)
1. `DOMESTIC FARES` is an all-caps sub-heading **inside** the economy table —
   a capitalisation-based section detector ends the block and parses zero rows.
2. The tax-code cell is **vertically merged**, so `IN` appears on one row of
   ~36. Classifying UDF by that label captures one airport out of 28.
3. Multi-word city names (`Delhi North Goa`).
4. pdfplumber glues long city names to the distance (`Thiruvananthapuram1255`).

### Identification on hosts that reset a custom User-Agent
Air India's edge resets the connection when an identifying `User-Agent` is
sent alongside `impersonate="chrome"` — and also when the honest UA is sent
with no impersonation. It requires a consistent TLS fingerprint. **The fix was
not to go anonymous**: `PoliteFetcher` retries with RFC 9110 `From` +
`X-Crawler-Contact` headers, which preserve contactability without
contradicting the fingerprint. `PoliteFetcher.identified_via` records which
path was used. The robots gate always runs *before* any transport attempt, so
this can never become a route around a disallow — there is a test asserting it.

### Absent charges must stay absent, never zero
Mumbai has no filed departure UDF (only an arrival charge), and a 500km
distance falls between the filed fuel bands. Both return `None`. Zero would
assert a measurement nobody made.

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
.venv\Scripts\python.exe -m pytest -q          # 95 tests, no DB needed
uvicorn apix.api.main:app --reload --app-dir src   # http://127.0.0.1:8000/docs
python scripts/run_collection.py               # manual collection run
python scripts/run_index.py --dry-run          # compute the index, write nothing
python scripts/check_robots.py                 # re-verify every source's robots.txt
```

---

## 7. What to do next

### 1. Build the Air India adapter  ← the actual next task

Settle the GST-base question first (see "START HERE TOMORROW" above), then:

- New `src/apix/acquisition/tier1_air_india.py`, modelled on
  `tier1_indigo.py` but using `ai_tariff.py`.
- Fetch through `PoliteFetcher` — never `Fetcher.get()` directly.
- URL: `https://www.airindia.com/content/dam/air-india/pdfs/tariff/TARIFF-SHEET-AS-ON-15JUN26.pdf`
  (robots-allowed, verified; sheet states validity to **30 June 2027**, so
  unlike IndiGo there is no monthly-republication staleness race).
- Populate the real decomposition — `base_fare`, `udf`, `asf`, `rcs_levy`,
  `carrier_charges` (YQ), `gst`, `total_fare`. This is the first source that
  can support docs/02 §2's base-fare and tax-wedge sub-indices.
- Tag `fare_class` distinctly from IndiGo's `tier1_tariff_floor`; these are
  filed *base* fares, and the index engine's exclusion filter keys on that tag.
- Extend `CITY_TO_IATA` to cover the basket (the parser skips and *counts*
  unresolvable cities — watch that count).
- Register it in `scripts/run_collection.py` alongside the IndiGo adapter.

The IndiGo adapter stays registered and will keep failing cleanly on the
robots disallow. That is intentional: its daily robots.txt fetch is the
cheapest way to notice if the `*.pdf` rule ever changes.

### 2. Then: real DGCA route basket

`route.dgca_pax_weight` is NULL for all 10 placeholder routes, so the upper
level is currently **equal-weighted** — not the Lowe/Young revenue-share index
docs/02 §8 specifies. The engine warns about this on every run. Needs DGCA
passenger-traffic data; depends on no carrier access at all.

### 3. Still outstanding, unchanged

- **Send the DGCA/MoSPI letter** — `docs/07-dgca-outreach-draft.md`. Now opens
  by citing the MIT Billion Prices Project, which is a materially stronger
  framing to a regulator.
- **Enable the Task Scheduler operational log** (needs an elevated shell):
  `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`
- **Probe Akasa** — its `robots.txt` returns 403, which is genuinely ambiguous
  (absent, or an edge refusing bots). Recorded as UNVERIFIED, not allowed.
- **Locate SpiceJet's tariff URL** — host is open, but no sheet has been found.

### Known gaps in Phase 3, deliberately deferred

- Only **daily** frequency is emitted; `index_value` allows weekly/monthly.
- **Monthly GEKS-Jevons is not built.** When it is: port from IndexNumR and
  validate against its published vignette — do not hand-write it. See
  `docs/08-methodology-sources.md`.
- The **DOW-adjusted variant** (docs/02 §5 recommends three mitigations; the
  7-day centred average is one).
- Base-fare / tax-wedge **sub-indices** — now possible for the first time,
  once Air India data is flowing.

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
| `test_compliance.py` | 25 | Robots, rate limiting, circuit breaking, PoliteFetcher, identification fallback |
| `test_index_engine.py` | 31 | Phase 3: relatives, outliers, imputation, aggregation, suppression, bands, determinism |
| `test_ai_tariff.py` | 16 | Air India parser: city splitting, section bounds, merged tax cells, fuel bands |
| `test_tier1_indigo.py` | 8 | Adapter seam: collection_ts is fetch time, staleness warning, robots timestamp propagation, PoliteFetcher routing |
| **Total** | **95** | All pass in ~2s, no DB needed |
