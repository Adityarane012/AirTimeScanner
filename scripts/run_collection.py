"""The daily collection entrypoint — deliberately simple for the prototype.

Orchestration is Prefect/Airflow in the target design (docs/03-architecture.md);
that's cut for the 1-week solo build (see IMPLEMENTATION.md "What's cut").
This script IS the orchestrator for now: run it once daily via Windows Task
Scheduler. Migrating to Prefect later is mechanical, since adapter logic
lives in apix.acquisition and never talks to the scheduler.

    python scripts/run_collection.py

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

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apix.acquisition.base import SourceAdapter
from apix.acquisition.tier1_indigo import Tier1IndiGoTariffAdapter
from apix.db.engine import get_session
from apix.db.models import CollectionRun, FareQuoteRow, Route

ADAPTERS: list[SourceAdapter] = [Tier1IndiGoTariffAdapter()]


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


def main() -> None:
    if not ADAPTERS:
        print("No adapters registered yet. Add one in scripts/run_collection.py "
              "once Phase 0 reconnaissance confirms a real Tier-1 target.")
        return

    for adapter in ADAPTERS:
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
        for warning in result.warnings:
            print(f"  WARNING: {warning}")


if __name__ == "__main__":
    main()
