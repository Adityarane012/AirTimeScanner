-- NOT CURRENTLY USED — the project runs on Supabase-hosted Postgres for now
-- (see IMPLEMENTATION.md). Kept here as the fallback path if you ever want to
-- move back to a fully local Postgres instance instead.
--
-- Run ONCE, by you, as the postgres superuser. Not by Claude — this keeps the
-- superuser password out of the session entirely; only a scoped app password
-- ever goes in .env.
--
-- How to run (pick one):
--   pgAdmin 4 (installed alongside PostgreSQL 18): open Query Tool on any DB, paste, execute.
--   psql:  "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -f scripts\bootstrap_db.sql
--
-- 1. Change the password below to something of your choosing before running.
--    Never commit a real password here — this file is tracked in git.
-- 2. Put that same password into .env as part of DATABASE_URL (see env.example).

CREATE ROLE apix_app WITH LOGIN PASSWORD 'CHANGE_ME';
CREATE DATABASE apix OWNER apix_app;

-- Nothing else needed here — 0001_init.sql (run as apix_app against the apix
-- database) creates the actual schema.
