# Session Handoff — AirTimeScanner / APIx

> **Last updated:** 2026-09-23
> **Purpose:** Everything the next coding session needs to pick up without re-reading the entire codebase.

---

## 1. What this project is (one paragraph)

**APIx** is an automated airfare price-collection and index-construction platform for Indian domestic routes, designed to augment CPI published by MoSPI/NSO. It collects fare data daily from legally mandated airline tariff-sheet disclosures (Tier 1) and, since 2026-09-23, from the one offer surface a compliant collector may fetch (Tier 3), normalises quotes into a comparable schema, computes a Jevons/Lowe-Young price index with vintage stamping and sensitivity bands, and exposes results via a FastAPI REST API. The repo name is `AirTimeScanner`, the Python package is `apix`.

---

## 2. Where we are in the build

| Phase | Status | Notes |
|---|---|---|
| **0 — Setup & recon** | ✅ Re-verified twice | Every robots verdict re-checked with a real parser. Two Phase-0 verdicts were wrong; one (EaseMyTrip) later *changed under us* — `docs/06` |
| **1 — Vertical slice** | ⚠️ Built, source blocked | IndiGo adapter works but its source is robots-disallowed (`Disallow: *.pdf`). Kept as a daily tripwire |
| **2 — Multi-source** | ✅ Two live adapters | Air India (Tier 1, filed tariff) and Goibibo (Tier 3, offers) |
| **3 — Cleaning & index engine** | ✅ Engine complete | Verified end-to-end. Still produces nothing, for the reason in START HERE |
| **4 — API & dashboard** | ❌ Pending | `/v1/index*` returns empty until the headline has inputs |
| **5 — Docs & validation** | ❌ Pending | |

### START HERE

**The one thing blocking a published index: no offer source with a departure
date we control.**

This is now an evidence-backed statement, not a design assumption:

1. **Filed tariffs cannot produce an index.** Fourteen days of Air India
   collection (09-09 to 09-23) moved by **exactly zero rupees** on all ten
   routes. The raw PDF's content hash is identical every day. A filed tariff is
   a document that changes a few times a year, not a market.
2. **Offers exist and are collectible** — `tier3_goibibo` proved it on 09-23 —
   **but the departure date is Goibibo's choice.** Query strings are
   robots-disallowed, so the date cannot be requested. Observed range on the
   first run: **T+8 to T+88, differing per route on the same day.**
3. So those rows are a **separate uncontrolled-lead series**, excluded from the
   headline by `ADVANCE_PURCHASE_WINDOWS` in `apix.index.engine`. Mixing lead
   times would make a period-to-period relative compare different goods.

**What would unblock the headline**, roughly in order of cost:

- A date-controllable offer source. Nothing found yet that is robots-allowed:
  every OTA's dynamic search path is disallowed (`docs/06`, Tier-3 sweep).
  Akasa's booking path is robots-allowed and was never probed — that is the
  cheapest unexplored lead.
- Tier 2, a licensed feed. There is **no free tier any more** (Amadeus closed
  its self-service portal in July 2026) — this needs a budget decision, Q6.
- Tier 0, the statutory ask. The draft letter in `docs/07` is written and
  **not sent**. The evidence for it is now much stronger than in Phase 0.

**The second task, unblocked and independent:** the real DGCA route basket.
`route.dgca_pax_weight` is NULL for all 10 placeholder routes, so the upper
level is equal-weighted, not the Lowe/Young revenue-share index docs/02 §8
specifies. The engine warns on every run. Needs DGCA passenger-traffic data and
no carrier access at all.

### The data situation

`fare_quote` holds **101 rows**:

| Source | Rows | What it is |
|---|---|---|
| `tier1_air_india_tariff` | 90 | 9 collection days × 10 routes, full decomposition, **zero variance** |
| `tier3_goibibo_offers` | 9 | First offer run, 09-23, five carriers, lead times 8–88 days |
| `tier1_indigo_tariff` | 2 | Legacy, flagged `exclusion_reason`, excluded everywhere |

