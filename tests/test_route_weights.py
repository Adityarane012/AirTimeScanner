"""The weight failsafes: a partly weighted basket, and a visible methodology.

Both of these are about the same risk. A route weight moves every published
number, so the two ways it can go wrong quietly are (a) being applied to only
part of the basket and (b) being applied without the output saying it changed.
"""

import dataclasses
from datetime import date
from decimal import Decimal

from apix.index import config as index_config
from apix.index.engine import MIN_WEIGHT_COVERAGE, compute, weight_coverage
from apix.weights.dgca_city_pairs import parse_city_pairs

HEADER = "Year,Month,City1,City2,PaxToCity2,PaxFromCity2,FreightToCity2,FreightFromCity2,MailToCity2,MailFromCity2"


def _config(**overrides):
    cfg = index_config.load()
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


# --- coverage floor ---------------------------------------------------------


def test_coverage_counts_only_routes_that_have_a_weight():
    assert weight_coverage({1: 0.5, 2: 0.5}) == 1.0
    assert weight_coverage({1: 0.5, 2: None}) == 0.5
    assert weight_coverage({}) == 0.0


def test_a_partly_weighted_basket_is_refused_and_falls_back_to_equal():
    """Half a basket weighted is worse than none: the weighted routes dominate
    and nothing in the output says so."""
    weights = {1: 0.9, 2: None, 3: None, 4: None}
    assert weight_coverage(weights) < MIN_WEIGHT_COVERAGE

    _panel, _rows, report = compute([], weights, _config(), computed_on=date(2026, 9, 27))

    assert not report.route_weights_are_real
    assert any("REFUSED" in w and "EQUAL weight" in w for w in report.warnings)


def test_a_fully_weighted_basket_is_used():
    weights = {1: 0.25, 2: 0.25, 3: 0.25, 4: 0.25}
    _panel, _rows, report = compute([], weights, _config(), computed_on=date(2026, 9, 27))
    assert report.route_weights_are_real
    assert not any("REFUSED" in w for w in report.warnings)


def test_no_weights_at_all_warns_about_equal_weighting():
    _panel, _rows, report = compute(
        [], {1: None, 2: None}, _config(), computed_on=date(2026, 9, 27)
    )
    assert not report.route_weights_are_real
    assert any("falls back to" in w.lower() or "fall back to" in w.lower() for w in report.warnings)


# --- the methodology must record which weights were in force ----------------


def test_the_weight_source_changes_the_config_hash():
    """An equal-weighted series and a traffic-weighted one are different
    methodologies. docs/02 s9 requires that to be visible in the stamp, not
    inferable from a changelog."""
    equal = _config(route_weight_source="equal_fallback")
    weighted = _config(
        route_weight_source="passenger_share:dgca_city_pair@8307cfcac03b:2025-08..2026-07"
    )
    assert equal.config_hash != weighted.config_hash
    assert equal.vintage_id(date(2026, 9, 27)) != weighted.vintage_id(date(2026, 9, 27))


def test_the_weight_source_is_part_of_the_hashed_parameters():
    cfg = _config(route_weight_source="passenger_share:x:2025-08..2026-07")
    assert cfg.canonical_params()["route_weight_source"] == "passenger_share:x:2025-08..2026-07"


def test_changing_the_basis_alone_changes_the_hash():
    """Passenger share and expenditure share are different statistics computed
    over the same period; swapping one for the other is a methodology change."""
    pax = _config(route_weight_source="passenger_share:src:2025-08..2026-07")
    spend = _config(route_weight_source="expenditure_share:src:2025-08..2026-07")
    assert pax.config_hash != spend.config_hash


# --- the mirror-faithfulness check -----------------------------------------


def test_the_national_total_counts_every_city_pair_not_just_mapped_ones():
    """This total exists to be compared against DGCA's published headline, so
    it must include the 168 cities outside the basket."""
    traffic = parse_city_pairs(
        f"{HEADER}\n"
        "2026,07,DELHI,MUMBAI,100.00,100.00,0,0,0,0\n"
        "2026,07,ADAMPUR,AGARTALA,7.00,3.00,0,0,0,0\n"  # neither city is mapped
    )
    assert traffic.flows  # the mapped pair is still usable for weights
    assert traffic.unmapped_cities == ("ADAMPUR", "AGARTALA")
    assert traffic.monthly_totals[date(2026, 7, 1)] == Decimal(210)
