# Session Handoff — AirTimeScanner / APIx

> **Last updated:** 2026-09-09, end of session
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
| **2 — Multi-source** | ✅ **Adapter live** | Air India adapter built, registered and run against the real sheet. 10 quotes/day flowing with a full fare decomposition — `IMPLEMENTATION.md §5d` |
| **3 — Cleaning & index engine** | ✅ Engine complete | Full pipeline built and verified end-to-end against Supabase. Still waiting on *offer* data — every row collected so far is a filed tariff band, which the engine correctly excludes — `IMPLEMENTATION.md §5c` |
| **4 — API & dashboard** | ❌ Pending | `/v1/index*` already reads `index_value`; returns empty until data exists |
| **5 — Docs & validation** | ❌ Pending | |

### START HERE TOMORROW

**The collection clock is running — do not break it.** The Air India adapter
is live and writing 10 quotes/day. `IMPLEMENTATION.md §0` notes the series is
wall-clock bound and cannot be backfilled, so from here the first duty of any
change is to not silently stop the daily run. Check `logs/collection.log` and
`collection_run.status` before anything else.

The next task is **the real DGCA route basket** (§7 item 1 below). It is the
last thing standing between the engine and a defensible upper-level
aggregation, and it depends on no carrier access at all.

**The GST decision is closed** (operator, 2026-09-09). Air India files
**base** fares while docs/02 §2 requires the headline on **total payable**, and
the sheet's *"5% ... on Base Fare & YR"* left it ambiguous whether the
pass-through airport charges sit inside the taxable base. **The rule in force
is the broad reading**: GST applies to base + UDF + ASF + RCS + CUTE, and not
to the fuel surcharge (YQ). For DEL→HYD:

```
taxable 1250 + 152 + 236 + 10 + 160 = 1808  ->  GST 90.40
total   1808 + YQ 549 + GST 90.40          =  2447.40
```

The narrower literal reading (GST on base + YR only) would give 71.00 and
2428.00 — about 2% on the index **level**, largely cancelling in the
period-to-period relatives docs/02 §3 validates against. Both readings are
written up in `tier1_air_india.py`'s docstring and the rule is pinned by
`test_gst_base_is_the_operator_chosen_broad_reading`. **If it is ever changed,
bump `CONFIG_HASH`** — vintage stamping is what makes a methodology change
visible instead of silent.

### The data situation

**The daily series has started.** `fare_quote` holds **12 rows**: the 2 old
IndiGo rows (flagged `exclusion_reason`, excluded) plus the first **10 Air
India rows**, one per basket route, each carrying a full decomposition —
`base_fare`, `udf`, `asf`, `rcs_levy`, `carrier_charges` (YQ), `gst`,
`total_fare`. First collected 2026-09-09; the scheduled task adds a day every
morning.

