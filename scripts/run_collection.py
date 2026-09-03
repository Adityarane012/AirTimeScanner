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
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apix.acquisition.base import SourceAdapter  # noqa: E402
from apix.db.engine import get_session  # noqa: E402
from apix.db.models import CollectionRun  # noqa: E402

# Register adapters here as they're built (Phase 1+). Empty on purpose at
# scaffold time — Tier1TariffStubAdapter is a template, not a runnable source,
# until Phase 0 reconnaissance fills in a real target.
ADAPTERS: list[SourceAdapter] = []


def main() -> None:
    if not ADAPTERS:
        print("No adapters registered yet. Add one in scripts/run_collection.py "
              "once Phase 0 reconnaissance confirms a real Tier-1 target.")
        return

    for adapter in ADAPTERS:
        result = adapter.run()
        with get_session() as session:
            session.add(
                CollectionRun(
                    run_id=uuid.uuid4(),
                    source=result.source,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    status=result.status,
                    config_hash=result.config_hash,
                    selector_relocated=result.selector_relocated,
                    notes=result.error,
                )
            )
            session.commit()
        print(f"{result.source}: {result.status} ({len(result.quotes)} quotes)")


if __name__ == "__main__":
    main()
