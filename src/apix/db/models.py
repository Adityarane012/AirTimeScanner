"""SQLAlchemy models mirroring scripts/sql/0001_init.sql 1:1.

The SQL migration is the source of truth for the schema (run it to actually
create tables); these models are the typed Python read/write surface used by
NORMALISE, the index engine, and the API. Keep the two in sync by hand for
now — reassess an Alembic-driven single-source-of-truth once the schema
stabilises past Phase 2.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Route(Base):
    __tablename__ = "route"

    route_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    stage_length_km: Mapped[float | None] = mapped_column(Numeric(6, 1))
    stratum_class: Mapped[str] = mapped_column(Text, nullable=False)
    dgca_pax_weight: Mapped[float | None] = mapped_column(Numeric(10, 6))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CollectionRun(Base):
    __tablename__ = "collection_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    robots_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    selector_relocated: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class FareQuoteRow(Base):
    __tablename__ = "fare_quote"

    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("collection_run.run_id"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    carrier: Mapped[str] = mapped_column(Text, nullable=False)
    route_id: Mapped[int] = mapped_column(Integer, ForeignKey("route.route_id"))
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    collection_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    advance_purchase_days: Mapped[int] = mapped_column(Integer, nullable=False)
    fare_class: Mapped[str | None] = mapped_column(Text)
    is_nonstop: Mapped[bool] = mapped_column(Boolean, default=True)

    base_fare: Mapped[float | None] = mapped_column(Numeric(10, 2))
    carrier_charges: Mapped[float | None] = mapped_column(Numeric(10, 2))
    udf: Mapped[float | None] = mapped_column(Numeric(10, 2))
    asf: Mapped[float | None] = mapped_column(Numeric(10, 2))
    rcs_levy: Mapped[float | None] = mapped_column(Numeric(10, 2))
    gst: Mapped[float | None] = mapped_column(Numeric(10, 2))
    convenience_fee: Mapped[float | None] = mapped_column(Numeric(10, 2))
    total_fare: Mapped[float | None] = mapped_column(Numeric(10, 2))

    observation_status: Mapped[str] = mapped_column(Text, nullable=False)
    outlier_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    raw_payload_hash: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("total_fare IS NULL OR total_fare >= 0", name="chk_total_fare_nonneg"),
    )


class IndexValue(Base):
    __tablename__ = "index_value"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vintage_id: Mapped[str] = mapped_column(Text, nullable=False)
    series_id: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    coverage_ratio: Mapped[float | None] = mapped_column(Numeric(5, 4))
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    sensitivity_low: Mapped[float | None] = mapped_column(Numeric(12, 6))
    sensitivity_high: Mapped[float | None] = mapped_column(Numeric(12, 6))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
