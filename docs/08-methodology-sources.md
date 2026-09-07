# 08 — Methodology sources, and the build-vs-borrow decision

Two things this document settles, both of which were assumed rather than
checked when the index engine was written:

1. Where each methodological choice in `docs/02-methodology.md` comes from, so
   a reader can check it against the literature instead of taking it on trust.
2. Whether the index engine should have used an existing open-source index-
   number library instead of implementing the formulas — asked late, answered
   with evidence, and answered *no* for the runtime with a specific exception.

## 1. Prior art — this approach is not novel, and that is good

The premise of APIx (high-frequency web-collected prices as a supplement to an
official CPI) has an established academic precedent worth citing whenever the
project has to justify itself:

**The Billion Prices Project**, Alberto Cavallo & Roberto Rigobon, MIT Sloan /
Harvard Business School.
*Journal of Economic Perspectives* 30(2), 2016, 151–178. NBER WP 22111.
<https://www.nber.org/papers/w22111>

Two findings matter directly here:

- **BPP constructs Jevons indices from web-collected price data.** docs/02 §8
  chose Jevons independently, on HICP grounds. Arriving at the same elementary
  formula as the largest published project of this kind is a useful
  independent check on that choice.
- **Daily online collection at scale is an accepted research method**, not an
  improvisation. BPP ran 2007–2020, collecting ~5 million prices/day from 300+
  retailers across 50 countries against the BLS's ~80,000 prices/month. The
  micro data was collected by PriceStats, now part of State Street.

This belongs in `docs/07-dgca-outreach-draft.md`. "This follows the approach of
the MIT Billion Prices Project, published in the *Journal of Economic
Perspectives*" is a materially stronger opening to a regulator than describing
it as a personal project.

## 2. Where each rule in docs/02 comes from

| Rule | Source |
|---|---|
| Jevons for elementary aggregation; Carli prohibited | ILO/IMF/OECD **CPI Manual and Theory** (2020), ch. 8; HICP practice |
| Multilateral GEKS / TPD for high-churn, high-frequency data | CPI Manual (2020) ch. 8; Eurostat *Guide on Multilateral Methods* (2022) |
| Rolling-window multilateral with mean splicing | Established at ONS, ABS, Statistics Netherlands for scanner data |
| Modified z-score on log relatives, median + MAD | Iglewicz & Hoaglin (1993), *How to Detect and Handle Outliers*, ASQC |
| MAD's degenerate case → mean-absolute-deviation fallback | Iglewicz & Hoaglin, same source — this is their own documented fallback |
| Class-mean imputation, never carry-forward | CPI Manual (2020); HICP guidance on temporarily missing prices |
| Coverage-floor suppression before publication | Standard official-statistics disclosure practice |
| Vintages, immutability, config-hash provenance | CPI Manual (2020) ch. on revisions; general official-statistics practice |

## 3. Build vs borrow — evaluated, with the evidence

Four open-source libraries implement these methods. Assessed 2026-09-07:

| Library | Language | Methods | Maintenance | Verdict |
|---|---|---|---|---|
| [IndexNumR](https://cran.r-project.org/package=IndexNumR) | R | GEKS (Jevons/Törnqvist/TPD), Geary-Khamis, WTPD | Active — CRAN update May 2026 | Best-in-class, wrong language |
| [gpindex](https://github.com/marberts/gpindex) | R | CPI Manual (2020) methods: relatives, outliers, decomposition | Active | Same |
| [PriceIndices](https://github.com/JacekBialek/PriceIndices) | R | Bilateral + multilateral, scanner-data oriented | Active | Same |
| [PriceIndexCalc](https://github.com/drrobotk/PriceIndexCalc) | **Python** | Jevons, GEKS-*, TPD, TDH, GK | **Last push Feb 2024**, 10 stars, not on PyPI | Rejected as a runtime dependency |

### Decision

**Do not take a runtime dependency on any of them. Cite them, and use them as
validation oracles.**

The reasoning, stated so it can be revisited rather than inherited:

- **PriceIndexCalc is the only Python option and it is not maintained.** Two
  and a half years without a push, ten stars, no PyPI release, and a PySpark
  flavour this project has no use for. Making an unmaintained package the core
  of a published statistic is a larger risk than the tested code already here.
- **The R packages are mature but are R.** Adding an R runtime to a solo
  Windows project — for formulas that are a geometric mean and a weighted
  arithmetic mean — is a poor trade.
- **Most of `apix/index/` is not formulas anyway.** The `tier1_tariff_floor`
  exclusion, coverage-floor suppression, the mandatory sensitivity band, the
  config-hash and vintage stamping, the day-of-week centred average: no library
  provides these, because they are this project's rules, not general ones.

### The exception, and it is a real one

**GEKS-Jevons over a rolling window with mean splicing (docs/02 §8, the monthly
headline) must not be hand-written.** It is the one genuinely difficult
computation in the methodology, and unlike the elementary formulas there is no
version of it that is obviously correct on inspection. When it is built:

1. Port the algorithm from IndexNumR's documented implementation, citing it.
2. Validate against the worked values in IndexNumR's published vignette, as a
   golden fixture in the same style as `tests/test_jevons.py`.
3. Do not publish a monthly headline until that fixture passes.

### An honest note on process

This evaluation should have happened before the index engine was written, not
after. The outcome — hand-rolled elementary formulas, a library for GEKS —
would probably have been the same, but it would have been a decision rather
than a default, and the MAD degenerate case that a failing test caught is
exactly the kind of thing `gpindex` had already solved.
