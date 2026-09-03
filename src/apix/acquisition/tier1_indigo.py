"""Real Tier-1 adapter: IndiGo's published tariff sheet (Rule 135(2), Aircraft
Rules 1937 / DGCA ATC 02 of 2010). First real adapter in the project — see
docs/06-recon-log.md for the live compliance verification (robots.txt, T&C,
the actual fetch) done before this was written, and pdf_tariff.py's docstring
for the document structure this depends on.

Honest scope of what this adapter actually produces, stated up front because
it matters for how Phase 3's index engine must treat these rows:

- The tariff sheet gives a **filed floor fare per city-pair**, not a live
  offer for a specific departure date. `total_fare` here is the lowest
  non-NA bucket in the "Minimum" row of the "ONE WAY ECONOMY FARES" section
  — a ceiling/floor band, not an availability-adjusted quote.
- The band applies **symmetrically to both directions** (confirmed: no
  reverse-direction row exists anywhere in the 68-page document). So the
  same value is emitted for both directional routes in our basket that share
  this city pair (e.g. DEL->HYD and HYD->DEL both get IndiGo's Delhi-
  Hyderabad floor fare) — this is real data, not fabricated, but it cannot
  by itself establish the directional asymmetry docs/02 says the live index
  needs. Tier 3 sources are what eventually supply that.
- `departure_date`/`advance_purchase_days` are a stated convention, not
  data in the source: the tariff sheet isn't tied to a specific departure
  date, so this adapter anchors it to `collection_ts + 30 days` /
  `advance_purchase_days=30`. Flagged via `fare_class="tier1_tariff_floor"`
  so downstream code can tell these apart from real Tier-3 offer quotes —
  never treat these as the live headline series without that filter.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from scrapling.fetchers import Fetcher

from apix.acquisition.base import CollectionResult, SourceAdapter
from apix.acquisition.pdf_tariff import (
    CITY_TO_IATA,
    TARGET_SECTION_HEADER,
    lowest_filed_fare,
    parse_tariff_sections,
)
from apix.contracts.fare_quote import FareQuote
from apix.settings import settings
from apix.storage.object_store import ObjectStore

CONFIG_HASH = "tier1_indigo_v1"

# Fixed for Phase 1 (matches config/routes.yaml's current placeholder basket).
# Extend once Phase 2 loads the real DGCA-weighted basket.
TARGET_CITY_PAIRS = [("Delhi", "Hyderabad")]

TARIFF_URL = "https://www.goindigo.in/content/dam/s6web/in/en/assets/documents/IndiGo-Tariff-Sheet-2026-05-08.pdf"


class Tier1IndiGoTariffAdapter(SourceAdapter):
    name = "tier1_indigo_tariff"

    def __init__(self) -> None:
        self.store = ObjectStore(settings.raw_store_path)

    def fetch_and_parse(self) -> CollectionResult:
        response = Fetcher.get(
            TARIFF_URL,
            impersonate="chrome",
            headers={"User-Agent": settings.apix_user_agent},
        )
        put = self.store.put(response.body)

        try:
            quotes = self._parse(response.body, raw_payload_hash=put.content_hash)
        except Exception as exc:  # isolation boundary — never let a parse bug take down the run
            return CollectionResult(source=self.name, config_hash=CONFIG_HASH, error=str(exc))

        return CollectionResult(source=self.name, config_hash=CONFIG_HASH, quotes=quotes)

    def _parse(self, pdf_bytes: bytes, raw_payload_hash: str) -> list[FareQuote]:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            issue_line = (pdf.pages[0].extract_text() or "").split("\n")[0].strip()
            pages_text = [p.extract_text() or "" for p in pdf.pages]

        collection_ts = self._parse_issue_timestamp(issue_line)
        departure_date = (collection_ts + timedelta(days=30)).date()

        sections = parse_tariff_sections(pages_text)
        economy_rows = sections.get(TARGET_SECTION_HEADER, [])
        if not economy_rows:
            raise ValueError(f"'{TARGET_SECTION_HEADER}' section not found — document structure may have changed")

        quotes: list[FareQuote] = []
        for origin_city, dest_city in TARGET_CITY_PAIRS:
            fare = lowest_filed_fare(economy_rows, origin_city, dest_city)
            if fare is None:
                continue  # route not in this filing — no_service would overclaim; just skip
            origin_iata = CITY_TO_IATA.get(origin_city)
            dest_iata = CITY_TO_IATA.get(dest_city)
            if not origin_iata or not dest_iata:
                continue

            # Symmetric band -> emit for both directions in our basket, honestly labeled.
            for o, d in [(origin_iata, dest_iata), (dest_iata, origin_iata)]:
                quotes.append(
                    FareQuote(
                        source=self.name,
                        carrier="6E",
                        origin=o,
                        destination=d,
                        departure_date=departure_date,
                        collection_ts=collection_ts,
                        advance_purchase_days=30,
                        fare_class="tier1_tariff_floor",
                        is_nonstop=True,  # assumption — the tariff sheet doesn't state stops
                        total_fare=fare,
                        observation_status="observed",
                        raw_payload_hash=raw_payload_hash,
                    )
                )
        return quotes

    @staticmethod
    def _parse_issue_timestamp(line: str) -> datetime:
        # Observed format: "2026−05−08 15:29:02.126928" (MINUS SIGN date separator)
        normalized = line.replace("−", "-")
        try:
            dt = datetime.strptime(normalized.split(".")[0], "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)
