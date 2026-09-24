"""Phase 3 index engine — golden-fixture tests with hand-worked expected values.

Same standard as test_jevons.py, and for the same reason: this code decides
what number gets published as a statistic, so the expected values here are
computed by hand from docs/02-methodology.md rather than recorded from a run.
A test that just pins whatever the code did today would ratify a bug.

No database: the statistical modules are pure by construction, and
engine.compute() takes plain objects.
"""

from datetime import date, timedelta

import pytest

from apix.index import aggregate, engine
from apix.index.config import MethodologyConfig
from apix.index.relatives import (
    Observation,
    Relative,
    StratumKey,
    build_relatives,
    flag_outliers,
    impute_missing,
)

BASE = date(2026, 9, 1)
DAY2 = date(2026, 9, 2)


def make_config(**overrides) -> MethodologyConfig:
    defaults = {
        "booking_curve_version": "test_v1",
        "booking_curve": {"T1": 0.10, "T7": 0.20, "T15": 0.30, "T30": 0.40},
        "sensitivity_alternates": {
            "front_loaded": {"T1": 0.40, "T7": 0.30, "T15": 0.20, "T30": 0.10},
            "back_loaded": {"T1": 0.05, "T7": 0.15, "T15": 0.30, "T30": 0.50},
        },
        "stratum_suppression_floor": 0.60,
        "headline_suppression_floor": 0.75,
        "expected_carriers": ("6E", "AI"),
    }
    defaults.update(overrides)
    return MethodologyConfig(**defaults)


def obs(period, route_id, apd, carrier, fare) -> Observation:
    return Observation(period, route_id, apd, carrier, fare)


# --------------------------------------------------------------------------
# Price relatives — fixed base, matched model
# --------------------------------------------------------------------------


def test_relatives_are_against_the_fixed_base_not_the_previous_period():
    """docs/02 §8: 'fixed-base bilateral within the month. No chaining.'
    Day 3 must be priced against day 1, not against day 2."""
    day3 = date(2026, 9, 3)
    observations = [
        obs(BASE, 1, 7, "6E", 100.0),
        obs(DAY2, 1, 7, "6E", 200.0),
        obs(day3, 1, 7, "6E", 400.0),
    ]
    rels = {r.period: r.relative for r in build_relatives(observations, BASE)}
    assert rels[DAY2] == pytest.approx(2.0)
    # Chained against day 2 this would be 2.0; fixed-base it is 4.0.
    assert rels[day3] == pytest.approx(4.0)


def test_unmatched_carrier_contributes_no_relative():
    """A carrier absent from the base period has no relative. It must not be
    treated as though its price were unchanged."""
    observations = [
        obs(BASE, 1, 7, "6E", 100.0),
        obs(DAY2, 1, 7, "6E", 110.0),
        obs(DAY2, 1, 7, "AI", 500.0),  # never seen in base
    ]
    rels = build_relatives(observations, BASE)
    assert [r.carrier for r in rels] == ["6E"]


def test_non_positive_fares_produce_no_relative():
    observations = [obs(BASE, 1, 7, "6E", 0.0), obs(DAY2, 1, 7, "6E", 100.0)]
    assert build_relatives(observations, BASE) == []


# --------------------------------------------------------------------------
# Outliers — docs/02 §7
# --------------------------------------------------------------------------


def rel(carrier, value, period=DAY2, route_id=1, apd=7) -> Relative:
    return Relative(period, StratumKey(route_id, apd), carrier, value)


def test_outlier_flagged_but_never_dropped():
    """docs/02 §7: 'Flag and review, do not silently drop.' The 300% surge is
    the signal, so it must survive into the aggregate carrying a flag."""
    group = [rel(f"C{i}", 1.0) for i in range(6)] + [rel("SURGE", 4.0)]
    flagged = flag_outliers(group, modified_z_threshold=3.5)

    assert len(flagged) == 7, "flagging must not remove observations"
    surge = next(r for r in flagged if r.carrier == "SURGE")
    assert surge.outlier is True
    assert all(r.outlier is False for r in flagged if r.carrier != "SURGE")