`stratum_panel` and `index_value` are **empty, correctly**: filed tariffs are
excluded by fare class, and the Goibibo offers by advance-purchase window.
`run_index.py --dry-run` reports `quotes 0` and warns.

**The finding worth quoting to a sponsor:** on 2026-09-23, offers ran **1.6× to
3.6×** the filed tariff for the same route on the same day (DEL→HYD: filed
₹2,447, cheapest non-stop offer ₹8,933). Filed tariff bands are not prices
anyone pays.

### Collection reliability — where it actually stands

| Days since 09-09 | Collected | Missed |
|---|---|---|
| 15 | 9 | **09-10 to 09-13** (console-close bug, fixed), **09-18 to 09-19** (laptop off all day) |

Three fixes landed, all proven in production:

1. **Hourly launches** that skip a source already collected today
   (`apix.ops.collection_health.decide`). The 06:00-only schedule bet the whole
   day on one moment the laptop was rarely awake for.
2. **Missed-day alerts** (`apix.ops.notify`). Fired unattended on 09-20:
   *"collected again after missing 2 day(s): 2026-09-18 to 2026-09-19"*.
3. **The offline spool** (`apix.ops.spool`). Every result is written to disk
   before the database is touched, and uploaded by the next run that can reach
   it. **This rescued 09-23**, collected on a network that cannot reach Supabase.

**The remaining hole:** a day with the machine off is lost, and no local fix can
change that. See §7 — moving the collector to GitHub Actions is the permanent
answer.

### Network gotcha that cost nine runs

The direct Supabase host `db.<ref>.supabase.co` publishes **only an AAAA
record**. On an IPv4-only network psycopg fails with `getaddrinfo failed`.
`.env` now uses the **session pooler** (`aws-0-ap-south-1.pooler.supabase.com`,
username `postgres.<ref>`), which has A records. Note the campus network
(SVKMGRP.COM) additionally drops ports 5432 and 6543, so **no connection string
works there** — that is what the spool exists for.

---

## 3. Git state

Branch `claude/airfare-price-index-india-saqd83`, which **is** the repo default
(`origin/HEAD` points at it; `main` does not exist). Working tree clean, 177
tests green, ruff clean.

Recent commits, newest first:

```
6fd5851  Collect the first offer prices, from Goibibo's route pages
00bf21e  Keep collecting when the database cannot be reached
154f5cd  Point the connection string at the IPv4 session pooler
286f0ea  Alert when a collection day is lost instead of finding out days later
2dd2016  Run the collector hourly with no console window
24070b5  Skip collection sources that already ran today
```

Don't trust a hand-maintained "N commits unpushed" note — ask git:

```
git status -sb          # ahead/behind vs origin, after a fetch
```

Pushes are denied at the Claude Code session's permission layer, so run it
yourself, where Git Credential Manager can prompt:

```
git push origin claude/airfare-price-index-india-saqd83
```

## 4. Codebase map (what changed recently)

```
src/apix/
├── acquisition/
│   ├── tier1_air_india.py    # Tier 1 — filed tariff, full decomposition
│   ├── tier1_indigo.py       # robots-disallowed; kept as a daily tripwire
│   └── tier3_goibibo.py      # NEW 09-23 — the first offer source
├── ops/                      # operational bookkeeping (no index logic)
│   ├── collection_health.py  # decide(), assess(), run_alert()
│   ├── notify.py             # Windows toast; never raises, never opens a window
│   ├── sources.py            # THE source registry — add new adapters here
│   └── spool.py              # write-ahead spool; survives an unreachable DB
├── contracts/fare_quote.py   # advance_purchase_days is now int, not Literal
└── index/engine.py           # headline restricted to ADVANCE_PURCHASE_WINDOWS

scripts/
├── run_collection.py         # spool-first: fetch, write locally, then upload
├── check_collection.py       # NEW — is collection happening? Works offline
├── check_robots.py           # robots verdicts via the production parser
├── register_task.ps1         # hourly Task Scheduler registration
├── run_collection_scheduled.pyw  # pythonw entrypoint — no console to close
└── sql/0003_allow_uncontrolled_lead_times.sql   # NEW — applied to live DB
```

