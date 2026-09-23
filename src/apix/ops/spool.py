"""Write-ahead spool for collection results, so an unreachable database never
costs a day.

The series is wall-clock bound: a day that is not *fetched* on that day is
gone. A day that is fetched but not yet *written to the database* is not; it
only needs uploading. Until 2026-09-15 the collector conflated the two. It
queried the database before fetching anything, so every run on a network that
could not reach Supabase died before touching the source. Nine runs failed
that way on 09-15, on a campus Wi-Fi that has no IPv6 (the direct Supabase host
is IPv6-only) and also drops ports 5432 and 6543 (so the IPv4 pooler does not
help there either). The day survived only because an earlier run on a phone
hotspot had already collected it.

Now every run's result is written here first, as one JSON file, before any
database write is attempted:

    <spool>/pending/  written, not yet in the database
    <spool>/sent/     in the database; kept a while as a local record of
                      today's runs, which is what lets the collector decide
                      "already collected today" while offline

Uploading is idempotent (collection_run by run_id, fare_quote by the daily
observation index in sql/0002), so a crash between the database commit and the
move to sent/ just re-uploads and finds nothing to write.

File operations only; the database side lives in scripts/run_collection.py.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from apix.contracts.fare_quote import FareQuote

# Sent files older than this are deleted. Only today's are needed to make the
# offline skip decision; the rest are a short local audit trail.
KEEP_SENT_DAYS = 14


@dataclass(frozen=True)
class SpooledRun:
    """One collection run: the future collection_run row plus its quotes."""

    run_id: uuid.UUID
    source: str
    started_at: datetime
    finished_at: datetime
    status: str
    config_hash: str
    robots_checked_at: datetime | None = None
    selector_relocated: bool = False
    notes: str | None = None
    quotes: list[FareQuote] = field(default_factory=list)

    @property
    def utc_day(self) -> date:
        return self.started_at.astimezone(UTC).date()

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": str(self.run_id),
                "source": self.source,
                "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat(),
                "status": self.status,
                "config_hash": self.config_hash,
                "robots_checked_at": (
                    self.robots_checked_at.isoformat() if self.robots_checked_at else None
                ),
                "selector_relocated": self.selector_relocated,
                "notes": self.notes,
                # mode="json" writes Decimals as strings, so fares round-trip
                # exactly rather than through float.
                "quotes": [q.model_dump(mode="json") for q in self.quotes],
            },
            indent=1,
        )

    @classmethod
    def from_json(cls, text: str) -> SpooledRun:
        d = json.loads(text)
        return cls(
            run_id=uuid.UUID(d["run_id"]),
            source=d["source"],
            started_at=datetime.fromisoformat(d["started_at"]),
            finished_at=datetime.fromisoformat(d["finished_at"]),
            status=d["status"],
            config_hash=d["config_hash"],
            robots_checked_at=(
                datetime.fromisoformat(d["robots_checked_at"]) if d["robots_checked_at"] else None
            ),
            selector_relocated=d["selector_relocated"],
            notes=d["notes"],
            quotes=[FareQuote.model_validate(q) for q in d["quotes"]],
        )


class Spool:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pending_dir = root / "pending"
        self.sent_dir = root / "sent"
        self._alert_marker = root / "overdue_alerted_on"

    def first_alert_today(self, today: date) -> bool:
        """True once per UTC day, so an hourly collector raises the overdue
        alert daily rather than hourly."""
        try:
            if self._alert_marker.read_text(encoding="utf-8").strip() == today.isoformat():
                return False
        except OSError:
            pass
        self.root.mkdir(parents=True, exist_ok=True)
        self._alert_marker.write_text(today.isoformat(), encoding="utf-8")
        return True

    def write(self, run: SpooledRun) -> Path:
        """Durably record a run as pending. Atomic: a crash mid-write leaves a
        .tmp file that is never read, not a truncated JSON file that is."""
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        stamp = run.started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.pending_dir / f"{stamp}_{run.source}_{run.run_id.hex[:8]}.json"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(run.to_json())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return path

    def pending(self) -> list[tuple[Path, SpooledRun]]:
        """Pending runs, oldest first (file names sort by start time)."""
        return self._read(self.pending_dir)

    def mark_sent(self, path: Path) -> None:
        self.sent_dir.mkdir(parents=True, exist_ok=True)
        os.replace(path, self.sent_dir / path.name)

    def records(self, source: str) -> list[tuple[date, str]]:
        """Every spooled run of `source` still on disk, uploaded or not, as
        (utc_day, status). The local stand-in for the collection_run table."""
        return [
            (run.utc_day, run.status)
            for directory in (self.sent_dir, self.pending_dir)
            for _, run in self._read(directory)
            if run.source == source
        ]

    def statuses_on(self, source: str, day: date) -> list[str]:
        """Statuses of every spooled run of `source` on a UTC day, uploaded or
        not. Stands in for the database's view of today while offline."""
        return [status for utc_day, status in self.records(source) if utc_day == day]

    def prune_sent(self, today: date, keep_days: int = KEEP_SENT_DAYS) -> int:
        """Delete sent files older than `keep_days`. Never touches pending."""
        cutoff = today - timedelta(days=keep_days)
        removed = 0
        for path, run in self._read(self.sent_dir):
            if run.utc_day < cutoff:
                path.unlink()
                removed += 1
        return removed

    @staticmethod
    def _read(directory: Path) -> list[tuple[Path, SpooledRun]]:
        if not directory.is_dir():
            return []
        return [
            (path, SpooledRun.from_json(path.read_text(encoding="utf-8")))
            for path in sorted(directory.glob("*.json"))
        ]


def overdue_upload_alert(pending: list[SpooledRun], today: date) -> str | None:
    """A message if runs from before today are still waiting to upload.

    Nothing is lost while runs sit in pending/, so a single offline day is not
    news. Pending runs from an earlier day are: whatever blocks the upload has
    outlasted a network change, and "unreachable" includes things that will
    never fix themselves, such as a rotated database password.
    """
    overdue = [run for run in pending if run.utc_day < today]
    if not overdue:
        return None
    oldest = min(run.utc_day for run in overdue)
    return (
        f"{len(overdue)} collection run(s) since {oldest} are saved locally but still "
        f"not uploaded: the database has been unreachable since then. Nothing is lost "
        f"yet; check DATABASE_URL and the network."
    )
