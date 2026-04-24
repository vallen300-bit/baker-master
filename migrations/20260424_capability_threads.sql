-- == migrate:up ==
-- BRIEF_CAPABILITY_THREADS_1: episodic memory for Pattern-2 capabilities.
-- Hybrid thread stitching (implicit similarity + Director override, Q6-ratified)
-- per _ops/ideas/2026-04-23-ao-pm-continuity-program.md §6.
--
-- Idempotent and additive. Zero impact on existing rows in pm_state_history.
-- Applied by config/migration_runner.py on next Render boot (lesson #35/#37).

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Threads: one row per logical conversation topic.
CREATE TABLE IF NOT EXISTS capability_threads (
    thread_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pm_slug TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_turn_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    topic_summary TEXT,
    entity_cluster JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'dormant', 'resolved', 'superseded')),
    superseded_by_thread_id UUID REFERENCES capability_threads(thread_id),
    turn_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_capability_threads_pm_slug_status
    ON capability_threads (pm_slug, status, last_turn_at DESC);

CREATE INDEX IF NOT EXISTS idx_capability_threads_entity_cluster_gin
    ON capability_threads USING gin (entity_cluster);

COMMENT ON TABLE capability_threads IS
  'BRIEF_CAPABILITY_THREADS_1: per-PM conversation threads. Topic vectors live in Qdrant baker-conversations with payload {pm_slug, thread_id}; this table is the relational anchor.';

-- Turns: one row per Q/A pair (any surface).
CREATE TABLE IF NOT EXISTS capability_turns (
    turn_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id UUID NOT NULL REFERENCES capability_threads(thread_id) ON DELETE CASCADE,
    pm_slug TEXT NOT NULL,
    surface TEXT NOT NULL
        CHECK (surface IN ('sidebar','decomposer','signal','agent_tool','opus_auto','backfill','other')),
    mutation_source TEXT,
    turn_order INT NOT NULL,
    question TEXT,
    answer TEXT,
    state_updates JSONB,
    pm_state_history_id INTEGER REFERENCES pm_state_history(id) ON DELETE SET NULL,
    stitch_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_capability_turns_thread_order
    ON capability_turns (thread_id, turn_order);

CREATE INDEX IF NOT EXISTS idx_capability_turns_pm_slug_created
    ON capability_turns (pm_slug, created_at DESC);

COMMENT ON COLUMN capability_turns.stitch_decision IS
  'BRIEF_CAPABILITY_THREADS_1: {score, matched_on, cosine, entity_overlap, alternatives:[{tid,score}]} for later tuning.';

COMMENT ON COLUMN capability_turns.mutation_source IS
  'Mirrors pm_state_history.mutation_source (Amendment H §H4). Door-level attribution for audit.';

-- Link state snapshots to originating thread. Additive + nullable.
-- No _ensure_pm_state_history_base exists in memory/store_back.py (grepped 2026-04-24);
-- DDL lives ONLY here per lesson #37.
ALTER TABLE pm_state_history
    ADD COLUMN IF NOT EXISTS thread_id UUID REFERENCES capability_threads(thread_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_pm_state_history_thread_id
    ON pm_state_history (thread_id) WHERE thread_id IS NOT NULL;

COMMENT ON COLUMN pm_state_history.thread_id IS
  'BRIEF_CAPABILITY_THREADS_1: thread attribution for audit-trail snapshots. NULL for rows pre-dating this migration.';

-- == migrate:down ==
-- Reversal only if threads feature is deliberately retired. Paste manually:
--
-- BEGIN;
-- ALTER TABLE pm_state_history DROP COLUMN IF EXISTS thread_id;
-- DROP TABLE IF EXISTS capability_turns;
-- DROP TABLE IF EXISTS capability_threads;
-- COMMIT;