def test_outliers_are_computed_within_stratum_not_pooled():
    """docs/02 §7: 'never pooled across routes of different distances.' A fare
    that is ordinary in a long-haul stratum must not be flagged because it is
    large next to a short-haul stratum."""
    short_haul = [rel(f"C{i}", 1.0, route_id=1) for i in range(6)]
    long_haul = [rel(f"C{i}", 5.0, route_id=2) for i in range(6)]
    flagged = flag_outliers([*short_haul, *long_haul], modified_z_threshold=3.5)
    assert not any(r.outlier for r in flagged), "pooling would flag one whole stratum"


def test_thin_stratum_is_not_flagged():
    """With two observations, 'which one is the outlier' has no answer."""
    flagged = flag_outliers([rel("6E", 1.0), rel("AI", 99.0)], modified_z_threshold=3.5)
    assert not any(r.outlier for r in flagged)


def test_zero_dispersion_flags_nothing():
    flagged = flag_outliers([rel(f"C{i}", 2.0) for i in range(5)], modified_z_threshold=3.5)
    assert not any(r.outlier for r in flagged)


def test_outlier_rule_uses_log_relatives_symmetrically():
    """On logs, a halving and a doubling are the same distance from 1.0. On
    levels they are not, which is why docs/02 §7 requires logs."""
    base = [rel(f"C{i}", 1.0) for i in range(6)]
    up = flag_outliers([*[rel(f"C{i}", 1.0) for i in range(6)], rel("X", 8.0)], 3.5)
    down = flag_outliers([*base, rel("X", 0.125)], 3.5)
    z_up = abs(next(r for r in up if r.carrier == "X").modified_z)
    z_down = abs(next(r for r in down if r.carrier == "X").modified_z)
    assert z_up == pytest.approx(z_down)


# --------------------------------------------------------------------------
# Imputation — docs/02 §6
# --------------------------------------------------------------------------


def test_imputation_fills_missing_carriers_at_the_stratum_geometric_mean():
    group = [rel("6E", 2.0), rel("AI", 8.0)]
    filled = impute_missing(group, expected_carriers=("6E", "AI", "SG"))
    imputed = [r for r in filled if r.imputed]
    assert len(imputed) == 1
    assert imputed[0].carrier == "SG"
    # Geometric mean of 2 and 8 is 4, not the arithmetic 5.
    assert imputed[0].relative == pytest.approx(4.0)


def test_imputation_is_neutral_to_the_elementary_index():
    """Class-mean imputation at the geometric mean cannot move a Jevons
    aggregate. It changes n_imputed -- the quality signal -- not the number."""
    cfg = make_config(expected_carriers=("6E", "AI", "SG"))
    group = [rel("6E", 2.0), rel("AI", 8.0)]

    before = aggregate.elementary_panel(group, cfg)[0].jevons_relative
    after_rows = aggregate.elementary_panel(impute_missing(group, cfg.expected_carriers), cfg)
    assert after_rows[0].jevons_relative == pytest.approx(before)
    assert after_rows[0].n_observed == 2
    assert after_rows[0].n_imputed == 1


def test_imputation_never_invents_an_unexpected_carrier():
    filled = impute_missing([rel("6E", 2.0)], expected_carriers=("6E",))
    assert all(not r.imputed for r in filled)


# --------------------------------------------------------------------------
# Elementary aggregation and suppression
# --------------------------------------------------------------------------


def test_elementary_is_the_geometric_mean_of_relatives():
    cfg = make_config(expected_carriers=("6E", "AI"))
    rows = aggregate.elementary_panel([rel("6E", 1.0), rel("AI", 4.0)], cfg)
    assert rows[0].jevons_relative == pytest.approx(2.0)  # sqrt(1*4), not 2.5
    assert rows[0].coverage_ratio == pytest.approx(1.0)
    assert rows[0].suppressed is False


