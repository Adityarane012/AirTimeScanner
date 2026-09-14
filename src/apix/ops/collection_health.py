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
