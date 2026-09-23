-- 0003 — allow an advance-purchase window the collector did not choose.
--
-- Until now every observation came from a Tier-1 filed tariff sheet, whose
-- departure date the collector assigns itself (collection_ts + 30 days by
-- convention). So `advance_purchase_days IN (1, 7, 15, 30)` was not a
-- constraint on the world, only on our own arithmetic.
--
-- The first Tier-3 offer source breaks that. Goibibo's route pages are the
-- one fare-search surface its robots.txt permits, and they serve a departure
-- date of Goibibo's choosing: every URL carrying a query string is disallowed
-- (`Disallow: /flights/*?*`), so the date cannot be requested. Measured on
-- 2026-09-23 across the ten basket routes, the served dates ranged from T+8
-- to T+88, and differed per route on the same day.
--
-- Two ways to store that. Round it to the nearest canonical window, which
-- would record a measurement nobody made -- the same error as writing zero
-- for an absent charge. Or record the lead time actually observed, and keep
-- these rows out of the headline index by other means. This migration takes
-- the second.
--
-- The headline index is protected in two independent places, because one of
-- them is a filter someone can forget:
--   * apix.index.engine restricts the headline to INDEX_WINDOWS (1, 7, 15,
--     30), so an uncontrolled-lead row can never reach it by construction.
--   * these rows also carry fare_class = 'tier3_offer_uncontrolled_lead'.
--
-- Safe to re-run.

ALTER TABLE fare_quote
    DROP CONSTRAINT IF EXISTS fare_quote_advance_purchase_days_check;

ALTER TABLE fare_quote
    ADD CONSTRAINT fare_quote_advance_purchase_days_check
    CHECK (advance_purchase_days BETWEEN 0 AND 365);

-- stratum_panel stores the window it aggregated, and only ever sees index
-- windows, but it has no CHECK to widen -- noted here so the next reader does
-- not go looking for one.