def test_stratum_below_the_coverage_floor_is_suppressed():
    """docs/01 coverage floor: 0.60 for a stratum. One carrier of five is 0.2."""
    cfg = make_config(expected_carriers=("6E", "AI", "SG", "QP", "IX"))
    rows = aggregate.elementary_panel([rel("6E", 1.5)], cfg)
    assert rows[0].coverage_ratio == pytest.approx(0.2)
    assert rows[0].suppressed is True


def test_outliers_stay_in_the_elementary_aggregate():
    cfg = make_config(expected_carriers=("6E", "AI"))
    group = [rel("6E", 1.0), rel("AI", 4.0)]
    group[1].outlier = True
    rows = aggregate.elementary_panel(group, cfg)
    assert rows[0].jevons_relative == pytest.approx(2.0)


# --------------------------------------------------------------------------
# Upper level — Lowe/Young, sensitivity band
# --------------------------------------------------------------------------


def panel_row(route_id, apd, relative, coverage=1.0, period=DAY2):
    return aggregate.StratumResult(
        period=period,
        stratum=StratumKey(route_id, apd),
        jevons_relative=relative,
        n_observed=2,
        n_imputed=0,
        coverage_ratio=coverage,
        suppressed=False,
    )


def test_upper_level_weights_by_booking_curve():
    """Hand-worked: T7 relative 1.0 weight 0.20, T30 relative 2.0 weight 0.40.
    Weighted arithmetic mean = (0.2*1 + 0.4*2) / 0.6 = 1.6667 -> 166.67."""
    cfg = make_config()
    panel = [panel_row(1, 7, 1.0), panel_row(1, 30, 2.0)]
    value, _, n = aggregate.upper_level(panel, {1: None}, cfg, DAY2)
    assert value == pytest.approx(100.0 * (0.2 * 1.0 + 0.4 * 2.0) / 0.6)
    assert value == pytest.approx(166.666667, abs=1e-5)
    assert n == 2


def test_upper_level_weights_by_route_when_dgca_weights_exist():
    """Route weights multiply the curve weights. Same window, so the curve
    weight cancels and the result is the route-weighted mean:
    (0.75*1.0 + 0.25*3.0) / 1.0 = 1.5 -> 150."""
    cfg = make_config()
    panel = [panel_row(1, 7, 1.0), panel_row(2, 7, 3.0)]
    value, _, _ = aggregate.upper_level(panel, {1: 0.75, 2: 0.25}, cfg, DAY2)
    assert value == pytest.approx(150.0)


def test_suppressed_strata_are_excluded_from_the_aggregate():
    cfg = make_config()
    good = panel_row(1, 7, 1.0)
    bad = aggregate.StratumResult(DAY2, StratumKey(2, 7), 99.0, 1, 0, 0.2, suppressed=True)
    value, _, n = aggregate.upper_level([good, bad], {1: None, 2: None}, cfg, DAY2)
    assert n == 1
    assert value == pytest.approx(100.0)


def test_composite_always_carries_a_sensitivity_band_containing_the_value():
    """docs/02 §4 / Q1: never publish the composite as a bare point estimate."""
    cfg = make_config()
    panel = [panel_row(1, 1, 3.0), panel_row(1, 30, 1.0)]
    result = aggregate.composite(panel, {1: None}, cfg, DAY2)

    assert result.sensitivity_low <= result.value <= result.sensitivity_high
    # T1 is expensive here, so the front-loaded curve must give a higher index.
    assert result.sensitivity_high > result.value
    assert result.sensitivity_low < result.value


def test_sensitivity_band_collapses_when_the_curve_cannot_matter():
    """One window means every curve reduces to the same weighted mean."""
    cfg = make_config()
    result = aggregate.composite([panel_row(1, 7, 1.5)], {1: None}, cfg, DAY2)
    assert result.sensitivity_low == pytest.approx(result.value)
    assert result.sensitivity_high == pytest.approx(result.value)


def test_headline_suppressed_below_the_headline_floor():
    cfg = make_config()
    thin = aggregate.StratumResult(DAY2, StratumKey(1, 7), 1.0, 1, 0, 0.5, suppressed=False)
    result = aggregate.composite([thin], {1: None}, cfg, DAY2, expected_strata=1)
    assert result.coverage_ratio == pytest.approx(0.5)
    assert result.suppressed is True


