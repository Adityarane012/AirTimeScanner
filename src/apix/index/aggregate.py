"""Elementary and upper-level aggregation — docs/02-methodology.md §8, plus the
coverage-floor suppression from docs/01 and the mandatory sensitivity band from
docs/02 §4.

Pure functions over the panel produced by relatives.py. The two levels are kept
separate because they answer different questions and fail differently:
elementary aggregation is unweighted within a stratum (Jevons, carriers as
items); upper aggregation is weighted across strata (Lowe/Young, route revenue
share × booking-curve weight).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from apix.index.config import MethodologyConfig
from apix.index.relatives import Relative, StratumKey

# The index is expressed against its base period = 100.
BASE_INDEX_VALUE = 100.0


@dataclass(frozen=True)
class StratumResult:
    """One row of stratum_panel."""

    period: date
    stratum: StratumKey
    jevons_relative: float
    n_observed: int
    n_imputed: int
    coverage_ratio: float
    suppressed: bool


@dataclass(frozen=True)
class CompositeResult:
    """One row of index_value, with the band docs/02 §4 makes mandatory."""

    period: date
    value: float
    coverage_ratio: float
    suppressed: bool
    sensitivity_low: float
    sensitivity_high: float
    n_strata: int


def elementary_panel(
    relatives: list[Relative],
    config: MethodologyConfig,
) -> list[StratumResult]:
    """Jevons within each (period, stratum) — docs/02 §8 elementary level.

    Unweighted geometric mean of the price relatives of the carriers in the
    stratum. Carli is upward-biased and prohibited in HICP; Dutot is invalid
    across heterogeneous items. Neither is offered as an option here.

    Flagged outliers are **included**. docs/02 §7: "Flag and review, do not
    silently drop." Dropping them would remove exactly the large genuine moves
    the index exists to measure.

    Coverage is measured against the carriers the basket claims to cover, so a
    stratum where four of five carriers went uncollected is visibly thin rather
    than quietly averaging one number.
    """
    n_expected = len(config.expected_carriers)
    grouped: dict[tuple[date, StratumKey], list[Relative]] = {}
    for r in relatives:
        grouped.setdefault((r.period, r.stratum), []).append(r)

    results: list[StratumResult] = []
    for (period, stratum), group in sorted(
        grouped.items(), key=lambda kv: (kv[0][0], kv[0][1].route_id, kv[0][1].advance_purchase_days)
    ):
        n_observed = sum(1 for r in group if not r.imputed)
        n_imputed = sum(1 for r in group if r.imputed)
        jevons = math.exp(sum(r.log_relative for r in group) / len(group))
        coverage = (n_observed / n_expected) if n_expected else 0.0
        results.append(
            StratumResult(
                period=period,
                stratum=stratum,
                jevons_relative=jevons,
                n_observed=n_observed,
                n_imputed=n_imputed,
                coverage_ratio=coverage,
                suppressed=coverage < config.stratum_suppression_floor,
            )
        )
    return results


def _stratum_weight(
    stratum: StratumKey,
    route_weights: dict[int, float | None],
    config: MethodologyConfig,
    curve: str,
) -> float:
    """Lowe/Young weight — docs/02 §8 upper level.

    Route revenue share (DGCA passenger traffic × average fare) combined with
    the booking-curve weight for the window.

    `dgca_pax_weight` is NULL for the current placeholder basket, so routes fall
    back to equal weight. That fallback is reported by `route_weights_are_real`
    rather than hidden — an equally-weighted route basket is not the Lowe/Young
    index docs/02 specifies, and a consumer of the series needs to know which
    one they have.
    """
    route_w = route_weights.get(stratum.route_id)
    route_w = 1.0 if route_w is None else float(route_w)
    return route_w * config.curve_weight(stratum.advance_purchase_days, curve)


def route_weights_are_real(route_weights: dict[int, float | None]) -> bool:
    return bool(route_weights) and any(v is not None for v in route_weights.values())


def upper_level(
    panel: list[StratumResult],
    route_weights: dict[int, float | None],
    config: MethodologyConfig,
    period: date,
    curve: str = "central",
    expected_strata: int | None = None,
) -> tuple[float, float, int] | None:
    """Weighted arithmetic aggregation across strata for one period.

    Returns (index_value, coverage_ratio, n_strata), or None when no stratum
    survived — in which case there is nothing to publish and the caller must
    not invent a value.

    Suppressed strata are excluded from the aggregate but still count against
    coverage: a collapsed stratum is missing information, not absent demand.
    """
    rows = [r for r in panel if r.period == period]
    if not rows:
        return None

    included = [r for r in rows if not r.suppressed]
    if not included:
        return None

    weights = [_stratum_weight(r.stratum, route_weights, config, curve) for r in included]
    total_weight = sum(weights)
    if total_weight <= 0:
        return None

    value = BASE_INDEX_VALUE * sum(
        w * r.jevons_relative for w, r in zip(weights, included, strict=True)
    ) / total_weight

    denominator = expected_strata if expected_strata else len(rows)
    coverage = sum(r.coverage_ratio for r in rows) / denominator if denominator else 0.0
    return value, min(coverage, 1.0), len(included)


def composite(
    panel: list[StratumResult],
    route_weights: dict[int, float | None],
    config: MethodologyConfig,
    period: date,
    expected_strata: int | None = None,
) -> CompositeResult | None:
    """The composite index for one period, with its sensitivity band.

    docs/02 §4 and Q1: the booking curve is the largest unresolved
    methodological assumption in the project, so "never publish the composite as
    a bare point estimate without the band". This function is the only way to
    produce a composite, which is what makes that rule structural rather than a
    thing to remember.

    The band spans the central curve and every alternate in
    booking_curve.yaml, so `sensitivity_low <= value <= sensitivity_high`
    always holds.
    """
    central = upper_level(
        panel, route_weights, config, period, curve="central", expected_strata=expected_strata
    )
    if central is None:
        return None
    value, coverage, n_strata = central

    values = [value]
    for curve in config.curve_names:
        if curve == "central":
            continue
        alt = upper_level(
            panel, route_weights, config, period, curve=curve, expected_strata=expected_strata
        )
        if alt is not None:
            values.append(alt[0])

    return CompositeResult(
        period=period,
        value=value,
        coverage_ratio=coverage,
        suppressed=coverage < config.headline_suppression_floor,
        sensitivity_low=min(values),
        sensitivity_high=max(values),
        n_strata=n_strata,
    )


def window_index(
    panel: list[StratumResult],
    route_weights: dict[int, float | None],
    config: MethodologyConfig,
    period: date,
    advance_purchase_days: int,
) -> tuple[float, float] | None:
    """Per-window sub-index — docs/02 §4 option 3, published alongside the
    composite.

    These carry no booking-curve assumption at all, so they are the honest
    fallback if the assumed curve is ever rejected: route-weighted only, within
    a single advance-purchase window.
    """
    rows = [
        r
        for r in panel
        if r.period == period and r.stratum.advance_purchase_days == advance_purchase_days
    ]
    if not rows:
        return None
    included = [r for r in rows if not r.suppressed]
    if not included:
        return None

    weights = []
    for r in included:
        w = route_weights.get(r.stratum.route_id)
        weights.append(1.0 if w is None else float(w))
    total = sum(weights)
    if total <= 0:
        return None

    value = BASE_INDEX_VALUE * sum(
        w * r.jevons_relative for w, r in zip(weights, included, strict=True)
    ) / total
    coverage = sum(r.coverage_ratio for r in rows) / len(rows)
    return value, min(coverage, 1.0)


def centred_moving_average(
    series: list[tuple[date, float]],
    window: int = 7,
) -> list[tuple[date, float]]:
    """7-day centred moving average — docs/02 §5.

    Fixed advance-purchase windows put a deterministic weekday cycle in the raw
    daily series: T+7 collected on a Monday always prices a Monday departure,
    and airfares have a strong day-of-week pattern. That cycle is an artefact of
    the collection design, not a price signal, so docs/02 §5 requires the daily
    headline to be published smoothed with the raw series exposed separately as
    a labelled diagnostic.

    Only fully-populated windows produce a value — a partial window would
    reintroduce exactly the weekday bias the average exists to remove.
    """
    if window % 2 == 0:
        raise ValueError("centred moving average needs an odd window")
    ordered = sorted(series)
    half = window // 2
    out: list[tuple[date, float]] = []
    for i in range(half, len(ordered) - half):
        chunk = ordered[i - half : i + half + 1]
        expected_span = window - 1
        if (chunk[-1][0] - chunk[0][0]).days != expected_span:
            continue  # a gap in the days: not a complete week
        out.append((ordered[i][0], sum(v for _, v in chunk) / window))
    return out
