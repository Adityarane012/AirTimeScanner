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
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

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
        response = Fetcher.get(
            self.target_url,
            headers={"User-Agent": settings.apix_user_agent},
            adaptive=True,
        )
        payload = response.body if hasattr(response, "body") else str(response).encode()
        put = self.store.put(payload)

        quotes = self._parse_response(response, raw_payload_hash=put.content_hash)

        return CollectionResult(
            source=self.name,
            config_hash=CONFIG_HASH,
            quotes=quotes,
            selector_relocated=getattr(response, "adaptive_relocated", False),
        )

    def _parse_response(self, response, raw_payload_hash: str) -> list[FareQuote]:
        """TODO(Phase 0/1): real selectors go here once the target page is known.

        Left unimplemented on purpose — a fabricated selector against a page
        that doesn't exist would be worse than an honest NotImplementedError.
        """
        raise NotImplementedError(
            "Fill in _parse_response() once a real Tier-1 tariff-sheet URL and "
            "page structure have been confirmed in Phase 0 reconnaissance."
        )


def _content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