def test_window_sub_index_carries_no_curve_assumption():
    cfg = make_config()
    panel = [panel_row(1, 7, 2.0), panel_row(1, 30, 99.0)]
    value, _ = aggregate.window_index(panel, {1: None}, cfg, DAY2, advance_purchase_days=7)
    assert value == pytest.approx(200.0)


def test_no_surviving_stratum_yields_nothing_rather_than_a_number():
    cfg = make_config()
    dead = aggregate.StratumResult(DAY2, StratumKey(1, 7), 1.0, 0, 0, 0.0, suppressed=True)
    assert aggregate.upper_level([dead], {1: None}, cfg, DAY2) is None
    assert aggregate.composite([dead], {1: None}, cfg, DAY2) is None


# --------------------------------------------------------------------------
# Day-of-week artefact — docs/02 §5
# --------------------------------------------------------------------------


def test_centred_moving_average_needs_seven_consecutive_days():
    series = [(BASE + timedelta(days=i), 100.0 + i) for i in range(7)]
    smoothed = aggregate.centred_moving_average(series, window=7)
    assert len(smoothed) == 1
    assert smoothed[0][0] == BASE + timedelta(days=3)  # centred
    assert smoothed[0][1] == pytest.approx(103.0)


def test_centred_moving_average_skips_windows_with_a_gap():
    """A partial window would reintroduce the weekday bias the average exists
    to remove, so a missed collection day must produce no smoothed value."""
    days = [0, 1, 2, 3, 4, 5, 7]  # day 6 missing
    series = [(BASE + timedelta(days=d), 100.0) for d in days]
    assert aggregate.centred_moving_average(series, window=7) == []


def test_moving_average_window_must_be_odd():
    with pytest.raises(ValueError, match="odd window"):
        aggregate.centred_moving_average([], window=6)


# --------------------------------------------------------------------------
# End-to-end determinism — docs/02 §9
# --------------------------------------------------------------------------


def _week_of_observations() -> list[Observation]:
    out = []
    for i in range(8):
        day = BASE + timedelta(days=i)
        for apd in (1, 7, 15, 30):
            out.append(obs(day, 1, apd, "6E", 1000.0 + 10 * i + apd))
            out.append(obs(day, 1, apd, "AI", 1200.0 + 12 * i + apd))
    return out


def test_recompute_is_bit_identical():
    """docs/02 §9: 'The index is recomputable bit-for-bit from the warehouse
    alone.' Phase 3's definition of done names this explicitly."""
    cfg = make_config()
    observations = _week_of_observations()
    first = engine.compute(observations, {1: None}, cfg, computed_on=date(2026, 9, 30))
    second = engine.compute(observations, {1: None}, cfg, computed_on=date(2026, 9, 30))
    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2].vintage_id == second[2].vintage_id


def test_end_to_end_produces_panel_and_index_values():
    cfg = make_config()
    panel, index_rows, report = engine.compute(
        _week_of_observations(), {1: None}, cfg, computed_on=date(2026, 9, 30)
    )
    assert panel, "expected stratum_panel rows"
    assert index_rows, "expected index_value rows"
    assert report.base_period == BASE

    series = {r["series_id"] for r in index_rows}
    assert engine.SERIES_HEADLINE_RAW in series
    assert f"{engine.SERIES_WINDOW_PREFIX}.T7" in series
    # 8 days of data -> exactly one complete centred 7-day window.
    assert engine.SERIES_HEADLINE in series

    for row in index_rows:
        assert row["config_hash"] == cfg.config_hash
        assert row["vintage_id"] == report.vintage_id
        if row["series_id"] == engine.SERIES_HEADLINE_RAW:
            assert row["sensitivity_low"] is not None
            assert row["sensitivity_high"] is not None


def test_single_collection_day_publishes_nothing_and_says_why():
    """Early in the collection window this is the expected state. It must warn,
    not invent a base-equals-current index of 100."""
    cfg = make_config()
    panel, rows, report = engine.compute(
        [obs(BASE, 1, 7, "6E", 100.0)], {1: None}, cfg, computed_on=BASE
    )
    assert panel == [] and rows == []
    assert any("one collection day" in w for w in report.warnings)


