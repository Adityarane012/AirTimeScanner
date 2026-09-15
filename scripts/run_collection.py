"""The daily collection entrypoint — deliberately simple for the prototype.

Orchestration is Prefect/Airflow in the target design (docs/03-architecture.md);
that's cut for the 1-week solo build (see IMPLEMENTATION.md "What's cut").
This script IS the orchestrator for now, launched by Windows Task Scheduler.
Migrating to Prefect later is mechanical, since adapter logic lives in
apix.acquisition and never talks to the scheduler.

    python scripts/run_collection.py            # collect whatever is due today
    python scripts/run_collection.py --force    # fetch every source regardless

**Safe to launch as often as you like.** Each source is fetched at most once
per UTC day once it succeeds (see `apix.ops.collection_health.decide`), so the
scheduler does not have to bet on a single slot — which matters on a laptop
that is shut down every night and was never once awake at 06:00. A launch with
nothing due makes one small query per source and no network requests.

Adapter isolation is enforced here: one adapter's exception can never stop
the others (SourceAdapter.run() already catches internally; this loop is a
second belt-and-braces layer).

Persistence here is a minimal, inline stand-in for the proper NORMALISE
stage in docs/03-architecture.md's pipeline (PARSE -> NORMALISE -> ...) --
acceptable for the Phase-1 vertical slice per docs/04-delivery-plan.md ("it
can write to a plain table, it can be ugly"), not the final design. Phase 2
should pull this out into a real normalise module once there's more than one
adapter's worth of quotes flowing.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apix.db.engine import get_session
from apix.db.models import CollectionRun, FareQuoteRow, Route
from apix.ops.collection_health import DONE_STATUSES, decide, run_alert, utc_day_bounds
from apix.ops.notify import notify
from apix.ops.sources import scheduled_sources


def _last_success_before(session, source: str, today: date) -> date | None:
    start, _ = utc_day_bounds(today)
    stmt = select(func.max(CollectionRun.started_at)).where(
        CollectionRun.source == source,
        CollectionRun.status.in_(DONE_STATUSES),
        CollectionRun.started_at < start,
    )
    latest = session.execute(stmt).scalar_one_or_none()
    return latest.astimezone(UTC).date() if latest else None


def _statuses_today(session, source: str, today: date) -> list[str]:
    start, end = utc_day_bounds(today)
    stmt = select(CollectionRun.status).where(
        CollectionRun.source == source,
        CollectionRun.started_at >= start,
        CollectionRun.started_at < end,
    )
    return list(session.execute(stmt).scalars())


def _persist_quotes(session, quotes, run_id) -> tuple[int, int]:
    """Resolve each FareQuote's (origin, destination) to a route_id and write
    a fare_quote row. Skips (with a printed warning, not a silent drop) any
    quote whose route isn't in the `route` table yet -- that's a real
    Phase 2 gap (route basket too narrow), not something to paper over.

    Writes go through ON CONFLICT DO NOTHING against the daily-observation
    unique index added in sql/0002. That makes a same-day re-run idempotent
    instead of duplicating -- re-running the collector after a partial
    failure is a normal operator action, and it should not corrupt the
    series. Returns (written, skipped_as_duplicate).
    """
    written = 0
    duplicates = 0
    for q in quotes:
        route = session.execute(
            select(Route).where(Route.origin == q.origin, Route.destination == q.destination)
        ).scalar_one_or_none()
        if route is None:
            print(f"  SKIPPED {q.origin}->{q.destination}: not in route table yet")
            continue
        stmt = (
            pg_insert(FareQuoteRow)
            .values(
                quote_id=uuid.uuid4(),
                run_id=run_id,
                source=q.source,
                carrier=q.carrier,
                route_id=route.route_id,
                departure_date=q.departure_date,
                collection_ts=q.collection_ts,
                advance_purchase_days=q.advance_purchase_days,
                fare_class=q.fare_class,
                is_nonstop=q.is_nonstop,
                # The decomposition columns have existed since 0001_init.sql
                # with nothing writing them, because IndiGo's sheet publishes
                # only a total. Air India files the breakdown, and it is what
                # docs/02 §2's base-fare and tax-wedge sub-indices are built
                # from — writing only total_fare would have thrown away the
                # entire reason for adding the source.
                base_fare=q.base_fare,
                carrier_charges=q.carrier_charges,
                udf=q.udf,
                asf=q.asf,
                rcs_levy=q.rcs_levy,
                gst=q.gst,
                convenience_fee=q.convenience_fee,
                total_fare=q.total_fare,
                observation_status=q.observation_status,
                raw_payload_hash=q.raw_payload_hash,
            )
            .on_conflict_do_nothing()
            .returning(FareQuoteRow.quote_id)
        )
        if session.execute(stmt).scalar_one_or_none() is None:
            duplicates += 1
            print(f"  DUPLICATE {q.origin}->{q.destination}: already collected today, not rewritten")
        else:
            written += 1
    return written, duplicates


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="fetch every source even if it already ran today (operator use)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    today = datetime.now(UTC).date()
    print(f"--- collection run {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC ---")

    # Adapter isolation: one source's failure cannot stop the others, since
    # SourceAdapter.run() catches internally and the loop carries on.
    for scheduled in scheduled_sources():
        adapter = scheduled.adapter
        with get_session() as session:
            statuses_today = _statuses_today(session, adapter.name, today)
            previous_success = _last_success_before(session, adapter.name, today)

        if not args.force:
            decision = decide(statuses_today, scheduled.max_attempts_per_day)
            if not decision.run:
                print(f"{adapter.name}: skipped ({decision.reason})")
                continue
            print(f"{adapter.name}: running ({decision.reason})")

        started_at = datetime.now(UTC)
        result = adapter.run()
        run_id = uuid.uuid4()

        with get_session() as session:
            session.add(
                CollectionRun(
                    run_id=run_id,
                    source=result.source,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    status=result.status,
                    # docs/01's "robots.txt re-checked on every run" is only
                    # auditable if the check timestamp is actually persisted.
                    # The column existed from day one and nothing wrote it.
                    robots_checked_at=result.robots_checked_at,
                    config_hash=result.config_hash,
                    selector_relocated=result.selector_relocated,
                    notes=result.notes,
                )
            )
            session.flush()  # run row must exist before fare_quote FKs reference it
            written, duplicates = _persist_quotes(session, result.quotes, run_id)
            session.commit()

        summary = f"{len(result.quotes)} quotes parsed, {written} written"
        if duplicates:
            summary += f", {duplicates} duplicate"
        print(f"{result.source}: {result.status} ({summary})")

        if not scheduled.tripwire:
            alert = run_alert(
                source=adapter.name,
                status=result.status,
                statuses_earlier_today=statuses_today,
                max_attempts=scheduled.max_attempts_per_day,
                previous_success=previous_success,
                today=today,
                notes=result.notes,
            )
            if alert:
                # Logged first and unconditionally: the toast is best effort.
                print(f"  ALERT: {alert}")
                shown = notify("APIx collection", alert)
                print(f"  (desktop notification {'shown' if shown else 'NOT shown'})")
        for warning in result.warnings:
            print(f"  WARNING: {warning}")


if __name__ == "__main__":
    main()
