"""Golden-fixture tests for the Jevons elementary aggregate.

Per docs/03-architecture.md "Testing strategy": hand-worked expected values,
including examples from the ILO CPI Manual, since the index engine is pure
and deterministic and this is cheap and high-value.
"""

import math

import pytest

from apix.index.jevons import jevons_index, jevons_relative


def test_jevons_relative_no_change():
    assert jevons_relative([100.0, 200.0], [100.0, 200.0]) == pytest.approx(1.0)


def test_jevons_relative_uniform_10pct_increase():
    # Every item up 10% -> geometric mean of relatives is exactly 1.10,
    # regardless of price dispersion (this is the point of a geometric mean).
    assert jevons_relative([110.0, 220.0, 330.0], [100.0, 200.0, 300.0]) == pytest.approx(1.10)


def test_jevons_relative_hand_worked_ilo_style():
    # ILO CPI Manual-style worked example: three items, mixed direction moves.
    # Relatives: 120/100=1.2, 90/100=0.9, 150/120=1.25
    # Geometric mean = (1.2 * 0.9 * 1.25) ** (1/3)
    base = [100.0, 100.0, 120.0]
    current = [120.0, 90.0, 150.0]
    expected = (1.2 * 0.9 * 1.25) ** (1 / 3)
    assert jevons_relative(current, base) == pytest.approx(expected)


def test_jevons_relative_insensitive_to_scale_carli_would_not_be():
    # Carli (arithmetic mean of relatives) is biased upward and prohibited in
    # HICP for exactly this reason: it responds asymmetrically to an outlier
    # ratio. Confirm Jevons treats a 4x and a 1/4x symmetrically in log-space.
    up = jevons_relative([400.0], [100.0])
    down = jevons_relative([100.0], [400.0])
    assert math.log(up) == pytest.approx(-math.log(down))


def test_jevons_relative_rejects_empty_input():
    with pytest.raises(ValueError):
        jevons_relative([], [])


def test_jevons_relative_rejects_mismatched_length():
    with pytest.raises(ValueError):
        jevons_relative([100.0, 200.0], [100.0])


def test_jevons_relative_rejects_nonpositive_price():
    with pytest.raises(ValueError):
        jevons_relative([0.0], [100.0])


def test_jevons_index_base_period_is_100():
    result = jevons_index([[100.0, 200.0], [110.0, 220.0]])
    assert result[0] == pytest.approx(100.0)
    assert result[1] == pytest.approx(110.0)


def test_jevons_index_empty_input():
    assert jevons_index([]) == []
