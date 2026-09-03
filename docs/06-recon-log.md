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
| **IndiGo** | `https://www.goindigo.in/content/dam/s6web/in/en/assets/documents/IndiGo-Tariff-Sheet-2026-05-08.pdf` — dated-filename pattern, updates roughly monthly (Mar 24 → May 8 2026 seen) | **Likely allowed.** `goindigo.in`'s robots.txt disallows are scoped (`/content/dam/goindigo/investor-relations/restricted/*`, `/content/indigo/sme/`, etc.) — the tariff path is under `/content/dam/s6web/...`, a different subtree, not covered by any disallow found. **Not independently confirmed** — every direct `WebFetch` to `goindigo.in` itself (incl. `/robots.txt`) timed out (60s), consistent with docs/01's "High — Enterprise bot management" estimate. Verdict is from search-indexed robots.txt content, not a live fetch. | 3.2MB PDF, "R Graphics Output" per its PDF metadata — binary/vector content, not machine-readable text. **Confirm in Phase 1**: (a) live robots.txt fetch via Scrapling, (b) whether the PDF is actually parseable (may need PDF table extraction, not a simple selector) |
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

1. Live-verify IndiGo and Air India robots.txt via Scrapling (not WebFetch) —
   confirm the search-indexed content above is current and complete.
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
   (HTML, CSV) may exist and be preferable if so.
