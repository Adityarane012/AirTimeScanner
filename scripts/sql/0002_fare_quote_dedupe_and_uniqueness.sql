-- 0002 — de-duplicate fare_quote and add the uniqueness guard that would have
-- made the Phase-1 duplicate defect fail loudly instead of silently.
--
-- Background (see tier1_indigo.py's docstring for the full account): the
-- IndiGo adapter set `collection_ts` from the tariff PDF's own issue
-- timestamp rather than the actual fetch time. The sheet is republished only
-- ~monthly, so every daily run wrote rows identical in every meaningful
-- column — same collection_ts, departure_date, total_fare and
-- raw_payload_hash — differing only in the surrogate quote_id and run_id.
-- Six rows in the table were three exact copies of two real observations.
--
-- Two changes, in order:
--   1. Collapse existing duplicate groups to their earliest row. No
--      information is lost: the discarded rows are byte-identical to the
--      survivor in every non-surrogate column.
--   2. Add a unique index at the grain the collector is actually designed to
--      produce — one observation per (source, carrier, route, departure date,
--      advance-purchase window, fare class) per calendar day of collection.
--      A same-day re-run is then idempotent rather than duplicating, and a
--      future adapter that freezes its clock the same way cannot quietly
--      accrete copies.
--
-- NOTE on grain: this deliberately keys on the UTC *date* of collection_ts,
-- not the instant. The design is a daily collector (docs/03 pipeline, one
-- scheduled run per day). If a Tier-3 source later needs intra-day
-- collection, this index is what must change first — that is the intended
-- signal, not an obstacle to route around.

BEGIN;

-- 1. Collapse exact duplicate groups, keeping the earliest by created_at.
WITH ranked AS (
    SELECT quote_id,
           ROW_NUMBER() OVER (
               PARTITION BY source, carrier, route_id, departure_date,
                            advance_purchase_days, COALESCE(fare_class, ''),
                            (collection_ts AT TIME ZONE 'UTC')::date
               ORDER BY created_at, quote_id
           ) AS rn
    FROM fare_quote
)
DELETE FROM fare_quote
WHERE quote_id IN (SELECT quote_id FROM ranked WHERE rn > 1);

-- 2. Prevent recurrence.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fare_quote_daily_observation
    ON fare_quote (
        source,
        carrier,
        route_id,
        departure_date,
        advance_purchase_days,
        COALESCE(fare_class, ''),
        ((collection_ts AT TIME ZONE 'UTC')::date)
    );

COMMIT;
