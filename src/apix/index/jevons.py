"""Elementary aggregation — docs/02-methodology.md §8.

Jevons: unweighted geometric mean of price relatives. Chosen over Carli
(upward-biased, prohibited in HICP) and Dutot (invalid across heterogeneous
items). Pure, deterministic, side-effect-free — see docs/03-architecture.md
"Testing strategy": golden fixtures with hand-worked expected values,
including ILO CPI Manual examples.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def jevons_relative(current_prices: Sequence[float], base_prices: Sequence[float]) -> float:
    """Geometric mean of price relatives (p_current / p_base) for one stratum.

    `current_prices` and `base_prices` must be the same length and pairwise
    correspond to the same item (e.g. same carrier) across the two periods.
    Raises on empty input or non-positive prices — a silent NaN here would be
    worse than a loud failure, given this feeds a published statistic.
    """
    if not current_prices or not base_prices:
        raise ValueError("jevons_relative requires at least one price pair")
    if len(current_prices) != len(base_prices):
        raise ValueError("current_prices and base_prices must be the same length")

    log_relatives = []
    for cur, base in zip(current_prices, base_prices, strict=True):
        if cur <= 0 or base <= 0:
            raise ValueError("prices must be strictly positive")
        log_relatives.append(math.log(cur / base))

    return math.exp(sum(log_relatives) / len(log_relatives))


def jevons_index(prices_by_period: Sequence[Sequence[float]]) -> list[float]:
    """Chained-from-base Jevons index over a sequence of periods, each period
    being a list of item prices in a fixed item order. Period 0 = 100.

    NOTE: this fixed-base helper is for elementary-level, within-month use
    only. Daily chaining across months is prohibited by design (see
    docs/02-methodology.md "Chaining and drift") — the monthly headline uses
    a rolling-window multilateral method instead, implemented separately.
    """
    if not prices_by_period:
        return []
    base = prices_by_period[0]
    out = [100.0]
    for period in prices_by_period[1:]:
        out.append(100.0 * jevons_relative(period, base))
    return out
