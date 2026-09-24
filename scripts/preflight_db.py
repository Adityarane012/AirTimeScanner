"""Can this machine reach the database? Answer before fetching anything.

On a laptop, a collection run that cannot reach the database is still worth
making: `apix.ops.spool` keeps the observation on disk and the next run
uploads it. The fetch is the irreplaceable part.

**On an ephemeral runner that reasoning inverts.** A GitHub Actions container
is deleted when the job ends, so a spooled run there is not "waiting to
upload", it is about to be destroyed. Fetching first and discovering that
afterwards is the worst of both worlds: ten OTA page requests made for
nothing, which is exactly the load docs/01's politeness posture exists to
avoid, and a job that reports lost observations that were never at risk.
That happened on both scheduled runs of 2026-09-23.

So CI runs this first, and stops the job if the answer is no. Exit codes:

    0  reachable
    1  not reachable (the reason is printed, and emitted as a GitHub
       annotation so it is visible without opening the log)

The failure message names the **host and username but never the password**,
because the annotation is public on a public repository — and a wrong host is
the likeliest cause of the failure it is diagnosing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from apix.settings import settings


def describe_target(database_url: str) -> str:
    """Host, port and username — never the password.

    Supabase publishes two connection strings and they fail differently:
    `db.<ref>.supabase.co` has an AAAA record only, so it cannot be resolved
    at all from an IPv4-only network such as a GitHub runner, while
    `aws-N-<region>.pooler.supabase.com` has A records. Naming the host turns
    that from a mystery into a one-line fix.
    """
    try:
        url = make_url(database_url)
    except Exception:  # noqa: BLE001 - a malformed URL must not leak its contents
        return "<unparseable DATABASE_URL>"
    return f"{url.host}:{url.port} as {url.username} (database {url.database})"


def main() -> int:
    target = describe_target(settings.database_url)
    print(f"database target: {target}")

    if ".pooler.supabase.com" not in (settings.database_url or ""):
        print(
            "note: this is not a Supabase session pooler host. On an IPv4-only "
            "runner the direct db.<ref>.supabase.co host cannot be resolved."
        )

    try:
        from apix.db.engine import get_session

        with get_session() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        reason = str(getattr(exc, "orig", exc)).strip().splitlines()[0]
        print(f"::error::Database unreachable at {target} — {reason}")
        print("Nothing was fetched. Fix DATABASE_URL (use the session pooler URL).")
        return 1

    print("database reachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
