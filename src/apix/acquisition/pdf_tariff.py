"""Shared parsing for space-delimited tariff-band tables embedded in airline
PDF tariff sheets — first built against IndiGo's real, live-verified sheet
(see docs/06-recon-log.md), reused across carriers where the format matches.

Real structure confirmed by direct inspection this session (not assumed):

    <issue timestamp>
    ONE WAY ECONOMY FARES
    Route v.v. Type Distance Fare-1 Fare-2 ... Fare-21
    Agartala − Ajmer Maximum 1678 NA NA 6710 7328 ... 33000
    Agartala − Ajmer Minimum 1678 NA NA 6039 6595 ... 29700
    ...

Findings that shape the parsing logic below, all confirmed against the real
document (`.scratch/*.txt` from this session's inspection, not committed —
scratch only):

- The route separator is U+2212 MINUS SIGN (−), not an ASCII hyphen —
  a plain `" - "` split silently fails on every row.
- Each city-pair appears **once**, not twice — confirmed by scanning all 68
  pages for a reverse-direction entry (e.g. "Ajmer − Agartala") and
  finding none. The "v.v." heading means the filed band applies to both
  directions symmetrically. **This tariff sheet cannot, by itself, support
  the directional pricing docs/02 requires for the live index** — it's a
  structural anchor (docs/01's phrase), not a substitute for Tier 3 data.
- The document has **multiple fare-table sections** with different bucket
  counts (a 21-bucket "ONE WAY ECONOMY FARES" table, and at least one other
  section with only 4 buckets seen on a later page — likely a different
  cabin/fare type). Parsing must track the current section header and only
  emit rows from the section matching the product spec (docs/02 §1: one-way,
  economy), not blindly grab every row-shaped line in the document.
- City names, not IATA codes. A name->IATA lookup is required and will be
  incomplete for the full network — extend `CITY_TO_IATA` as new routes are
  added to `config/routes.yaml` (Phase 2 concern, not Phase 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ROUTE_SEP = "−"  # MINUS SIGN — not ASCII '-'. Confirmed via direct byte inspection.

TARGET_SECTION_HEADER = "ONE WAY ECONOMY FARES"

_LINE_RE = re.compile(
    rf"^(?P<origin>.+?) {ROUTE_SEP} (?P<destination>.+?) "
    rf"(?P<band_type>Maximum|Minimum) (?P<distance>\d+) (?P<fares>.+)$"
)

# Extend as config/routes.yaml grows (Phase 2). Only what Phase 1 needs today.
CITY_TO_IATA = {
    "Delhi": "DEL",
    "Mumbai": "BOM",
    "Bengaluru": "BLR",
    "Kolkata": "CCU",
    "Hyderabad": "HYD",
}


@dataclass
class TariffBandRow:
    origin_city: str
    destination_city: str
    band_type: str  # "Maximum" | "Minimum"
    distance_km: int
    fares: list[float | None]  # None for "NA" buckets, in Fare-1..Fare-N order


def parse_tariff_sections(full_text_by_page: list[str]) -> dict[str, list[TariffBandRow]]:
    """Split the document into sections by header line, parse each section's
    rows, and return {section_header: [rows]}. Only rows inside a
    section are trusted to share a bucket count/meaning — never merge
    rows across sections.
    """
    sections: dict[str, list[TariffBandRow]] = {}
    current_header: str | None = None

    for page_text in full_text_by_page:
        for line in page_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = _LINE_RE.match(line)
            if m:
                if current_header is None:
                    continue  # row before any recognized header — skip, don't guess
                fares = [None if tok == "NA" else float(tok) for tok in m.group("fares").split()]
                sections.setdefault(current_header, []).append(
                    TariffBandRow(
                        origin_city=m.group("origin"),
                        destination_city=m.group("destination"),
                        band_type=m.group("band_type"),
                        distance_km=int(m.group("distance")),
                        fares=fares,
                    )
                )
            elif "FARES" in line.upper() and "Route" not in line:
                # Heuristic section-header detector: an all-caps-ish line
                # containing "FARES" that isn't the column-header row itself
                # (which contains "Route" and is not a section title).
                current_header = line

    return sections


def lowest_filed_fare(rows: list[TariffBandRow], origin_city: str, destination_city: str) -> float | None:
    """The floor tariff for a route: the first non-NA bucket in its Minimum
    row. This is the best available Tier-1 proxy for "lowest available total
    fare" — NOT a live offer, a filed floor. See fare_class tagging in the
    adapter that calls this; never write it as an unqualified headline quote.
    """
    for row in rows:
        if row.band_type != "Minimum":
            continue
        if row.origin_city == origin_city and row.destination_city == destination_city:
            for fare in row.fares:
                if fare is not None:
                    return fare
    return None
