"""The one interface every source adapter implements — docs/03-architecture.md
"Adapter isolation" is the single most important structural decision in the
project: an adapter failure is caught, reason-coded, and never propagates.
Adding a source is adding one file plus a fixture set; nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from apix.contracts.fare_quote import FareQuote


@dataclass
class CollectionResult:
    source: str
    config_hash: str
    quotes: list[FareQuote] = field(default_factory=list)
    selector_relocated: bool = False
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "failed"
        if self.selector_relocated:
            return "partial"  # quarantined — see the adaptive-selector rule
        return "succeeded"


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
