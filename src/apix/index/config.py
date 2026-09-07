"""Versioned methodology parameters and the config hash every published value
carries — docs/02-methodology.md §9.

docs/02 §9 is unambiguous: "Methodology parameters (weights, booking curve,
outlier thresholds, suppression floors) are versioned configuration, and every
published value records the config hash it was computed under." This module is
the single place those parameters are assembled, so a value can never be
published under parameters nobody wrote down.

The hash is taken over the *canonicalised parameters*, not over the config
files' bytes. Reformatting a YAML file, reordering its keys or editing a
comment must not invent a new methodology vintage; changing a weight must.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

# docs/02 §7: the modified z-score cutoff from Iglewicz & Hoaglin. Flags roughly
# the same tail a 3.5-sigma rule would on symmetric data, but built on the
# median and MAD so a right-skewed fare distribution does not drag the
# threshold out with it.
DEFAULT_OUTLIER_MODIFIED_Z = 3.5

# The four windows the basket collects. Kept here rather than inferred from the
# data so a window going entirely uncollected is visible as missing coverage
# rather than silently vanishing from the composite.
ADVANCE_PURCHASE_WINDOWS = (1, 7, 15, 30)


def _window_key(days: int) -> str:
    """booking_curve.yaml keys windows as T1/T7/T15/T30."""
    return f"T{days}"


@dataclass(frozen=True)
class MethodologyConfig:
    """Every parameter that can move a published number.

    Frozen because a run must not be able to retune itself partway through and
    then stamp everything with one hash.
    """

    booking_curve_version: str
    booking_curve: dict[str, float]
    sensitivity_alternates: dict[str, dict[str, float]]
    stratum_suppression_floor: float
    headline_suppression_floor: float
    outlier_modified_z: float = DEFAULT_OUTLIER_MODIFIED_Z
    expected_carriers: tuple[str, ...] = ()
    # Recorded in the hash because they change what the number means, even
    # though they are structural rather than tunable.
    elementary_formula: str = "jevons"
    upper_formula: str = "lowe_young"
    base_period_rule: str = "first_collection_day_of_month"

    # Populated by load(); excluded from the hash (see canonical_params).
    source_files: tuple[str, ...] = field(default=(), compare=False)

    def canonical_params(self) -> dict:
        """The exact object the config hash is computed over.

        Sorted and rounded so that a value's hash depends on the methodology
        and nothing else — not on dict ordering, not on float formatting drift
        between platforms.
        """

        def _round_weights(d: dict[str, float]) -> dict[str, float]:
            return {k: round(float(v), 10) for k, v in sorted(d.items())}

        return {
            "booking_curve_version": self.booking_curve_version,
            "booking_curve": _round_weights(self.booking_curve),
            "sensitivity_alternates": {
                name: _round_weights(w)
                for name, w in sorted(self.sensitivity_alternates.items())
            },
            "stratum_suppression_floor": round(self.stratum_suppression_floor, 10),
            "headline_suppression_floor": round(self.headline_suppression_floor, 10),
            "outlier_modified_z": round(self.outlier_modified_z, 10),
            "expected_carriers": sorted(self.expected_carriers),
            "elementary_formula": self.elementary_formula,
            "upper_formula": self.upper_formula,
            "base_period_rule": self.base_period_rule,
        }

    @property
    def config_hash(self) -> str:
        blob = json.dumps(self.canonical_params(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def vintage_id(self, computed_on: date) -> str:
        """Identifies one publication run.

        Deterministic in (date, config): recomputing the same day under the same
        methodology reproduces the same vintage and upserts over itself, which
        is what makes docs/02 §9's "recomputable bit-for-bit" checkable. A
        methodology change on the same day produces a different vintage rather
        than silently overwriting what was already published under the old one.
        """
        return f"v{computed_on:%Y%m%d}.{self.config_hash[:8]}"

    def curve_weight(self, advance_purchase_days: int, curve: str = "central") -> float:
        weights = (
            self.booking_curve if curve == "central" else self.sensitivity_alternates[curve]
        )
        return float(weights.get(_window_key(advance_purchase_days), 0.0))

    @property
    def curve_names(self) -> tuple[str, ...]:
        """Central curve plus every alternate — the set the sensitivity band is
        taken across. docs/02 §4: never publish the composite as a bare point
        estimate."""
        return ("central", *sorted(self.sensitivity_alternates))


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load(config_dir: Path | None = None) -> MethodologyConfig:
    """Assemble the methodology config from the versioned YAML files."""
    cfg_dir = config_dir or CONFIG_DIR
    curve = _load_yaml(cfg_dir / "booking_curve.yaml")
    suppression = _load_yaml(cfg_dir / "suppression.yaml")
    routes = _load_yaml(cfg_dir / "routes.yaml")

    weights = {str(k): float(v) for k, v in curve["weights"].items()}
    _validate_curve("weights", weights)

    alternates = {}
    for name, alt in (curve.get("sensitivity_alternates") or {}).items():
        alt_weights = {str(k): float(v) for k, v in alt.items()}
        _validate_curve(f"sensitivity_alternates.{name}", alt_weights)
        alternates[str(name)] = alt_weights

    return MethodologyConfig(
        booking_curve_version=str(curve["version"]),
        booking_curve=weights,
        sensitivity_alternates=alternates,
        stratum_suppression_floor=float(suppression["stratum_suppression_floor"]),
        headline_suppression_floor=float(suppression["headline_suppression_floor"]),
        expected_carriers=tuple(str(c) for c in (routes.get("carriers") or ())),
        source_files=(
            str(cfg_dir / "booking_curve.yaml"),
            str(cfg_dir / "suppression.yaml"),
            str(cfg_dir / "routes.yaml"),
        ),
    )


def _validate_curve(label: str, weights: dict[str, float]) -> None:
    """A booking curve that does not cover the collected windows, or does not
    sum to 1, silently rescales the composite. Fail at load rather than publish
    a number nobody can reconstruct.
    """
    expected = {_window_key(d) for d in ADVANCE_PURCHASE_WINDOWS}
    missing = expected - set(weights)
    extra = set(weights) - expected
    if missing or extra:
        raise ValueError(
            f"booking_curve.yaml {label}: window mismatch — "
            f"missing {sorted(missing) or 'none'}, unexpected {sorted(extra) or 'none'}. "
            f"Expected exactly {sorted(expected)}."
        )
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"booking_curve.yaml {label}: weights sum to {total}, must sum to 1.0")
