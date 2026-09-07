"""Parser for Air India's domestic tariff sheet.

A separate module from `pdf_tariff.py`, not an extension of it: Air India's
sheet shares no structure with IndiGo's beyond both being PDFs.

    IndiGo                            Air India
    68 pages                          8 pages
    "Agartala − Ajmer" (U+2212)       "Ahmedabad Bengaluru" (separate columns)
    21 fare buckets                   13 fare levels
    total fare only                   BASE fare + a separate tax schedule

The last difference is the important one. IndiGo publishes a single number;
Air India publishes the decomposition docs/02 §2 asks for — base fare, UDF,
ASF, RCS, CUTE and a distance-banded fuel surcharge — and states the
construction rule itself: "Total Fare comprises of Base Fare (Page I) plus
Tax/Fee/Charge (Page II) and applicable GST". That makes it the first source
capable of supporting §2's base-fare and tax-and-fee-wedge sub-indices.

Three extraction hazards, all found in the real document rather than assumed:

1. **Multi-word city names.** "Ahmedabad North Goa 823 Minimum ..." — a
   whitespace split cannot tell where the origin ends. Resolved by matching
   against a known-city vocabulary and requiring exactly one valid split.
2. **Glued tokens.** "Mumbai Thiruvananthapuram1255 Minimum ..." — pdfplumber
   emits no space between a long city name and the distance.
3. **`extract_text()` garbles the tax page.** Its columns interleave
   vertically ("Visak D h e a h p r a a t d n u a n m"). `extract_tables()`
   recovers it cleanly, so the tax schedule is read from tables and the fare
   tables from text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

# Section headers as they appear. Only the economy table feeds the index --
# docs/02 §1 specifies economy cabin.
ECONOMY_SECTION_HEADER = "ECONOMY BASE FARE"

# "1 Ahmedabad Bengaluru 1219 Minimum 1530 3280 ..." -- the distance is the
# integer immediately before Minimum/Maximum, and `\s*` before it tolerates
# hazard 2 (no space after a long city name).
_FARE_ROW_RE = re.compile(
    r"^\s*(?P<sno>\d+)\s+(?P<cities>.+?)\s*(?P<distance>\d+)\s+"
    r"(?P<band_type>Minimum|Maximum)\s+(?P<fares>[\d\s]+)$"
)

# Economy GST, from the sheet: "(a) in Economy 5%". Held here rather than in
# config because it is a statutory rate stated by the source document itself.
ECONOMY_GST_RATE = Decimal("0.05")


@dataclass
class AirIndiaFareRow:
    origin_city: str
    destination_city: str
    distance_km: int
    band_type: str  # "Minimum" | "Maximum"
    fares: list[Decimal]  # Level 1..N, ascending


@dataclass
class TaxSchedule:
    """The Page-II charge schedule, as filed."""

    # User Development Fee, levied at the *departure* airport.
    udf_by_city: dict[str, Decimal] = field(default_factory=dict)
    # Arrival-side charges, keyed by destination IATA (the "All -> DEL*" rows).
    arrival_by_iata: dict[str, Decimal] = field(default_factory=dict)
    asf: Decimal | None = None  # P2, Airport Security Fee
    rcs: Decimal | None = None  # YR, Regional Connectivity Fee
    cute: Decimal | None = None  # YR, CUTE Fee
    # (lower_km, upper_km_or_None, amount) fuel-surcharge bands, YQ.
    fuel_bands: list[tuple[int, int | None, Decimal]] = field(default_factory=list)

    def udf_for(self, city: str) -> Decimal | None:
        return self.udf_by_city.get(city)

    def fuel_for(self, distance_km: int) -> Decimal | None:
        for low, high, amount in self.fuel_bands:
            if distance_km >= low and (high is None or distance_km <= high):
                return amount
        return None


def split_city_pair(cities: str, known_cities: set[str]) -> tuple[str, str] | None:
    """Split "Ahmedabad North Goa" into its origin and destination.

    Requires **exactly one** split where both halves are known cities. Zero
    matches means a city outside our vocabulary (skip the row); more than one
    would be genuinely ambiguous, and guessing between them is how a fare gets
    attributed to the wrong route. Both cases return None rather than pick.
    """
    tokens = cities.split()
    candidates = [
        (" ".join(tokens[:i]), " ".join(tokens[i:]))
        for i in range(1, len(tokens))
        if " ".join(tokens[:i]) in known_cities and " ".join(tokens[i:]) in known_cities
    ]
    return candidates[0] if len(candidates) == 1 else None


def parse_base_fares(
    pages_text: list[str],
    known_cities: set[str],
) -> tuple[list[AirIndiaFareRow], int]:
    """Economy base-fare rows, plus a count of rows skipped as unresolvable.

    The skip count is returned rather than swallowed: a sudden jump in it means
    the document changed or the city vocabulary has fallen behind the basket,
    and either should be visible.
    """
    rows: list[AirIndiaFareRow] = []
    skipped = 0
    in_economy = False

    for page in pages_text:
        for raw in page.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if ECONOMY_SECTION_HEADER in line.upper():
                in_economy = True
                continue
            # Only a banner introducing a DIFFERENT fare section ends the
            # economy block. An earlier version ended it on any all-caps line,
            # which killed it immediately on the "DOMESTIC FARES" sub-heading
            # that sits inside the economy table itself.
            if in_economy and _is_section_terminator(line):
                in_economy = False
                continue
            if not in_economy:
                continue

            match = _FARE_ROW_RE.match(line)
            if not match:
                continue
            pair = split_city_pair(match.group("cities").strip(), known_cities)
            if pair is None:
                skipped += 1
                continue
            fares = [Decimal(f) for f in match.group("fares").split()]
            if not fares:
                skipped += 1
                continue
            rows.append(
                AirIndiaFareRow(
                    origin_city=pair[0],
                    destination_city=pair[1],
                    distance_km=int(match.group("distance")),
                    band_type=match.group("band_type"),
                    fares=fares,
                )
            )
    return rows, skipped


# Banners that begin a different fare section. Listed explicitly rather than
# inferred: "DOMESTIC FARES" is an all-caps sub-heading *inside* the economy
# table, so any heuristic based on capitalisation alone gets this wrong.
_SECTION_TERMINATORS = (
    "PREMIUM ECONOMY",
    "BUSINESS AND FIRST",
    "FIRST-CLASS BASE FARE",
    "OTHER RULES",
    "TAXES/FEES/CHARGES",
)


def _is_section_terminator(line: str) -> bool:
    upper = line.upper()
    return any(banner in upper for banner in _SECTION_TERMINATORS)


def parse_tax_schedule(tables: list[list[list[str | None]]]) -> TaxSchedule:
    """Read the Page-II charge schedule from extracted tables.

    Tables, not text: `extract_text()` interleaves this page's columns into
    unusable strings (hazard 3 in the module docstring).
    """
    schedule = TaxSchedule()

    for table in tables:
        for raw_row in table:
            cells = [(c or "").replace("\n", " ").strip() for c in raw_row]
            if len(cells) >= 5:
                _read_charge_row(cells, schedule)
            elif len(cells) == 2:
                _read_fuel_row(cells, schedule)
    return schedule


def _read_charge_row(cells: list[str], schedule: TaxSchedule) -> None:
    """Classify one charge row.

    The tax-code cell is *vertically merged* across each block, so pdfplumber
    emits it on one row only -- the 'IN' code lands beside Bengaluru while the
    other ~35 UDF rows carry an empty code cell. Reading the code as a
    carried-forward label therefore captured exactly one airport.

    So rows are classified by shape first, and by label only where a label is
    actually present on the row. Within this table the shapes are unambiguous:
    a per-airport UDF row has a single city in "From" and "All" in "To", while
    ASF, RCS and CUTE all carry their own code and description and have either
    a comma-separated airport list or "All" in "From".
    """
    label = f"{cells[0]} {cells[1]}".upper()
    frm, to = cells[2], cells[3]
    amount = _money(cells[4])
    if amount is None:
        return  # "NA" rows are filed as not-applicable, not as zero.

    if "ASF" in label or "SECURITY FEE" in label:
        schedule.asf = amount
        return
    if "CUTE" in label:
        schedule.cute = amount
        return
    if "RCS" in label or "REGIONAL CONNECTIVITY" in label:
        schedule.rcs = amount
        return
    if "PSF" in label or "PASSENGER SERVICE" in label:
        return  # filed NA for the listed airports

    # Shape-based: the UDF block.
    if to == "All" and frm and frm != "All" and "," not in frm:
        schedule.udf_by_city[frm] = amount
    elif frm == "All" and to.endswith("*"):
        schedule.arrival_by_iata[to.rstrip("*")] = amount


_FUEL_BAND_RE = re.compile(r"^\s*(?:(?P<low>\d+)\s*-\s*(?P<high>\d+)|"
                           r"Less than\s*(?P<lt>\d+)|(?P<plus>\d+)\s*\+)\s*$")


def _read_fuel_row(cells: list[str], schedule: TaxSchedule) -> None:
    band, amount_text = cells[0].strip(), cells[1]
    match = _FUEL_BAND_RE.match(band)
    amount = _money(amount_text)
    if not match or amount is None:
        return
    if match.group("lt"):
        schedule.fuel_bands.append((0, int(match.group("lt")) - 1, amount))
    elif match.group("plus"):
        schedule.fuel_bands.append((int(match.group("plus")), None, amount))
    else:
        schedule.fuel_bands.append((int(match.group("low")), int(match.group("high")), amount))


def _money(text: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d.]", "", (text or "").replace("INR", ""))
    if not cleaned or cleaned == ".":
        return None
    try:
        return Decimal(cleaned)
    except Exception:  # noqa: BLE001 - an unparseable amount is simply absent
        return None
