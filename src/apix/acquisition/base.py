"""The one interface every source adapter implements — docs/03-architecture.md
"Adapter isolation" is the single most important structural decision in the
project: an adapter failure is caught, reason-coded, and never propagates.
Adding a source is adding one file plus a fixture set; nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from apix.contracts.fare_quote import FareQuote


@dataclass
class CollectionResult:
    source: str
    config_hash: str
    quotes: list[FareQuote] = field(default_factory=list)
    selector_relocated: bool = False
    error: str | None = None
    # docs/01 requires robots.txt to be re-checked on every run; recording
    # *when* is what makes that auditable rather than merely claimed. Persisted
    # to collection_run.robots_checked_at.
    robots_checked_at: datetime | None = None
    # Publication timestamp of the source document itself, where the source
    # states one. Deliberately NOT the same thing as a quote's collection_ts
    # (see the Phase-1 defect note in tier1_indigo.py): a monthly-updated
    # tariff sheet has one issue date and many collection dates.
    source_document_ts: datetime | None = None
    # Non-fatal conditions worth a human's attention — a stale source document,
    # a route missing from the filing. Persisted to collection_run.notes so a
    # degraded run is visible without being silently counted as a clean one.
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.error:
            return "failed"
        if self.selector_relocated:
            return "partial"  # quarantined — see the adaptive-selector rule
        if self.warnings:
            return "partial"
        return "succeeded"

    @property
    def notes(self) -> str | None:
        """What goes in collection_run.notes: the error if it failed, else any
        warnings, else nothing."""
        if self.error:
            return self.error
        if self.warnings:
            return "; ".join(self.warnings)
        return None


class SourceAdapter(ABC):
    """One adapter = one source. Must never raise past `run()` — catch
    everything internally and return a CollectionResult with `error` set.
    The orchestrator (scripts/run_collection.py) relies on that contract to
    guarantee one adapter's failure can never take down the whole run.
    """

    name: str

    @abstractmethod
    def fetch_and_parse(self) -> CollectionResult:
        """Fetch this source's targets for the current run and parse them into
        FareQuote objects. Must record `raw_payload_hash` for every observed
        quote (write through apix.storage.object_store first) — this is the
        audit-trail requirement, not optional.
        """
        raise NotImplementedError

    def run(self) -> CollectionResult:
        try:
            return self.fetch_and_parse()
        except Exception as exc:  # noqa: BLE001 - isolation boundary, intentional
            return CollectionResult(source=self.name, config_hash="unknown", error=str(exc))
