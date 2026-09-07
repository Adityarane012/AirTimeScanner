"""The index engine — reads fare_quote, writes stratum_panel and index_value.

This is the only module in `apix.index` that touches the database or the clock.
Everything statistical lives in `relatives.py`, `aggregate.py` and `jevons.py`
as pure functions, so the methodology can be checked against hand-worked
fixtures without a database anywhere near it.

Pipeline, in order:

    load observed quotes for the month
      -> fixed-base price relatives, matched by carrier within stratum
      -> robust outlier flagging (flag, never drop)
      -> stratum class-mean imputation
      -> Jevons elementary aggregate  ->  stratum_panel
      -> Lowe/Young upper level + sensitivity band
      -> 7-day centred moving average  ->  index_value

Two filters at the input decide whether the output is a statistic or a
plausible-looking number, and both are easy to omit by accident:

1. **`fare_class = 'tier1_tariff_floor'` rows are excluded from the headline.**
   IMPLEMENTATION.md §5a flagged this three phases in advance. Those rows are
   filed tariff *bands* — non-directional, not tied to a departure date, and a
   floor rather than an available offer. They are structural anchors, not index
   inputs. Including them would silently contaminate the headline with a
   different economic object.
2. **Rows carrying an `exclusion_reason` are excluded.** docs/02 §7 requires
   excluded observations to be retained and auditable, not deleted — so they
   are still in the table, and the engine must actively filter them out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apix.db.models import FareQuoteRow, IndexValue, Route, StratumPanel
from apix.index import aggregate
from apix.index.config import ADVANCE_PURCHASE_WINDOWS, MethodologyConfig
from apix.index.relatives import Observation, build_relatives, flag_outliers, impute_missing

# Rows tagged with this fare_class are Tier-1 filed tariff bands, not offers.
TIER1_ANCHOR_FARE_CLASS = "tier1_tariff_floor"

SERIES_HEADLINE = "apix.headline"
SERIES_HEADLINE_RAW = "apix.headline.raw"
SERIES_WINDOW_PREFIX = "apix.window"


@dataclass
class IndexRunReport:
    """What a run actually did. Returned rather than printed so the entrypoint
    decides presentation and tests can assert on it."""

    vintage_id: str
    config_hash: str
    base_period: date | None
    n_quotes_loaded: int = 0
    n_relatives: int = 0
    n_outliers: int = 0
    n_imputed: int = 0
    n_panel_rows: int = 0
    n_index_values: int = 0
    route_weights_are_real: bool = False
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


def load_observations(session, period_start: date, period_end: date) -> list[Observation]:
    """Index-eligible quotes only. See the two filters in the module docstring."""
    stmt = (
        select(
            FareQuoteRow.collection_ts,
            FareQuoteRow.route_id,
            FareQuoteRow.advance_purchase_days,
            FareQuoteRow.carrier,
            FareQuoteRow.total_fare,
        )
        .where(
            FareQuoteRow.observation_status == "observed",
            FareQuoteRow.exclusion_reason.is_(None),
            FareQuoteRow.total_fare.is_not(None),
            FareQuoteRow.total_fare > 0,
            FareQuoteRow.collection_ts >= datetime.combine(period_start, datetime.min.time(), UTC),
            FareQuoteRow.collection_ts < datetime.combine(period_end, datetime.min.time(), UTC),
        )
        .where(
            (FareQuoteRow.fare_class.is_(None))
            | (FareQuoteRow.fare_class != TIER1_ANCHOR_FARE_CLASS)
        )
    )
    return [
        Observation(
            period=ts.astimezone(UTC).date(),
            route_id=route_id,
            advance_purchase_days=apd,
            carrier=carrier,
            total_fare=float(fare),
        )
        for ts, route_id, apd, carrier, fare in session.execute(stmt)
    ]


def load_route_weights(session) -> dict[int, float | None]:
    rows = session.execute(
        select(Route.route_id, Route.dgca_pax_weight).where(Route.active.is_(True))
    ).all()
    return {rid: (float(w) if w is not None else None) for rid, w in rows}


def compute(
    observations: list[Observation],
    route_weights: dict[int, float | None],
    config: MethodologyConfig,
    computed_on: date,
) -> tuple[list[aggregate.StratumResult], list[dict], IndexRunReport]:
    """The whole computation, with no database in sight.

    Returns (panel, index_value payloads, report). Deterministic in its inputs:
    the same observations and config produce byte-identical output, which is
    what docs/02 §9's "recomputable bit-for-bit" requires.
    """
    report = IndexRunReport(
        vintage_id=config.vintage_id(computed_on),
        config_hash=config.config_hash,
        base_period=None,
        n_quotes_loaded=len(observations),
        route_weights_are_real=aggregate.route_weights_are_real(route_weights),
    )
    if not report.route_weights_are_real:
        report.warnings.append(
            "route.dgca_pax_weight is NULL for every active route — routes fall back to "
            "EQUAL weight. This is not the Lowe/Young revenue-share aggregation docs/02 §8 "
            "specifies; the composite is provisional until the real DGCA basket lands."
        )

    if not observations:
        report.warnings.append("no index-eligible quotes in the period — nothing computed")
        return [], [], report

    periods = sorted({o.period for o in observations})
    base_period = periods[0]
    report.base_period = base_period
    if len(periods) < 2:
        report.warnings.append(
            f"only one collection day ({base_period}) — a fixed-base index needs at least "
            "one period after the base, so no index value can be computed yet"
        )
        return [], [], report

    relatives = build_relatives(observations, base_period)
    report.n_relatives = len(relatives)
    if not relatives:
        report.warnings.append(
            "no matched carrier appears in both the base period and a later period — "
            "nothing to compute a price relative from"
        )
        return [], [], report

    relatives = flag_outliers(relatives, config.outlier_modified_z)
    report.n_outliers = sum(1 for r in relatives if r.outlier)

    relatives = impute_missing(relatives, config.expected_carriers)
    report.n_imputed = sum(1 for r in relatives if r.imputed)

    panel = aggregate.elementary_panel(relatives, config)
    report.n_panel_rows = len(panel)

    expected_strata = len(route_weights) * len(ADVANCE_PURCHASE_WINDOWS)
    index_rows = _build_index_rows(
        panel, route_weights, config, periods[1:], expected_strata, report
    )
    report.n_index_values = len(index_rows)

    # A run that computes a full panel and then publishes nothing is a
    # legitimate outcome -- it is what the coverage floor is for -- but it must
    # never be a silent one. Without this the operator sees "0 index rows" and
    # no reason, which is indistinguishable from a bug.
    if panel and not index_rows:
        n_suppressed = sum(1 for r in panel if r.suppressed)
        worst = max((r.coverage_ratio for r in panel), default=0.0)
        report.warnings.append(
            f"{n_suppressed} of {len(panel)} strata are below the "
            f"{config.stratum_suppression_floor:.0%} coverage floor (best stratum reached "
            f"{worst:.0%}), so every period was suppressed and no index value was "
            f"published. With {len(config.expected_carriers)} carriers expected per "
            f"stratum, this is what too few live sources looks like — not a computation "
            f"failure."
        )
    return panel, index_rows, report


def _build_index_rows(
    panel: list[aggregate.StratumResult],
    route_weights: dict[int, float | None],
    config: MethodologyConfig,
    periods: list[date],
    expected_strata: int,
    report: IndexRunReport,
) -> list[dict]:
    rows: list[dict] = []
    raw_series: list[tuple[date, float]] = []
    band_by_period: dict[date, tuple[float, float, float, bool]] = {}

    for period in periods:
        result = aggregate.composite(
            panel, route_weights, config, period, expected_strata=expected_strata
        )
        if result is None:
            continue
        raw_series.append((period, result.value))
        band_by_period[period] = (
            result.sensitivity_low,
            result.sensitivity_high,
            result.coverage_ratio,
            result.suppressed,
        )
        # docs/02 §5: the raw daily series is published, but as a clearly
        # labelled diagnostic, never as the headline.
        rows.append(
            _index_row(
                config, SERIES_HEADLINE_RAW, "daily", period, result.value,
                result.coverage_ratio, result.suppressed,
                result.sensitivity_low, result.sensitivity_high, report,
            )
        )

        for window in ADVANCE_PURCHASE_WINDOWS:
            sub = aggregate.window_index(panel, route_weights, config, period, window)
            if sub is None:
                continue
            value, coverage = sub
            # No booking-curve assumption enters a single-window index, so it
            # carries no sensitivity band -- there is nothing to be sensitive to.
            rows.append(
                _index_row(
                    config, f"{SERIES_WINDOW_PREFIX}.T{window}", "daily", period, value,
                    coverage, coverage < config.headline_suppression_floor,
                    None, None, report,
                )
            )

    # docs/02 §5: the headline is the 7-day centred moving average.
    smoothed = aggregate.centred_moving_average(raw_series, window=7)
    if not smoothed and raw_series:
        report.warnings.append(
            f"only {len(raw_series)} complete daily value(s) — the 7-day centred moving "
            f"average that docs/02 §5 requires for the headline needs 7 consecutive days, "
            f"so {SERIES_HEADLINE} is not published yet ({SERIES_HEADLINE_RAW} is)"
        )
    low_series = dict(
        aggregate.centred_moving_average([(p, band_by_period[p][0]) for p in band_by_period])
    )
    high_series = dict(
        aggregate.centred_moving_average([(p, band_by_period[p][1]) for p in band_by_period])
    )
    for period, value in smoothed:
        coverage, suppressed = band_by_period[period][2], band_by_period[period][3]
        rows.append(
            _index_row(
                config, SERIES_HEADLINE, "daily", period, value, coverage, suppressed,
                low_series.get(period), high_series.get(period), report,
            )
        )
    return rows


def _index_row(
    config: MethodologyConfig,
    series_id: str,
    frequency: str,
    period: date,
    value: float,
    coverage: float,
    suppressed: bool,
    low: float | None,
    high: float | None,
    report: IndexRunReport,
) -> dict:
    return {
        "vintage_id": report.vintage_id,
        "series_id": series_id,
        "frequency": frequency,
        "period": period,
        "value": round(value, 6),
        "coverage_ratio": round(coverage, 4),
        "suppressed": suppressed,
        "config_hash": config.config_hash,
        "sensitivity_low": None if low is None else round(low, 6),
        "sensitivity_high": None if high is None else round(high, 6),
    }


def persist(session, panel: list[aggregate.StratumResult], index_rows: list[dict]) -> None:
    """Upsert the panel and the index values.

    Upsert, not insert: the index is recomputable by design (docs/02 §9), so
    running it twice over the same inputs must converge on the same rows rather
    than accumulate duplicates. Both tables carry the natural key as a UNIQUE
    constraint, which is what makes this safe.
    """
    for row in panel:
        stmt = pg_insert(StratumPanel).values(
            date=row.period,
            route_id=row.stratum.route_id,
            advance_purchase_days=row.stratum.advance_purchase_days,
            jevons_relative=round(row.jevons_relative, 8),
            n_observed=row.n_observed,
            n_imputed=row.n_imputed,
            coverage_ratio=round(row.coverage_ratio, 4),
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["date", "route_id", "advance_purchase_days"],
                set_={
                    "jevons_relative": stmt.excluded.jevons_relative,
                    "n_observed": stmt.excluded.n_observed,
                    "n_imputed": stmt.excluded.n_imputed,
                    "coverage_ratio": stmt.excluded.coverage_ratio,
                },
            )
        )

    for row in index_rows:
        stmt = pg_insert(IndexValue).values(published_at=datetime.now(UTC), **row)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["vintage_id", "series_id", "frequency", "period"],
                set_={
                    "value": stmt.excluded.value,
                    "coverage_ratio": stmt.excluded.coverage_ratio,
                    "suppressed": stmt.excluded.suppressed,
                    "config_hash": stmt.excluded.config_hash,
                    "sensitivity_low": stmt.excluded.sensitivity_low,
                    "sensitivity_high": stmt.excluded.sensitivity_high,
                },
            )
        )


def flag_outlier_quotes(session, period_start: date, period_end: date, outliers: set) -> int:
    """Write outlier flags back to fare_quote.

    docs/02 §7: "Retain every excluded observation with its exclusion reason, so
    exclusions are auditable and reversible in a revision." Flagged rows stay in
    the index -- the flag marks a review queue, not a deletion -- so this sets
    `outlier_flag` only and deliberately leaves `exclusion_reason` alone.
    """
    if not outliers:
        return 0
    updated = 0
    for period, route_id, apd, carrier in outliers:
        result = session.execute(
            FareQuoteRow.__table__.update()
            .where(
                FareQuoteRow.route_id == route_id,
                FareQuoteRow.advance_purchase_days == apd,
                FareQuoteRow.carrier == carrier,
                FareQuoteRow.collection_ts >= datetime.combine(period, datetime.min.time(), UTC),
                FareQuoteRow.collection_ts
                < datetime.combine(period, datetime.max.time(), UTC),
            )
            .values(outlier_flag=True)
        )
        updated += result.rowcount or 0
    return updated
