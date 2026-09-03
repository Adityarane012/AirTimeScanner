# 02 — Index Methodology

This is the document that determines whether the output is a credible statistic or
a dashboard. The engineering in [`03-architecture.md`](03-architecture.md) is
comparatively routine; the decisions below are not.

## 1. Product specification

CPI methodology requires a tightly specified, repeatable product. Ours:

> One adult passenger, one-way, economy cabin, **non-stop**, hand-baggage
> inclusive, **lowest available total fare**, on a specified **directional**
> origin–destination pair, with a specified carrier, for a specified departure
> date, excluding all optional ancillaries, observed at a recorded collection
> timestamp.

Notes on each choice:

- **Directional.** DEL→BOM and BOM→DEL price differently and must be separate
  strata. Treating a city-pair as symmetric is a common and material error.
- **Non-stop only.** A connecting itinerary is a different product. Including it
  contaminates the price relative with a quality change.
- **Lowest available.** This is what a price-sensitive consumer faces and what
  OTAs surface. It also has a useful property under sold-out conditions — see §6.
- **Total fare, not base fare** — see §2.
- **One-way.** Simpler to specify than return, and return fares in the Indian
  domestic market are generally the sum of two one-ways rather than a distinct
  product. Revisit if Phase 0 reconnaissance contradicts this.

The **full fare ladder** (all available buckets and their prices) is captured and
stored, but is not part of the headline specification. It is research data and
supports the elasticity views on the dashboard.

## 2. Which price: base fare or total?

The problem statement asks for separation of base fare from taxes, UDF and
convenience charges. That separation is correct as a *diagnostic*, but the
**headline index must run on the total payable fare**.

CPI is an acquisition-price index: it measures what the household actually parts
with. GST is in scope for CPI. A regulated charge increase is a genuine price
increase to the consumer, not a distortion to be stripped out.

Components to decompose and store:

| Component | Nature | In headline? |
|---|---|---|
| Base fare | Airline-set, dynamic | Yes |
| Carrier/fuel charges | Airline-set | Yes |
| UDF — User Development Fee | Airport-specific, regulated | Yes |
| ASF — Aviation Security Fee | Fixed per departing passenger, MoCA-revised | Yes |
| RCS/UDAN levy | Route-applicable statutory levy | Yes |
| GST | 5% economy / 12% business, domestic | Yes |
| OTA convenience fee | Unavoidable on that channel | Yes, when unavoidable |
| Seats, bags, meals, insurance | Optional ancillaries | No |

Publish sub-indices on base fare and on the **tax-and-fee wedge** separately. The
wedge series is genuinely useful to policy — it isolates administered price changes
from market pricing, which is something the current CPI cannot show at all.

## 3. Offer price vs transaction price

**Scraped fares are offers. DGCA average fares are realised transactions.** These
are different economic objects and they will not agree in level.

An offered lowest-available fare is an upper-envelope observation on a
supply-constrained menu; a realised average fare is a volume-weighted outcome
across every bucket actually sold, including corporate, group and promotional
inventory not visible to a public search.

Two consequences, both important:

1. **Validation must compare changes, never levels.** A level comparison will show
   a persistent gap and will be misread as the system being wrong. Every
   validation metric in this project is defined on month-over-month or
   period-over-period *changes*: direction-of-change agreement, rank correlation,
   and MAPE on changes.
