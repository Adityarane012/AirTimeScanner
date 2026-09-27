"""DGCA city-pair weights: the traps that produce wrong numbers silently.

Every fixture city name below is a real name from the published file
(2015-04 to 2026-07), including the two Mumbai variants that exist because a
second Mumbai airport opened mid-series.
"""

from datetime import date
from decimal import Decimal

import pytest

from apix.weights.dgca_city_pairs import (
    CITY_TO_IATA,
    DISTINCT_NEARBY_AIRPORTS,
    basket_weights,
    parse_city_pairs,
    window_months,
)

HEADER = "Year,Month,City1,City2,PaxToCity2,PaxFromCity2,FreightToCity2,FreightFromCity2,MailToCity2,MailFromCity2"


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


def test_both_directions_are_kept_apart():
    """DEL->BOM and BOM->DEL are separate routes with separate tax wedges.
    Summing the two columns would halve the basket and lose the asymmetry."""
    traffic = parse_city_pairs(_csv("2026,07,DELHI,MUMBAI,100.00,80.00,0,0,0,0"))
    flows = {(f.origin, f.destination): f.passengers for f in traffic.flows}
    assert flows == {("DEL", "BOM"): Decimal(100), ("BOM", "DEL"): Decimal(80)}


def test_navi_mumbai_is_refused_not_merged_into_bom():
    """NMI is a different airport. Substring-matching Mumbai would inflate
    BOM's weight with traffic that never touched the airport we price."""
    traffic = parse_city_pairs(
        _csv(
            "2026,07,DELHI,MUMBAI,100.00,100.00,0,0,0,0",
            "2026,07,DELHI,MUMBAI (NAVI MUMBAI),900.00,900.00,0,0,0,0",
        )
    )
    flows = {(f.origin, f.destination): f.passengers for f in traffic.flows}
    assert flows == {("DEL", "BOM"): Decimal(100), ("BOM", "DEL"): Decimal(100)}
    assert "MUMBAI (NAVI MUMBAI)" in traffic.refused_cities
    assert "NMI" in DISTINCT_NEARBY_AIRPORTS.values()


def test_the_mid_series_mumbai_rename_still_counts_as_bom():
    """Newer months say 'MUMBAI (MUMBAI)'. Matching only 'MUMBAI' would drop
    exactly the recent months a current weight depends on."""
    traffic = parse_city_pairs(
        _csv(
            "2026,06,DELHI,MUMBAI,100.00,0.00,0,0,0,0",
            "2026,07,DELHI,MUMBAI (MUMBAI),150.00,0.00,0,0,0,0",
        )
    )
    total = sum(f.passengers for f in traffic.flows if (f.origin, f.destination) == ("DEL", "BOM"))
    assert total == Decimal(250)
    assert CITY_TO_IATA["MUMBAI"] == CITY_TO_IATA["MUMBAI (MUMBAI)"] == "BOM"


def test_bengaluru_is_the_published_spelling():
    traffic = parse_city_pairs(_csv("2026,07,BENGALURU,DELHI,10.00,10.00,0,0,0,0"))
    assert {f.origin for f in traffic.flows} == {"BLR", "DEL"}


def test_an_unmapped_city_is_reported_not_guessed():
    traffic = parse_city_pairs(_csv("2026,07,DELHI,SOMEWHERE NEW,10.00,10.00,0,0,0,0"))
    assert traffic.flows == []
    assert traffic.unmapped_cities == ("SOMEWHERE NEW",)


def test_a_missing_passenger_count_is_skipped_never_zeroed():
    """A blank cell is an absent measurement. Recording it as zero traffic
    would drag the route's weight down with invented data."""
    traffic = parse_city_pairs(_csv("2026,07,DELHI,MUMBAI,,50.00,0,0,0,0"))
    flows = {(f.origin, f.destination): f.passengers for f in traffic.flows}
    assert flows == {("BOM", "DEL"): Decimal(50)}


def test_a_file_without_the_expected_columns_raises():
    with pytest.raises(ValueError, match="missing columns"):
        parse_city_pairs("Year,Month,Airport,Pax\n2026,07,DELHI,100")


# --- the window and the shares ----------------------------------------------


def test_the_window_spans_twelve_complete_months_inclusive():
    assert window_months(date(2026, 7, 1), 12) == (date(2025, 8, 1), date(2026, 7, 1))
    assert window_months(date(2026, 1, 1), 3) == (date(2025, 11, 1), date(2026, 1, 1))


def test_shares_sum_to_one_across_the_basket():
    """The upper level aggregates within the basket, so weights are shares of
    the basket's traffic, not of all India."""
    traffic = parse_city_pairs(
        _csv(
            "2026,07,DELHI,MUMBAI,600.00,600.00,0,0,0,0",
            "2026,07,DELHI,BENGALURU,400.00,400.00,0,0,0,0",
            # Outside the basket: must not dilute the shares.
            "2026,07,DELHI,JAIPUR,9000.00,9000.00,0,0,0,0",
        )
    )
    basket = [("DEL", "BOM"), ("BOM", "DEL"), ("DEL", "BLR"), ("BLR", "DEL")]
    weights, missing = basket_weights(traffic, basket, months=1)

    assert missing == []
    assert sum(w.share for w in weights) == Decimal(1)
    by_route = {(w.origin, w.destination): w.share for w in weights}
    assert by_route[("DEL", "BOM")] == Decimal(600) / Decimal(2000)


def test_a_route_with_no_traffic_is_missing_not_zero_weighted():
    """A zero weight drops the route from the index silently. The caller has
    to decide whether a basket that incomplete is loadable at all."""
    traffic = parse_city_pairs(_csv("2026,07,DELHI,MUMBAI,100.00,100.00,0,0,0,0"))
    weights, missing = basket_weights(traffic, [("DEL", "BOM"), ("HYD", "DEL")], months=1)
    assert [(w.origin, w.destination) for w in weights] == [("DEL", "BOM")]
    assert missing == [("HYD", "DEL")]


def test_months_outside_the_window_are_excluded():
    traffic = parse_city_pairs(
        _csv(
            "2026,07,DELHI,MUMBAI,100.00,0.00,0,0,0,0",
            "2024,01,DELHI,MUMBAI,999999.00,0.00,0,0,0,0",
        )
    )
    weights, _ = basket_weights(traffic, [("DEL", "BOM")], months=12, latest=date(2026, 7, 1))
    assert weights[0].passengers == Decimal(100)
    assert weights[0].months_observed == 1
