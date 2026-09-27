"""DGCA city-pair passenger traffic — the weights the upper level needs.

`route.dgca_pax_weight` has been NULL since the schema was created, so
`apix.index.aggregate` falls back to **equal** weights across the basket. That
is not the Lowe/Young revenue-share aggregation docs/02 §8 specifies, and the
engine has warned about it on every run since Phase 3. This module turns
DGCA's published city-pair traffic into those weights.

**Directional, which is the whole point.** DGCA publishes one row per city
pair per month carrying both directions — `PaxToCity2` is City1→City2 and
`PaxFromCity2` is City2→City1. The basket is directional too (DEL→BOM and
BOM→DEL are separate routes with separate tax wedges, see
`tier1_air_india.py`), so the two columns are kept apart rather than summed.

Three traps in the city names, each of which silently produces wrong weights
rather than an error:

1. **`MUMBAI (NAVI MUMBAI)` is a different airport** — NMI, the new second
   Mumbai field. Matching Mumbai by substring merges it into BOM, inflating
   BOM's weight with traffic that never touched the airport we price. The
   same airport turned up in Goibibo's listings (see `tier3_goibibo`), so
   this is not a hypothetical.
2. **Mumbai was renamed mid-series.** Older months say `MUMBAI`; newer ones
   say `MUMBAI (MUMBAI)`, presumably disambiguated when NMI opened. Matching
   exactly on `MUMBAI` silently drops the most recent months — the ones that
   matter most for a current weight.
3. **`BENGALURU`, not `BANGALORE`.** The IATA code is BLR either way.

So the mapping is an **explicit table of exact names**, and any name that
does not appear in it is reported to the caller. Nothing is guessed, and a
route that cannot be resolved is not silently assigned zero: a zero weight
would drop the route from the index entirely, which is the worst possible
failure mode for a basket this small.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# Exact DGCA city names -> IATA. Several names may map to one airport (a
# rename), but one name never maps to two airports.
CITY_TO_IATA: dict[str, str] = {
    "DELHI": "DEL",
    "MUMBAI": "BOM",
    "MUMBAI (MUMBAI)": "BOM",  # renamed when Navi Mumbai opened; same airport
    "BENGALURU": "BLR",
    "BANGALORE": "BLR",  # historical spelling, kept in case older files use it
    "KOLKATA": "CCU",
    "HYDERABAD": "HYD",
    "CHENNAI": "MAA",
    "AHMEDABAD": "AMD",
    "PUNE": "PNQ",
    "GOA": "GOI",
    "COCHIN": "COK",
    "KOCHI": "COK",
    "JAIPUR": "JAI",
    "LUCKNOW": "LKO",
}

# Names that look like a basket city but are a *different* airport. Listed
# explicitly so the resolver can refuse them loudly rather than by omission.
DISTINCT_NEARBY_AIRPORTS: dict[str, str] = {
    "MUMBAI (NAVI MUMBAI)": "NMI",
    "DELHI (NOIDA)": "DXN",
    "DELHI (HINDON)": "HDO",
}

# A weight computed from a single month would carry that month's seasonality
# into the index's upper level. Twelve complete months is the shortest window
# that averages a full seasonal cycle.
DEFAULT_WINDOW_MONTHS = 12


@dataclass(frozen=True)
class DirectionalFlow:
    """Passengers flown on one directional city pair in one month."""

    origin: str
    destination: str
    year: int
    month: int
    passengers: Decimal

    @property
    def period(self) -> date:
        return date(self.year, self.month, 1)


@dataclass(frozen=True)
class ParsedTraffic:
    flows: list[DirectionalFlow]
    # City names present in the file that the table does not resolve. Reported,
    # never guessed: a mapping gap must be visible to whoever loads weights.
    unmapped_cities: tuple[str, ...]
    # Names deliberately refused as a different airport (NMI, DXN, HDO).
    refused_cities: tuple[str, ...]
    latest_period: date | None
    # Total passengers per month across EVERY city pair in the file, mapped or
    # not. Not used for weights — it exists to check the file against DGCA's
    # published monthly headline, which is the only independent evidence that a
    # mirror of a statistic is faithful to the statistic.
    monthly_totals: dict[date, Decimal] = field(default_factory=dict)


def parse_city_pairs(csv_text: str) -> ParsedTraffic:
    """Parse DGCA city-pair traffic into directional monthly flows.

    Pure: no network, no clock. Rows whose passenger count is absent or
    unparseable are skipped rather than treated as zero — a missing
    measurement is not a measurement of nothing.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"Year", "Month", "City1", "City2", "PaxToCity2", "PaxFromCity2"}
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"DGCA city-pair file is missing columns: {sorted(missing)}")

    flows: list[DirectionalFlow] = []
    unmapped: set[str] = set()
    refused: set[str] = set()
    monthly_totals: dict[date, Decimal] = defaultdict(Decimal)

    for row in reader:
        city1, city2 = (row["City1"] or "").strip(), (row["City2"] or "").strip()

        # National total first, before any mapping decision: the check this
        # feeds must cover the whole file, not the subset we can resolve.
        try:
            period = date(int(row["Year"]), int(row["Month"]), 1)
        except (TypeError, ValueError):
            period = None
        if period is not None:
            for column in ("PaxToCity2", "PaxFromCity2"):
                pax = _passengers(row[column])
                if pax is not None:
                    monthly_totals[period] += pax

        codes = []
        for name in (city1, city2):
            if name in DISTINCT_NEARBY_AIRPORTS:
                refused.add(name)
                codes.append(None)
            elif name in CITY_TO_IATA:
                codes.append(CITY_TO_IATA[name])
            else:
                unmapped.add(name)
                codes.append(None)
        code1, code2 = codes
        if code1 is None or code2 is None or code1 == code2:
            continue

        try:
            year, month = int(row["Year"]), int(row["Month"])
        except (TypeError, ValueError):
            continue
        if not 1 <= month <= 12:
            continue

        # PaxToCity2 is city1 -> city2; PaxFromCity2 is the return direction.
        for origin, destination, raw in (
            (code1, code2, row["PaxToCity2"]),
            (code2, code1, row["PaxFromCity2"]),
        ):
            pax = _passengers(raw)
            if pax is None:
                continue
            flows.append(DirectionalFlow(origin, destination, year, month, pax))

    periods = [f.period for f in flows]
    return ParsedTraffic(
        flows=flows,
        unmapped_cities=tuple(sorted(unmapped)),
        refused_cities=tuple(sorted(refused)),
        latest_period=max(periods) if periods else None,
        monthly_totals=dict(monthly_totals),
    )