`stratum_panel` and `index_value` are still empty, and that is **correct, not
a bug**: every row collected so far is a filed tariff band, which the index
engine deliberately excludes from the headline (see §5's fare-class fork).
`run_index.py --dry-run` reports `quotes 0` and warns accordingly. The headline
series stays empty until a **Tier-3 offer** source exists — that is now the
binding constraint, not collection.

### What changed on 2026-09-09 (full detail in IMPLEMENTATION.md §5d)

1. **The Air India adapter went live** — `src/apix/acquisition/tier1_air_india.py`,
   registered in `scripts/run_collection.py`, verified against the real sheet
   and then against the actual table. 10 quotes on the first run, no warnings.
2. **The GST base decision was taken** (see START HERE above) and pinned by a
   test that fails loudly if the rule changes.
3. **Fixed: the decomposition columns were never persisted.** `base_fare`,
   `udf`, `asf`, `rcs_levy`, `gst` and `carrier_charges` have existed since
   `0001_init.sql` and `_persist_quotes` wrote none of them — it only ever
   wrote `total_fare`, because IndiGo's sheet publishes nothing else. Left
   unfixed, the Air India source would have thrown away the entire reason for
   adding it.
4. **Fixed: the index engine's headline filter was a single hard-coded tag.**
   It is now `TIER1_FILED_FARE_CLASSES`, a set. This is a silent-failure seam:
   a new Tier-1 adapter that tags distinctly and is not added to the set does
   not error — it quietly feeds filed tariff bands into the headline.
5. **Re-verified every carrier robots verdict** before the first live fetch.
   Air India still ALLOWED; both known-blocked controls still BLOCKED, so the
   checker has not regressed.

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

Branch `claude/airfare-price-index-india-saqd83`. Working tree clean, 119/119
tests green, ruff clean.

**10 commits unpushed** (the earlier batch of 10 has already been pushed):

```
85b807f  Record the Air India adapter and the closed GST decision in the docs
9886b82  Add the Air India adapter and start the daily collection series
191f6ff  Exclude every Tier-1 filed fare class from the headline index
1d18f4b  Update the handoff for end of session; correct an overstated test count
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
│   │   ├── compliance.py         # RobotsGate, RateLimiter, CircuitBreaker, PoliteFetcher
│   │   ├── pdf_tariff.py         # IndiGo-shaped tariff PDFs (MINUS SIGN separator) + CITY_TO_IATA
│   │   ├── ai_tariff.py          # Air India sheet — base fares + tax schedule
│   │   ├── tier1_air_india.py    # NEW: the live adapter — fare construction, GST rule, tax wedge
│   │   ├── tier1_indigo.py       # IndiGo adapter — works, but its source is robots-disallowed
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
├── tests/                        # 119 tests, no DB and no network needed
│   ├── test_jevons.py            # Golden-fixture elementary aggregation (ILO-style)
│   ├── test_index_engine.py      # Golden-fixture tests for the Phase 3 engine
│   ├── test_pdf_tariff.py        # IndiGo parser, fixture-based
│   ├── test_ai_tariff.py         # Air India parser, fixture-based
│   ├── test_tier1_indigo.py      # IndiGo adapter seams (the Phase-1 defect regressions)
│   ├── test_tier1_air_india.py   # NEW: the GST rule, the tax wedge, and what it refuses to fabricate
│   └── test_compliance.py        # RobotsGate, RateLimiter, CircuitBreaker
│
├── data/raw/                     # Content-hashed raw payloads (gitignored)
├── logs/collection.log           # Task Scheduler output
└── .scratch/                     # Scratch inspection files (gitignored)
```

---

## 5. Key architectural decisions & gotchas

### The filed-tariff fare_class fork
A Tier-1 tariff sheet gives a **filed fare band per city-pair**, not a
per-departure-date offer. These rows are written to `fare_quote` with
`departure_date` conventionally anchored to `collection_ts + 30 days` and a
`fare_class` tag saying what they are. **The index engine MUST filter them out
of the headline series** — they're validation/anchor data, not live index
inputs. See `IMPLEMENTATION.md §5a`.

There are now two tags, because they are different economic objects:

| Tag | Source | What it is |
|---|---|---|
| `tier1_tariff_floor` | IndiGo | Filed floor band, **total fare only**, non-directional |
| `tier1_filed_base_fare` | Air India | Filed **base fare + full decomposition**; base is non-directional but the tax wedge is not |

Both live in `apix.index.engine.TIER1_FILED_FARE_CLASSES`. **Adding a Tier-1
adapter means adding its tag there.** Forgetting does not fail — it quietly
contaminates the headline, which is precisely what the filter exists to
prevent.

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
.venv\Scripts\python.exe -m pytest -q          # 119 tests, no DB needed
uvicorn apix.api.main:app --reload --app-dir src   # http://127.0.0.1:8000/docs
python scripts/run_collection.py               # manual collection run
python scripts/run_index.py --dry-run          # compute the index, write nothing
python scripts/check_robots.py                 # re-verify every source's robots.txt
```

---

## 7. What to do next

### 1. Real DGCA route basket  ← the actual next task

`route.dgca_pax_weight` is NULL for all 10 placeholder routes, so the upper
level is currently **equal-weighted** — not the Lowe/Young revenue-share index
docs/02 §8 specifies. The engine warns about this on every run. Needs DGCA
passenger-traffic data; depends on no carrier access at all.

### 2. Found 2026-09-09, not fixed: the robots timestamp is lost on a disallow

`collection_run.robots_checked_at` is NULL for the IndiGo run, and NULL is
exactly the wrong value there — that run is the one where the robots check
*did* something. The cause: `RobotsDisallowed` is raised inside
`PoliteFetcher.get()`, so it escapes `fetch_and_parse()` and is caught by
`SourceAdapter.run()`'s catch-all, which builds a `CollectionResult` with no
verdict and `config_hash="unknown"`. The reason survives in `notes`; the
auditable timestamp docs/01 asks for does not.

Left alone deliberately — it is outside the Air India task and the fix wants
`RobotsDisallowed` to carry its `RobotsVerdict` so the adapter can catch it and
return a properly-stamped failed result. Small, but it touches the compliance
exception contract, so it deserves its own change.

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
- Base-fare / tax-wedge **sub-indices** — the inputs now exist in
  `fare_quote` (Air India writes the full decomposition daily), but nothing
  computes them yet. This is the first Phase-3 gap that is no longer blocked
  on data.

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
