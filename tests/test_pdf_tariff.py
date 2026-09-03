"""Contract test for the tariff-band parser — recorded fixture only, per
docs/03-architecture.md "Testing strategy": parser tests never hit live
sites, or here, never re-download the live PDF. Fixture is a minimal
synthetic excerpt matching the *real* structure confirmed in docs/06-recon-log.md
(section header, column header, MINUS SIGN route separator, NA handling,
multiple sections with different bucket counts) — not the actual IndiGo
document, which isn't checked into the repo.
"""

from apix.acquisition.pdf_tariff import (
    TARGET_SECTION_HEADER,
    lowest_filed_fare,
    parse_tariff_sections,
)

FIXTURE_PAGE_1 = (
    "2026−05−08 15:29:02.126928\n"
    "ONE WAY ECONOMY FARES\n"
    "Route v.v. Type Distance Fare−1 Fare−2 Fare−3\n"
    "Delhi − Hyderabad Maximum 1268 5484 NA 4769\n"
    "Delhi − Hyderabad Minimum 1268 1503 NA 2004\n"
    "Delhi − Mumbai Maximum 1150 6000 6500 7000\n"
    "Delhi − Mumbai Minimum 1150 NA 2500 2800\n"
)

FIXTURE_PAGE_2_BUSINESS = (
    "ONE WAY BUSINESS CLASS FARES\n"
    "Route v.v. Type Distance Fare−1\n"
    "Delhi − Hyderabad Maximum 1268 22000\n"
    "Delhi − Hyderabad Minimum 1268 18000\n"
)


def test_parses_economy_section_rows():
    sections = parse_tariff_sections([FIXTURE_PAGE_1])
    rows = sections[TARGET_SECTION_HEADER]
    assert len(rows) == 4
    first = rows[0]
    assert first.origin_city == "Delhi"
    assert first.destination_city == "Hyderabad"
    assert first.band_type == "Maximum"
    assert first.distance_km == 1268
    assert first.fares == [5484.0, None, 4769.0]


def test_na_bucket_parsed_as_none():
    sections = parse_tariff_sections([FIXTURE_PAGE_1])
    rows = sections[TARGET_SECTION_HEADER]
    delhi_mumbai_min = next(
        r for r in rows if r.destination_city == "Mumbai" and r.band_type == "Minimum"
    )
    assert delhi_mumbai_min.fares[0] is None  # first bucket is "NA"


def test_lowest_filed_fare_skips_leading_na():
    sections = parse_tariff_sections([FIXTURE_PAGE_1])
    rows = sections[TARGET_SECTION_HEADER]
    # Delhi-Mumbai Minimum row is [NA, 2500, 2800] -> first non-NA is 2500
    fare = lowest_filed_fare(rows, "Delhi", "Mumbai")
    assert fare == 2500.0


def test_lowest_filed_fare_unknown_route_returns_none():
    sections = parse_tariff_sections([FIXTURE_PAGE_1])
    rows = sections[TARGET_SECTION_HEADER]
    assert lowest_filed_fare(rows, "Delhi", "Chennai") is None


def test_sections_are_kept_separate_by_bucket_count():
    """The real document's guard: a 3-bucket business-class row must never
    end up merged into the 21-bucket (here, 3-bucket-fixture-standin)
    economy section just because both mention the same city pair."""
    sections = parse_tariff_sections([FIXTURE_PAGE_1, FIXTURE_PAGE_2_BUSINESS])
    assert TARGET_SECTION_HEADER in sections
    assert "ONE WAY BUSINESS CLASS FARES" in sections
    econ_rows = sections[TARGET_SECTION_HEADER]
    biz_rows = sections["ONE WAY BUSINESS CLASS FARES"]
    assert len(econ_rows) == 4
    assert len(biz_rows) == 2
    # Confirm lowest_filed_fare against ONLY the economy rows still finds the
    # right (lower, real) value rather than accidentally picking up business fares
    assert lowest_filed_fare(econ_rows, "Delhi", "Hyderabad") == 1503.0


def test_rows_before_any_header_are_skipped_not_guessed():
    text_no_header = "Delhi − Hyderabad Maximum 1268 5484 NA 4769\n"
    sections = parse_tariff_sections([text_no_header])
    assert sections == {}
