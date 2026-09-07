# 06 — Phase 0 Reconnaissance Log

Real findings, not the anti-bot-posture *estimates* in `01-data-acquisition.md`'s
source table. Gathered via `WebFetch`/`WebSearch` in this session — treat as a
strong first pass, not a substitute for the "probe before escalating" live
check with `Fetcher(impersonate="chrome")` in Phase 1 (a different HTTP client
than what did this recon; a WebFetch timeout doesn't prove Scrapling will also
be blocked, and vice versa).

## Tier 1 — carrier tariff sheets

| Carrier | Tariff-sheet URL found | robots.txt verdict | Notes |
|---|---|---|---|
| **IndiGo** ❌ | `https://www.goindigo.in/content/dam/s6web/in/en/assets/documents/IndiGo-Tariff-Sheet-2026-05-08.pdf` — dated-filename pattern, updates roughly monthly (Mar 24 → May 8 2026 seen) | **❌ BLOCKED — the earlier "CONFIRMED ALLOWED" verdict recorded here was WRONG. See the correction section below.** The live robots.txt contains a single `User-Agent: *` group whose line 225 is `Disallow: *.pdf` — a site-wide rule disallowing every PDF on `www.goindigo.in`, the tariff sheet included. The original check searched the file for `s6web` (the tariff path's subtree), found nothing, and concluded allowed — it never checked for a rule matching by *file extension* rather than by path. Verified with `protego`: `can_fetch(tariff_url, 'APIx-Collector')` is `False`, and becomes `True` if and only if line 225 is removed. Non-PDF paths on the same host remain allowed | **Gotcha found and worth keeping — narrower than first thought**: `www.goindigo.in`'s **site root/HTML pages** (incl. `/robots.txt` itself) reset the connection (`HTTP/2 stream reset by server`) when fetched with a *custom* `User-Agent` header alongside `impersonate="chrome"` — a TLS/HTTP2 fingerprint mismatch. Dropping the custom header there fixed it. **But the DAM asset host serving the actual PDF does NOT have this problem** — re-tested the same PDF fetch *with* our honest, identifying UA (`APIx-Collector/0.1 (+mailto:...)`) alongside `impersonate="chrome"`, and it succeeded (`200`, same byte count). So: **the one-off robots.txt reconnaissance check needs impersonation with no extra header; the actual recurring adapter fetch can and should keep the honest self-identifying UA** — no compliance/evasion tension for the real adapter, only for this recon step. `tier1_tariff_stub.py` already does the latter correctly. PDF is "R Graphics Output" (vector/binary) — Phase 1 needs to confirm actual parseability, not assume it |
| **Air India** | `https://www.airindia.com/content/dam/air-india/pdfs/tariff/TARIFF-SHEET-AS-ON-15JUN26.pdf` — dated-filename pattern, several 2025–2026 versions indexed | **Unconfirmed.** Every `WebFetch` to `airindia.com/robots.txt` timed out — same signature as IndiGo. Docs/01 estimate: "High — Enterprise bot management" | Cadence looks roughly monthly-to-quarterly (Jul'25, Sep'25, Nov'24, Jan'26, Jun'26 seen) — check for a more current file in Phase 1 (today is Sep 2026, most recent found is Jun 2026) |
| **Air India Express** | `https://www.airindiaexpress.com/content/dam/airindiaexpress/documents/Air_India_Express_Tariff_Sheet.pdf` | **⚠️ BLOCKED.** Live-fetched robots.txt: `Disallow: /content/dam` and `Disallow: /dam`, both under `User-agent: *`. The tariff PDF's path (`/content/dam/airindiaexpress/documents/...`) matches the disallowed prefix exactly. | **Real conflict, not hypothetical**: the DGCA-mandated public disclosure sits under a path the airline's own robots.txt blocks for automated access. Per this project's compliance stance (docs/01, accepted in IMPLEMENTATION.md Q7) we do **not** bypass robots.txt. Options for Phase 1: check for a non-`/dam` mirror of the same data (an HTML page, not just the PDF); fall back to DGCA TMU data for this carrier; or treat as a manual-download-only source (a human, not an automated adapter, fetching it monthly is not "automated access" in the same sense — worth a real compliance read, not an engineering shortcut) |
| **Akasa Air** | `https://assets.akasaair.com/f/159922/x/c1ce86c83e/fare-sheet-akasa-air.pdf` — a Bynder-style DAM URL shape, last updated per search results "June 26, 2026" | **Ambiguous.** Main site `akasaair.com/robots.txt` is fully open (`User-agent: *`, no Disallow, two Sitemaps). But the PDF lives on a **separate third-party asset domain**, `assets.akasaair.com`, whose own `/robots.txt` returned **HTTP 403** — could mean "no robots.txt configured, default-open" or could mean the edge blocks automated fetches outright. Genuinely unclear, not defaulting either way | Confirm live in Phase 1: does a plain `Fetcher.get()` on the PDF itself succeed, and does the 403 on `/robots.txt` reproduce from a different client |
| **SpiceJet** | **Not located.** No tariff/fare-sheet PDF turned up via search under `spicejet.com`, `corporate.spicejet.com`, or `book.spicejet.com` | robots.txt confirmed live: `User-agent: *` mostly open, disallows only `/cgi-bin/`, `/api/v1`, `/public/`, `/externalBooking` — none of which would block a tariff page if one exists | **Carried to Phase 1**: manually browse `corporate.spicejet.com`'s legal/mandatory-disclosure section (Air India Express's equivalent page — `.../mandatory-disclosure/` — is where its fees PDF lived; SpiceJet may have an analogous path not surfaced by search) |

**Headline finding: 2 of 5 carrier main sites (IndiGo, Air India) block even a
basic automated `robots.txt` fetch outright** — this matches docs/01's
prediction exactly ("Enterprise bot management") and is now a confirmed
operational fact, not an estimate. Doesn't block Tier 1 collection of the
*tariff-sheet PDFs themselves* (those loaded fine via search-engine-indexed
URLs and, for Air India Express, a direct fetch) — but means routine
robots.txt re-checking (docs/01's "per-source robots.txt re-checked on every
run" rule) may itself need to run through Scrapling's impersonation layer,
not a plain request, for these two.

## ⚠️ Correction — IndiGo tariff PDF is robots.txt-disallowed (found 2026-09-07)

**This section corrects a Phase 0 finding that was wrong, and that Phase 1 was
built on top of.** Recording it rather than quietly editing history, because
the *way* it was wrong is the reusable lesson.

**What happened.** Phase 0 verified IndiGo's robots.txt by fetching it live and
searching for `s6web`, the tariff PDF's path subtree. There were no matches, so
the verdict recorded was "CONFIRMED ALLOWED — live-verified". The IndiGo
adapter was built and scheduled against that verdict, and ran daily.

**What was actually true.** The same robots.txt has one `User-Agent: *` group
containing, at line 225:

```
Disallow: *.pdf
```

A wildcard rule matching by file extension, not by path. It disallows every PDF
on `www.goindigo.in`. A substring search for the *path* could never find it.

**How it surfaced.** Wiring `PoliteFetcher` into the adapter — the compliance
module written in Phase 1 but not connected until now — turned the very first
real run into a clean `RobotsDisallowed` failure. The control worked exactly as
designed, on its first live exercise. It also means every collection run before
that point fetched a disallowed URL.

**The transferable lesson.** "Grep robots.txt for our path" is not a robots.txt
check. Rules match by prefix *and* by wildcard; a file-extension rule is
invisible to a path search. Only an actual parser evaluating the actual URL is
a verdict. Every carrier verdict in the table above that was reached by
substring search rather than by `protego` should be treated as unverified until
re-checked the right way — that includes Air India, Akasa and SpiceJet.

**Current state:** the gate is enforcing. The adapter fails cleanly, writes no
quotes, and records the reason in `collection_run.notes`. No exception was
added and no bypass was built — consistent with the Air India Express decision
already recorded above, and with Q7. The scheduled task is deliberately left
enabled: its daily robots.txt fetch is now the cheapest way to notice if this
rule ever changes.

**Open decision for the operator** (same shape as the Air India Express
conflict, and now the more urgent of the two): a DGCA-mandated *public
disclosure* sits behind a blanket `*.pdf` crawl rule that was near-certainly
aimed at search-engine indexing of marketing PDFs, not at a research collector
reading one filed tariff sheet once a day. The project's stated posture (docs/01,
Q7) does not permit deciding that unilaterally in code. The realistic options
are unchanged from the Air India Express case: seek written permission from the
carrier; ask DGCA for the filings directly (the outreach letter in
`docs/07-dgca-outreach-draft.md` becomes materially more important); find a
non-PDF representation of the same filing; or treat it as a manual,
human-download source rather than an automated one.

## Tier 3 — easiest OTAs, baseline only (deferred past week 1 per IMPLEMENTATION.md)

| Source | robots.txt verdict |
|---|---|
| **Cleartrip** | `Disallow: /flights/search*`, `/m/flights/search*`, `/flights/international/search`, `/flights/itinerary/*`, plus parametrized-URL blocks (`*?page=`, `*?service`) — **the actual fare-search and results paths are explicitly disallowed** |
| **EaseMyTrip** | `Disallow: /cheap_flights/`, `/cheap-flights/`, `/flight-search/listing*` — **same pattern**: the results-listing path is explicitly disallowed |

**This is a stronger finding than docs/01's "Moderate — assess individually"
estimate suggested**: both OTAs don't just have generic bot-management
friction, they **explicitly robots.txt-disallow the fare-search paths
themselves**. A compliant collector cannot hit these paths at all, regardless
of how well it evades bot detection — reinforces that Tier 1 is not just the
easier starting point but, for these two sources at least, close to the only
compliant option. Ixigo and Yatra not yet checked (deferred — Tier 3 is out
of scope for week 1 per IMPLEMENTATION.md §1).

## Open items carried into Phase 1

1. ~~Live-verify IndiGo robots.txt~~ — **done above, fully confirmed.**
   Air India's still not live-verified (same site-root reset expected;
   apply the same `impersonate="chrome"`-no-custom-header technique when
   it's Air India's turn).
