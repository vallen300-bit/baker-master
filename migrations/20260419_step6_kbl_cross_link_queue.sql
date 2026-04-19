-- STEP6-FINALIZE-IMPL: cross-link staging queue (Option C)
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STEP6-FINALIZE-IMPL (2026-04-19)
-- Director-ratified design: Render (Step 6) performs zero vault FS writes;
-- Step 6 UPSERTs one row per related_matter into kbl_cross_link_queue,
-- then Step 7 on Mac Mini reads unrealized rows + appends the stub_row
-- verbatim to wiki/<target_slug>/_links.md under flock, setting
-- realized_at = NOW() in the same transaction. Honours Inv 9
-- (Mac Mini single writer) structurally.
--
-- Additive, idempotent.
--
-- PK (source_signal_id, target_slug):
--   Gives us free idempotency — re-running Step 6 on the same signal
--   produces the same rows (UPSERT with EXCLUDED values). Spec §4.2
--   idempotency-by-signal-id is now a PG constraint, not an application
--   regex scan.
--
-- idx_kbl_cross_link_queue_unrealized:
--   Partial index that Step 7 hits on every tick to find
--   `realized_at IS NULL` rows. Keeps tick reads O(unrealized) not
--   O(all-history).
--
-- idx_kbl_cross_link_queue_target_slug:
--   Step 7 batches all unrealized rows for one target_slug into a single
--   file-append + single git commit. (target_slug, created_at DESC)
--   ordering gives the natural newest-first layout for _links.md.
--
-- Apply order: manual operator run.
--   BEGIN; \i migrations/20260419_step6_kbl_cross_link_queue.sql ; COMMIT;


-- == migrate:up ==

BEGIN;

CREATE TABLE IF NOT EXISTS kbl_cross_link_queue (
    source_signal_id BIGINT NOT NULL REFERENCES signal_queue(id) ON DELETE CASCADE,
    target_slug      TEXT NOT NULL,
    stub_row         TEXT NOT NULL,
    vedana           TEXT,
    source_path      TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    realized_at      TIMESTAMPTZ,
    PRIMARY KEY (source_signal_id, target_slug)
);

CREATE INDEX IF NOT EXISTS idx_kbl_cross_link_queue_unrealized
    ON kbl_cross_link_queue (created_at)
    WHERE realized_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_kbl_cross_link_queue_target_slug
    ON kbl_cross_link_queue (target_slug, created_at DESC);

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run.
--
-- BEGIN;
-- DROP INDEX IF EXISTS idx_kbl_cross_link_queue_target_slug;
-- DROP INDEX IF EXISTS idx_kbl_cross_link_queue_unrealized;
-- DROP TABLE IF EXISTS kbl_cross_link_queue;
-- COMMIT;
