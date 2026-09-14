"""Collection bookkeeping: when to fetch, and (later in this file) what is missing.

The collector is now launched repeatedly rather than once at 06:00, so the
decision about whether a launch should touch the network is what stands
between "robust to a laptop that is off every morning" and "fetches Air India's
tariff sheet 24 times a day".
"""

from datetime import UTC, date, datetime, timedelta, timezone

from apix.ops.collection_health import decide, utc_day_bounds

# --- decide ----------------------------------------------------------------


def test_the_first_launch_of_the_day_runs():
    assert decide([], max_attempts=3).run


def test_a_source_that_succeeded_today_is_not_fetched_again():
    decision = decide(["succeeded"], max_attempts=3)
    assert not decision.run
    assert "already collected" in decision.reason


def test_a_partial_run_counts_as_done():
    """Partial means warnings, such as a stale sheet. Fetching the same document
    again an hour later cannot clear them, so it would only add load."""
    assert not decide(["partial"], max_attempts=3).run


def test_a_failure_is_retried():
    """Straight after boot the network is often not up yet. That should cost
    an hour, not a day."""
    decision = decide(["failed"], max_attempts=3)
    assert decision.run
    assert "attempt 2 of 3" in decision.reason


def test_retries_stop_at_the_daily_limit():
    """A source failing for a real reason (a robots disallow, a changed
    document) must not be re-fetched every hour all day."""
    decision = decide(["failed", "failed", "failed"], max_attempts=3)
    assert not decision.run
    assert "limit 3" in decision.reason


def test_a_success_after_failures_still_ends_the_day():
    assert not decide(["failed", "succeeded"], max_attempts=3).run


def test_a_tripwire_gets_exactly_one_attempt():
    """IndiGo's daily robots.txt check is expected to fail. One look a day is
    its whole purpose."""
    assert decide([], max_attempts=1).run
    assert not decide(["failed"], max_attempts=1).run


# --- utc_day_bounds --------------------------------------------------------


def test_day_bounds_are_a_half_open_utc_day():
    start, end = utc_day_bounds(date(2026, 9, 14))
    assert start == datetime(2026, 9, 14, tzinfo=UTC)
    assert end == datetime(2026, 9, 15, tzinfo=UTC)


def test_an_early_morning_ist_run_belongs_to_the_previous_utc_day():
    """01:00 IST on the 14th is 19:30 UTC on the 13th. Same grain as the
    sql/0002 dedupe index, so the two cannot disagree about which day a run
    was on."""
    ist = timezone(timedelta(hours=5, minutes=30))
    run = datetime(2026, 9, 14, 1, 0, tzinfo=ist)
    start, end = utc_day_bounds(date(2026, 9, 13))
    assert start <= run < end
