"""Real Tier-1 adapter: Air India's domestic tariff sheet (Rule 135(2),
Aircraft Rules 1937 / DGCA ATC 02 of 2010). The second real adapter, and the
first source that can support docs/02 §2's base-fare and tax-wedge
sub-indices — IndiGo publishes one number, Air India publishes the
decomposition.

Parsing lives in `ai_tariff.py`; this module is the adapter around it —
compliance, timestamps, route selection and the fare *construction* rule.

## What this adapter emits, stated up front

- A **filed base fare per city-pair**, not a live offer. `base_fare` is Level 1
  of the "Minimum" band row — the lowest filed level, the closest a filed
  sheet gets to docs/02 §1's "lowest available total fare".
- `total_fare` is **constructed**, not read: the sheet gives base fares on one
  page and a charge schedule on another, and states the construction rule
  itself ("Total Fare comprises of Base Fare (Page I) plus Tax/Fee/Charge
  (Page II) and applicable GST"). See "The GST base" below — that rule is not
  fully determined by the document, so the choice is recorded here rather than
  buried in an expression.
- Like IndiGo's sheet, the base fare is filed **"Market & V.V."** — one row per
  city pair, applying to both directions. Unlike IndiGo's, the *charges* are
  directional: UDF is levied at the departure airport and the arrival tax at
  the destination. So DEL->BOM and BOM->DEL share a base fare but carry
  genuinely different totals. That asymmetry is real, filed data — it is still
  not a substitute for the directional *offer* prices Tier 3 must supply.
- `departure_date`/`advance_purchase_days` are a stated convention, not data:
  a filed tariff is not tied to a departure date, so this anchors to
  `collection_ts + 30 days`, matching `tier1_indigo.py`.

## The GST base (an operator decision, taken 2026-09-09)

The sheet says GST is "(a) in Economy 5% ... on Base Fare & YR". Whether the
pass-through airport charges (UDF, ASF) sit inside or outside that base is
genuinely ambiguous in the source, and the reading moves the index **level** by
roughly 2%. It largely cancels in the period-to-period relatives docs/02 §3
validates against, so it is not fatal either way — but it must be a stated
rule.

**The rule in force:** GST applies to base fare + UDF + ASF + RCS + CUTE, and
*not* to the fuel surcharge (YQ). Chosen by the operator over the narrower
literal reading.

**The alternative reading**, for whoever revisits this: "on Base Fare & YR"
taken literally means base + RCS + CUTE only, with UDF and ASF outside the
taxable base. For DEL->HYD that is GST 71 against 90, and a total of ~2428
against ~2447. If it is ever changed, `CONFIG_HASH` must be bumped — the
index engine's vintage stamping is what makes a methodology change visible
instead of silent.

## Charge applicability is not modelled, and today that is safe

ASF and RCS are filed against explicit airport lists, and RCS carries an
exemption list (north-east and J&K stations). `ai_tariff.TaxSchedule` holds
each as a single scalar. Verified against the 15JUN26 sheet: every city in the
current basket (Delhi, Mumbai, Bengaluru, Kolkata, Hyderabad) appears in both
the ASF and RCS "From" lists and none appears in the RCS exemption list, so a
scalar is correct here. **Re-verify when the basket grows** — a station on the
exemption list would be over-charged by RCS_EXEMPT_RISK rupees.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from apix.acquisition.ai_tariff import (
    ECONOMY_GST_RATE,
    AirIndiaFareRow,
    TaxSchedule,
    parse_base_fares,
    parse_tax_schedule,
)
from apix.acquisition.base import CollectionResult, SourceAdapter
from apix.acquisition.compliance import PoliteFetcher
from apix.acquisition.pdf_tariff import CITY_TO_IATA
from apix.contracts.fare_quote import FareQuote
from apix.settings import settings
from apix.storage.object_store import ObjectStore

CONFIG_HASH = "tier1_air_india_v1"

TARIFF_URL = (
    "https://www.airindia.com/content/dam/air-india/pdfs/tariff/TARIFF-SHEET-AS-ON-15JUN26.pdf"
)

# Deliberately NOT tier1_indigo's "tier1_tariff_floor": these rows carry a full
# decomposition and a directional tax wedge, so downstream code must be able to
# tell them apart. Both tags are excluded from the headline index by
# apix.index.engine — a filed band is a filed band, whatever its detail.
FARE_CLASS = "tier1_filed_base_fare"

# Same anchoring convention as the IndiGo adapter, for the same reason.
ANCHOR_ADVANCE_PURCHASE_DAYS = 30

# config/routes.yaml's five city pairs. Order here is irrelevant — the sheet
# files each pair once, in its own order ("Kolkata Delhi", not "Delhi Kolkata"),
# so lookup is direction-insensitive and both directions are emitted.
TARGET_CITY_PAIRS = [
    ("Delhi", "Mumbai"),
    ("Delhi", "Bengaluru"),
    ("Delhi", "Kolkata"),
    ("Delhi", "Hyderabad"),
    ("Mumbai", "Bengaluru"),
]

# The sheet's own city vocabulary, needed by `split_city_pair` to know where a
# multi-word origin ends ("Ahmedabad North Goa"). Derived from the 15JUN26
# sheet by taking every unambiguous two-token row, which resolves all 224
# economy rows with zero skips. Extend when the sheet adds a station — a row
# whose cities are not both in here is *counted*, not silently dropped.
AIR_INDIA_CITIES = frozenset({
    "Ahmedabad", "Amritsar", "Aurangabad", "Bagdogra", "Bengaluru", "Bhopal",
    "Bhubaneswar", "Bhuj", "Chandigarh", "Chennai", "Coimbatore", "Dehradun",
    "Delhi", "Dibrugarh", "Dimapur", "Gaya", "Goa", "Guwahati", "Halwara",
    "Hyderabad", "Imphal", "Indore", "Jaipur", "Jaisalmer", "Jammu",
    "Jamnagar", "Jodhpur", "Khajuraho", "Kochi", "Kolkata", "Kozhikode",
    "Leh", "Lucknow", "Madurai", "Mangalore", "Mumbai", "Nagpur", "North Goa",
    "Patna", "PortBlair", "Pune", "Raipur", "Rajkot", "Ranchi", "Silchar",
    "Srinagar", "Thiruvananthapuram", "Tirupati", "Udaipur", "Vadodara",
    "Varanasi", "Vijayawada", "Vizag",
})

# The 15JUN26 sheet files 28 departure UDF rows. The historical failure mode
# here was silent and specific: the tax-code cell is vertically merged, and
# classifying rows by that label captured exactly ONE airport. A collapse in
# this count means the table structure moved again, so it is checked rather
# than trusted.
MIN_EXPECTED_UDF_ROWS = 20

# Rupees of RCS that would be wrongly added to a station on the sheet's
# exemption list. Named so the module docstring's warning carries a magnitude.
RCS_EXEMPT_RISK = 10

_VALIDITY_RE = re.compile(
    r"period\s+W\.I\.E\.\s+till\s+(?P<day>\d{1,2})\w{0,2}\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

_CREATION_DATE_RE = re.compile(r"D:(?P<stamp>\d{14})(?P<sign>[+-])(?P<oh>\d{2})'(?P<om>\d{2})")


class Tier1AirIndiaTariffAdapter(SourceAdapter):
    name = "tier1_air_india_tariff"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.store = ObjectStore(settings.raw_store_path)
        # One PoliteFetcher per adapter instance == one robots.txt check per
        # run, which is docs/01's "re-checked on every run, not cached
        # indefinitely". Injected so tests never touch the network.
        self.fetcher = fetcher or PoliteFetcher()

    def fetch_and_parse(self) -> CollectionResult:
        fetched = self.fetcher.get(TARIFF_URL, settings.apix_user_agent)
        collection_ts = datetime.now(UTC)
        put = self.store.put(fetched.body)

        try:
            quotes, document_ts, warnings = self._parse(
                fetched.body,
                raw_payload_hash=put.content_hash,
                collection_ts=collection_ts,
            )
        except Exception as exc:  # noqa: BLE001 - isolation boundary; a parse bug must not take down the run
            return CollectionResult(
                source=self.name,
                config_hash=CONFIG_HASH,
                error=str(exc),
                robots_checked_at=fetched.robots.checked_at,
            )

        return CollectionResult(
            source=self.name,
            config_hash=CONFIG_HASH,
            quotes=quotes,
            robots_checked_at=fetched.robots.checked_at,
            source_document_ts=document_ts,
            warnings=warnings,
        )

    def _parse(
        self,
        pdf_bytes: bytes,
        raw_payload_hash: str,
        collection_ts: datetime,
    ) -> tuple[list[FareQuote], datetime | None, list[str]]:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Text for the fare tables, tables for the charge schedule: on the
            # charge page `extract_text()` interleaves the columns into
            # unusable strings (ai_tariff.py hazard 3).
            pages_text = [p.extract_text() or "" for p in pdf.pages]
            tables: list[list[list[str | None]]] = []
            for page in pdf.pages:
                tables.extend(page.extract_tables() or [])
            document_ts = _parse_creation_date(pdf.metadata)

        warnings: list[str] = []

        rows, skipped = parse_base_fares(pages_text, set(AIR_INDIA_CITIES))
        if not rows:
            raise ValueError(
                "no ECONOMY BASE FARE rows parsed — document structure may have changed"
            )
        if skipped:
            warnings.append(
                f"{skipped} economy row(s) had cities outside AIR_INDIA_CITIES and were "
                f"skipped — the sheet has likely added a station; extend the vocabulary"
            )

        validity_end = _parse_validity_end(pages_text[0] if pages_text else "")
        if validity_end is not None and collection_ts.date() > validity_end:
            warnings.append(
                f"tariff sheet expired on {validity_end:%Y-%m-%d} — a superseded filing "
                f"is being collected; find the current sheet on airindia.com"
            )

        quotes, build_warnings = build_quotes(
            source=self.name,
            rows=rows,
            schedule=parse_tax_schedule(tables),
            collection_ts=collection_ts,
            raw_payload_hash=raw_payload_hash,
        )
        return quotes, document_ts, warnings + build_warnings


def build_quotes(
    *,
    source: str,
    rows: list[AirIndiaFareRow],
    schedule: TaxSchedule,
    collection_ts: datetime,
    raw_payload_hash: str,
) -> tuple[list[FareQuote], list[str]]:
    """Turn parsed rows plus a charge schedule into quotes for the basket.

    Split out of `_parse` and kept free of pdfplumber deliberately: the fare
    *construction* rule is the part of this adapter with a methodology
    decision inside it, and IMPLEMENTATION.md §5b's lesson was that the seams
    are where the silent defects lived. This one is testable against the same
    kind of fixtures `test_ai_tariff.py` uses, with no PDF anywhere near it.

    Returns the quotes and any non-fatal warnings. Raises only when the charge
    schedule is structurally unusable — see `_require_charge_schedule`.
    """
    _require_charge_schedule(schedule)

    warnings: list[str] = []
    if len(schedule.udf_by_city) < MIN_EXPECTED_UDF_ROWS:
        warnings.append(
            f"only {len(schedule.udf_by_city)} departure UDF rows parsed "
            f"(expected >= {MIN_EXPECTED_UDF_ROWS}) — the charge table's structure "
            f"has probably moved; totals are understated until this is checked"
        )

    departure_date = (collection_ts + timedelta(days=ANCHOR_ADVANCE_PURCHASE_DAYS)).date()
    quotes: list[FareQuote] = []

    for city_a, city_b in TARGET_CITY_PAIRS:
        row = _find_minimum_row(rows, city_a, city_b)
        if row is None:
            warnings.append(
                f"{city_a}-{city_b} has no Minimum-band economy row in this filing — "
                f"no quote emitted"
            )
            continue

        yq = schedule.fuel_for(row.distance_km)
        if yq is None:
            # The filed bands leave gaps (500 km falls between "Less than 500"
            # and "501 - 1000"). Guessing a neighbouring band would fabricate
            # the largest single charge on the ticket.
            warnings.append(
                f"{city_a}-{city_b}: no filed YQ band covers {row.distance_km} km — "
                f"total fare is not constructible, no quote emitted"
            )
            continue

        for origin_city, dest_city in ((city_a, city_b), (city_b, city_a)):
            origin_iata = CITY_TO_IATA.get(origin_city)
            dest_iata = CITY_TO_IATA.get(dest_city)
            if not origin_iata or not dest_iata:
                warnings.append(
                    f"no IATA mapping for {origin_city} or {dest_city} — extend "
                    f"CITY_TO_IATA; no quote emitted"
                )
                continue

            quotes.append(
                _build_quote(
                    source=source,
                    row=row,
                    schedule=schedule,
                    origin_city=origin_city,
                    origin_iata=origin_iata,
                    dest_iata=dest_iata,
                    yq=yq,
                    collection_ts=collection_ts,
                    departure_date=departure_date,
                    raw_payload_hash=raw_payload_hash,
                )
            )

    return quotes, warnings


def _require_charge_schedule(schedule: TaxSchedule) -> None:
    """ASF, RCS and CUTE apply to every sector in the basket, so a missing one
    is a structural change, not a gap in the data. Failing here is deliberate:
    a total silently short by 236 rupees is worse than no total at all.
    """
    missing = [
        name
        for name, value in (("ASF", schedule.asf), ("RCS", schedule.rcs), ("CUTE", schedule.cute))
        if value is None
    ]
    if missing:
        raise ValueError(
            f"charge schedule is missing {', '.join(missing)} — the Page-II table "
            f"structure has changed; refusing to construct partial totals"
        )


def _find_minimum_row(
    rows: list[AirIndiaFareRow], city_a: str, city_b: str
) -> AirIndiaFareRow | None:
    """The Minimum-band row for a city pair, in either filed order.

    "Market & V.V." means one row covers both directions, and which city the
    sheet lists first is arbitrary — Kolkata-Delhi is filed that way while
    Delhi-Hyderabad is filed the other. Matching on the ordered pair alone
    silently loses routes.
    """
    wanted = {city_a, city_b}
    for row in rows:
        if row.band_type == "Minimum" and {row.origin_city, row.destination_city} == wanted:
            return row
    return None


def gst_and_total(
    base: Decimal, udf: Decimal, asf: Decimal, rcs_and_cute: Decimal, yq: Decimal
) -> tuple[Decimal, Decimal]:
    """The construction rule from the module docstring, as one pure function so
    the methodology choice is testable without a PDF anywhere near it.

    GST base = base + UDF + ASF + RCS + CUTE. YQ sits outside it.
    """
    taxable = base + udf + asf + rcs_and_cute
    gst = (taxable * ECONOMY_GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return gst, taxable + yq + gst


def _build_quote(
    *,
    source: str,
    row: AirIndiaFareRow,
    schedule: TaxSchedule,
    origin_city: str,
    origin_iata: str,
    dest_iata: str,
    yq: Decimal,
    collection_ts: datetime,
    departure_date: date,
    raw_payload_hash: str,
) -> FareQuote:
    base = row.fares[0]  # Level 1 — the lowest filed level of the Minimum band.

    # UDF is two filed components and both are directional: a departure fee at
    # the origin, and the "new Arrival Tax" the sheet marks with an asterisk at
    # seven destinations (IXE, TRV, GOX, DEL, GAU, BOM, JAI). Both sit in the
    # code-IN block, so they are reported together in the `udf` column.
    #
    # A missing departure row reads as *not filed for that airport*, not as
    # unknown: Mumbai has no departure UDF anywhere in the sheet and appears
    # only as an arrival tax, which is a filing choice rather than an omission.
    # The guard against a parse regression is MIN_EXPECTED_UDF_ROWS above,
    # which catches the failure that actually happened — the whole block
    # collapsing to one row — instead of second-guessing each airport.
    udf = (schedule.udf_for(origin_city) or Decimal(0)) + (
        schedule.arrival_by_iata.get(dest_iata) or Decimal(0)
    )

    # RCS and CUTE are both filed under tax code YR, and the sheet's own GST
    # clause refers to "YR" as one bucket. Reported together for that reason:
    # 10 of RCS and 160 of CUTE on the current sheet.
    assert schedule.asf is not None and schedule.rcs is not None and schedule.cute is not None
    rcs_and_cute = schedule.rcs + schedule.cute

    gst, total = gst_and_total(base, udf, schedule.asf, rcs_and_cute, yq)

    return FareQuote(
        source=source,
        carrier="AI",
        origin=origin_iata,
        destination=dest_iata,
        departure_date=departure_date,
        collection_ts=collection_ts,
        advance_purchase_days=ANCHOR_ADVANCE_PURCHASE_DAYS,
        fare_class=FARE_CLASS,
        is_nonstop=True,  # assumption — the tariff sheet doesn't state stops
        base_fare=base,
        udf=udf,
        asf=schedule.asf,
        rcs_levy=rcs_and_cute,
        carrier_charges=yq,  # YQ, the distance-banded fuel surcharge
        gst=gst,
        total_fare=total,
        observation_status="observed",
        raw_payload_hash=raw_payload_hash,
    )


def _parse_creation_date(metadata: dict | None) -> datetime | None:
    """The sheet carries no printed issue timestamp, unlike IndiGo's. Its PDF
    CreationDate is the next best thing and agrees with the dated URL
    ("AS ON 15JUN26"). Returns None rather than falling back to now(): an
    undated sheet must not masquerade as a freshly-issued one.
    """
    raw = (metadata or {}).get("CreationDate")
    if not isinstance(raw, str):
        return None
    match = _CREATION_DATE_RE.match(raw)
    if not match:
        return None
    try:
        naive = datetime.strptime(match.group("stamp"), "%Y%m%d%H%M%S")  # noqa: DTZ007
    except ValueError:
        return None
    offset = timedelta(hours=int(match.group("oh")), minutes=int(match.group("om")))
    if match.group("sign") == "-":
        offset = -offset
    return (naive - offset).replace(tzinfo=UTC)


def _parse_validity_end(first_page_text: str) -> date | None:
    """"Fares for the period W.I.E. till 30th June 2027" -> that date.

    This replaces the IndiGo adapter's issue-age heuristic with the stronger
    check this document actually supports: Air India states an explicit
    validity end, so staleness is a fact rather than an inference from
    republication cadence.
    """
    match = _VALIDITY_RE.search(first_page_text)
    if not match:
        return None
    try:
        return datetime.strptime(  # noqa: DTZ007
            f"{match.group('day')} {match.group('month')[:3]} {match.group('year')}", "%d %b %Y"
        ).date()
    except ValueError:
        return None
