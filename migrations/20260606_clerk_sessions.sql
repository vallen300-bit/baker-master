-- CLERK_WORKBENCH_2: persistent Clerk workbench sessions.
-- Session ids are generated in Python as UUID text to avoid extension coupling.

CREATE TABLE IF NOT EXISTS clerk_sessions (
    session_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    draft_content TEXT,
    draft_path TEXT,
    source_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clerk_sessions_created_at
    ON clerk_sessions (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clerk_sessions_status
    ON clerk_sessions (status);
