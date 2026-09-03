# 04 — Delivery Plan

## The scheduling insight that should drive everything

**The validation window is wall-clock-bound, not effort-bound.**

You cannot collect airfare data retrospectively. Every day of delay before the
first collector goes live is a day that can never be recovered, no matter how many
people are added to the team afterwards. The 30-day (or, preferably, 90-day)
observation window is the project's critical path, and it is the one component that
throwing effort at cannot compress.

**Therefore: get one adapter — the Tier 1 tariff-sheet collector — into daily
production by the end of Week 4, before the cleaning pipeline, before the index
engine, before the dashboard.** It can write to a plain table. It can be ugly.
Everything else is built around a collection window that is already running.

This inverts the natural build order and it is the single most valuable
scheduling decision in the plan.

## Phases

| Phase | Weeks | Output | Gate |
|---|---|---|---|
| **0 — Discovery & legal** | 1–2 | robots.txt and ToS audit per source; anti-bot reconnaissance; DGCA/MoSPI engagement opened; route basket fixed from DGCA traffic data; **compliance posture signed off** | Sponsor answers [Q4](05-open-questions.md#q4), [Q6](05-open-questions.md#q6), [Q7](05-open-questions.md#q7) |
| **1 — Vertical slice** | 3–4 | One Tier 1 adapter, raw landing, minimal schema, scheduled daily. **Collection starts.** | Data flowing daily and durably stored |
| **2 — Multi-source** | 5–7 | Remaining Tier 1 adapters + 2–3 Tier 3 adapters; normalisation; fare decomposition; de-duplication | ≥3 sources at ≥90% yield |
| **3 — Cleaning & index engine** | 8–9 | Outlier and imputation logic; Jevons → Lowe/Young → multilateral; vintages and config hashing; golden-fixture test suite | Index reproducible bit-for-bit |
| **4 — API & dashboard** | 10–12 | FastAPI with SDMX; six dashboard views; coverage panel | External consumer can pull a series via SDMX |
| **5 — Validation** | 8–16 *(overlaps)* | Back-test/validation against DGCA; cross-source agreement; booking-curve sensitivity analysis; validation report | Metrics from [`02-methodology.md`](02-methodology.md#10-validation-design) reported honestly |
| **6 — Documentation & handover** | 15–16 | Methodology document, revision policy, runbooks, ops handover | A statistician can reproduce a published value unaided |

**Calendar: ~16 weeks.** Phase 5 runs in parallel from Week 8 and is gated by the
collection window, not by engineering.

## Dependency structure

```
Week   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16
P0    ███████
P1            ███████
P2                    ███████████
P3                                ███████
P4                                        ███████████
P5                                ░░░░░░░░░░░░░░░░░░░░░░░░░░░░
P6                                                            ███████
                                  ▲
                                  └─ collection window opens; from here the
                                     schedule is bounded by calendar days, not effort
```

## Effort estimate

Indicative, for a prototype delivered to the standard described in these documents.

| Role | Load | Concentrated in |
|---|---|---|
| Data engineer | 1.0 FTE × 16 wk | Phases 1–3 |
| Backend/API engineer | 0.5 FTE × 8 wk | Phases 3–4 |
| Frontend engineer | 0.5 FTE × 6 wk | Phase 4 |
| Statistician / methodologist | 0.4 FTE × 16 wk | Phases 0, 3, 5 — **do not omit this role** |
| DevOps | 0.2 FTE × 16 wk | Throughout |

≈ **2.6 FTE peak, ~40 person-weeks total.**

The methodologist is the line most likely to be cut and the one that most
determines whether the output is usable. Every decision in
[`02-methodology.md`](02-methodology.md) needs someone who owns it.

## Risk register

Ordered by expected impact.

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Booking-curve weights unavailable → composite index rests on assumption | High | High | Publish sensitivity bands mandatorily; pursue Tier 0/1 data; fall back to window-specific sub-indices ([Q1](05-open-questions.md#q1)) |
| 2 | Tier 3 sources block collection | High | High | Tier 1 first; adapter isolation; coverage floor with pre-agreed suppression; graceful degradation |
| 3 | Back-test as specified is not statistically meaningful | High | Medium | Renegotiate to forward validation + historical archive ([Q3](05-open-questions.md#q3)) |
| 4 | Offer-vs-transaction gap misread as inaccuracy | Certain | Medium | Compare changes only; state the price concept in metadata, API and dashboard |
| 5 | Day-of-week artefact mistaken for signal | Certain if unhandled | Medium | 7-day MA headline; DOW-adjusted variant; complete-week aggregation |
| 6 | ToS/legal challenge from a source | Medium | High | Tier 0/1 emphasis; documented compliance posture; identified UA; immediate stop on request |
| 7 | Parser rot from site redesigns | High | Medium | Fixture-based contract tests; parse-error-rate alerting; adapter isolation caps the blast radius |
| 8 | Regulatory fare intervention (fare bands/caps) during the window | Medium | Medium | Flag as a structural break in the series; do not smooth it away |
| 9 | Festival and event contamination | High | Low | Event calendar as metadata; do not exclude — it is real consumer inflation |
| 10 | No Tier 2 budget → thinner coverage | Medium | Medium | Resolve in Phase 0 ([Q6](05-open-questions.md#q6)); scope coverage claims to the answer |
| 11 | Chain drift if daily chaining is used | Certain if used | High | Prohibited by design; fixed-base daily, multilateral monthly |
| 12 | Overclaiming headline CPI impact | Medium | Medium (reputational) | Value proposition fixed in [`00-scope.md`](00-scope.md#5-success-criteria--and-the-honest-value-proposition) |

## Definition of done

The prototype is complete when:

- [ ] ≥3 sources collecting daily at ≥90% yield, for ≥30 consecutive days
- [ ] A published index value can be traced to its raw payloads and its config hash
- [ ] A frozen vintage recomputes bit-identically
- [ ] SDMX endpoint serves the series to an external consumer
- [ ] Dashboard shows all six views including the data-quality panel
- [ ] Validation report published with metrics computed on *changes*, and with the
      booking-curve sensitivity band
- [ ] Methodology document and revision policy written and reviewed
- [ ] Test suite green in CI, with parser tests running against fixtures only
- [ ] Compliance posture documented: which sources, under what basis, at what rate

## Explicitly deferred

Not failures — decisions to defer, recorded so they are not silently forgotten.

- International routes
- Return-trip and multi-city product specifications
- Ancillary price indices (bags, seats, meals)
- Rail, hotel and ride-hailing extension of the same pipeline pattern —
  *this is the largest follow-on opportunity and should be named in any pitch*
- Automated MoSPI production integration
- Nowcasting or forecasting of the index