---

## 5. Key architectural decisions & gotchas

### The headline index has two independent gates
A row reaches the headline only if it is **not** a filed fare class *and* its
advance-purchase window is one of `ADVANCE_PURCHASE_WINDOWS` (1, 7, 15, 30).
The window gate was added with the Tier-3 source and does not depend on anyone
remembering to tag anything — the fare-class set does, which is why a second
gate exists.

### Absent charges must stay absent, never zero
Mumbai files no departure UDF; Goibibo publishes one undecomposed "Surcharges"
lump. Both leave the component columns `None`. Zero would assert a measurement
nobody made.

### A robots verdict is a fact with a timestamp
EaseMyTrip's recorded verdict became wrong without anyone touching it: the host
rewrote robots.txt to `Allow: *`. Re-run `scripts/check_robots.py` rather than
trusting this log or any other.

### Goibibo searches by city, the basket is keyed by airport
A DEL page serves DXN (Noida) and HDO (Hindon) journeys; BOM serves NMI (Navi
Mumbai). Those are skipped, not relabelled. On a normal day most of a page is
other airports and connections, so that skip is silent — only a route that
yields *nothing* raises a warning.

### A Tier-3 day is not always one row per route
The daily-observation unique index keys on the *served departure date*, and
Goibibo moves it. Two runs in one day (a `--force` run, say) can therefore
write two rows for the same route: on 09-24 DEL→BLR came back as T+7 in the
morning and T+8 in the afternoon, both at ₹8,828. That is honest — they are
two different products — but it means the offer series does not have a fixed
row count per day the way the Tier-1 series does.

### The collector must never need the database to collect
`apix.ops.spool` is the rule made structural. A day not *fetched* is gone; a day
not *uploaded* is merely waiting.

### robots.txt checks go through `scripts/check_robots.py` — never by grep
A rule can match by file extension (`Disallow: *.pdf`), invisible to a path
search. This cost Phase 1.

### Earlier gotchas, unchanged
The MINUS SIGN separator in IndiGo's PDF; Air India's four extraction hazards
(all pinned by tests); the identification fallback on hosts that reset a custom
User-Agent; Supabase RLS enabled with no policies; advance-purchase windows are
T+1/7/15/30 only for the *index* (the column now stores any 0–365).

---

## 6. Environment

| Item | Value |
|---|---|
| Python | 3.11.15 |
| Package manager | `uv 0.11.19` |
| Venv | `.venv/` |
| DB | Supabase Postgres 17, **via the session pooler** (see §2) |
| OS | Windows |
| Task Scheduler | `APIx-DailyCollection`, **hourly**, runs `run_collection_scheduled.pyw` under `pythonw` |

### Quick start
```
.venv\Scripts\python.exe -m pytest -q       # 177 tests, no DB needed
python scripts/run_collection.py            # one collection run
python scripts/check_collection.py          # health: missed days, pending uploads
python scripts/run_index.py --dry-run       # compute the index, write nothing
python scripts/check_robots.py              # re-verify robots verdicts
```

---

## 7. What to do next

1. ~~Move collection off this laptop.~~ **Done and proven on 2026-09-24.**
   `.github/workflows/collect.yml` collected from a GitHub runner at 13:05 UTC:
   Air India succeeded, Goibibo succeeded on all ten routes, and the rows are
   in the database. Two things that were genuinely unknown are now answered —
   **the datacenter IP is not a problem** (Air India is Akamai-fronted and
   served the runner fine), and the runner reaches Supabase through the pooler.
   The local Task Scheduler job stays enabled alongside it; whichever runs
   first collects and the other skips.

   The three scheduled runs before that failed, all the same way: the runner
   collected, could not write, and the job refused to let the container delete
   the spooled files. Fixed by re-setting the `DATABASE_URL` secret and by the
   preflight in `scripts/preflight_db.py`, which now stops a run *before* it
   fetches anything it cannot store. GitHub's cron is heavily delayed in
   practice — observed 5h18m and 4h01m late — so do not read a missing
   08:00 IST run as a failure until much later in the day.
