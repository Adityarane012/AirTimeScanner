-- APIx core schema — mirrors the data model in docs/03-architecture.md#core-data-model.
--
-- Plain PostgreSQL for the prototype (no TimescaleDB — see IMPLEMENTATION.md
-- "What's cut for the compressed timeline"). At the project's actual scale
-- (~3k headline rows/day, 5-11M rows/year) a btree index on collection_ts is
-- sufficient; migrate to a hypertable later only if evidence says it's needed.

CREATE TABLE IF NOT EXISTS route (
    route_id            SERIAL PRIMARY KEY,
    origin              CHAR(3) NOT NULL,           -- IATA code
    destination         CHAR(3) NOT NULL,           -- IATA code
    direction           TEXT NOT NULL,               -- redundant-but-explicit: 'origin->destination'
    stage_length_km      NUMERIC(6,1),
    stratum_class        TEXT NOT NULL CHECK (stratum_class IN ('metro_metro', 'metro_nonmetro', 'rcs_udan')),
    dgca_pax_weight       NUMERIC(10,6),              -- revenue/passenger share; NULL until Q2/Q8 basket is finalised
    active                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (origin, destination)
);

CREATE TABLE IF NOT EXISTS collection_run (
    run_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source                TEXT NOT NULL,              -- adapter name, e.g. 'tier1_indigo_tariff'
    started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at           TIMESTAMPTZ,
    status                TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'partial')),
    robots_checked_at     TIMESTAMPTZ,
    config_hash           TEXT NOT NULL,
    selector_relocated    BOOLEAN NOT NULL DEFAULT FALSE,
    notes                 TEXT
);

CREATE INDEX IF NOT EXISTS ix_collection_run_source_started
    ON collection_run (source, started_at DESC);

CREATE TABLE IF NOT EXISTS selector_confirmation (
    id                    SERIAL PRIMARY KEY,
    adapter               TEXT NOT NULL,
    detected_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    old_selector          TEXT,
    new_selector          TEXT,
    confirmed_by          TEXT,
    confirmed_at          TIMESTAMPTZ,
    resulting_config_hash TEXT
);

CREATE TABLE IF NOT EXISTS fare_quote (
    quote_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                UUID NOT NULL REFERENCES collection_run (run_id),
    source                TEXT NOT NULL,
    carrier               TEXT NOT NULL,
    route_id              INTEGER NOT NULL REFERENCES route (route_id),
    departure_date        DATE NOT NULL,
    collection_ts         TIMESTAMPTZ NOT NULL,
    advance_purchase_days INTEGER NOT NULL CHECK (advance_purchase_days IN (1, 7, 15, 30)),
    fare_class            TEXT,
    is_nonstop            BOOLEAN NOT NULL DEFAULT TRUE,

    base_fare             NUMERIC(10,2),
    carrier_charges       NUMERIC(10,2),
    udf                   NUMERIC(10,2),
    asf                   NUMERIC(10,2),
    rcs_levy              NUMERIC(10,2),
    gst                   NUMERIC(10,2),
    convenience_fee       NUMERIC(10,2),
    total_fare            NUMERIC(10,2),

    observation_status    TEXT NOT NULL CHECK (observation_status IN
                              ('observed', 'no_service', 'collection_failed', 'imputed')),
    outlier_flag          BOOLEAN NOT NULL DEFAULT FALSE,
    exclusion_reason      TEXT,
    raw_payload_hash      TEXT,        -- -> object store key; NULL only when observation_status != 'observed'

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Property-test invariants from docs/02-methodology.md, enforced at the DB boundary too:
    CONSTRAINT chk_total_fare_nonneg CHECK (total_fare IS NULL OR total_fare >= 0),
    CONSTRAINT chk_total_ge_components CHECK (
        total_fare IS NULL OR (
            total_fare >= COALESCE(base_fare, 0) + COALESCE(carrier_charges, 0)
                + COALESCE(udf, 0) + COALESCE(asf, 0) + COALESCE(rcs_levy, 0)
                + COALESCE(gst, 0) - 0.01  -- tolerance for rounding
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_fare_quote_collection_ts ON fare_quote (collection_ts);
CREATE INDEX IF NOT EXISTS ix_fare_quote_stratum
    ON fare_quote (route_id, advance_purchase_days, departure_date);
CREATE INDEX IF NOT EXISTS ix_fare_quote_run ON fare_quote (run_id);

CREATE TABLE IF NOT EXISTS stratum_panel (
    id                    SERIAL PRIMARY KEY,
    date                  DATE NOT NULL,
    route_id              INTEGER NOT NULL REFERENCES route (route_id),
    advance_purchase_days INTEGER NOT NULL,
    jevons_relative       NUMERIC(12,8),
    n_observed            INTEGER NOT NULL DEFAULT 0,
    n_imputed             INTEGER NOT NULL DEFAULT 0,
    coverage_ratio        NUMERIC(5,4),
    UNIQUE (date, route_id, advance_purchase_days)
);

CREATE TABLE IF NOT EXISTS index_value (
    id                    SERIAL PRIMARY KEY,
    vintage_id            TEXT NOT NULL,
    series_id             TEXT NOT NULL,
    frequency             TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
    period                DATE NOT NULL,
    value                 NUMERIC(12,6) NOT NULL,
    coverage_ratio        NUMERIC(5,4),
    suppressed            BOOLEAN NOT NULL DEFAULT FALSE,
    config_hash           TEXT NOT NULL,
    sensitivity_low       NUMERIC(12,6),
    sensitivity_high      NUMERIC(12,6),
    published_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vintage_id, series_id, frequency, period)
);

CREATE INDEX IF NOT EXISTS ix_index_value_series_period ON index_value (series_id, frequency, period);
