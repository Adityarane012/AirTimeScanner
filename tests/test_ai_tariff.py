"""Air India tariff-sheet parser — fixture-based, per docs/03's testing rule.

The fixtures are synthetic but reproduce the exact structural hazards found in
the real 2026 sheet, each of which broke a first attempt:

- "DOMESTIC FARES" is an all-caps sub-heading *inside* the economy table, so a
  section detector keyed on capitalisation ends the block immediately and
  parses nothing.
- City names can be multi-word ("North Goa").
- pdfplumber emits no space between a long city name and the distance
  ("Thiruvananthapuram1255").
- The tax-code cell is vertically merged, so only one row of ~36 carries the
  "IN" code. Classifying UDF rows by that label captures exactly one airport.
"""

from decimal import Decimal

from apix.acquisition.ai_tariff import (
    parse_base_fares,
    parse_tax_schedule,
    split_city_pair,
)

KNOWN = {"Delhi", "Mumbai", "Hyderabad", "Bengaluru", "North Goa", "Thiruvananthapuram"}

ECONOMY_PAGE = """ECONOMY BASE FARE
Instant purchase (IP) fares with no advance purchase restriction
DOMESTIC FARES
Market & V.V.
S.No Origin Destination DistanceMinimum / MaximumLevel 1 Level 2 Level 3
1 Delhi Hyderabad 1265 Minimum 1250 3280 3740
2 Delhi Hyderabad 1265 Maximum 4259 4500 4800
7 Delhi North Goa 1462 Minimum 670 3303 4045
91 Mumbai Thiruvananthapuram1255 Minimum 1230 5440 5641
"""

OTHER_CABIN_PAGE = """PREMIUM ECONOMY FARE
Instant purchase (IP) fares with no advance purchase restriction
1 Delhi Hyderabad 1265 Minimum 99999 99999 99999
"""

TAX_TABLE = [
    ["Tax Code", "Description", "From", "To", "Amount (Rs)", "Remark"],
    ["", "", "All", "DEL*", "66", ""],
    ["", "", "Ahmedabad", "All", "708", ""],
    # The merged code cell lands on exactly one row of the UDF block.
    ["IN", "User Development Fee (UDF)", "Bengaluru", "All", "649", ""],
    ["", "", "Delhi", "All", "152", ""],
    ["", "", "Hyderabad", "All", "885", ""],
    ["WO", "Passenger Service Fee (PSF)", "Delhi, Goa Mopa", "All", "NA", ""],
    ["P2", "Airport Security Fee (ASF)", "Agra,Aizwal,Ahmedabad", "All", "236", ""],
    ["YR", "Regional Connectivity Fee (RCS)", "Agra,Ahmedabad", "All", "10", ""],
    ["YR", "CUTE Fee", "All", "All", "160", ""],
]

FUEL_TABLE = [
    ["FUEL SURCHARGES (YQ)", ""],
    ["Distance Band", "Fuel Surcharge YQ"],
    ["Less than 500", "INR 299"],
    ["501 - 1000", "INR 399"],
    ["1001 - 1500", "INR 549"],
    ["2000+", "INR 899"],
]


# --- city splitting --------------------------------------------------------


def test_splits_a_simple_city_pair():
    assert split_city_pair("Delhi Hyderabad", KNOWN) == ("Delhi", "Hyderabad")


def test_splits_a_multi_word_destination():
    assert split_city_pair("Delhi North Goa", KNOWN) == ("Delhi", "North Goa")


def test_refuses_to_guess_when_no_split_is_valid():
    assert split_city_pair("Agartala Ajmer", KNOWN) is None


def test_refuses_to_guess_when_a_split_is_ambiguous():
    """Two valid readings must yield None. Picking one is how a fare gets
    attributed to the wrong route."""
    ambiguous = {"North", "Goa North", "Goa"}
    assert split_city_pair("North Goa North Goa", ambiguous) is None


# --- base fares ------------------------------------------------------------


