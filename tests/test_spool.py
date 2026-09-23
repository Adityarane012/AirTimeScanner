"""The spool: an unreachable database must never cost a day of collection.

Fixtures replay 2026-09-15: Air India collected at 07:49 IST on a phone
hotspot, then nine runs failed on a campus network that could not reach the
database at all.
"""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from apix.contracts.fare_quote import FareQuote
from apix.ops.collection_health import decide
from apix.ops.spool import Spool, SpooledRun, overdue_upload_alert

IST = timezone(timedelta(hours=5, minutes=30))
SEP15 = date(2026, 9, 15)
AI = "tier1_air_india_tariff"


def _quote(**overrides):
    params = {
        "source": AI,
        "carrier": "AI",
        "origin": "DEL",
        "destination": "HYD",
        "departure_date": date(2026, 10, 15),
        "collection_ts": datetime(2026, 9, 15, 2, 19, 41, tzinfo=UTC),
        "advance_purchase_days": 30,
        "fare_class": "tier1_filed_base_fare",
        "base_fare": Decimal(1250),
        "carrier_charges": Decimal(549),
        "udf": Decimal(152),
        "asf": Decimal(236),
        "rcs_levy": Decimal(10),
        "gst": Decimal("90.40"),
        "convenience_fee": None,
        "total_fare": Decimal("2447.40"),
        "observation_status": "observed",
        "raw_payload_hash": "ab" * 32,
    }
    params.update(overrides)
    return FareQuote(**params)


def _run(started_at, status="succeeded", source=AI, quotes=None):
    return SpooledRun(
        run_id=uuid.uuid4(),
        source=source,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=30),
        status=status,
        config_hash="cfg",
        robots_checked_at=started_at,
        quotes=quotes if quotes is not None else [],
    )


def test_a_run_round_trips_exactly(tmp_path):
    """Fares are Decimals, and an upload hours later must write the same
    numbers and the same fetch timestamp, not a float approximation of them."""
    run = _run(datetime(2026, 9, 15, 2, 19, 41, tzinfo=UTC), quotes=[_quote()])
    spool = Spool(tmp_path)
    spool.write(run)

    [(_, loaded)] = spool.pending()
    assert loaded == run
    assert loaded.quotes[0].gst == Decimal("90.40")
    assert loaded.quotes[0].convenience_fee is None  # absent stays absent, never zero
    assert loaded.quotes[0].collection_ts == run.quotes[0].collection_ts


def test_pending_is_oldest_first(tmp_path):
    spool = Spool(tmp_path)
    later = _run(datetime(2026, 9, 15, 9, 0, tzinfo=UTC))
    earlier = _run(datetime(2026, 9, 15, 3, 0, tzinfo=UTC))
    spool.write(later)
    spool.write(earlier)
    assert [run.run_id for _, run in spool.pending()] == [earlier.run_id, later.run_id]


def test_an_interrupted_write_is_never_read(tmp_path):
    spool = Spool(tmp_path)
    spool.pending_dir.mkdir(parents=True)
    (spool.pending_dir / "20260915T031938Z_x_deadbeef.tmp").write_text('{"trunc')
    assert spool.pending() == []


def test_a_sent_run_leaves_pending_but_still_counts_for_today(tmp_path):
    """The offline skip decision depends on this: a run uploaded this morning
    at home must still read as 'collected' on a network that cannot check."""
    spool = Spool(tmp_path)
    path = spool.write(_run(datetime(2026, 9, 15, 2, 19, tzinfo=UTC)))
    spool.mark_sent(path)
    assert spool.pending() == []
    assert spool.statuses_on(AI, SEP15) == ["succeeded"]


def test_the_incident_morning_offline_skips_instead_of_refetching(tmp_path):
    """Collected at 07:49 IST, then offline for the rest of the day: every
    later launch decides from the spool and skips."""
    spool = Spool(tmp_path)
    spool.mark_sent(spool.write(_run(datetime(2026, 9, 15, 7, 49, tzinfo=IST))))
    decision = decide(spool.statuses_on(AI, SEP15), max_attempts=3)
    assert not decision.run
    assert decision.reason == "already collected today"


def test_offline_failures_count_toward_the_daily_limit(tmp_path):
    spool = Spool(tmp_path)
    for hour in (3, 4, 5):
        spool.write(_run(datetime(2026, 9, 15, hour, 0, tzinfo=UTC), status="failed"))
    assert not decide(spool.statuses_on(AI, SEP15), max_attempts=3).run


def test_statuses_are_per_source_and_per_utc_day(tmp_path):
    spool = Spool(tmp_path)
    spool.write(_run(datetime(2026, 9, 15, 3, 0, tzinfo=UTC), source="tier1_indigo_tariff"))
    # 01:00 IST on the 15th is still the 14th in UTC.
    spool.write(_run(datetime(2026, 9, 15, 1, 0, tzinfo=IST)))
    assert spool.statuses_on(AI, SEP15) == []
    assert spool.statuses_on(AI, date(2026, 9, 14)) == ["succeeded"]


def test_pruning_removes_old_sent_runs_and_never_pending_ones(tmp_path):
    spool = Spool(tmp_path)
    old = datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
    spool.mark_sent(spool.write(_run(old)))
    spool.write(_run(old))  # never uploaded: must survive any pruning
    spool.mark_sent(spool.write(_run(datetime(2026, 9, 14, 3, 0, tzinfo=UTC))))

    assert spool.prune_sent(SEP15) == 1
    assert len(spool.pending()) == 1
    assert spool.statuses_on(AI, date(2026, 9, 14)) == ["succeeded"]


# --- overdue uploads ---------------------------------------------------------


def test_runs_pending_since_today_are_not_news():
    pending = [_run(datetime(2026, 9, 15, 3, 0, tzinfo=UTC))]
    assert overdue_upload_alert(pending, SEP15) is None


def test_runs_pending_from_an_earlier_day_raise_an_alert():
    pending = [
        _run(datetime(2026, 9, 13, 3, 0, tzinfo=UTC)),
        _run(datetime(2026, 9, 14, 3, 0, tzinfo=UTC)),
        _run(datetime(2026, 9, 15, 3, 0, tzinfo=UTC)),
    ]
    alert = overdue_upload_alert(pending, SEP15)
    assert "2 collection run(s) since 2026-09-13" in alert
    assert "Nothing is lost" in alert


def test_the_overdue_alert_is_raised_once_per_day(tmp_path):
    spool = Spool(tmp_path)
    assert spool.first_alert_today(SEP15)
    assert not spool.first_alert_today(SEP15)
    assert spool.first_alert_today(SEP15 + timedelta(days=1))
