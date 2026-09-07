"""Compute the index for a month and publish it — Phase 3 entrypoint.

    python scripts/run_index.py                 # current month
    python scripts/run_index.py --month 2026-09
    python scripts/run_index.py --month 2026-09 --dry-run

Separate from run_collection.py on purpose. Collection is time-critical and
must run daily on a schedule; the index is recomputable from the warehouse at
any time (docs/02-methodology.md §9), so it never needs to race collection and
a failure here can never cost a day of data.

--dry-run computes and reports without writing, which is how to inspect a
methodology change before it produces a published vintage.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apix.db.engine import get_session
from apix.index import config as index_config
from apix.index import engine


def _month_bounds(month: str | None) -> tuple[date, date]:
    """[start, end) for the given YYYY-MM, defaulting to the current month."""
    today = datetime.now(UTC).date()
    if month:
        year, mon = (int(p) for p in month.split("-"))
    else:
        year, mon = today.year, today.month
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", help="YYYY-MM (default: current month)")
    parser.add_argument(
        "--dry-run", action="store_true", help="compute and report, but write nothing"
    )
    args = parser.parse_args()

    start, end = _month_bounds(args.month)
    cfg = index_config.load()
    print(f"APIx index — period {start} to {end} (exclusive)")
    print(f"  config_hash : {cfg.config_hash}")
    print(f"  booking curve: {cfg.booking_curve_version} {cfg.booking_curve}")

    with get_session() as session:
        observations = engine.load_observations(session, start, end)
        route_weights = engine.load_route_weights(session)
        panel, index_rows, report = engine.compute(
            observations, route_weights, cfg, computed_on=datetime.now(UTC).date()
        )

        print(f"  vintage_id  : {report.vintage_id}")
        print(f"  base period : {report.base_period}")
        print(
            f"  quotes {report.n_quotes_loaded} -> relatives {report.n_relatives} "
            f"(+{report.n_imputed} imputed, {report.n_outliers} flagged outliers)"
        )
        print(f"  stratum_panel rows: {report.n_panel_rows}")
        print(f"  index_value rows  : {report.n_index_values}")

        if args.dry_run:
            print("\n--dry-run: nothing written.")
        elif panel or index_rows:
            engine.persist(session, panel, index_rows)
            session.commit()
            print("\nWritten.")
        else:
            print("\nNothing to write.")

    for warning in report.warnings:
        print(f"  WARNING: {warning}")

    # A run that computed nothing is not a failure -- early in the collection
    # window it is the expected state -- but it must not read as a success.
    return 0 if report.n_index_values else 1


if __name__ == "__main__":
    sys.exit(main())
