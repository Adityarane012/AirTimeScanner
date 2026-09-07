"""Regression tests for the two silent Phase-1 defects in the IndiGo adapter.

Both defects passed every test that existed at the time, because the tests
covered the PDF *parser* and never the adapter's own timestamp handling. They
were only visible in the database, days later, as duplicate rows. These tests
pin the behaviour that was wrong:

1. `collection_ts` must be the time we fetched, never the document's own issue
   timestamp — otherwise a monthly-republished source yields byte-identical
   rows on every daily run.
2. A source document older than the republication cadence must raise a run
   warning, because a dated URL that stops advancing means the hardcoded URL
   has been superseded and nothing else would ever say so.

No network and no real PDF: the fetcher, object store and parser are all
injected, per docs/03's testing rule.
"""

from datetime import UTC, datetime, timedelta

from apix.acquisition.compliance import PolitenessResult, RobotsVerdict
from apix.acquisition.tier1_indigo import TARIFF_MAX_AGE_DAYS, Tier1IndiGoTariffAdapter

ROBOTS_CHECKED_AT = datetime(2026, 9, 7, 6, 0, tzinfo=UTC)


class _FakeFetcher:
    """Stands in for PoliteFetcher — records the call, returns a fixed body."""

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
                robots_url="https://www.goindigo.in/robots.txt",
            ),
            slept_s=0.0,
        )


class _FakePut:
    content_hash = "deadbeef"


class _FakeStore:
    def put(self, body):
        return _FakePut()


def _adapter(document_ts, quotes=None):
    """Adapter wired to fakes, with the PDF parse stubbed to return a chosen
    document timestamp. Captures the collection_ts the adapter passed in."""
    adapter = Tier1IndiGoTariffAdapter(fetcher=_FakeFetcher())
    adapter.store = _FakeStore()
    captured = {}

    def fake_parse(pdf_bytes, raw_payload_hash, collection_ts):
        captured["collection_ts"] = collection_ts
        captured["raw_payload_hash"] = raw_payload_hash
        return (quotes or []), document_ts

    adapter._parse = fake_parse
    return adapter, captured


def test_collection_ts_is_fetch_time_not_document_issue_time():
    """The original defect: a May-issued sheet fetched in September produced
    rows stamped May, identical on every run."""
    document_ts = datetime(2026, 5, 8, 15, 29, 2, tzinfo=UTC)
    adapter, captured = _adapter(document_ts)

    before = datetime.now(UTC)
    result = adapter.fetch_and_parse()
    after = datetime.now(UTC)

    assert before <= captured["collection_ts"] <= after
    assert captured["collection_ts"] != document_ts
    # The document's own timestamp is kept, just not conflated with ours.
    assert result.source_document_ts == document_ts


def test_stale_source_document_raises_a_warning_and_degrades_status():
    stale = datetime.now(UTC) - timedelta(days=TARIFF_MAX_AGE_DAYS + 10)
    adapter, _ = _adapter(stale)

    result = adapter.fetch_and_parse()

    assert result.error is None
    assert len(result.warnings) == 1
    assert "likely" in result.warnings[0]
    # A stale-source run is not a clean run.
    assert result.status == "partial"
    assert result.notes == result.warnings[0]


def test_fresh_source_document_produces_no_warning():
    fresh = datetime.now(UTC) - timedelta(days=3)
    adapter, _ = _adapter(fresh)

    result = adapter.fetch_and_parse()

    assert result.warnings == []
    assert result.status == "succeeded"
    assert result.notes is None


def test_robots_check_timestamp_is_propagated_for_persistence():
    """docs/01's 'robots.txt re-checked on every run' is only auditable if the
    check time reaches collection_run.robots_checked_at."""
    adapter, _ = _adapter(datetime.now(UTC))

    result = adapter.fetch_and_parse()

    assert result.robots_checked_at == ROBOTS_CHECKED_AT


def test_robots_timestamp_survives_a_parse_failure():
    """A failed parse still made a compliant request; losing that record would
    understate what we actually checked."""
    adapter, _ = _adapter(datetime.now(UTC))

    def boom(pdf_bytes, raw_payload_hash, collection_ts):
        raise ValueError("section not found")

    adapter._parse = boom
    result = adapter.fetch_and_parse()

    assert result.status == "failed"
    assert result.robots_checked_at == ROBOTS_CHECKED_AT
    assert "section not found" in result.error


def test_fetch_goes_through_the_polite_fetcher_with_identifying_agent():
    """The compliance module is only worth having if adapters actually route
    through it — the original adapter called Fetcher.get() directly."""
    adapter, _ = _adapter(datetime.now(UTC))

    adapter.fetch_and_parse()

    assert len(adapter.fetcher.calls) == 1
    url, user_agent = adapter.fetcher.calls[0]
    assert url.endswith(".pdf")
    assert "APIx" in user_agent


def test_issue_timestamp_returns_none_rather_than_now_when_unparseable():
    """Falling back to now() would make an undated sheet look freshly issued
    and permanently defeat the staleness check."""
    assert Tier1IndiGoTariffAdapter._parse_issue_timestamp("not a timestamp") is None


def test_issue_timestamp_handles_the_minus_sign_date_separator():
    parsed = Tier1IndiGoTariffAdapter._parse_issue_timestamp("2026−05−08 15:29:02.126928")
    assert parsed == datetime(2026, 5, 8, 15, 29, 2, tzinfo=UTC)
