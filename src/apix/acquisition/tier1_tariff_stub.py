"""TEMPLATE Tier-1 adapter — mandated public tariff sheet, one carrier.

This is a worked SKELETON, not a finished adapter: the actual tariff-sheet URL,
page structure, and selectors depend on Phase 0 reconnaissance (see
IMPLEMENTATION.md Day 1) — capture a real response first, then fill in
_parse_response(). Copy this file per carrier once a target URL is confirmed;
one file per source, per docs/03-architecture.md "Adapter isolation".

Probe-before-escalating (docs/03-architecture.md): try `Fetcher` plain, then
`Fetcher(impersonate="chrome")`, before ever reaching for StealthyFetcher.
Tier-1 tariff pages are expected to need neither — they're static disclosure
pages, not booking engines.

Verified against the installed scrapling==0.4.15 API (requires the
`scrapling[fetchers]` extra — see pyproject.toml):

- `adaptive` is NOT a `Fetcher.get()` kwarg (it belongs on `.css()`/`.xpath()`
  calls, matched against a saved `identifier`) — passing it to `.get()` raises
  `TypeError: Session.request() got an unexpected keyword argument 'adaptive'`.
  So: fetch plain, then parse with adaptive selectors.
- There is no `response.adaptive_relocated` flag. Detecting an actual
  relocation event means checking, per selector, whether a prior save exists
  (`response.retrieve(identifier)`) before this run and comparing that saved
  element's content against what `.css(..., adaptive=True)` returns now — see
  `_check_relocation` below. This is adapter-specific logic, not something
  Scrapling hands you as a boolean; keep it, don't fake it.
"""

from __future__ import annotations

from scrapling.fetchers import Fetcher

from apix.acquisition.base import CollectionResult, SourceAdapter
from apix.contracts.fare_quote import FareQuote
from apix.settings import settings
from apix.storage.object_store import ObjectStore

CONFIG_HASH = "tier1_tariff_stub_v0"  # bump when selectors or logic change


class Tier1TariffStubAdapter(SourceAdapter):
    name = "tier1_tariff_stub"

    # TODO(Phase 0): replace with the carrier's actual published tariff-sheet URL
    # (Rule 135(2), Aircraft Rules 1937 / DGCA ATC 02 of 2010 mandates one exists).
    target_url = "https://example-airline.invalid/tariff-sheet"

    def __init__(self) -> None:
        self.store = ObjectStore(settings.raw_store_path)

    def fetch_and_parse(self) -> CollectionResult:
        # No `adaptive=` here — that's a parse-time concern, not a fetch-time one.
        response = Fetcher.get(self.target_url, headers={"User-Agent": settings.apix_user_agent})
        put = self.store.put(response.body)

        quotes, relocated = self._parse_response(response, raw_payload_hash=put.content_hash)

        return CollectionResult(
            source=self.name,
            config_hash=CONFIG_HASH,
            quotes=quotes,
            selector_relocated=relocated,
        )

    def _parse_response(self, response, raw_payload_hash: str) -> tuple[list[FareQuote], bool]:
        """TODO(Phase 0/1): real selectors go here once the target page is known.

        Left unimplemented on purpose — a fabricated selector against a page
        that doesn't exist would be worse than an honest NotImplementedError.

        Worked pattern once a real selector exists (e.g. `.fare-row .price`):

            identifier = "fare_row_price"
            had_prior_save = response.retrieve(identifier) is not None
            elements = response.css(".fare-row .price", identifier=identifier,
                                     adaptive=True, auto_save=True)
            relocated = had_prior_save and self._check_relocation(response, identifier, elements)

        Return (quotes, relocated) — `relocated=True` triggers the quarantine
        rule in docs/03-architecture.md: the run is written as
        `collection_failed`, never enters the index build unreviewed.
        """
        raise NotImplementedError(
            "Fill in _parse_response() once a real Tier-1 tariff-sheet URL and "
            "page structure have been confirmed in Phase 0 reconnaissance."
        )

    @staticmethod
    def _check_relocation(response, identifier: str, elements) -> bool:
        """True if this run's adaptive match landed on a materially different
        element than what was saved for `identifier` last run — i.e. the page
        changed shape and Scrapling silently re-targeted. Compare on element
        tag + attributes, not exact text (text is expected to change; the
        DOM position/identity is what "relocation" means).
        """
        saved = response.retrieve(identifier)
        if not saved or not elements:
            return False
        current = elements[0]
        return (saved.get("tag"), saved.get("attributes")) != (
            getattr(current, "tag", None),
            getattr(current, "attrib", None),
        )