2. **It must be stated in the metadata and on the dashboard.** APIx is an
   *offered-price* index. If the sponsor requires a transaction-price index for CPI
   substitution, that requires Tier 0 data and is a different project — see
   [Q5](05-open-questions.md#q5).

## 4. The booking-curve gap

*This is the largest unresolved methodological issue in the project, and the
problem statement does not mention it.*

The mandated design collects five advance-purchase windows (T+1, T+7, T+15, T+30,
T+45). To combine them into one index, each window needs a weight: **the share of
Indian domestic bookings actually made at that lead time.**

That distribution — the booking curve — is not publicly available.

The failure mode if it is ignored is not subtle. Equal-weighting the five windows
implicitly asserts that as many passengers book one day out as book forty-five days
out. Last-minute fares run several times advance fares, so equal weights would:

- **overstate the index level** substantially,
- **overstate its volatility**, because the T+1 stratum is by far the noisiest, and
- make the series respond to capacity shocks in a way no consumer experiences.

Options, in order of preference:

1. **Obtain the curve from airlines/OTAs/DGCA** (Tier 0/1 engagement). Correct
   answer; requires institutional access.
2. **Estimate it** from any available booking-lead-time study for the Indian
   domestic market, applied as a fixed assumed curve, versioned in configuration.
3. **Publish window-specific sub-indices only** and defer the composite. Honest,
   but delivers less than the problem statement asks for.

**Recommended for the prototype:** option 2 as the default, with the curve held in
a versioned config file, *plus* a mandatory **sensitivity band** published
alongside every composite value showing the index under plausible alternative
curves. Never publish the composite as a point estimate without the band. And
pursue option 1 in parallel, because it is the thing that upgrades the prototype
into a production statistic.

## 5. The day-of-week artefact

A concrete consequence of fixed advance-purchase windows that is easy to miss.

Under daily collection with a fixed lead time, each window has a **fixed weekday
offset** from the collection date, because the offsets are congruent modulo 7:

| Window | Offset mod 7 | Departure weekday, relative to collection weekday |
|---|---|---|
| T+1 | 1 | next day |
| T+7 | 0 | **same weekday, always** |
| T+15 | 1 | next day |
| T+30 | 2 | two days later |
| T+45 | 3 | three days later |

So T+7 collected on a Monday *always* prices a Monday departure. Airfares have a
strong, systematic day-of-week pattern. Therefore **the raw daily index carries a
deterministic 7-day cycle that is an artefact of the collection design, not a
price signal.**

Mitigations, all three recommended together:

- Publish the daily headline as a **7-day centred moving average**; expose the raw
  daily series as a separate, clearly labelled diagnostic.
- Model the day-of-week effect explicitly and **publish a DOW-adjusted variant**.
- Ensure the **weekly and monthly** series aggregate over complete weeks, so the
  cycle averages out by construction.

Failing to handle this produces a headline index that oscillates on a weekly
rhythm and will be — correctly — dismissed on first inspection.

## 6. Missing values, sold-out flights and cancellations

The critical distinction, which the problem statement conflates:

- **A sold-out cheap bucket is not missing data. It is a price signal.** When the
  lowest available fare rises because the cheap inventory is gone, that is exactly
  the inflation the index exists to measure. Under the lowest-available-fare
  specification this is captured correctly and automatically. Do nothing.
- **A cancelled or withdrawn flight** — no service offered on that route/date/carrier
  — is genuine missingness in that stratum.
- **A collection failure** (source blocked, parse error, timeout) is missingness of
  a different kind and must be recorded with a distinct reason code, never silently
  merged with the above.

Every quote row carries an explicit **observation status**: `observed`,
`no_service`, `collection_failed`, `imputed`. Aggregation rules differ by status,
and the API exposes the status mix so consumers can judge a value's quality.

**Imputation:** use **stratum class-mean imputation** — impute the missing price
relative from the mean relative of the stratum it belongs to. Do **not** carry the
last price forward; carry-forward mechanically dampens measured inflation and is
discouraged in HICP practice for exactly this reason.

## 7. Outlier treatment

Airfare price distributions are heavily right-skewed, so symmetric outlier rules
misbehave. Recommended:

- Work on **log price relatives**, not levels
- Flag on a robust criterion (median absolute deviation, or the quartile-based
  tau method used in HICP practice) computed **within stratum**, never pooled
  across routes of different distances
- **Flag and review, do not silently drop.** A genuine 300% festival surge is the
  signal, not the noise. Automatic deletion of large moves is the fastest way to
  build an index that cannot see the thing it was built to see.
- Retain every excluded observation with its exclusion reason, so exclusions are
  auditable and reversible in a revision.

## 8. Aggregation

### Elementary level (within stratum)

**Jevons** — the unweighted geometric mean of price relatives.

- **Carli** (arithmetic mean of relatives) has a known upward bias and is
  prohibited in HICP. Do not use it.
- **Dutot** (ratio of mean prices) is invalid across heterogeneous items — a
  stratum containing routes of different stage lengths would be dominated by the
  long-haul price level. Only defensible within a very tight stratum.
- **Jevons** handles skewed distributions well, is the HICP default for
  heterogeneous elementary aggregates, and implies a unit elasticity of
  substitution — a reasonable assumption for consumers choosing between carriers on
  a route.

Stratum definition: `origin × destination × direction × advance-purchase window`,
with carriers as the items *within* the stratum. This lets carrier substitution
happen inside the geometric mean, which is what consumers actually do.

### Upper level (across strata)

**Lowe/Young weighted arithmetic aggregation**, weights from DGCA passenger traffic
× average fare (i.e. route revenue shares), combined with the booking-curve weights
from §4. Weights are held in versioned configuration and updated on a stated
schedule, not continuously.

### Chaining and drift

**Daily chaining is prohibited in this design.** Chaining a bouncing, high-frequency
price series produces severe chain drift — the index wanders away from its own
fixed-base value for purely mechanical reasons. Airfares bounce more than almost
any other consumer price.

Therefore:

- **Daily and weekly series:** fixed-base bilateral within the month. No chaining.
- **Monthly headline:** rolling-window **multilateral** method — GEKS-Jevons or a
  Time Product Dummy over a 13-month window, extended by mean splicing.

The multilateral choice is not gold-plating. Airfare data has precisely the
characteristics multilateral methods were developed for in the scanner-data
literature: high frequency, high churn (routes and carriers entering and exiting
the sample), and volatile relatives. Rolling-window GEKS with splicing is
established practice at ONS, ABS and Statistics Netherlands for exactly this data
shape.

## 9. Vintages and revisions

Non-negotiable for anything intended for official use:

- Every published value is **stamped with a vintage** and is immutable once published
- The index is **recomputable bit-for-bit** from the warehouse alone, with no live
  source dependency
- Methodology parameters (weights, booking curve, outlier thresholds, suppression
  floors) are **versioned configuration**, and every published value records the
  config hash it was computed under
- A **written revision policy** states when revisions occur, how far back they
  reach, and how they are announced — published before the first release, not
  written after the first embarrassment

## 10. Validation design

Against DGCA monthly average fares, on comparable routes:

| Metric | Computed on | Why |
|---|---|---|
| Direction-of-change agreement | MoM changes | The primary test. Does APIx move the right way? |
| Spearman rank correlation | Route-level fare levels | Tests cross-sectional plausibility without requiring level agreement |
| MAPE | MoM changes only | Level MAPE is meaningless here — see §3 |
| Coverage/yield | Collection slots | Engineering health, reported alongside every statistical metric |
| Booking-curve sensitivity | Composite index | Shows how much of the result is assumption |

Additionally, **cross-source agreement** within our own data — comparing the same
route/window/carrier/date observed via an airline site and via an OTA — is a
strong internal consistency check that requires no external benchmark and is
available from day one. Use it as the early-warning signal for parser regressions.

If the collection window is extended (see [Q3](05-open-questions.md#q3)), add
lead-lag and cointegration tests between APIx and the DGCA series. These require
considerably more than three monthly observations to mean anything.
