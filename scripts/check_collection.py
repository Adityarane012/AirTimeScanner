"""Is collection actually happening? One command, instead of a SQL query.

    python scripts/check_collection.py            # last 30 days
    python scripts/check_collection.py --days 90

Prints, per source: the last successful day, whether today is collected, and
every missed day in the window. Exits 1 if any collecting source is stale
(yesterday, UTC, passed without a success), so it can gate a script or a
morning routine.

The collector raises a desktop notification on its own when a day is lost
(apix.ops.notify). This is the other half: it works even when the collector is
not running at all, which is the one failure the collector cannot report about
itself.

**It answers on a network that cannot reach the database too**, by reading the
local spool instead (apix.ops.spool). That is the network this script is most
likely to be run from — the one where collection looks broken. The spool only
keeps recent days, so the window is shorter and it says so rather than
reporting an old day as missed when it simply cannot see it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from apix.db.engine import get_session
from apix.db.models import CollectionRun
from apix.ops.collection_health import assess, format_days, utc_day_bounds
from apix.ops.sources import scheduled_sources
from apix.ops.spool import KEEP_SENT_DAYS, Spool
from apix.settings import settings


def _runs_from_db(window_start: datetime) -> dict[str, list[tuple[date, str]]]:
    """Every run in the window, by source. Raises OperationalError if the
    database cannot be reached."""
    runs: dict[str, list[tuple[date, str]]] = {}
    with get_session() as session:
        stmt = select(
            CollectionRun.source, CollectionRun.started_at, CollectionRun.status
        ).where(CollectionRun.started_at >= window_start)
        for source, started, status in session.execute(stmt):
            runs.setdefault(source, []).append((started.astimezone(UTC).date(), status))
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=30, help="look-back window (default 30)")
    args = parser.parse_args(argv)

    today = datetime.now(UTC).date()
    days = args.days
    window_start, _ = utc_day_bounds(today - timedelta(days=days))
    spool = Spool(settings.spool_path)
    pending = [run for _, run in spool.pending()]

    try:
        runs = _runs_from_db(window_start)
        source_of_truth = "database"
        # Runs that have been collected but not yet uploaded are real runs.
        for run in pending:
            runs.setdefault(run.source, []).append((run.utc_day, run.status))
    except OperationalError as exc:
        reason = str(getattr(exc, "orig", exc)).strip().splitlines()[0]
        print(f"Database unreachable ({reason}).")
        print("Reporting from the local spool instead.\n")
        runs = {}
        for source in {s.name for s in scheduled_sources()}:
            runs[source] = spool.records(source)
        source_of_truth = "local spool"
        days = min(days, KEEP_SENT_DAYS)
        window_start, _ = utc_day_bounds(today - timedelta(days=days))

    print(f"Collection health, UTC {today}, last {days} days (from the {source_of_truth})\n")
    any_stale = False

    for scheduled in scheduled_sources():
        in_window = [(day, status) for day, status in runs.get(scheduled.name, [])
                     if day >= window_start.date()]
        health = assess(scheduled.name, in_window, today)

        if scheduled.tripwire:
            verdict = "TRIPWIRE (failure expected)"
        elif health.stale:
            verdict = "STALE"
            any_stale = True
        elif health.collected_today:
            verdict = "OK"
        else:
            verdict = "PENDING (nothing yet today)"

        print(f"{scheduled.name}  {verdict}")
        print(f"  last success   : {health.last_success or 'never in window'}")
        print(f"  today          : {'collected' if health.collected_today else 'not yet'}"
              f", {health.failures_today} failed attempt(s)")
        if not scheduled.tripwire:
            print(f"  missed days    : {format_days(health.missed)}")
        waiting = [run for run in pending if run.source == scheduled.name]
        if waiting:
            oldest = min(run.utc_day for run in waiting)
            print(f"  not uploaded   : {len(waiting)} run(s), oldest {oldest}")
        print()

    if pending:
        print(f"{len(pending)} collected run(s) are saved locally and not yet in the database. "
              "Nothing is lost; the next run on a network that can reach it will upload them.")
    if any_stale:
        print("STALE: at least one collecting source missed yesterday. Check "
              "logs/collection.log and Get-ScheduledTaskInfo -TaskName APIx-DailyCollection.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
