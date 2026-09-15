"""Collection bookkeeping: when to fetch, and what has been missed.

The collector is now launched repeatedly rather than once at 06:00, so the
decision about whether a launch should touch the network is what stands
between "robust to a laptop that is off every morning" and "fetches Air India's
tariff sheet 24 times a day".
"""

from datetime import UTC, date, datetime, timedelta, timezone

from apix.ops.collection_health import (
    assess,
    days_between,
    decide,
    format_days,
    run_alert,
    utc_day_bounds,
)

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


# --- missed days -------------------------------------------------------------
#
# Fixtures replay the real incident: Air India collected on 09-09, then nothing
# until 09-14.

SEP = {d: date(2026, 9, d) for d in range(1, 31)}
INCIDENT = [(SEP[9], "succeeded"), (SEP[14], "succeeded")]


def test_days_between_excludes_both_ends():
    assert days_between(SEP[9], SEP[14]) == [SEP[10], SEP[11], SEP[12], SEP[13]]
    assert days_between(SEP[9], SEP[10]) == []


def test_consecutive_days_collapse_into_a_span():
    assert format_days([SEP[10], SEP[11], SEP[12], SEP[13]]) == "2026-09-10 to 2026-09-13"
    assert format_days([SEP[13], SEP[10], SEP[11], SEP[20]]) == (
        "2026-09-10 to 2026-09-11, 2026-09-13, 2026-09-20"
    )
    assert format_days([]) == "none"


def test_the_incident_gap_is_reported_exactly():
    health = assess("air_india", INCIDENT, today=SEP[14])
    assert health.missed == (SEP[10], SEP[11], SEP[12], SEP[13])
    assert health.last_success == SEP[14]
    assert health.collected_today


def test_days_before_the_first_success_are_not_counted_as_missed():
    """The series starts at its first collection; days before that were never
    part of it."""
    assert assess("air_india", [(SEP[9], "succeeded")], today=SEP[10]).missed == ()


def test_today_is_never_counted_as_missed():
    """Today is still in progress. At 08:00 IST the first hourly launch may
    not have happened yet."""
    assert assess("air_india", [(SEP[9], "succeeded")], today=SEP[10]).missed == ()


def test_a_failed_day_is_a_missed_day():
    runs = [(SEP[9], "succeeded"), (SEP[10], "failed"), (SEP[11], "succeeded")]
    health = assess("air_india", runs, today=SEP[12])
    assert health.missed == (SEP[10],)


def test_nothing_yet_today_is_pending_not_stale():
    assert not assess("air_india", [(SEP[13], "succeeded")], today=SEP[14]).stale


def test_a_whole_missed_yesterday_is_stale():
    """What check_collection.py would have said on the morning of 09-11."""
    health = assess("air_india", [(SEP[9], "succeeded")], today=SEP[11])
    assert health.stale
    assert health.missed == (SEP[10],)


def test_a_source_that_has_never_succeeded_is_stale():
    assert assess("air_india", [(SEP[14], "failed")], today=SEP[14]).stale


def test_todays_failures_are_counted():
    runs = [(SEP[14], "failed"), (SEP[14], "failed"), (SEP[13], "failed")]
    assert assess("air_india", runs, today=SEP[14]).failures_today == 2


# --- run_alert ---------------------------------------------------------------


def _alert(**overrides):
    params = {
        "source": "tier1_air_india_tariff",
        "status": "succeeded",
        "statuses_earlier_today": [],
        "max_attempts": 3,
        "previous_success": SEP[13],
        "today": SEP[14],
        "notes": None,
    }
    params.update(overrides)
    return run_alert(**params)


def test_an_ordinary_daily_success_raises_nothing():
    assert _alert() is None


def test_the_success_that_ends_a_gap_names_the_lost_days():
    """The alert that would have turned a five-day silent gap into a same-day
    notice once collection recovered."""
    alert = _alert(previous_success=SEP[9])
    assert "missing 4 day(s)" in alert
    assert "2026-09-10 to 2026-09-13" in alert
    assert "cannot be backfilled" in alert


def test_the_very_first_success_is_not_a_gap():
    assert _alert(previous_success=None) is None


def test_a_forced_rerun_after_todays_success_does_not_repeat_the_alert():
    assert _alert(previous_success=SEP[9], statuses_earlier_today=["succeeded"]) is None


def test_a_failure_with_retries_left_stays_quiet():
    """The next hourly launch will retry; one failure is not yet news."""
    assert _alert(status="failed", statuses_earlier_today=["failed"], notes="timeout") is None


def test_the_last_permitted_failure_alerts_once_with_the_error():
    alert = _alert(status="failed", statuses_earlier_today=["failed", "failed"], notes="HTTP 404")
    assert "failed all 3 attempts" in alert
    assert "HTTP 404" in alert


def test_a_forced_failure_past_the_limit_stays_quiet():
    assert _alert(status="failed", statuses_earlier_today=["failed"] * 3) is None