2. Resolve the Air India Express `/content/dam` conflict — don't build an
   adapter against it until this is actually decided, not assumed.
3. Confirm `assets.akasaair.com`'s actual crawl posture (the 403 on
   `/robots.txt` is ambiguous, not a verdict).
4. Find SpiceJet's actual tariff-sheet URL (or confirm it doesn't publish one
   in a discoverable location, which would itself be a compliance-relevant
   fact worth raising with DGCA/the sponsor per Q4).
5. Sanity-check whether these PDFs are machine-parseable at all (IndiGo's is
   flagged as vector/graphics output) before committing to "PDF parsing" as
   the Phase 1 approach for any given carrier — a table-only alternate format
   (HTML, CSV) may exist and be preferable if so. **First concrete task of
   the Phase 1 build below.**

## Phase 0 sign-off

Per `docs/04-delivery-plan.md`'s Phase 0 gate ("sponsor answers Q4, Q6, Q7")
and this project's compressed solo form of it (`IMPLEMENTATION.md` §6, where
you are both engineer and sponsor):

- **Q7 (evasion exclusion) — accepted, and demonstrated in practice above.**
  Every fetch this session used a real, working, non-evasive path: honest
  identification where the target tolerated it, standard browser
  impersonation (not fingerprint spoofing beyond that, not proxy rotation,
  not CAPTCHA-solving) where a site's own edge needed a consistent TLS
  fingerprint to not misfire. No robots.txt was bypassed; the one confirmed
  block (Air India Express) was left blocked, not routed around.
- **Q6 (no Tier 2 budget) — accepted**, unchanged, no budget line surfaced.
- **Q4 (DGCA/MoSPI engagement) — outreach drafted**, not yet sent: see
  `docs/07-dgca-outreach-draft.md`. Sending it is yours to do (outbound
  correspondence to a government body under your name), not something to
  automate.
- **Compliance posture for the Phase-1 target (IndiGo)** — signed off:
  robots.txt confirmed clear, Terms & Conditions checked for anti-automation
  language (none found), identified UA used, rate limiting still to be
  applied at adapter-build time (single low-frequency fetch, not a crawl).
