# 01 — Data Acquisition Strategy

## The contradiction in the problem statement

One paragraph asks the system to handle *"dynamic CAPTCHAs, anti-bot measures, IP
rotation, and session management"* and, in the same sentence, to remain *"compliant
with the robots.txt and terms of service of source websites"*.

These are not compatible. robots.txt on airline and OTA fare-search paths is
generally restrictive, and their terms of service prohibit automated access.
Defeating a CAPTCHA is definitionally the circumvention of an access control that
says no.

This document resolves the contradiction by **inverting the usual order of
attack**. Most teams start at the booking engine — the hardest, most legally
exposed, least stable surface — and work outwards. We start at the statutory
sources and treat the booking engine as the last resort.

## The four-tier source ladder

### Tier 0 — Statutory returns *(production endgame; not achievable in prototype)*

The **Collection of Statistics Act, 2008** empowers MoSPI to require statistical
returns from any person or company. Airfare data can be notified as a required
return.

This is the only path that yields **transaction-weighted realised fares with
booking-lead-time distributions** — that is, the data that resolves the project's
single largest methodological gap (see [`02-methodology.md`](02-methodology.md#the-booking-curve-gap)).
No amount of scraping produces it, because offered prices do not carry volumes.

A prototype cannot invoke this. But the scope document must name it, because it is
what makes the system *sustainable* rather than a permanently adversarial arms
race. The prototype's job is to be good enough to justify the statutory ask.

### Tier 1 — Mandated public tariff sheets *(build first)*

**Rule 135(2) of the Aircraft Rules, 1937** requires every air transport
undertaking to publish its established tariff on its website or in two daily
newspapers, and to display it in its offices. **DGCA Air Transport Circular 02 of
2010** sharpens this: airlines must display, on their websites, the **tariff sheet
route-wise across their network in various fare categories** and the manner in
which each is offered.

This matters more than it first appears:

- It is a **legally mandated public disclosure**, not a booking funnel. Collecting
  it is on far firmer ground than scraping a search result.
- It is comparatively **static and low-hostility** — no CAPTCHA, no session state,
  no dynamic rendering in most cases.
- It gives the **fare-bucket ladder** — the fare categories and their price points —
  which is exactly the structural information needed to interpret a lowest-available
  fare observation.
- **DGCA's own Tariff Monitoring Unit already does this**: monthly monitoring of
  fares on ~78 routes covering roughly 27% of domestic traffic, collected from
  airline websites. There is an existing government precedent for the method, an
  existing benchmark series, and an obvious institutional partner.

Tier 1 alone will not produce a daily dynamic-fare index — published tariffs are
ranges, not live availability-adjusted prices. But it anchors the fare structure,
validates the live tier, and is the component least likely to break.

### Tier 2 — Licensed and commercial feeds *(budget line, not free)*

Airline NDC/distribution APIs, GDS access, OTA affiliate and partner programmes,
and commercial flight-pricing vendors.

**A 2026 correction worth noting:** the standard recommendation here used to be the
Amadeus Self-Service API free tier. **Amadeus closed its Self-Service portal on
17 July 2026**, taking the free sandbox with it. Current realistic options:

| Option | Reality |
|---|---|
| Amadeus Enterprise | Full catalogue, access on request, commercial terms |
| Duffel | Test environment exists but its data is synthetic, not real fares |
| Kiwi Tequila | Partner access is invitation-only |
| Skyscanner partner API | Partner programme, commercial terms |
| Commercial fare-data vendors | Paid, per-call or subscription |

The scoping implication is concrete: **there is no free licensed API tier any
more.** Either a budget line exists for Tier 2 or it does not, and that answer
changes the achievable coverage. Raise it early — see [Q6](05-open-questions.md#q6).

### Tier 3 — Consented public-page collection *(the actual scraper)*

Where, and only where, robots.txt permits the path:

- Identified, contactable user agent naming the project and an operator email
- Conservative rate limits — target load indistinguishable from a slow human;
  one request per source per several seconds, with jitter
- Off-peak collection windows, so we never contend with real booking traffic
- Full backoff and circuit-breaking on 429/403; a source that signals stop, stops
- Per-source robots.txt re-checked on every run, not cached indefinitely
- Raw payloads retained content-hashed as immutable evidence

This is where a real browser session lives, for genuinely JavaScript-rendered
pages — see [`03-architecture.md`](03-architecture.md#acquisition-scrapling-across-the-tier-ladder)
for the tool decision and the fetcher-per-tier mapping. Escalate to it only after
a lighter-weight impersonated HTTP request has actually been tried and blocked,
per source.

## What we do *not* build

**Excluded: CAPTCHA-solving services, residential-proxy IP rotation to evade bot
management, session/credential reuse, and mobile-app private-API
reverse-engineering.**

The ethical argument is real, but the *operational* argument is the one that should
persuade a sponsor:

1. **It does not stay working.** Akamai Bot Manager and equivalents update
   continuously. Every update is an unplanned outage on a series with a publication
   schedule. An official statistic cannot have a release calendar hostage to a
   vendor's release calendar.
2. **It forecloses Tier 0.** The moment MoSPI is seen to be circumventing airline
   access controls, the cooperative statutory route — the one that actually solves
   the booking-curve problem — becomes politically much harder. The prototype
   would be trading away the production system.
3. **It is legally exposed.** ToS breach as contract (Indian Contract Act),
   potential exposure under IT Act s.43 for downloading data from a computer
   resource without permission, and thin but non-zero compilation-copyright risk.
   Note that DPDP Act 2023 is *not* engaged, because no personal data is touched —
   a point worth making explicitly, as it is often assumed to apply.
4. **The requirement is soluble another way.** Tiers 0–2 exist precisely because
   this problem has been solved institutionally before.

If the sponsor requires the evasion capability regardless, that is their call to
make — but it should be made explicitly and recorded, not smuggled in as an
implementation detail. See [Q7](05-open-questions.md#q7).

## Source-by-source assessment

Anti-bot posture below is an initial estimate to be confirmed in Phase 0
reconnaissance. It drives sequencing, not final source selection.

| Source | Tier | Expected difficulty | Notes |
|---|---|---|---|
| Airline tariff sheets (all 5 carriers) | 1 | Low | Statutory publication; **build first** |
| DGCA TMU published monitoring | 1 | Low | Benchmark series and partnership route |
| SpiceJet booking | 3 | Moderate | Historically lighter protection |
| Akasa Air | 3 | Moderate | Navitaire-based platform |
| Air India Express | 3 | Moderate | Navitaire-based platform |
| IndiGo | 3 | High | Enterprise bot management |
| Air India | 3 | High | Enterprise bot management |
| MakeMyTrip / Goibibo | 3 | High | Heavy protection; same corporate group |
| EaseMyTrip / Ixigo / Cleartrip / Yatra | 3 | Moderate | Assess individually in Phase 0 |

**Design consequence:** because Tier 3 sources will be unreliable and will fail
asymmetrically, the architecture must isolate them. Every source is an independent
adapter behind one stable `FareQuote` contract. A source going dark degrades
coverage on its strata and raises an alarm; it never fails the index build. This is
the single most important architectural constraint and it comes directly from this
analysis — see [`03-architecture.md`](03-architecture.md#adapter-isolation).

## Coverage floor

Define, before building, the minimum stratum coverage below which a daily index
value is **suppressed rather than published**. Publishing a value computed from a
collapsed sample is worse than publishing nothing, and official statistics
practice requires the suppression rule to be set in advance rather than negotiated
after a bad day. Recommend: suppress a stratum below 60% expected slot fill;
suppress the headline below 75% overall.
