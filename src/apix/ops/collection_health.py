"""Per-source, per-UTC-day collection bookkeeping.

The collector used to assume it would be launched exactly once a day. On a
laptop that is shut down every night that assumption failed completely:
2026-09-10 to 09-14 produced nothing (IMPLEMENTATION.md §5e). The fix is to
launch it often and let it decide for itself whether there is anything to do,
which is what `decide()` is for.

Everything here keys on the **UTC date** of `collection_run.started_at`, the
same grain as the daily-observation unique index in `sql/0002`. In IST that
day runs from 05:30 to 05:30, which is why a run at 01:00 IST still belongs to
the previous day.

Pure functions only; the queries live with their callers, so this can be
tested without a database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

# A run with one of these statuses means the source is done for the day.
# "partial" counts: it carries warnings (a stale sheet, a missing route), and
# re-fetching the same document later in the day will not clear them.
DONE_STATUSES = frozenset({"succeeded", "partial"})


@dataclass(frozen=True)
class RunDecision:
    run: bool
    reason: str


def decide(statuses_today: Sequence[str], max_attempts: int) -> RunDecision:
    """Whether a source should be fetched now, given today's earlier runs.

    Done once it has succeeded. Retried after a failure, because the likeliest
    failure right after a boot is the network not being up yet, but only up to
    `max_attempts`: a source that fails for a real reason (a robots disallow, a
    changed document) should not be re-fetched every hour all day.
    """
    if any(status in DONE_STATUSES for status in statuses_today):
        return RunDecision(False, "already collected today")
    attempts = len(statuses_today)
    if attempts >= max_attempts:
        return RunDecision(False, f"{attempts} failed attempt(s) today, limit {max_attempts}")
    return RunDecision(True, f"attempt {attempts + 1} of {max_attempts} today")


def utc_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) of a UTC calendar day, for filtering `started_at`."""
    start = datetime.combine(day, time.min, UTC)
    return start, start + timedelta(days=1)


# --- Missed days -------------------------------------------------------------
#
# The 09-10 to 09-14 gap was discovered five days late, and only because
# someone asked. Nothing in the system knew a day was missing. What follows is
# how it knows now.


def days_between(earlier: date, later: date) -> list[date]:
    """The calendar days strictly between two dates."""
    return [earlier + timedelta(days=k) for k in range(1, (later - earlier).days)]


def format_days(days: Sequence[date]) -> str:
    """"2026-09-10 to 2026-09-13, 2026-09-15": consecutive runs collapsed, so a
    long outage reads as one span rather than a wall of dates."""
    if not days:
        return "none"
    spans: list[tuple[date, date]] = []
    for day in sorted(days):
        if spans and day == spans[-1][1] + timedelta(days=1):
            spans[-1] = (spans[-1][0], day)
        else:
            spans.append((day, day))
    return ", ".join(f"{a}" if a == b else f"{a} to {b}" for a, b in spans)


@dataclass(frozen=True)
class SourceHealth:
    source: str
    today: date
    last_success: date | None
    collected_today: bool
    failures_today: int
    # Full UTC days after the first success in the window, before today, with
    # no success. Today is never counted: it is still in progress.
    missed: tuple[date, ...]

    @property
    def stale(self) -> bool:
        """Yesterday passed without a success, or there has never been one.

        Deliberately not "nothing yet today": at 08:00 IST the first hourly
        launch may simply not have happened yet.
        """
        if self.collected_today:
            return False
        return self.last_success is None or self.last_success < self.today - timedelta(days=1)


def assess(source: str, runs: Sequence[tuple[date, str]], today: date) -> SourceHealth:
    """Summarise `(utc_day, status)` run records for one source."""
    success_days = {day for day, status in runs if status in DONE_STATUSES}
    past_successes = sorted(d for d in success_days if d < today)

    missed: tuple[date, ...] = ()
    if past_successes:
        # Days from the first success up to yesterday, minus the ones collected.
        missed = tuple(d for d in days_between(past_successes[0], today) if d not in success_days)

    return SourceHealth(
        source=source,
        today=today,
        last_success=max(success_days) if success_days else None,
        collected_today=today in success_days,
        failures_today=sum(1 for day, status in runs if day == today and status == "failed"),
        missed=missed,
    )


def run_alert(
    *,
    source: str,
    status: str,
    statuses_earlier_today: Sequence[str],
    max_attempts: int,
    previous_success: date | None,
    today: date,
    notes: str | None,
) -> str | None:
    """The one message this run should raise, or None.

    `previous_success` is the last successful day *before* today. Both alerts
    fire once per event with no state of their own. Only the first success of
    a day can end a gap, and only one run is ever exactly the last permitted
    attempt; a `--force` run past that limit stays quiet, since an operator is
    already watching it. Never pass a tripwire source here: its failure is
    expected.
    """
    if any(s in DONE_STATUSES for s in statuses_earlier_today):
        return None  # the day was already collected; a forced re-run is not news
    if status in DONE_STATUSES:
        if previous_success is None:
            return None
        gap = days_between(previous_success, today)
        if not gap:
            return None
        return (
            f"{source} collected again after missing {len(gap)} day(s): {format_days(gap)}. "
            f"Those days cannot be backfilled."
        )
    if len(statuses_earlier_today) + 1 == max_attempts:
        return (
            f"{source} failed all {max_attempts} attempts today and will not retry "
            f"until tomorrow (UTC). Last error: {notes or 'none recorded'}"
        )
    return None
