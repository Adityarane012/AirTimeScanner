# 00 — Scope

## 1. What changed since the problem statement was written

The problem statement describes CPI price collection under the **2012 base-year
series**, where air fare sits as an item under the *Transport and Communication*
sub-group of the *Miscellaneous* group.

That is no longer the target. MoSPI released the **CPI 2024 base-year series on
12 February 2026**:

- Weights from **HCES 2023–24** (replacing CES 2011–12)
- **COICOP 2018** classification — 12 divisions, 43 groups, 92 classes, 162 sub-classes
- Weighted items increased from 299 to **358**
- Food and beverages weight cut sharply; **transport weight up materially**
- Stated methodology changes include *"inclusion of alternative data sources"*,
  *"use of modern technology"*, *"refinement in index compilation methodology"*
  and *"more granular data dissemination"*

Three consequences for this project:

1. **Air travel now classifies under COICOP 2018 Division 07 (Transport)**, in the
   passenger-transport-by-air class — not under *Miscellaneous*. All index outputs,
   API metadata and dashboard labelling must use COICOP 2018 codes so the series is
   internationally comparable and directly mappable onto the published series.
   *The exact sub-class code and its CPI 2024 weight must be read off MoSPI's
   published weighting diagram — see [Q8](05-open-questions.md#q8). It was not
   retrievable from this environment (mospi.gov.in is blocked by the network
   egress proxy), so no weight figure is asserted anywhere in these documents.*

2. **The positioning changes.** This is no longer a proposal to displace manual
   collection over institutional resistance. MoSPI has already committed to
   alternative data sources in the live series. The project supplies a concrete,
   auditable implementation of a commitment already made. That is a much easier
   case to make and it should be made explicitly.

3. **Transport carries more weight than it used to**, which raises the value of
   getting this sub-index right — though see §5 on not overclaiming.

## 2. What the system is

A pipeline that collects Indian domestic airfare quotes daily from multiple
sources, normalises them into a single comparable schema, and computes an
**Airfare Price Index (APIx)** at daily, weekly and monthly frequency, published
through a statistical API and an interactive dashboard.

Four components, in dependency order:

| # | Component | Output |
|---|---|---|
| A | Multi-source acquisition engine | Raw, evidence-preserved fare payloads |
| B | Cleaning and normalisation pipeline | De-duplicated quote database with full metadata |
| C | Index construction engine | APIx series, vintage-stamped and reproducible |
| D | API + dashboard | SDMX/JSON/CSV endpoints; trend, heatmap and elasticity views |

## 3. In scope

**Collection**
- Directional city-pair basket (~50 pairs, both directions treated separately),
  selected from DGCA passenger-traffic data, stratified metro–metro /
  metro–non-metro / RCS-UDAN
- Advance-purchase windows T+1, T+7, T+15, T+30, T+45 from each collection date
- Carriers: IndiGo, Air India, Air India Express, Akasa Air, SpiceJet
- One adult, one-way, economy, non-stop, lowest available fare as the headline
  quote; full fare ladder retained for research
- Daily collection cadence, with a fixed collection window and recorded
  collection timestamp per quote

**Processing**
- Fare decomposition: base fare, carrier/fuel charges, UDF, ASF, GST,
  RCS-UDAN levy, OTA convenience fee
- Outlier detection, sold-out and cancellation handling, imputation
- Immutable raw-payload retention for audit and reproducibility

**Index**
- Jevons elementary aggregates; Lowe/Young upper-level weighting on DGCA
  revenue shares
- Daily and weekly indicator series; monthly headline series
- Frozen vintages and a published revision policy

**Delivery**
- FastAPI service exposing **SDMX-JSON and SDMX-ML** alongside JSON and CSV
- Dashboard: index trends, sector heatmap, lead-time elasticity curves,
  carrier dispersion, and a data-quality/coverage panel
- Documentation, automated tests, and a validation report

## 4. Out of scope

| Excluded | Why |
|---|---|
| CAPTCHA solving, residential-proxy rotation, bot-management evasion | Contradicts the compliance requirement in the same paragraph of the problem statement; and an official statistic cannot rest on a supply line that breaks whenever a vendor updates its bot manager. See [`01-data-acquisition.md`](01-data-acquisition.md#what-we-do-not-build) |
| Mobile-app private API reverse-engineering | Same reasoning; additionally a clear ToS breach |
| International routes | DGCA monitors them, but the CPI item concerns domestic household consumption. Deferred, not rejected |
| Booking, ticketing, or any transaction capability | Read-only price observation only |
| Ancillary pricing (seats, bags, meals) as index components | Captured as metadata; not in the headline specification |
| Personal or passenger-level data | None collected. Keeps the system outside DPDP Act 2023 scope entirely |
| Replacing NSO collection | The system augments and cross-validates; substitution is a policy decision, not an engineering one |

## 5. Success criteria — and the honest value proposition

**Engineering**
- ≥95% daily collection success across the stratum grid, measured as filled
  quote-slots ÷ expected quote-slots
- Index reproducible bit-for-bit from the warehouse alone, with no live
  dependency on any source
- Full audit trail from published index value back to raw payload

**Statistical**
- Direction-of-change agreement with DGCA monthly average fares on comparable
  routes
- Route-level Spearman rank correlation against DGCA fare levels
- MAPE computed on **month-over-month changes, never on levels** — see
  [`02-methodology.md`](02-methodology.md#offer-price-vs-transaction-price)
- Documented sensitivity of the index to the booking-curve weighting assumption

**What this project should not claim**

Air fare is a small share of the CPI basket. Even a large, correct improvement in
airfare measurement moves headline retail inflation by a negligible amount. Any
pitch built on "fixing headline CPI" will not survive contact with a statistician.

The defensible value is threefold:

1. **Sub-index quality** — the airfare component becomes genuinely representative
   of dynamic pricing rather than a thin manual sample, at daily frequency.
2. **A reusable pattern** — the acquisition, evidence-retention, index and
   revision-policy machinery transfers directly to other volatile services MoSPI
   must eventually measure this way (rail, hotels, ride-hailing, streaming).
   This is the largest institutional payoff.
3. **A high-frequency policy indicator** — a daily airfare index has standalone
   value to RBI and to DGCA's tariff monitoring irrespective of whether it is ever
   folded into the official CPI.

State these three. Do not state a headline-CPI impact figure.
