"""Tests for the Air India adapter — the fare *construction* rule and the
adapter seams, not the PDF parsing (that is `test_ai_tariff.py`).

IMPLEMENTATION.md §5b's lesson shaped what is covered here: four of the five
Phase-1 defects passed a green suite because the tests exercised pure
functions and never the seams between them. So these tests target exactly
those seams — the GST rule, the directional tax wedge, what happens when a
filed charge is missing, and whether the emitted tag is actually understood by
the index engine downstream.

Fixtures are synthetic but numerically real: every figure below is the value
filed in the 15JUN26 sheet, so a change in the construction rule shows up as a
changed expected total rather than an abstract failure.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apix.acquisition.ai_tariff import AirIndiaFareRow, TaxSchedule
from apix.acquisition.compliance import PolitenessResult, RobotsVerdict
from apix.acquisition.tier1_air_india import (
    ANCHOR_ADVANCE_PURCHASE_DAYS,
    FARE_CLASS,
    MIN_EXPECTED_UDF_ROWS,
    Tier1AirIndiaTariffAdapter,
    _find_minimum_row,
    _parse_creation_date,
    _parse_validity_end,
    build_quotes,
    gst_and_total,
)
from apix.index.engine import TIER1_FILED_FARE_CLASSES

ROBOTS_CHECKED_AT = datetime(2026, 9, 9, 6, 0, tzinfo=UTC)
COLLECTION_TS = datetime(2026, 9, 9, 6, 0, 30, tzinfo=UTC)

# Real filed values from the 15JUN26 sheet.
DEL_HYD = AirIndiaFareRow("Delhi", "Hyderabad", 1265, "Minimum", [Decimal(1250), Decimal(3280)])
DEL_BOM = AirIndiaFareRow("Mumbai", "Delhi", 1136, "Minimum", [Decimal(2080), Decimal(4000)])
DEL_HYD_MAX = AirIndiaFareRow("Delhi", "Hyderabad", 1265, "Maximum", [Decimal(4259)])


def _schedule(**overrides) -> TaxSchedule:
    """The real charge schedule, trimmed to the airports these tests touch.
    `udf_by_city` is padded to MIN_EXPECTED_UDF_ROWS so the parse-regression
    warning does not fire except in the test that asks for it.
    """
    udf = {"Delhi": Decimal(152), "Bengaluru": Decimal(649), "Hyderabad": Decimal(885)}
    udf.update({f"Filler{i}": Decimal(500) for i in range(MIN_EXPECTED_UDF_ROWS)})
    schedule = TaxSchedule(
        udf_by_city=udf,
        # Mumbai files no departure UDF; it appears only as an arrival tax.
        arrival_by_iata={"DEL": Decimal(66), "BOM": Decimal(89)},
        asf=Decimal(236),
        rcs=Decimal(10),
        cute=Decimal(160),
        fuel_bands=[(1001, 1500, Decimal(549)), (1501, 2000, Decimal(749))],
    )
    for key, value in overrides.items():
        setattr(schedule, key, value)
    return schedule


def _build(rows=None, schedule=None):
    return build_quotes(
        source="tier1_air_india_tariff",
        rows=rows if rows is not None else [DEL_HYD, DEL_BOM],
        schedule=schedule or _schedule(),
        collection_ts=COLLECTION_TS,
        raw_payload_hash="deadbeef",
    )


def _quote(quotes, origin, destination):
    match = [q for q in quotes if q.origin == origin and q.destination == destination]
    assert len(match) == 1, f"expected exactly one {origin}->{destination}, got {len(match)}"
    return match[0]


def _other_warnings(warnings):
    """Warnings other than "this basket pair isn't in the fixture".

    These fixtures carry one or two filed rows while TARGET_CITY_PAIRS holds
    five, so the absent pairs warn — correctly. Filtering them keeps each test
    asserting on the condition it is actually about.
    """
    return [w for w in warnings if "no Minimum-band economy row" not in w]


# --- the GST rule ----------------------------------------------------------


def test_gst_base_is_the_operator_chosen_broad_reading():
    """The decision recorded in the module docstring, pinned as a number.

    Base 1250 + UDF 152 + ASF 236 + RCS 10 + CUTE 160 = 1808 taxable;
    5% = 90.40; + YQ 549 => 2447.40. The narrower literal reading ("on Base
    Fare & YR" = base + RCS + CUTE only) would give 71.00 and 2428.00 — so
    this test fails loudly if the rule is ever changed without being restated.
    """
    gst, total = gst_and_total(
        base=Decimal(1250),
        udf=Decimal(152),
        asf=Decimal(236),
        rcs_and_cute=Decimal(170),
        yq=Decimal(549),
    )
    assert gst == Decimal("90.40")
    assert total == Decimal("2447.40")


def test_the_fuel_surcharge_is_outside_the_taxable_base():
    """YQ is excluded from the GST base under the rule in force. If it ever
    leaks in, GST moves with it — which this catches and a total-only
    assertion would not."""
    args = {
        "base": Decimal(1000),
        "udf": Decimal(100),
        "asf": Decimal(236),
        "rcs_and_cute": Decimal(170),
    }
    cheap_gst, _ = gst_and_total(**args, yq=Decimal(299))
    dear_gst, _ = gst_and_total(**args, yq=Decimal(899))
    assert cheap_gst == dear_gst


def test_the_reported_components_sum_to_the_reported_total():
    """The decomposition is the reason this source exists; a total that does
    not reconcile to its own parts would make the sub-indices nonsense."""
    quotes, _ = _build()
    for q in quotes:
        assert q.base_fare + q.udf + q.asf + q.rcs_levy + q.carrier_charges + q.gst == q.total_fare


# --- the directional tax wedge --------------------------------------------


def test_both_directions_are_emitted_from_one_filed_row():
    quotes, warnings = _build(rows=[DEL_HYD])
    assert _other_warnings(warnings) == []
    assert {(q.origin, q.destination) for q in quotes} == {("DEL", "HYD"), ("HYD", "DEL")}


def test_directions_share_a_base_fare_but_not_a_total():
    """The sheet files one base fare per pair ("Market & V.V.") while UDF is
    charged at departure and the arrival tax at the destination. That
    asymmetry is real filed data — collapsing it would discard it."""
    quotes, _ = _build(rows=[DEL_HYD])
    out, back = _quote(quotes, "DEL", "HYD"), _quote(quotes, "HYD", "DEL")

    assert out.base_fare == back.base_fare == Decimal(1250)
    assert out.udf == Decimal(152)               # Delhi departure; HYD levies no arrival tax
    assert back.udf == Decimal(885) + Decimal(66)  # Hyderabad departure + Delhi arrival
    assert out.total_fare != back.total_fare


def test_an_airport_with_no_filed_departure_udf_is_not_treated_as_a_gap():
    """Mumbai files no departure UDF anywhere in the sheet and appears only as
    an arrival tax. That is a filing choice, so BOM->DEL carries the Delhi
    arrival tax alone rather than being dropped as unconstructible."""
    quotes, warnings = _build(rows=[DEL_BOM])
    assert _quote(quotes, "BOM", "DEL").udf == Decimal(66)
    assert _quote(quotes, "DEL", "BOM").udf == Decimal(152) + Decimal(89)
    assert _other_warnings(warnings) == []


# --- refusing to fabricate -------------------------------------------------


def test_a_distance_no_filed_band_covers_yields_no_quote_and_a_warning():
    """YQ is the largest single charge on the ticket. Interpolating a band the
    sheet does not file would fabricate it."""
    quotes, warnings = _build(
        rows=[DEL_HYD], schedule=_schedule(fuel_bands=[(1, 500, Decimal(299))])
    )
    assert quotes == []
    assert _other_warnings(warnings) == [
        (
            "Delhi-Hyderabad: no filed YQ band covers 1265 km — "
            "total fare is not constructible, no quote emitted"
        )
    ]


def test_a_missing_filed_charge_fails_the_run_rather_than_understating_totals():
    """ASF applies to every sector in the basket, so its absence means the
    Page-II table moved — not that the charge is zero. A total quietly short
    by 236 is worse than no total."""
    with pytest.raises(ValueError, match="ASF"):
        _build(schedule=_schedule(asf=None))


def test_a_collapsed_udf_block_warns_instead_of_passing_silently():
    """The historical defect: the tax-code cell is vertically merged, and
    classifying rows by that label captured exactly one airport. Totals stay
    constructible, so this degrades the run rather than failing it."""
    quotes, warnings = _build(
        rows=[DEL_HYD], schedule=_schedule(udf_by_city={"Bengaluru": Decimal(649)})
    )
    assert quotes  # still emitted — the failure mode is understatement, not absence
    assert any("UDF rows parsed" in w for w in warnings)


def test_a_route_missing_from_the_filing_is_reported_not_silently_skipped():
    quotes, warnings = _build(rows=[DEL_HYD])
    assert len(quotes) == 2
    assert len([w for w in warnings if "no Minimum-band economy row" in w]) == 4


# --- row selection ---------------------------------------------------------


def test_a_city_pair_is_found_in_either_filed_order():
    """The sheet files Kolkata-Delhi in that order and Delhi-Hyderabad in the
    other. Matching the ordered pair alone silently loses routes."""
    assert _find_minimum_row([DEL_BOM], "Delhi", "Mumbai") is DEL_BOM
    assert _find_minimum_row([DEL_BOM], "Mumbai", "Delhi") is DEL_BOM


def test_the_maximum_band_is_never_read_as_the_minimum():
    """docs/02 §1 asks for the lowest fare. Reading a Maximum row would roughly
    triple it."""
    assert _find_minimum_row([DEL_HYD_MAX], "Delhi", "Hyderabad") is None


def test_the_lowest_filed_level_is_the_one_taken():
    quotes, _ = _build(rows=[DEL_HYD])
    assert _quote(quotes, "DEL", "HYD").base_fare == Decimal(1250)  # not Level 2's 3280


# --- the tag, and the downstream coupling it depends on --------------------


def test_filed_rows_are_tagged_and_the_index_engine_excludes_that_tag():
    """The engine's headline filter keys on an exact fare_class. A new adapter
    that tags distinctly and is not added to that set does not fail — it
    quietly feeds filed tariff bands into the headline index."""
    quotes, _ = _build(rows=[DEL_HYD])
    assert all(q.fare_class == FARE_CLASS for q in quotes)
    assert FARE_CLASS in TIER1_FILED_FARE_CLASSES


def test_the_air_india_tag_is_distinct_from_indigos():
    """They are different economic objects — one is a total-only floor, the
    other a base fare with a decomposition — so downstream code must be able
    to tell them apart even though both are excluded from the headline."""
    assert FARE_CLASS != "tier1_tariff_floor"
    assert {"tier1_tariff_floor", FARE_CLASS} <= TIER1_FILED_FARE_CLASSES


def test_the_departure_date_anchor_is_the_stated_convention():
    quotes, _ = _build(rows=[DEL_HYD])
    expected = (COLLECTION_TS + timedelta(days=ANCHOR_ADVANCE_PURCHASE_DAYS)).date()
    for q in quotes:
        assert q.departure_date == expected
        assert q.advance_purchase_days == ANCHOR_ADVANCE_PURCHASE_DAYS
        assert q.carrier == "AI"


# --- document dating -------------------------------------------------------


def test_creation_date_is_read_and_converted_to_utc():
    """The sheet prints no issue timestamp; its PDF CreationDate is the only
    signal, and it is filed in +05:30."""
    parsed = _parse_creation_date({"CreationDate": "D:20260615172542+05'30'"})
    assert parsed == datetime(2026, 6, 15, 11, 55, 42, tzinfo=UTC)


def test_an_unreadable_creation_date_is_none_rather_than_now():
    """Falling back to now() would make an undated sheet look freshly issued."""
    assert _parse_creation_date({"CreationDate": "not a date"}) is None
    assert _parse_creation_date({}) is None
    assert _parse_creation_date(None) is None


def test_the_stated_validity_end_is_parsed():
    text = "Air India Domestic Fares\nFares for the period W.I.E. till 30th June 2027\nINDEX"
    assert _parse_validity_end(text) == date(2027, 6, 30)


def test_a_sheet_with_no_stated_validity_does_not_claim_one():
    assert _parse_validity_end("Air India Domestic Fares") is None


# --- adapter seams ---------------------------------------------------------


class _FakeFetcher:
    def __init__(self):
        self.calls = []

    def get(self, url, user_agent):
        self.calls.append((url, user_agent))
        return PolitenessResult(
            body=b"%PDF-fake",
            status=200,
            robots=RobotsVerdict(
                allowed=True,
                checked_at=ROBOTS_CHECKED_AT,
                crawl_delay=None,
                robots_url="https://www.airindia.com/robots.txt",
            ),
            slept_s=0.0,
        )


class _FakeStore:
    def put(self, body):
        return type("_Put", (), {"content_hash": "deadbeef"})()


def _adapter(document_ts=None, warnings=None):
    adapter = Tier1AirIndiaTariffAdapter(fetcher=_FakeFetcher())
    adapter.store = _FakeStore()
    captured = {}

    def fake_parse(pdf_bytes, raw_payload_hash, collection_ts):
        captured["collection_ts"] = collection_ts
        return [], document_ts, list(warnings or [])

    adapter._parse = fake_parse
    return adapter, captured


def test_collection_ts_is_fetch_time_not_the_documents_own_date():
    """The Phase-1 defect that produced a table of exact duplicates: a sheet
    republished ~yearly stamped every daily run with the same instant."""
    document_ts = datetime(2026, 6, 15, 11, 55, 42, tzinfo=UTC)
    adapter, captured = _adapter(document_ts=document_ts)

    before = datetime.now(UTC)
    result = adapter.fetch_and_parse()
    after = datetime.now(UTC)

    assert before <= captured["collection_ts"] <= after
    assert result.source_document_ts == document_ts


def test_fetch_goes_through_the_polite_fetcher_with_an_identifying_agent():
    """docs/01's compliance posture is only real if the adapter routes through
    it — the original IndiGo adapter called Fetcher.get() directly."""
    adapter, _ = _adapter()
    adapter.fetch_and_parse()

    assert len(adapter.fetcher.calls) == 1
    url, user_agent = adapter.fetcher.calls[0]
    assert url.startswith("https://www.airindia.com/")
    assert "APIx" in user_agent


def test_the_robots_check_timestamp_survives_a_parse_failure():
    """A failed parse still made a compliant request; losing that record would
    understate what was actually checked."""
    adapter, _ = _adapter()

    def boom(pdf_bytes, raw_payload_hash, collection_ts):
        raise ValueError("section not found")

    adapter._parse = boom
    result = adapter.fetch_and_parse()

    assert result.status == "failed"
    assert result.robots_checked_at == ROBOTS_CHECKED_AT
    assert "section not found" in result.error


def test_a_warned_run_is_not_reported_as_a_clean_one():
    adapter, _ = _adapter(warnings=["tariff sheet expired on 2027-06-30"])
    result = adapter.fetch_and_parse()

    assert result.status == "partial"
    assert result.notes == "tariff sheet expired on 2027-06-30"