def test_parses_the_economy_table():
    rows, skipped = parse_base_fares([ECONOMY_PAGE], KNOWN)
    assert skipped == 0
    assert len(rows) == 4

    first = rows[0]
    assert (first.origin_city, first.destination_city) == ("Delhi", "Hyderabad")
    assert first.distance_km == 1265
    assert first.band_type == "Minimum"
    assert first.fares[0] == Decimal("1250")


def test_domestic_fares_subheading_does_not_end_the_section():
    """The bug this fixture exists for: an all-caps sub-heading inside the
    economy table ended the block and produced zero rows."""
    assert parse_base_fares([ECONOMY_PAGE], KNOWN)[0] != []


def test_handles_a_city_glued_to_its_distance():
    rows, _ = parse_base_fares([ECONOMY_PAGE], KNOWN)
    glued = [r for r in rows if r.destination_city == "Thiruvananthapuram"]
    assert len(glued) == 1
    assert glued[0].distance_km == 1255
    assert glued[0].origin_city == "Mumbai"


def test_other_cabins_are_never_read_as_economy():
    """docs/02 §1 specifies economy. A premium fare leaking in would silently
    inflate the index."""
    rows, _ = parse_base_fares([ECONOMY_PAGE, OTHER_CABIN_PAGE], KNOWN)
    assert all(r.fares[0] != Decimal("99999") for r in rows)
    assert len(rows) == 4


def test_unknown_cities_are_counted_not_silently_dropped():
    rows, skipped = parse_base_fares([ECONOMY_PAGE], {"Delhi", "Hyderabad"})
    assert len(rows) == 2
    assert skipped == 2  # the North Goa and Thiruvananthapuram rows


# --- tax schedule ----------------------------------------------------------


def test_udf_is_read_for_every_airport_not_just_the_labelled_row():
    """The tax-code cell is vertically merged onto one row. Classifying by
    that label captured Bengaluru alone and missed the other 35 airports."""
    schedule = parse_tax_schedule([TAX_TABLE])
    assert schedule.udf_for("Bengaluru") == Decimal("649")  # the labelled row
    assert schedule.udf_for("Delhi") == Decimal("152")      # unlabelled
    assert schedule.udf_for("Hyderabad") == Decimal("885")  # unlabelled
    assert schedule.udf_for("Ahmedabad") == Decimal("708")  # before the label


def test_named_charges_are_classified_by_their_own_label():
    schedule = parse_tax_schedule([TAX_TABLE])
    assert schedule.asf == Decimal("236")
    assert schedule.rcs == Decimal("10")
    assert schedule.cute == Decimal("160")


def test_arrival_side_charges_are_kept_separate_from_udf():
    schedule = parse_tax_schedule([TAX_TABLE])
    assert schedule.arrival_by_iata["DEL"] == Decimal("66")
    # The arrival row must not have been mistaken for a departure UDF.
    assert "All" not in schedule.udf_by_city


def test_not_applicable_charges_are_absent_not_zero():
    """PSF is filed NA. Recording it as 0 would assert it was measured."""
    schedule = parse_tax_schedule([TAX_TABLE])
    assert all(v != Decimal("0") for v in schedule.udf_by_city.values())


def test_an_airport_with_no_filed_udf_returns_none():
    """Mumbai genuinely has no departure UDF row in the real sheet — it
    appears only as an arrival charge. That must read as unknown, not zero."""
    schedule = parse_tax_schedule([TAX_TABLE])
    assert schedule.udf_for("Mumbai") is None


# --- fuel surcharge --------------------------------------------------------


def test_fuel_surcharge_bands():
    schedule = parse_tax_schedule([TAX_TABLE, FUEL_TABLE])
    assert schedule.fuel_for(300) == Decimal("299")
    assert schedule.fuel_for(700) == Decimal("399")
    assert schedule.fuel_for(1265) == Decimal("549")
    assert schedule.fuel_for(2500) == Decimal("899")


def test_a_distance_the_filed_bands_do_not_cover_returns_none():
    """The real sheet bands are "Less than 500" then "501 - 1000", so 500 is
    genuinely unspecified. Returning None surfaces the gap; returning 0 would
    understate the fare."""
    schedule = parse_tax_schedule([TAX_TABLE, FUEL_TABLE])
    assert schedule.fuel_for(500) is None
