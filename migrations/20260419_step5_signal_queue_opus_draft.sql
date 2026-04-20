-- == migrate:up ==
-- STEP5-OPUS-IMPL: signal_queue + circuit-breaker state for Step 5 Opus synthesis
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STEP5-OPUS-IMPL (2026-04-19)
-- Additive, idempotent. ADD COLUMN IF NOT EXISTS + CREATE TABLE IF NOT EXISTS.
--
-- opus_draft_markdown
--   TEXT (free-form Markdown — frontmatter + body). Written by
--   kbl.steps.step5_opus.synthesize() on every routing path
--   (FULL_SYNTHESIS via Opus, STUB_ONLY + SKIP_INBOX via deterministic stubs).
--   No CHECK constraint — schema validation happens in Step 6 finalize().
--   Inv 6: every step5 outcome writes this column so Step 6 has a draft
--   to validate; pipeline never skips the next hop.
--
-- kbl_circuit_breaker
--   Across-signal consecutive-failure counter for the Opus call path.
--   Pre-call check gates can_fire_step5(); 3+ consecutive Opus failures
--   open the breaker and route subsequent signals to paused_cost_cap.
--   Minimal single-row table (key='opus_step5') — the column-per-circuit
--   shape lets future circuits (e.g. opus_step6 when Step 6 goes LLM)
--   add rows without altering the schema.
--
--   NOTE: the pre-existing anthropic_circuit_open state in
--   kbl_runtime_state is driven by kbl/retry.py and covers a distinct
--   concern (per-call 5xx ladder). Step 5's circuit tracks across-signal
--   R3-exhaust failures. Both exist intentionally.
--
-- Apply order: manual operator run.
--   BEGIN; \i migrations/20260419_step5_signal_queue_opus_draft.sql ; COMMIT;


-- == migrate:up ==

BEGIN;

ALTER TABLE signal_queue
  ADD COLUMN IF NOT EXISTS opus_draft_markdown TEXT;

CREATE TABLE IF NOT EXISTS kbl_circuit_breaker (
    circuit_key            TEXT PRIMARY KEY,
    consecutive_failures   INT NOT NULL DEFAULT 0,
    opened_at              TIMESTAMPTZ,
    last_failure_at        TIMESTAMPTZ,
    last_probe_at          TIMESTAMPTZ,
    updated_by             TEXT
);

-- Seed the opus_step5 circuit so can_fire_step5() reads don't race the
-- first write. ON CONFLICT preserves live state across re-runs.
INSERT INTO kbl_circuit_breaker (circuit_key, consecutive_failures, updated_by)
VALUES ('opus_step5', 0, 'kbl_b_step5_bootstrap')
ON CONFLICT (circuit_key) DO NOTHING;

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run.
--
-- BEGIN;
-- DROP TABLE IF EXISTS kbl_circuit_breaker;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS opus_draft_markdown;
-- COMMIT;
