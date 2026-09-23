"""The first offer source: what it must measure, and what it must refuse to.

Fixtures copy the real 2026-09-23 DEL->HYD page shape, including the details
that would each produce a wrong number if mishandled: the cheapest journey on
the page is a *connection*, amounts arrive wrapped in HTML font tags, and the
departure date is Goibibo's choice rather than a methodology window.

No network: the fetcher and object store are injected, per docs/03's testing
rule.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apix.acquisition.compliance import PolitenessResult, RobotsVerdict
from apix.acquisition.tier3_goibibo import (
    FARE_CLASS,
    ROUTE_PAIRS,
    GoibiboPageShapeError,
    Tier3GoibiboOffersAdapter,
    parse_offer_page,
)

COLLECTED_AT = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)
ROBOTS_CHECKED_AT = datetime(2026, 9, 23, 5, 59, tzinfo=UTC)


def _journey(*, fare, keys, base="6,041", airline="6E"):
    return {
        "fare": fare,
        "flightNumber": "6E 203",
        "airlineCodes": [airline],
        "simpleAirlineHeading": {"nm": "IndiGo"},
        "journeyKeys": [keys],
        "fareBreakup": {
            "fareBreakUpItems": [
                {"text": "<font style='font-size:14px'>TOTAL</font>",
                 "amount": f"<font style='font-size:14px'>₹ {fare:,}</font>"},
                {"text": "<font style='color:#878787'>Base Fare</font>",
                 "amount": f"<font style='color:#878787'>₹ {base}</font>"},
                {"text": "<font style='color:#878787'>Surcharges</font>",
                 "amount": "<font style='color:#878787'>₹ 1,816</font>"},
            ]
        },
    }


# The real page: a connection undercuts every non-stop.
NONSTOP_CHEAP = _journey(fare=8933, keys="DEL$HYD$2026-10-23 07:10$6E-203")
NONSTOP_DEAR = _journey(fare=9408, keys="DEL$HYD$2026-10-23 13:30$6E-6282")
CONNECTION = _journey(
    fare=7857,
    keys="DEL$NAG$2026-10-23 16:30$6E-6433|NAG$HYD$2026-10-23 20:15$6E-7695",
)


def _page(journeys) -> bytes:
    blob = {"props": {"pageProps": {"data": {"state": {"listing": {
        "journeys": {"allJourneys": [journeys]},
    }}}}}}
    html = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(blob)
        + "</script></body></html>"
    )
    return html.encode("utf-8")


def _parse(payload, origin="DEL", destination="HYD"):
    return parse_offer_page(
        payload,
        origin=origin,
        destination=destination,
        collection_ts=COLLECTED_AT,
        raw_payload_hash="ab" * 32,
    )


def test_the_cheapest_non_stop_wins_not_the_cheapest_journey():
    """The page's cheapest fare is a connection via Nagpur. Taking it would
    measure a different product than docs/02 s1 specifies."""
    quote, _ = _parse(_page([CONNECTION, NONSTOP_CHEAP, NONSTOP_DEAR]))
    assert quote.total_fare == Decimal(8933)
    assert quote.is_nonstop


def test_the_observed_lead_time_is_recorded_not_rounded_to_a_window():
    """Goibibo served 2026-10-23 for a run on 09-23: T+30 here, but T+8 and
    T+88 on other routes the same day. Whatever it is, it is recorded."""
    quote, _ = _parse(_page([NONSTOP_CHEAP]))
    assert quote.departure_date.isoformat() == "2026-10-23"
    assert quote.advance_purchase_days == 30


def test_the_fare_decomposition_stops_where_the_page_stops():
    """Base fare is published; UDF, ASF, RCS and GST are not. Absent must
    stay absent -- zero would assert a measurement nobody made."""
    quote, _ = _parse(_page([NONSTOP_CHEAP]))
    assert quote.base_fare == Decimal(6041)
    assert quote.udf is None
    assert quote.asf is None
    assert quote.rcs_levy is None
    assert quote.gst is None
    assert quote.carrier_charges is None


def test_offers_are_tagged_so_they_are_identifiable_in_sql():
    quote, _ = _parse(_page([NONSTOP_CHEAP]))
    assert quote.fare_class == FARE_CLASS
    assert quote.source == "tier3_goibibo_offers"
    assert quote.carrier == "6E"


def test_a_page_of_only_connections_yields_no_quote_and_says_why():
    quote, warnings = _parse(_page([CONNECTION]))
    assert quote is None
    assert "no non-stop journey for this airport pair" in warnings[0]
    assert "1 connections" in warnings[0]


def test_a_journey_for_another_route_is_refused_not_relabelled():
    """Delhi and Mumbai have several airports each, and a DEL page serves DXN
    and HDO journeys too. Recording one as DEL->HYD would fabricate an
    observation; the basket is keyed on airport pairs."""
    other = _journey(fare=4000, keys="BOM$HYD$2026-10-23 07:10$6E-999")
    quote, warnings = _parse(_page([other]))
    assert quote is None
    assert any("BOM->HYD" in w and "other airports" in w for w in warnings)


def test_an_implausible_lead_time_is_refused():
    stale = _journey(fare=5000, keys="DEL$HYD$2024-01-01 07:10$6E-203")
    quote, warnings = _parse(_page([stale]))
    assert quote is None
    assert any("implausible lead time" in w for w in warnings)


def test_a_rebuilt_page_raises_rather_than_reporting_no_offers():
    """'The site changed' and 'no offers today' must not look the same in the
    series."""
    with pytest.raises(GoibiboPageShapeError):
        _parse(b"<html><body>no next data here</body></html>")
    with pytest.raises(GoibiboPageShapeError):
        _parse(_page([]).replace(b"allJourneys", b"renamedByGoibibo"))


# --- the adapter seam -------------------------------------------------------


class _FakeFetcher:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, user_agent):
        self.calls.append((url, user_agent))
        return PolitenessResult(
            body=self.payload,
            status=200,
            robots=RobotsVerdict(
                allowed=True,
                checked_at=ROBOTS_CHECKED_AT,
                crawl_delay=None,
                robots_url="https://www.goibibo.com/robots.txt",
            ),
            slept_s=0.0,
        )


def test_the_adapter_fetches_every_basket_route_through_the_polite_fetcher(tmp_path, monkeypatch):
    from apix.acquisition import tier3_goibibo

    monkeypatch.setattr(tier3_goibibo.settings, "raw_store_path", tmp_path)
    fetcher = _FakeFetcher(_page([NONSTOP_CHEAP, CONNECTION]))
    result = tier3_goibibo.Tier3GoibiboOffersAdapter(fetcher=fetcher).run()

    assert len(fetcher.calls) == len(ROUTE_PAIRS)
    assert result.robots_checked_at == ROBOTS_CHECKED_AT
    # Every route page here serves a DEL->HYD journey, so only that route
    # yields a quote; the rest are refused rather than relabelled.
    assert [q.origin + "->" + q.destination for q in result.quotes] == ["DEL->HYD"]
    # Other airports and connections are normal page content, not warnings:
    # only the nine routes that yielded nothing are reported.
    assert all("no non-stop journey" in w for w in result.warnings)


def test_one_broken_route_does_not_take_down_the_run(tmp_path, monkeypatch):
    from apix.acquisition import tier3_goibibo

    monkeypatch.setattr(tier3_goibibo.settings, "raw_store_path", tmp_path)

    class _FlakyFetcher(_FakeFetcher):
        def get(self, url, user_agent):
            if "kolkata" in url:
                raise TimeoutError("connection reset")
            return super().get(url, user_agent)

    result = tier3_goibibo.Tier3GoibiboOffersAdapter(fetcher=_FlakyFetcher(_page([NONSTOP_CHEAP]))).run()
    assert result.status == "partial"  # warnings, not a failed run
    assert any("TimeoutError" in w for w in result.warnings)


def test_the_stored_evidence_is_the_state_blob(tmp_path, monkeypatch):
    """The audit trail must hold what the numbers were read from."""
    from apix.acquisition import tier3_goibibo

    monkeypatch.setattr(tier3_goibibo.settings, "raw_store_path", tmp_path)
    adapter = tier3_goibibo.Tier3GoibiboOffersAdapter(fetcher=_FakeFetcher(_page([NONSTOP_CHEAP])))
    result = adapter.run()

    stored = adapter.store.get(result.quotes[0].raw_payload_hash)
    assert json.loads(stored)["props"]["pageProps"]["data"]["state"]["listing"]


def test_the_url_shape_is_the_robots_allowed_one():
    """Query strings and the /flights/air-* search path are disallowed; only
    the static route page is permitted."""
    url = Tier3GoibiboOffersAdapter(fetcher=_FakeFetcher(b"")).url_for("DEL", "HYD")
    assert url == "https://www.goibibo.com/flights/delhi-to-hyderabad-flights/"
    assert "?" not in url