def _passengers(raw: str | None) -> Decimal | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except Exception:  # noqa: BLE001 - a malformed cell is skipped, never zeroed
        return None
    return value if value >= 0 else None


def window_months(latest: date, months: int = DEFAULT_WINDOW_MONTHS) -> tuple[date, date]:
    """The [start, latest] inclusive month range ending at `latest`."""
    year, month = latest.year, latest.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1), latest


@dataclass(frozen=True)
class RouteWeight:
    origin: str
    destination: str
    passengers: Decimal
    # Share of the basket's total traffic, not of all India: the upper level
    # aggregates within the basket, so the weights must sum to 1 across it.
    share: Decimal
    months_observed: int


def basket_weights(
    traffic: ParsedTraffic,
    basket: list[tuple[str, str]],
    *,
    months: int = DEFAULT_WINDOW_MONTHS,
    latest: date | None = None,
) -> tuple[list[RouteWeight], list[tuple[str, str]]]:
    """Passenger shares for each basket route, and the routes with no data.

    Returns `(weights, missing)`. A route with no traffic in the window is
    returned in `missing` rather than as a zero-weight entry: zero would
    remove it from the index silently, and the caller must decide whether a
    basket that incomplete should be loaded at all.
    """
    anchor = latest or traffic.latest_period
    if anchor is None:
        return [], list(basket)
    start, end = window_months(anchor, months)

    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    counted: dict[tuple[str, str], set[date]] = defaultdict(set)
    for flow in traffic.flows:
        if start <= flow.period <= end:
            key = (flow.origin, flow.destination)
            totals[key] += flow.passengers
            counted[key].add(flow.period)

    present = [route for route in basket if totals.get(route)]
    missing = [route for route in basket if not totals.get(route)]
    basket_total = sum((totals[route] for route in present), Decimal(0))
    if basket_total <= 0:
        return [], list(basket)

    weights = [
        RouteWeight(
            origin=origin,
            destination=destination,
            passengers=totals[(origin, destination)],
            share=totals[(origin, destination)] / basket_total,
            months_observed=len(counted[(origin, destination)]),
        )
        for origin, destination in present
    ]
    return weights, missing
