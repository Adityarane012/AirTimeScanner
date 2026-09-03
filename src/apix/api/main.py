"""FastAPI skeleton — endpoint surface from docs/03-architecture.md#api-surface.

Run: uvicorn apix.api.main:app --reload
Docs: http://127.0.0.1:8000/docs

Endpoints return real data once the DB has index_value rows (Phase 3+); until
then they return empty/placeholder shapes so the API contract is testable
from day one. SDMX-JSON/ML content negotiation on /v1/sdmx/data/{flow} is a
Phase 4 stretch goal — deliberately not stubbed as fake data here, since a
wrong-looking SDMX payload is worse than a 501.
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import select

from apix.db.engine import get_session
from apix.db.models import IndexValue, Route

app = FastAPI(
    title="APIx — Airfare Price Index for India",
    version="0.1.0",
    description="See docs/03-architecture.md#api-surface for the full contract.",
)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/v1/index")
def get_index(
    series: str = Query(...),
    freq: str = Query("monthly", pattern="^(daily|weekly|monthly)$"),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
) -> list[dict]:
    with get_session() as session:
        stmt = select(IndexValue).where(IndexValue.series_id == series, IndexValue.frequency == freq)
        if from_:
            stmt = stmt.where(IndexValue.period >= from_)
        if to:
            stmt = stmt.where(IndexValue.period <= to)
        stmt = stmt.order_by(IndexValue.period)
        rows = session.execute(stmt).scalars().all()
    return [
        {
            "period": r.period.isoformat(),
            "value": float(r.value),
            "coverage_ratio": float(r.coverage_ratio) if r.coverage_ratio is not None else None,
            "suppressed": r.suppressed,
            "vintage_id": r.vintage_id,
            "config_hash": r.config_hash,
            "sensitivity_low": float(r.sensitivity_low) if r.sensitivity_low is not None else None,
            "sensitivity_high": float(r.sensitivity_high) if r.sensitivity_high is not None else None,
        }
        for r in rows
    ]


@app.get("/v1/index/{series}/latest")
def get_index_latest(series: str, freq: str = Query("monthly")) -> dict:
    with get_session() as session:
        stmt = (
            select(IndexValue)
            .where(IndexValue.series_id == series, IndexValue.frequency == freq)
            .order_by(IndexValue.period.desc())
            .limit(1)
        )
        row = session.execute(stmt).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No published value for this series yet")
    return {
        "period": row.period.isoformat(),
        "value": float(row.value),
        "suppressed": row.suppressed,
        "vintage_id": row.vintage_id,
        "config_hash": row.config_hash,
    }


@app.get("/v1/routes")
def get_routes() -> list[dict]:
    with get_session() as session:
        rows = session.execute(select(Route).where(Route.active.is_(True))).scalars().all()
    return [
        {
            "route_id": r.route_id,
            "origin": r.origin,
            "destination": r.destination,
            "stratum_class": r.stratum_class,
            "dgca_pax_weight": float(r.dgca_pax_weight) if r.dgca_pax_weight is not None else None,
        }
        for r in rows
    ]


@app.get("/v1/coverage")
def get_coverage() -> dict:
    # TODO(Phase 3): per-stratum yield and suppression status, from stratum_panel.
    return {"status": "not_yet_implemented", "note": "wire up once stratum_panel is populated"}


@app.get("/v1/methodology")
def get_methodology() -> dict:
    return {
        "product_spec": "one adult, one-way, economy, non-stop, lowest available total fare",
        "elementary_aggregation": "Jevons (unweighted geometric mean of price relatives)",
        "upper_aggregation": "Lowe/Young weighted, DGCA revenue shares",
        "chaining": "fixed-base daily/weekly within month; rolling-window multilateral monthly",
        "see": "docs/02-methodology.md",
    }


@app.get("/v1/sdmx/data/{flow}")
def get_sdmx(flow: str):
    raise HTTPException(
        status_code=501,
        detail="SDMX-JSON/ML not yet implemented — see IMPLEMENTATION.md Phase 4 stretch goal",
    )
