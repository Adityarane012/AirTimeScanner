"""Load DGCA city-pair traffic into `route.dgca_pax_weight`.

    python scripts/load_dgca_weights.py              # dry run: report only
    python scripts/load_dgca_weights.py --apply      # write the weights
    python scripts/load_dgca_weights.py --months 24  # longer averaging window

Until this runs, `dgca_pax_weight` is NULL for every route and the index
aggregates the basket with **equal** weights, which docs/02 §8 does not
specify and the engine warns about on every run.

**Why the source is a mirror, and what that costs.** DGCA publishes city-pair
monthly traffic, and it is the right statistic: directional, monthly, and the
same series DGCA's own Tariff Monitoring Unit works from. But it is served
through a session-driven portal whose files sit behind opaque `attachId`
links, which is a brittle thing to automate and a worse thing to depend on
daily. This script therefore reads a **version-pinned** CSV mirror of that
data, and pins the exact commit so the input is reproducible rather than
"whatever the file said the day someone ran this". The raw bytes are stored
content-hashed in the object store like any other payload, so the weights can
be re-derived from what was actually read.

That is a real dependency on a third party's transcription, and it is
recorded in `route.weight_source` rather than glossed over. Verifying a figure
against an official DGCA publication is a separate step and is what
`--expect-monthly-total` exists for.

**What the weight measures: passenger share, not revenue share.** docs/02 §8
specifies a revenue-share Lowe/Young. A passenger share equals a revenue share
only if every route has the same average fare, and no basket has that — a
1,700 km route earns more per passenger than a 700 km one. Passenger share is
the honest first step because it needs no fare data of our own, and it is
recorded as `weight_basis = 'passenger_share'` so it can never be mistaken for
the revenue share it approximates. Moving to an expenditure basis is a
methodology change, and the basis is in the config hash.

Failsafes, in order of how much damage they prevent:

- Dry run by default. `--apply` is required to write anything.
- Nothing here touches collection. The daily collector, the adapters and the
  spool are untouched, so a bad weight load cannot cost a day of data.
- A basket route with no traffic in the window **aborts the load** rather
  than being written as zero. A zero weight removes a route from the index
  silently, which is the worst outcome for a ten-route basket.
- A basket city whose name the mapping does not resolve aborts the load, so a
  DGCA rename (Mumbai has already had one) cannot quietly drop a route.
- Weights are written in one transaction with their provenance, which
  `sql/0004` enforces with a CHECK: a weight without provenance cannot exist.
- Rollback is `UPDATE route SET dgca_pax_weight = NULL`, which returns the
  engine to equal weighting and says so in every run report.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx
from sqlalchemy import select

from apix.db.engine import get_session
from apix.db.models import Route
from apix.settings import settings
from apix.storage.object_store import ObjectStore
from apix.weights.dgca_city_pairs import (
    CITY_TO_IATA,
    DEFAULT_WINDOW_MONTHS,
    basket_weights,
    parse_city_pairs,
    window_months,
)

# Pinned so the weights are reproducible. Bump deliberately, with a note of
# what changed; never track a moving branch.
# Pinned 2026-09-27 to the commit that last touched this file (2026-09-08),
# so re-running reads the same bytes rather than whatever the branch holds.
MIRROR_COMMIT = "8307cfcac03b642e20393b2ae92bc753124b7caf"
MIRROR_URL = (
    "https://raw.githubusercontent.com/Vonter/india-aviation-traffic/"
    f"{MIRROR_COMMIT}/aggregated/domestic/city.csv"
)
SOURCE_NAME = f"dgca_city_pair_via_vonter_mirror@{MIRROR_COMMIT[:12]}"
WEIGHT_BASIS = "passenger_share"

# The published series runs a couple of months behind; more than this and the
# weights describe a market that has moved on.
MAX_STALENESS_MONTHS = 6

# How far the file's national monthly total may sit from the figure DGCA
# published for the same month. Tight on purpose: these should be the same
# number, and for 2026-07 they agreed to 0.00%.
VERIFICATION_TOLERANCE = Decimal("0.02")


def fetch_csv(url: str = MIRROR_URL) -> tuple[str, str]:
    """Return (text, content_hash), storing the raw bytes for the audit trail."""
    response = httpx.get(url, timeout=120, follow_redirects=True)
    response.raise_for_status()
    put = ObjectStore(settings.raw_store_path).put(response.content)
    return response.text, put.content_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the weights (default: dry run)")
    parser.add_argument(
        "--months", type=int, default=DEFAULT_WINDOW_MONTHS,
        help=f"averaging window in months (default {DEFAULT_WINDOW_MONTHS}, a full seasonal cycle)",
    )
    parser.add_argument(
        "--expect-monthly-total", type=float, default=None,
        help="verification: total domestic passengers DGCA published for the latest month; "
             "the load aborts if the file disagrees by more than 2%%",
    )
    parser.add_argument("--csv", help="read a local file instead of fetching the mirror")
    args = parser.parse_args(argv)

    if args.csv:
        text, content_hash = Path(args.csv).read_text(encoding="utf-8", errors="replace"), "local"
        print(f"source: {args.csv} (local file, not pinned)")
    else:
        text, content_hash = fetch_csv()
        print(f"source: {MIRROR_URL}")
        print(f"  raw payload sha256: {content_hash}")

    traffic = parse_city_pairs(text)
    if traffic.latest_period is None:
        print("ERROR: no usable rows in the file")
        return 1
    start, end = window_months(traffic.latest_period, args.months)
    age_months = _months_between(traffic.latest_period, datetime.now(UTC).date())
    print(f"  window: {start:%Y-%m} to {end:%Y-%m} ({args.months} months)")
    print(f"  latest published month: {traffic.latest_period:%Y-%m} ({age_months} months old)")
    print(f"  refused as separate airports: {', '.join(traffic.refused_cities) or 'none'}")

    if age_months > MAX_STALENESS_MONTHS:
        print(f"ERROR: the data is {age_months} months old, over the {MAX_STALENESS_MONTHS}-month limit")
        return 1

    if args.expect_monthly_total is not None:
        # Compared against the whole file, not the basket: this asks whether the
        # mirror is a faithful copy of DGCA's statistic, which is the one thing a
        # pinned commit and a stored payload cannot establish.
        observed = traffic.monthly_totals.get(traffic.latest_period, Decimal(0))
        expected = Decimal(str(args.expect_monthly_total))
        drift = abs(observed - expected) / expected
        print("\nverification against DGCA's published monthly total:")
        print(f"  DGCA published        : {expected:,.0f}")
        print(f"  file, all city pairs  : {observed:,.0f}")
        print(f"  difference            : {drift:.2%}")
        if drift > VERIFICATION_TOLERANCE:
            print(f"ERROR: over the {VERIFICATION_TOLERANCE:.0%} tolerance - refusing to load. "
                  "Either the mirror is not faithful, or the expected figure covers a "
                  "different population (scheduled vs total, or a different month).")
            return 1
        print("  verified: the mirror agrees with the published figure")

    with get_session() as session:
        routes = session.execute(
            select(Route).where(Route.active.is_(True)).order_by(Route.route_id)
        ).scalars().all()
        basket = [(r.origin, r.destination) for r in routes]
        weights, missing = basket_weights(traffic, basket, months=args.months, latest=end)

        unmapped_basket = sorted(
            {city for route in basket for city in route} - set(CITY_TO_IATA.values())
        )
        print(f"\nbasket: {len(basket)} active routes")
        if unmapped_basket:
            print(f"ERROR: no DGCA city name maps to {', '.join(unmapped_basket)} — refusing to load")
            return 1
        if missing:
            pairs = ", ".join(f"{o}-{d}" for o, d in missing)
            print(f"ERROR: no traffic in the window for {pairs} — refusing to load a partial basket")
            return 1

        by_route = {(w.origin, w.destination): w for w in weights}
        equal = Decimal(1) / Decimal(len(basket))
        print(f"\n{'route':<10}{'pax in window':>15}{'share':>9}{'vs equal':>10}{'months':>8}{'current':>10}")
        for route in routes:
            w = by_route[(route.origin, route.destination)]
            current = f"{route.dgca_pax_weight:.4f}" if route.dgca_pax_weight is not None else "NULL"
            delta = (w.share - equal) / equal * 100
            print(
                f"  {route.origin}-{route.destination:<6}{w.passengers:>15,.0f}"
                f"{float(w.share) * 100:>8.2f}%{delta:>+9.0f}%{w.months_observed:>8}{current:>10}"
            )
        print(f"  {'TOTAL':<8}{sum(w.passengers for w in weights):>15,.0f}"
              f"{float(sum(w.share for w in weights)) * 100:>8.2f}%")

        if not args.apply:
            print("\ndry run: nothing written. Re-run with --apply to write these weights.")
            return 0

        retrieved_at = datetime.now(UTC)
        for route in routes:
            w = by_route[(route.origin, route.destination)]
            route.dgca_pax_weight = float(w.share)
            route.weight_basis = WEIGHT_BASIS
            route.weight_source = SOURCE_NAME if not args.csv else f"local:{args.csv}"
            route.weight_period_start = start
            route.weight_period_end = end
            route.weight_retrieved_at = retrieved_at
        session.commit()
        print(f"\nwrote {len(routes)} weights, basis '{WEIGHT_BASIS}', period {start:%Y-%m}..{end:%Y-%m}")
        print("The index's config_hash changes with this: an equal-weighted run and a")
        print("traffic-weighted one are different methodologies (docs/02 §9).")
    return 0


def _months_between(earlier, later) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


if __name__ == "__main__":
    sys.exit(main())
