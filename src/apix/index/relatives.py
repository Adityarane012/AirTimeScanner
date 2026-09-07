"""Price relatives, outlier flagging and imputation — docs/02-methodology.md
§6, §7, §8.

Pure and deterministic, like jevons.py: no DB, no clock, no config file
reading. The engine supplies observations, this module returns the panel. That
keeps the statistical rules testable against hand-worked fixtures, which is the
only way anyone can check them.

The stratum, per docs/02 §8, is `origin × destination × direction ×
advance-purchase window`, with **carriers as the items inside it**. Route ids
are already directional, so a stratum key is (route_id, advance_purchase_days).
Carrier substitution then happens inside the geometric mean, which is what
consumers actually do.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

# Iglewicz & Hoaglin's constant: makes the MAD a consistent estimator of the
# standard deviation for normally distributed data, so the cutoff means roughly
# what a z-score cutoff means.
MAD_TO_SIGMA = 0.6745

# Their fallback constant, used when the MAD degenerates to zero because at
# least half the observations are identical. 1.253314 = sqrt(pi/2), which makes
# the mean absolute deviation a consistent estimator of sigma in the same way.
MEAN_AD_TO_SIGMA = 1.253314


@dataclass(frozen=True)
class Observation:
    """One collected price for one item in one stratum on one day."""

    period: date
    route_id: int
    advance_purchase_days: int
    carrier: str
    total_fare: float


@dataclass(frozen=True)
class StratumKey:
    route_id: int
    advance_purchase_days: int


@dataclass
class Relative:
    """One item's price relative against the stratum's base period."""

    period: date
    stratum: StratumKey
    carrier: str
    relative: float
    imputed: bool = False
    outlier: bool = False
    modified_z: float | None = None

    @property
    def log_relative(self) -> float:
        return math.log(self.relative)


def build_relatives(
    observations: list[Observation],
    base_period: date,
) -> list[Relative]:
    """Fixed-base price relatives, matched by item within stratum.

    docs/02 §8: "Daily and weekly series: fixed-base bilateral within the
    month. No chaining." So every period is compared against one base period,
    never against the period before it — chaining a series that bounces as hard
    as airfares produces severe chain drift.

    Matched-model: an item contributes only if it is priced in **both** the base
    period and the current period. A carrier that did not exist in the base has
    no relative to contribute and is not silently treated as though it did;
    that shows up as reduced coverage instead.
    """
    base_prices: dict[tuple[int, int, str], float] = {
        (o.route_id, o.advance_purchase_days, o.carrier): o.total_fare
        for o in observations
        if o.period == base_period
    }

    out: list[Relative] = []
    for o in observations:
        if o.period == base_period:
            continue
        base = base_prices.get((o.route_id, o.advance_purchase_days, o.carrier))
        if base is None or base <= 0 or o.total_fare <= 0:
            # Unmatched or non-positive: no relative exists. Never substitute a
            # 1.0 here -- that would assert "no price change" from no data.
            continue
        out.append(
            Relative(
                period=o.period,
                stratum=StratumKey(o.route_id, o.advance_purchase_days),
                carrier=o.carrier,
                relative=o.total_fare / base,
            )
        )
    return out


def flag_outliers(
    relatives: list[Relative],
    modified_z_threshold: float,
) -> list[Relative]:
    """Robust outlier flagging on log relatives, computed within stratum.

    docs/02 §7, followed literally:

    - **On log relatives, not levels.** Fare distributions are heavily
      right-skewed; a symmetric rule on levels flags every ordinary upward move
      and almost no downward one.
    - **Median and MAD, not mean and sd.** The statistics that define "unusual"
      must not themselves be dragged out by the outlier.
    - **Within stratum, never pooled across routes of different distances.**
      The pool for a stratum is every log relative observed in it across the
      window being processed — carriers and days both. Pooling DEL-BOM with a
      short regional hop would make the threshold meaningless for either.
    - **Flag, do not drop.** A genuine 300% festival surge is the signal this
      index exists to see. Flagged observations stay in the panel and stay in
      the aggregation; the flag is a review queue, not a delete.

    Mutates and returns the same Relative objects.
    """
    by_stratum: dict[StratumKey, list[Relative]] = {}
    for r in relatives:
        by_stratum.setdefault(r.stratum, []).append(r)

    for group in by_stratum.values():
        logs = [r.log_relative for r in group]
        if len(logs) < 3:
            # Too thin for a robust location/scale estimate. Leaving these
            # unflagged is the honest outcome: with two points, "which one is
            # the outlier" has no answer.
            continue
        median = statistics.median(logs)
        deviations = [abs(x - median) for x in logs]
        mad = statistics.median(deviations)

        if mad > 0:
            scale = mad / MAD_TO_SIGMA
        else:
            # MAD is zero whenever at least half the observations are
            # identical -- which happens constantly here, because a stratum
            # holding four unchanged carriers and one that spiked has a
            # zero median deviation. Taking that as "no dispersion, nothing
            # to flag" would blind the rule to exactly the case it exists
            # for. Iglewicz & Hoaglin's own fallback is the mean absolute
            # deviation about the median, with its own consistency constant.
            mean_ad = sum(deviations) / len(deviations)
            if mean_ad == 0:
                # Genuinely identical relatives. Nothing can be extreme.
                continue
            scale = MEAN_AD_TO_SIGMA * mean_ad

        for r in group:
            z = (r.log_relative - median) / scale
            r.modified_z = z
            r.outlier = abs(z) > modified_z_threshold
    return relatives


def impute_missing(
    relatives: list[Relative],
    expected_carriers: tuple[str, ...],
) -> list[Relative]:
    """Stratum class-mean imputation — docs/02 §6.

    For each (period, stratum), any expected carrier with no relative gets the
    stratum's mean relative for that period. docs/02 §6 is explicit that this,
    not carry-forward, is the method: "Do not carry the last price forward;
    carry-forward mechanically dampens measured inflation and is discouraged in
    HICP practice for exactly this reason."

    The mean used is the **geometric** mean, because the elementary aggregate
    is Jevons and imputation must be neutral in the space the index is computed
    in. A consequence worth stating plainly: imputing at the stratum mean
    leaves the Jevons relative for that stratum unchanged. That is correct and
    intended — imputation here exists to keep the item count and the coverage
    accounting honest, not to move the number. What it changes is `n_imputed`,
    and therefore what a consumer of the series can tell about its quality.

    Imputation only fills carriers that are *expected* in the stratum. It never
    invents an item the basket does not claim to cover.
    """
    if not expected_carriers:
        return relatives

    by_period_stratum: dict[tuple[date, StratumKey], list[Relative]] = {}
    for r in relatives:
        by_period_stratum.setdefault((r.period, r.stratum), []).append(r)

    imputed: list[Relative] = []
    for (period, stratum), group in by_period_stratum.items():
        observed = {r.carrier for r in group}
        missing = [c for c in expected_carriers if c not in observed]
        if not missing:
            continue
        mean_log = sum(r.log_relative for r in group) / len(group)
        stratum_mean = math.exp(mean_log)
        for carrier in missing:
            imputed.append(
                Relative(
                    period=period,
                    stratum=stratum,
                    carrier=carrier,
                    relative=stratum_mean,
                    imputed=True,
                )
            )
    return [*relatives, *imputed]
