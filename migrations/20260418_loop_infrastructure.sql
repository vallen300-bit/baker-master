-- LOOP-SCHEMA-1: Learning Loop infrastructure tables
-- Ticket: briefs/_tasks/CODE_1_PENDING.md LOOP-SCHEMA-1 (2026-04-18)
-- CHANDA §2 Leg 2 (Capture) + Leg 3 (Flow-forward) storage layer.
-- Also unblocks B2 Step 0 review S5 + S6 and B3 CHANDA audit Flag 1.
--
-- Three tables, additive, idempotent (IF NOT EXISTS throughout).
-- Writer code lives in KBL-B impl + KBL-C — NOT in this PR.
--
-- Notes on FK columns referencing signal_queue.id
-- -----------------------------------------------
-- Task brief specifies `BIGINT` for signal_id / source_signal_id columns.
-- Current schema declares signal_queue.id as SERIAL (INTEGER PRIMARY KEY)
-- per briefs/_drafts/KBL_A_SCHEMA.sql §46. The BIGINT column can hold any
-- INTEGER value (upward-compat), so inserts work; however PostgreSQL will
-- NOT accept a `REFERENCES signal_queue(id)` FK constraint across the
-- INTEGER/BIGINT type boundary without an explicit type match. For that
-- reason we follow the task brief LITERALLY:
--   * BIGINT storage (matches spec)
--   * No REFERENCES clause (matches spec comment wording)
-- If enforced referential integrity is desired post-merge, either upgrade
-- signal_queue.id to BIGSERIAL or switch these columns to INTEGER. Flagged
-- in the PR body.
--
-- Apply order: manual operator run (no migration framework in repo yet).
--   BEGIN; \i migrations/20260418_loop_infrastructure.sql ; COMMIT;
-- Rollback: paste the DOWN block at the bottom into psql.


-- == migrate:up ==

BEGIN;

-- feedback_ledger — CHANDA §2 Leg 2 Capture.
-- Every Director action (promote, correct, ignore, ayoniso_respond,
-- ayoniso_dismiss) writes a row here atomically with the primary effect.
-- If this write fails, the Director action fails — no best-effort, no
-- "retry tomorrow". The ledger IS the learning signal to Leg 3.
CREATE TABLE IF NOT EXISTS feedback_ledger (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    action_type    TEXT NOT NULL,       -- 'promote' | 'correct' | 'ignore' | 'ayoniso_respond' | 'ayoniso_dismiss'
    target_matter  TEXT,                -- slug from slug_registry, nullable for cross-matter actions
    target_path    TEXT,                -- vault path of affected wiki entry, nullable for non-vault actions
    signal_id      BIGINT,              -- FK to signal_queue.id (unenforced — see type note at top of file)
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- action-specific detail
    director_note  TEXT                 -- free-text rationale, optional
);
CREATE INDEX IF NOT EXISTS idx_feedback_ledger_created_at ON feedback_ledger(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_ledger_matter ON feedback_ledger(target_matter);


-- kbl_layer0_hash_seen — B2 Step 0 review §S5 (72h dedupe).
-- content_hash = sha256 of normalized signal content. TTL-based eviction
-- (operator or cron prunes where ttl_expires_at < now()).
CREATE TABLE IF NOT EXISTS kbl_layer0_hash_seen (
    content_hash     TEXT PRIMARY KEY,           -- sha256 of normalized content
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ttl_expires_at   TIMESTAMPTZ NOT NULL,
    source_signal_id BIGINT,                     -- FK to signal_queue.id (unenforced — see type note)
    source_kind      TEXT NOT NULL               -- 'email' | 'whatsapp' | 'meeting_transcript' | 'scan_query'
);
CREATE INDEX IF NOT EXISTS idx_kbl_layer0_hash_ttl ON kbl_layer0_hash_seen(ttl_expires_at);


-- kbl_layer0_review — B2 Step 0 review §S6 (1-in-50 drop sampling queue).
-- Every 50th signal dropped by Layer 0 gets sampled here so Director can
-- spot-audit false positives. reviewed_at=NULL means pending review.
CREATE TABLE IF NOT EXISTS kbl_layer0_review (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal_id       BIGINT NOT NULL,             -- FK to signal_queue.id (unenforced — see type note)
    dropped_by_rule TEXT NOT NULL,               -- rule name that triggered drop
    signal_excerpt  TEXT NOT NULL,               -- first 500 chars of payload for quick Director scan
    source_kind     TEXT NOT NULL,
    reviewed_at     TIMESTAMPTZ,                 -- NULL = pending, set when Director clicks through
    review_verdict  TEXT                         -- 'correct_drop' | 'false_positive' | 'ambiguous', NULL if unreviewed
);
CREATE INDEX IF NOT EXISTS idx_kbl_layer0_review_pending
    ON kbl_layer0_review(created_at)
    WHERE reviewed_at IS NULL;

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run. Paste into psql when needed.
-- Ordering: reverse of UP so (unenforced) FK intent is respected.
--
-- BEGIN;
-- DROP INDEX IF EXISTS idx_kbl_layer0_review_pending;
-- DROP TABLE IF EXISTS kbl_layer0_review;
-- DROP INDEX IF EXISTS idx_kbl_layer0_hash_ttl;
-- DROP TABLE IF EXISTS kbl_layer0_hash_seen;
-- DROP INDEX IF EXISTS idx_feedback_ledger_matter;
-- DROP INDEX IF EXISTS idx_feedback_ledger_created_at;
-- DROP TABLE IF EXISTS feedback_ledger;
-- COMMIT;
