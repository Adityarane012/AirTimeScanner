"""The registry of sources the collector runs, and how each one is treated.

Lives in the package rather than in scripts/run_collection.py because two
entrypoints need the same answer: the collector, to decide how often to try
each source, and scripts/check_collection.py, to decide whose missed days are
news. Kept in one place so the two cannot disagree about which failures are
expected.
"""

from __future__ import annotations

from dataclasses import dataclass

from apix.acquisition.base import SourceAdapter
from apix.acquisition.tier1_air_india import Tier1AirIndiaTariffAdapter
from apix.acquisition.tier1_indigo import Tier1IndiGoTariffAdapter

# Retries per UTC day for a source that is meant to be collecting. Enough to
# ride out a network that is not up yet straight after boot; few enough that a
# source failing for a real reason is not re-fetched all day.
MAX_ATTEMPTS_PER_DAY = 3


@dataclass(frozen=True)
class ScheduledSource:
    adapter: SourceAdapter
    # A tripwire is expected to fail. It exists to notice when that changes, so
    # one attempt a day is its whole job, and its failure is not news: no
    # alerts, and it never counts as stale.
    tripwire: bool = False

    @property
    def name(self) -> str:
        return self.adapter.name

    @property
    def max_attempts_per_day(self) -> int:
        return 1 if self.tripwire else MAX_ATTEMPTS_PER_DAY


def scheduled_sources() -> list[ScheduledSource]:
    """A fresh registry. Built per call, not at import, because each adapter
    owns a PoliteFetcher and docs/01 requires robots.txt to be re-checked per
    run; a module-level singleton would quietly share one across runs.
    """
    return [
        # IndiGo stays registered although its source is robots.txt-disallowed
        # and it fails cleanly every day: that daily robots.txt fetch is the
        # cheapest way to notice if the `*.pdf` rule ever changes. See
        # docs/06-recon-log.md.
        ScheduledSource(Tier1IndiGoTariffAdapter(), tripwire=True),
        ScheduledSource(Tier1AirIndiaTariffAdapter()),
    ]
