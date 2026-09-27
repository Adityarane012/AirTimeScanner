-- 0004 — record where a route weight came from, not just what it is.
--
-- `route.dgca_pax_weight` has existed since 0001_init.sql as a bare number
-- with no provenance. That is enough to compute an index and not enough to
-- defend one. docs/02 §9 requires every published value to record the
-- methodology it was computed under, and the upper-level weights are the
-- largest single methodological input after the booking curve.
--
-- Three things have to be recoverable years later, from the row itself:
--
--   * WHICH published statistic the weight came from, precisely enough to
--     re-derive it (source name plus the pinned revision of the file read).
--   * WHICH PERIOD it describes. A weight from the 12 months to 2026-07 is
--     not wrong in 2027, but it is stale, and staleness is invisible without
--     the period.
--   * WHAT THE WEIGHT MEASURES. Passenger share and expenditure share are
--     both defensible and they are different numbers: docs/02 §8 specifies a
--     revenue-share Lowe/Young, and a passenger share only equals a revenue
--     share if every route has the same average fare, which no route basket
--     has. Recording the basis stops the two being silently interchanged.
--
-- Additive and idempotent. Rolling back the weights themselves is
-- `UPDATE route SET dgca_pax_weight = NULL`, which returns the engine to
-- equal weighting and is reported by `route_weights_are_real`.

ALTER TABLE route ADD COLUMN IF NOT EXISTS weight_basis TEXT;
ALTER TABLE route ADD COLUMN IF NOT EXISTS weight_source TEXT;
ALTER TABLE route ADD COLUMN IF NOT EXISTS weight_period_start DATE;
ALTER TABLE route ADD COLUMN IF NOT EXISTS weight_period_end DATE;
ALTER TABLE route ADD COLUMN IF NOT EXISTS weight_retrieved_at TIMESTAMPTZ;

-- Only two bases are meaningful today; a third would be a methodology
-- decision, not an implementation detail, so the constraint is deliberate.
ALTER TABLE route DROP CONSTRAINT IF EXISTS chk_route_weight_basis;
ALTER TABLE route ADD CONSTRAINT chk_route_weight_basis
    CHECK (weight_basis IS NULL OR weight_basis IN ('passenger_share', 'expenditure_share'));

-- A weight without provenance is the state this migration exists to end.
ALTER TABLE route DROP CONSTRAINT IF EXISTS chk_route_weight_has_provenance;
ALTER TABLE route ADD CONSTRAINT chk_route_weight_has_provenance
    CHECK (
        dgca_pax_weight IS NULL
        OR (weight_basis IS NOT NULL AND weight_source IS NOT NULL
            AND weight_period_start IS NOT NULL AND weight_period_end IS NOT NULL)
    );

COMMENT ON COLUMN route.dgca_pax_weight IS
    'Upper-level weight, share of the basket (not of all India). See weight_basis '
    'for what it measures and weight_source for where it came from.';
