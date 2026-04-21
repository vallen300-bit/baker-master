-- == migrate:up ==
-- BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1: coerce signal_queue.hot_md_match
-- from BOOLEAN (legacy KBL-19 bootstrap DDL in memory/store_back.py
-- `_ensure_signal_queue_base`) to TEXT (BRIDGE_HOT_MD_AND_TUNING_1
-- semantic — verbatim matched pattern line, NULL when another axis fired).
--
-- Context: the original BRIDGE_HOT_MD_AND_TUNING_1 migration
-- (20260421_signal_queue_hot_md_match.sql) used
-- `ADD COLUMN IF NOT EXISTS hot_md_match TEXT`. On pre-existing DBs
-- where the column already existed as BOOLEAN — per the KBL-19-era
-- bootstrap DDL — the IF NOT EXISTS guard made that migration a silent
-- no-op and the live column stayed BOOLEAN. The bridge then bound TEXT
-- pattern values ("Lilienmatt", "Hagenauer", etc.) into a BOOLEAN column
-- and every tick aborted with:
--
--     invalid input syntax for type boolean: "Lilienmatt"
--
-- Diagnostic report: briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md
--
-- Safety on data:
--   * Live DB audit pre-migration: 16/16 rows have hot_md_match IS NULL.
--   * Zero non-NULL values means the ::text USING cast has zero data-loss
--     surface. A non-NULL boolean would become 'true' / 'false' text under
--     the cast — acceptable, but moot here.
--
-- Idempotency:
--   * The DO block guards on information_schema — no-op when the column
--     is already TEXT (fresh DB, or this migration re-run).
--   * ADD COLUMN IF NOT EXISTS is a belt-and-suspenders for DBs where the
--     bootstrap DDL never ran (ephemeral test DBs, new Neon branches).

ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS hot_md_match TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'signal_queue'
           AND column_name = 'hot_md_match'
           AND data_type  = 'boolean'
    ) THEN
        ALTER TABLE signal_queue
            ALTER COLUMN hot_md_match TYPE TEXT
            USING hot_md_match::text;
    END IF;
END $$;

COMMENT ON COLUMN signal_queue.hot_md_match IS
  'BRIDGE_HOT_MD_AND_TUNING_1: hot.md pattern (one line) that promoted this signal; NULL when another axis fired. TEXT type enforced by BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1 (2026-04-21 evening) after pre-existing legacy BOOLEAN bootstrap DDL was detected in live production.';


-- == migrate:down ==
-- Rolling back to BOOLEAN destroys all non-NULL TEXT values. We do not
-- support that path in normal operation. If you truly need it (only on
-- deliberate retirement of the hot.md axis), paste into psql:
--
-- BEGIN;
-- ALTER TABLE signal_queue
--     ALTER COLUMN hot_md_match TYPE BOOLEAN
--     USING (hot_md_match IS NOT NULL);
-- COMMIT;
--
-- Note this reduces the matched pattern to a mere "did something match"
-- bit — the original BOOLEAN semantic from the KBL-19 era. Use only
-- when the bridge's axis-5 attribution is being torn out entirely.
