# 05 — Open Questions

Eight decisions the sponsor must make. Each carries a recommended default so that
work is not blocked while answers are sought — but Q1, Q3 and Q7 change what gets
built, and should be settled in Phase 0.

---

<a id="q1"></a>
## Q1 — Who supplies the booking-curve weights? ⚠️ *Blocking for the composite index*

The share of Indian domestic bookings made at each advance-purchase window
(T+1/7/15/30/45) is not public, and the composite index cannot be correctly
weighted without it. See [`02-methodology.md`](02-methodology.md#4-the-booking-curve-gap)
for why equal weighting fails badly rather than approximately.

**Options:** obtain from airlines/OTAs/DGCA · estimate from published studies ·
publish window-specific sub-indices only.

**Recommended default:** assumed curve in versioned config, **with a mandatory
published sensitivity band**, while pursuing the real distribution through DGCA
engagement. Never publish the composite as a bare point estimate.

---

<a id="q2"></a>
## Q2 — What does "PSD" mean in the problem statement? ⚠️ *Blocking for the weighting spec*

The problem statement specifies *"an index-construction module based on PSD given
routes and weights"*. The acronym is not defined and is genuinely ambiguous:

- **Problem Statement Document** — i.e. use the routes and weights given in the PS
- **Price Schedule Data** — the CPI price-collection schedule terminology
- **Passenger Segment Data** — DGCA route-level traffic

Each implies a different weighting source and a different index specification.

**Recommended default:** proceed on the third reading — DGCA passenger/revenue
shares — as it is the only one that yields defensible CPI-consistent weights, and
confirm at the Phase 0 gate.

---

<a id="q3"></a>
## Q3 — How is the back-test requirement to be satisfied? ⚠️ *Blocking for Phase 5*

*"At least 30 days of back-tested results against publicly available DGCA monthly
average-fare data"* is internally inconsistent:

- Scraped fares **cannot be collected retrospectively**, so nothing can be
  back-tested — only forward-validated.
- 30 days against a **monthly** benchmark yields **one** comparison point. One
  point supports no statistical claim of any kind.

**Options:**

| | Approach | Yields |
|---|---|---|
| (a) | Reframe as 30-day **forward validation** — daily stability, coverage, cross-source agreement — plus one DGCA point | Honest, achievable, weak external validation |
| (b) | Extend collection to **90 days** | Three DGCA points; the minimum for any credible comparison |
| (c) | Source a **historical fare archive** (DGCA TMU records, airline tariff-sheet history, MoSPI's existing air-fare price schedules, or a commercial historical dataset) and reconstruct APIx over 12–24 months | A genuine back-test |

**Recommended default:** (a) + (c). (a) is deliverable within the timeline; (c) is
the only route to a real back-test and is an institutional ask, not an engineering
task — so it must be raised in Week 1 or it will not arrive in time. Adopt (b) as
well if the schedule permits.

---

<a id="q4"></a>
## Q4 — Is DGCA / MoSPI engagement available?

This determines whether Tiers 0 and 1 are reachable
([`01-data-acquisition.md`](01-data-acquisition.md#the-four-tier-source-ladder)).
DGCA's Tariff Monitoring Unit already performs monthly fare collection from airline
websites across ~78 routes; MoSPI's CPI 2024 series already commits to alternative
data sources. Both are natural partners rather than cold approaches.

**Impact if unavailable:** no booking-curve data (Q1 degrades to assumption),
no historical archive (Q3 loses option (c)), and the project stays a technical
demonstration rather than a candidate for adoption.

**Recommended default:** open the approach in Week 1 regardless of expectations.
The downside is a letter; the upside changes the project's category.

---

<a id="q5"></a>
## Q5 — Is an offered-price index acceptable for CPI augmentation?

APIx measures **offered** lowest-available fares. CPI conceptually wants
**transaction** prices. See
[`02-methodology.md`](02-methodology.md#3-offer-price-vs-transaction-price).

Most NSOs using web-scraped airfares accept offered prices as the practical proxy,
and the alternative requires Tier 0 statutory returns. But the sponsor should
confirm the concept is acceptable **before** Phase 5, not after seeing a level gap
against DGCA and concluding the system is broken.

**Recommended default:** proceed on offered prices, stated prominently in all
metadata and dashboard surfaces, with validation defined on changes only.

---

<a id="q6"></a>
## Q6 — Is there a budget for licensed data (Tier 2)?

There is **no free licensed flight-fare API tier any more** — Amadeus closed its
Self-Service portal on 17 July 2026, Duffel's test environment returns synthetic
data, and Kiwi/Skyscanner partner access is invitation-only. Licensed feeds are now
a procurement line or they are absent.

**Impact if absent:** coverage rests on Tier 1 (statutory tariff sheets) plus
whatever Tier 3 sources permit collection — thinner and more fragile, though still
viable. Coverage claims must then be scoped to match, honestly, from the start.

**Recommended default:** proceed assuming no Tier 2 budget; treat any licensed
feed as an upside that improves coverage rather than a dependency.

---

<a id="q7"></a>
## Q7 — Does the sponsor accept the exclusion of anti-bot evasion? ⚠️ *Blocking for Phase 0 sign-off*

This project **will not build** CAPTCHA-solving, residential-proxy IP rotation, or
bot-management circumvention, for the operational and legal reasons set out in
[`01-data-acquisition.md`](01-data-acquisition.md#what-we-do-not-build) — chiefly
that such a pipeline does not stay working, and that it forecloses the cooperative
statutory route that solves Q1.

The problem statement asks for these capabilities in the same sentence as it asks
for robots.txt and ToS compliance. That tension needs an explicit owner's decision
rather than an implementation-level fudge.

**Recommended default:** accept the exclusion, and record it in the compliance
posture at the Phase 0 gate. If the sponsor requires the capability regardless,
that is their decision to make and to record — but it should be an explicit,
documented instruction, and the coverage and legal-risk consequences should be
restated at that point.

---

<a id="q8"></a>
## Q8 — Confirm the CPI 2024 target classification and weight

The system should emit **COICOP 2018** codes matching the live CPI 2024 series
(released 12 February 2026), not the old *Transport and Communication* sub-group of
the 2012 series.

Needed from MoSPI's published CPI 2024 weighting diagram:

- The exact COICOP 2018 class/sub-class code for passenger transport by air
- Its All-India weight, and the rural/urban split
- Whether air fare is separately weighted or bundled within a broader class

*This could not be retrieved while preparing these documents — `mospi.gov.in` is
blocked by this environment's network egress proxy. No weight figure is asserted
anywhere in this repository. The weighting diagram is published on mospi.gov.in and
cpi.mospi.gov.in under the announcements tab and should be read directly.*

**Recommended default:** treat the COICOP code as configuration from day one, so
that confirming it later is a config change rather than a schema migration.

---

## Summary

| # | Question | Blocking? | Needed by |
|---|---|---|---|
| Q1 | Booking-curve weights | ⚠️ Composite index | Phase 3 |
| Q2 | Meaning of "PSD" | ⚠️ Weighting spec | Phase 0 gate |
| Q3 | Back-test feasibility | ⚠️ Phase 5 | **Week 1** — institutional lead time |
| Q4 | DGCA/MoSPI engagement | No, but changes category | Week 1 |
| Q5 | Offered-price concept acceptable | No | Before Phase 5 |
| Q6 | Tier 2 budget | No | Phase 0 gate |
| Q7 | Evasion exclusion accepted | ⚠️ Phase 0 sign-off | Phase 0 gate |
| Q8 | COICOP 2018 code and weight | No | Phase 3 |
