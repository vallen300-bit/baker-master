-- BAKER_DASHBOARD_V2_CANDIDATE_INGEST_1: dedup + due + structured dismissal for
-- the candidate-ingestion layer.
--
-- Extends signal_candidates (created additive in 20260622c, already applied) so
-- the ingestion writer can:
--   * dedup candidates idempotently (AC4 / AC3.4) via a deterministic dedup_key
--     + a partial UNIQUE index — repeated quiet-thread / proactive / system
--     catches and re-bridged legacy alerts collapse to one candidate.
--   * carry a due_at for deadline-shaped candidates (feeds the dedup key + later
--     triage/verify).
--   * record a structured dismiss_reason on triage dismissal (AC10), reusing the
--     same 10-value vocabulary as verified_items.dismiss_reason.
--
-- Additive + idempotent + runner-safe: ADD COLUMN IF NOT EXISTS / CREATE INDEX
-- IF NOT EXISTS only; no CONCURRENTLY (one-tx runner). 20260622c is already
-- applied to prod, so this is a NEW migration (not an edit of an applied file).
--
-- ROLLBACK: disaster-recovery only; DOWN ships commented (runner executes raw).
-- The pytest round-trip strips the `-- ` leader, so the DOWN section below holds
-- ONLY commented SQL — prose stays here, above the markers.

-- == migrate:up ==

ALTER TABLE signal_candidates ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;

ALTER TABLE signal_candidates ADD COLUMN IF NOT EXISTS dedup_key TEXT;

ALTER TABLE signal_candidates ADD COLUMN IF NOT EXISTS dismiss_reason TEXT;

-- Structured dismissal reasons (AC10) — same set as verified_items.dismiss_reason.
-- Drop-then-add so a re-run with a widened set stays idempotent.
ALTER TABLE signal_candidates DROP CONSTRAINT IF EXISTS signal_candidates_dismiss_reason_check;
ALTER TABLE signal_candidates ADD CONSTRAINT signal_candidates_dismiss_reason_check
    CHECK (
        dismiss_reason IS NULL OR dismiss_reason IN (
            'marketing', 'duplicate', 'wrong_matter', 'stale', 'not_important',
            'already_handled', 'system_noise', 'false_deadline', 'false_promise', 'other'
        )
    );

-- AC4 / AC3.4 — one candidate per dedup_key. Partial so legacy/early rows with a
-- NULL key (written before this migration) are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_candidates_dedup
    ON signal_candidates (dedup_key)
    WHERE dedup_key IS NOT NULL;

-- AC7 — matter-aware triage filtering.
CREATE INDEX IF NOT EXISTS idx_signal_candidates_matter_status
    ON signal_candidates (matter_slug, status);
CREATE INDEX IF NOT EXISTS idx_signal_candidates_trust
    ON signal_candidates (source_trust);

-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_signal_candidates_trust;
-- DROP INDEX IF EXISTS idx_signal_candidates_matter_status;
-- DROP INDEX IF EXISTS uq_signal_candidates_dedup;
-- ALTER TABLE signal_candidates DROP CONSTRAINT IF EXISTS signal_candidates_dismiss_reason_check;
-- ALTER TABLE signal_candidates DROP COLUMN IF EXISTS dismiss_reason;
-- ALTER TABLE signal_candidates DROP COLUMN IF EXISTS dedup_key;
-- ALTER TABLE signal_candidates DROP COLUMN IF EXISTS due_at;
