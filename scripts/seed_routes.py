"""Load config/routes.yaml into the `route` table. Idempotent (upsert on
origin+destination). Run after applying scripts/sql/0001_init.sql.

    python scripts/seed_routes.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apix.db.engine import get_session  # noqa: E402
from apix.db.models import Route  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "routes.yaml"


def main() -> None:
    data = yaml.safe_load(CONFIG_PATH.read_text())
    with get_session() as session:
        for r in data["routes"]:
            existing = session.execute(
                select(Route).where(Route.origin == r["origin"], Route.destination == r["destination"])
            ).scalar_one_or_none()
            if existing:
                existing.stratum_class = r["stratum_class"]
                continue
            session.add(
                Route(
                    origin=r["origin"],
                    destination=r["destination"],
                    direction=f"{r['origin']}->{r['destination']}",
                    stratum_class=r["stratum_class"],
                    active=True,
                    created_at=datetime.now(timezone.utc),
                )
            )
        session.commit()
    print(f"Seeded {len(data['routes'])} routes from {CONFIG_PATH.name}")


if __name__ == "__main__":
    main()