def test_missing_dgca_weights_are_reported_not_hidden():
    cfg = make_config()
    _, _, report = engine.compute(
        _week_of_observations(), {1: None}, cfg, computed_on=date(2026, 9, 30)
    )
    assert report.route_weights_are_real is False
    assert any("EQUAL weight" in w for w in report.warnings)


def test_no_eligible_quotes_is_reported_not_treated_as_zero_inflation():
    cfg = make_config()
    panel, rows, report = engine.compute([], {1: None}, cfg, computed_on=BASE)
    assert panel == [] and rows == []
    assert any("no index-eligible quotes" in w for w in report.warnings)


def test_everything_suppressed_is_explained_not_silent():
    """A full panel that publishes nothing is legitimate -- it is what the
    coverage floor is for -- but '0 index rows' with no reason is
    indistinguishable from a bug, so the run must say why."""
    cfg = make_config(expected_carriers=("6E", "AI", "SG", "QP", "IX"))
    panel, rows, report = engine.compute(
        _week_of_observations(), {1: None}, cfg, computed_on=date(2026, 9, 30)
    )
    assert panel, "the panel is still computed"
    assert rows == [], "2 of 5 carriers is below the 60% floor"
    assert any("coverage floor" in w for w in report.warnings)
    assert any("not a computation failure" in w for w in report.warnings)

# --- the headline's second gate: advance-purchase window ---------------------
#
# Added with the first Tier-3 offer source (2026-09-23). Those rows carry a
# lead time Goibibo chose -- T+8 to T+88, differing per route on the same day
# -- so they are real observations of a different product. The fare_class
# filter above is not enough on its own: an offer source tagged distinctly and
# then forgotten in TIER1_FILED_FARE_CLASSES would flow straight into the
# headline. This gate does not depend on remembering anything.


def test_the_headline_query_admits_only_methodology_windows():
    from sqlalchemy.dialects import postgresql

    from apix.index.config import ADVANCE_PURCHASE_WINDOWS
    from apix.index.engine import load_observations

    class _CapturingSession:
        def __init__(self):
            self.stmt = None

        def execute(self, stmt):
            self.stmt = stmt
            return []

    session = _CapturingSession()
    load_observations(session, date(2026, 9, 1), date(2026, 10, 1))
    sql = str(session.stmt.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))

    assert "advance_purchase_days IN (1, 7, 15, 30)" in sql.replace("\n", " ")
    assert tuple(ADVANCE_PURCHASE_WINDOWS) == (1, 7, 15, 30)


def test_an_uncontrolled_lead_offer_is_not_an_index_window():
    """T+10 and T+88 were both observed on the first sweep; neither is a
    window the headline aggregates."""
    from apix.index.config import ADVANCE_PURCHASE_WINDOWS

    assert 10 not in ADVANCE_PURCHASE_WINDOWS
    assert 88 not in ADVANCE_PURCHASE_WINDOWS


def test_an_offer_on_a_methodology_window_is_still_excluded():
    """Found in production on 2026-09-24. Goibibo picks its own departure
    date, and sometimes picks one that lands exactly on T+7 or T+30. Four such
    rows passed the window gate and reached the headline. The window gate
    cannot express "different product"; the tag has to."""
    from sqlalchemy.dialects import postgresql

    from apix.index.engine import (
        NON_HEADLINE_FARE_CLASSES,
        TIER1_FILED_FARE_CLASSES,
        load_observations,
    )

    assert "tier3_offer_uncontrolled_lead" in NON_HEADLINE_FARE_CLASSES
    assert TIER1_FILED_FARE_CLASSES < NON_HEADLINE_FARE_CLASSES  # strict superset

    class _CapturingSession:
        def execute(self, stmt):
            self.stmt = stmt
            return []

    session = _CapturingSession()
    load_observations(session, date(2026, 9, 1), date(2026, 10, 1))
    sql = str(session.stmt.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert "tier3_offer_uncontrolled_lead" in sql
