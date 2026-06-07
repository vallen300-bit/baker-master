-- CLERK_QWEN3_INTERACTIVE_REPL_1: real usage telemetry for Clerk sessions.
-- Nullable by design: CLI renders n/a for any field the model API/config does not supply.

ALTER TABLE clerk_sessions
    ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS completion_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS total_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS context_window_used INTEGER,
    ADD COLUMN IF NOT EXISTS context_window_max INTEGER,
    ADD COLUMN IF NOT EXISTS session_cost_usd NUMERIC(12, 8);
