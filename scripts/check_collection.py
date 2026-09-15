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
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from apix.db.engine import get_session
from apix.db.models import CollectionRun
from apix.ops.collection_health import assess, format_days, utc_day_bounds
from apix.ops.sources import scheduled_sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=30, help="look-back window (default 30)")
    args = parser.parse_args(argv)

    today = datetime.now(UTC).date()
    window_start, _ = utc_day_bounds(today - timedelta(days=args.days))

    print(f"Collection health, UTC {today}, last {args.days} days\n")
    any_stale = False

    with get_session() as session:
        for scheduled in scheduled_sources():
            stmt = select(CollectionRun.started_at, CollectionRun.status).where(
                CollectionRun.source == scheduled.name,
                CollectionRun.started_at >= window_start,
            )
            runs = [
                (started.astimezone(UTC).date(), status)
                for started, status in session.execute(stmt)
            ]
            health = assess(scheduled.name, runs, today)

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
            print()

    if any_stale:
        print("STALE: at least one collecting source missed yesterday. Check "
              "logs/collection.log and Get-ScheduledTaskInfo -TaskName APIx-DailyCollection.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
