"""Tier 3 — Goibibo route pages: the first *offer* prices in the series.

Every row collected before this adapter came from a filed tariff sheet: a
band an airline is required to publish, not a price anyone can buy. Nine days
of it (2026-09-09 to 09-23) moved by exactly zero rupees on all ten routes,
because the source document itself never changed. The headline index needs
offers, and until 2026-09-23 there was no evidence any offer source could be
collected within this project's compliance posture.

The feasibility sweep that day (docs/06) found one. Of the OTA and airline
fare-search surfaces checked, Goibibo's **static route page** is permitted by
its robots.txt, and it server-renders a complete listing into a Next.js data
blob — no JavaScript execution, no session, no search POST. The sweep's other
finding is the constraint this module is shaped by:

**The departure date is Goibibo's choice, not ours.** Every URL carrying a
query string is disallowed (`Disallow: /flights/*?*`), and the dynamic search
path is disallowed outright (`Disallow: /flights/air-*`), so a date cannot be
requested. Measured across the ten basket routes on 2026-09-23, the served
dates ranged from **T+8 to T+88, and differed per route on the same day**.

Consequences, all deliberate:

- The lead time is **recorded as observed**, never rounded to a methodology
  window. `sql/0003` widened the column's CHECK to allow it.
- These rows are **excluded from the headline index by construction**:
  `apix.index.engine.load_observations` aggregates only
  `ADVANCE_PURCHASE_WINDOWS`. Mixing lead times would make a period-to-period
  relative compare different goods. They also carry a distinct `fare_class`.
- The series is therefore a **separate, uncontrolled-lead offer series**
  (operator decision, 2026-09-23). It is useful as a level check against
  filed tariffs and as raw material for the booking-curve work — the first
  comparison already shows filed tariffs are nowhere near offers: Air India
  files ₹2,447 DEL→HYD while the cheapest non-stop offer that day was ₹8,933.

**Non-stop only**, per the product spec in docs/02 §1. The cheapest journey
on a page is often a connection (₹7,857 via Nagpur against ₹8,933 non-stop on
the DEL→HYD fixture), so taking the page's cheapest fare would silently
measure a different product.

What is *not* decomposed: the page gives a total and a base fare, with
everything else as one "Surcharges" lump. UDF, ASF, RCS and GST are therefore
left `None` rather than guessed — the same rule the Air India adapter follows
for absent charges. Zero would assert a measurement nobody made.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from apix.acquisition.base import CollectionResult, SourceAdapter
from apix.acquisition.compliance import PoliteFetcher
from apix.contracts.fare_quote import FareQuote
from apix.settings import settings
from apix.storage.object_store import ObjectStore

CONFIG_HASH = "tier3_goibibo_v1"

# Tagged distinctly so these rows are identifiable as offers with a lead time
# nobody chose. The engine's headline filter does not depend on this tag (it
# filters on the window), but the tag is what makes the rows readable in SQL.
FARE_CLASS = "tier3_offer_uncontrolled_lead"

BASE_URL = "https://www.goibibo.com/flights/{origin}-to-{destination}-flights/"

# Goibibo addresses routes by city slug, not IATA code. Only the five cities
# in config/routes.yaml's placeholder basket, matching the other adapters'
# convention of mirroring that file rather than reading it.
CITY_SLUGS = {
    "DEL": "delhi",
    "BOM": "mumbai",
    "BLR": "bangalore",
    "CCU": "kolkata",
    "HYD": "hyderabad",
}

ROUTE_PAIRS: list[tuple[str, str]] = [
    ("DEL", "BOM"), ("BOM", "DEL"),
    ("DEL", "BLR"), ("BLR", "DEL"),
    ("DEL", "CCU"), ("CCU", "DEL"),
    ("BOM", "BLR"), ("BLR", "BOM"),
    ("DEL", "HYD"), ("HYD", "DEL"),
]

# A served lead time outside this range means the page is showing something
# other than a near-term one-way fare, and the observation is not trustworthy
# as a price quote. Observed range on the first sweep was 8 to 88 days.
MIN_LEAD_DAYS = 0
MAX_LEAD_DAYS = 365

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)
_TAGS_RE = re.compile(r"<[^>]+>")
_AMOUNT_RE = re.compile(r"([\d,]+(?:\.\d+)?)")

# Departure times on the page are local clock times, and every airport in
# the basket is in IST. Attaching it keeps `departure_date` the date a
# passenger would recognise, rather than a UTC date that rolls over for an
# 05:00 IST departure.
IST = timezone(timedelta(hours=5, minutes=30))


class GoibiboPageShapeError(RuntimeError):
    """The page no longer has the shape this parser was written against.

    Raised rather than returning nothing, because "zero offers today" and
    "the site was rebuilt" must not look the same in the series.
    """


def _text(html_fragment: str | None) -> str:
    return _TAGS_RE.sub("", html_fragment or "").replace("₹", "").strip()


def _amount(html_fragment: str | None) -> Decimal | None:
    match = _AMOUNT_RE.search(_text(html_fragment))
    return Decimal(match.group(1).replace(",", "")) if match else None


def _segments(journey: dict) -> list[tuple[str, str, datetime | None, str]]:
    """Parse `journeyKeys` into (origin, destination, departure, flight).

    A key looks like:
        DEL$HYD$2026-10-23 07:10$6E-203
    joined by `|` for a connection:
        DEL$NAG$2026-10-23 16:30$6E-6433|NAG$HYD$2026-10-23 20:15$6E-7695
    """
    keys = journey.get("journeyKeys") or []
    if not keys or not isinstance(keys[0], str):
        return []
    out = []
    for leg in keys[0].split("|"):
        parts = leg.split("$")
        if len(parts) < 4:
            return []
        try:
            departs = datetime.strptime(parts[2], "%Y-%m-%d %H:%M").replace(tzinfo=IST)
        except ValueError:
            departs = None
        out.append((parts[0], parts[1], departs, parts[3]))
    return out


def _base_fare(journey: dict) -> Decimal | None:
    items = (journey.get("fareBreakup") or {}).get("fareBreakUpItems") or []
    for item in items:
        if "base fare" in _text(item.get("text")).lower():
            return _amount(item.get("amount"))
    return None


def parse_offer_page(
    payload: bytes,
    *,
    origin: str,
    destination: str,
    collection_ts: datetime,
    raw_payload_hash: str,
) -> tuple[FareQuote | None, list[str]]:
    """The cheapest non-stop offer on one route page, or None with a reason.

    Pure: no network, no clock, no store. `collection_ts` is passed in so the
    lead time is measured against the moment of the fetch (the Phase-1 defect
    in tier1_indigo.py was exactly this going wrong).
    """
    blob = extract_next_data(payload)
    try:
        listing = blob["props"]["pageProps"]["data"]["state"]["listing"]
        groups = listing["journeys"]["allJourneys"]
    except (KeyError, TypeError) as exc:
        raise GoibiboPageShapeError(f"listing.journeys.allJourneys not found: {exc}") from exc

    warnings: list[str] = []
    journeys = [j for group in groups for j in group]
    if not journeys:
        return None, [f"{origin}->{destination}: page served no journeys"]

    # Goibibo searches by *city*, and Delhi and Mumbai each have more than one
    # airport: DXN (Noida), HDO (Hindon), NMI (Navi Mumbai) all appear under a
    # DEL or BOM page. The basket in config/routes.yaml is keyed on airport
    # pairs, and `route` rows are too, so those journeys belong to a different
    # series and are skipped -- silently, because on a normal day most of a
    # page is other airports and connections. Only a route that ends up with
    # no quote at all is worth a human's attention.
    other_airports: list[str] = []
    connections = 0
    best: tuple[Decimal, dict, datetime] | None = None
    for journey in journeys:
        segments = _segments(journey)
        if len(segments) != 1:
            connections += 1
            continue  # a connection is a different product (docs/02 §1)
        seg_origin, seg_destination, departs, _flight = segments[0]
        if seg_origin != origin or seg_destination != destination:
            other_airports.append(f"{seg_origin}->{seg_destination}")
            continue
        fare = journey.get("fare")
        if not isinstance(fare, (int, float)) or fare <= 0 or departs is None:
            continue
        if best is None or Decimal(str(fare)) < best[0]:
            best = (Decimal(str(fare)), journey, departs)

    if best is None:
        detail = f"{len(journeys)} journeys: {connections} connections"
        if other_airports:
            shown = sorted(set(other_airports))[:3]
            detail += f", {len(other_airports)} for other airports ({', '.join(shown)})"
        return None, warnings + [
            f"{origin}->{destination}: no non-stop journey for this airport pair ({detail})"
        ]

    total_fare, journey, departs = best
    lead_days = (departs.date() - collection_ts.astimezone(UTC).date()).days
    if not MIN_LEAD_DAYS <= lead_days <= MAX_LEAD_DAYS:
        return None, warnings + [
            (
                f"{origin}->{destination}: implausible lead time {lead_days}d "
                f"(departure {departs.date()}), not recorded"
            )
        ]

    carrier = (journey.get("airlineCodes") or [""])[0] or _segments(journey)[0][3].split("-")[0]
    quote = FareQuote(
        source=Tier3GoibiboOffersAdapter.name,
        carrier=carrier,
        origin=origin,
        destination=destination,
        departure_date=departs.date(),
        collection_ts=collection_ts,
        advance_purchase_days=lead_days,
        fare_class=FARE_CLASS,
        is_nonstop=True,
        base_fare=_base_fare(journey),
        # The page publishes one undecomposed "Surcharges" figure. Leaving the
        # component columns None keeps "not measured" distinct from "zero".
        total_fare=total_fare,
        observation_status="observed",
        raw_payload_hash=raw_payload_hash,
    )
    return quote, warnings


def extract_next_data(payload: bytes) -> dict:
    """Pull the Next.js state blob out of a route page."""
    html = payload.decode("utf-8", errors="replace")
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise GoibiboPageShapeError(
            "__NEXT_DATA__ script not found — the page is no longer server-rendered "
            "in the shape this adapter parses"
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GoibiboPageShapeError(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc


class Tier3GoibiboOffersAdapter(SourceAdapter):
    """One request per route per run, through the production PoliteFetcher."""

    name = "tier3_goibibo_offers"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.store = ObjectStore(settings.raw_store_path)
        # One PoliteFetcher per adapter instance: robots.txt is re-checked per
        # run (docs/01), and the RateLimiter spaces the ten route fetches.
        self.fetcher = fetcher or PoliteFetcher()

    def url_for(self, origin: str, destination: str) -> str:
        return BASE_URL.format(origin=CITY_SLUGS[origin], destination=CITY_SLUGS[destination])

    def fetch_and_parse(self) -> CollectionResult:
        quotes: list[FareQuote] = []
        warnings: list[str] = []
        robots_checked_at: datetime | None = None
        failures = 0

        for origin, destination in ROUTE_PAIRS:
            url = self.url_for(origin, destination)
            try:
                fetched = self.fetcher.get(url, settings.apix_user_agent)
                robots_checked_at = fetched.robots.checked_at or robots_checked_at
                collection_ts = datetime.now(UTC)
                # Stored evidence is the state blob, not the ~2 MB page: it is
                # what the numbers are actually read from, and the full HTML
                # would be ~7 GB a year for a payload that is mostly markup.
                blob = _NEXT_DATA_RE.search(fetched.body.decode("utf-8", errors="replace"))
                put = self.store.put((blob.group(1) if blob else "").encode("utf-8"))
                quote, route_warnings = parse_offer_page(
                    fetched.body,
                    origin=origin,
                    destination=destination,
                    collection_ts=collection_ts,
                    raw_payload_hash=put.content_hash,
                )
            except Exception as exc:  # noqa: BLE001 - one route must not end the run
                failures += 1
                warnings.append(f"{origin}->{destination}: {type(exc).__name__}: {exc}")
                continue

            warnings.extend(route_warnings)
            if quote is not None:
                quotes.append(quote)

        if failures == len(ROUTE_PAIRS):
            return CollectionResult(
                source=self.name,
                config_hash=CONFIG_HASH,
                error=f"every route failed; first: {warnings[0] if warnings else 'unknown'}",
                robots_checked_at=robots_checked_at,
            )

        return CollectionResult(
            source=self.name,
            config_hash=CONFIG_HASH,
            quotes=quotes,
            robots_checked_at=robots_checked_at,
            warnings=warnings,
        )


def lead_days_for(quote: FareQuote, today: date) -> int:
    """Convenience for analysis scripts: the lead time as of a given day."""
    return (quote.departure_date - today).days