2. **The real DGCA route basket** (§2). Unblocked, needs no carrier access.
3. **Probe Akasa's booking path** — robots-allowed, never fetched. The cheapest
   remaining lead on a date-controllable offer source.
4. **Send the DGCA/MoSPI letter** (`docs/07`, your action). The case is much
   stronger now: filed tariffs demonstrably do not move, and offers are 1.6–3.6×
   the filed band.
5. Still outstanding: Task Scheduler operational log (needs an elevated shell,
   `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`); SpiceJet's
   tariff URL; the Air India Express `/content/dam` conflict.

### Known gaps in Phase 3, deliberately deferred
Daily frequency only; monthly GEKS-Jevons not built (port from IndexNumR, don't
hand-write — `docs/08`); the DOW-adjusted variant; base-fare / tax-wedge
sub-indices (inputs exist, nothing computes them).

---

## 8. Open questions status

| # | Question | Status |
|---|---|---|
| Q1 | Booking-curve weights | Assumed curve, sensitivity band required |
| Q2 | "PSD" meaning | Adopted: DGCA passenger/revenue shares |
| Q3 | Back-test | Forward validation; historical archive via DGCA |
| Q4 | DGCA/MoSPI engagement | Draft ready, **not sent** (your action) |
| Q5 | Offered vs transaction price | Accepted: offered prices, stated in metadata |
| Q6 | Tier 2 budget | Assumed none — and there is no free tier any more |
| Q7 | Anti-bot evasion exclusion | Accepted, unchanged |
| Q8 | COICOP 2018 code | Deferred as config value |
| — | **OTA Terms of Service** | **Operator decision 2026-09-23: robots.txt is the gate, as for Tier 1. Goibibo's terms have not been read.** If revisited, `tier3_goibibo` is the thing to revisit |

---

## 9. Files NOT to touch / gotchas

- **`.env`** — real Supabase credentials, now pointing at the pooler. Never commit; `check_secrets.py` guards this.
- **`scripts/sql/0002` and `0003` are already applied** to the live database. Committed for the record, not to be re-run (0003 is idempotent anyway).
- **`data/spool/`** — gitignored. `pending/` holds collected runs not yet uploaded; deleting it loses real observations.
- **`IMPLEMENTATION.md`** — the central build plan; update it as phases complete.
- **`bootstrap_db.sql`** — unused local-Postgres fallback.

---

## 10. Database state

- **6 tables**; 10 placeholder routes seeded, **0 with a DGCA weight**.
- **101 `fare_quote` rows** (see §2 breakdown); `stratum_panel` and `index_value` empty.
- Unique index `uq_fare_quote_daily_observation` enforces one observation per (source, carrier, route, departure date, window, fare class) per collection day — this is what makes a re-run and a spool re-upload idempotent.
- `advance_purchase_days` CHECK is now **0–365**, not `IN (1,7,15,30)` (sql/0003).
- RLS enabled on all tables, no policies (by design).

---

## 11. Test inventory

| File | What |
|---|---|
| `test_jevons.py` | Golden-fixture elementary aggregation |
| `test_index_engine.py` | Phase 3 engine + the headline's window gate |
| `test_pdf_tariff.py` / `test_ai_tariff.py` | Parser fixtures (IndiGo / Air India) |
| `test_tier1_indigo.py` / `test_tier1_air_india.py` | Adapter seams, GST rule, tax wedge |
| `test_tier3_goibibo.py` | Non-stop selection, observed lead time, refusing other airports |
| `test_compliance.py` | Robots, rate limiting, circuit breaking, identification fallback |
| `test_collection_health.py` | When to fetch; missed-day detection and alerts |
| `test_spool.py` | The spool: an unreachable database must not cost a day |
| `test_notify.py` | Never raises, never opens a console window |
| **Total** | **177**, ~2s, no DB and no network |
