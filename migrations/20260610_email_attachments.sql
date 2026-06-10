-- == migrate:up ==
-- EMAIL_ATTACHMENT_STORE_1 (EMAIL_HISTORY_BACKFILL arc, lane 1)
-- Durable, deduped, size-capped attachment store for the bluewin + brisengroup
-- historical backfill (b1 IMAP, b2 Graph, deputy-codex forward parity all write
-- against this schema). Schema LOCKED by lead 2026-06-10 — do not alter shape
-- here; objections go via bus.
--
-- email_attachments: one row per (message_id, content_sha256). Payloads >5MB
-- are stored metadata_only (data NULL) — retrieval endpoint 404s those.
-- email_backfill_progress: per-source resumable cursor for the backfill lanes.

BEGIN;

CREATE TABLE IF NOT EXISTS email_attachments (
  id BIGSERIAL PRIMARY KEY,
  message_id TEXT NOT NULL,
  source TEXT NOT NULL,                -- 'bluewin' | 'graph' | 'email'
  filename TEXT,
  mime_type TEXT,
  size_bytes BIGINT,
  content_sha256 TEXT NOT NULL,
  storage TEXT NOT NULL DEFAULT 'db',  -- 'db' | 'metadata_only' (>5MB)
  data BYTEA,                          -- NULL when metadata_only
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (message_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_email_attachments_message
    ON email_attachments (message_id);

CREATE TABLE IF NOT EXISTS email_backfill_progress (
  source TEXT PRIMARY KEY,
  cursor TEXT,
  done_count BIGINT DEFAULT 0,
  total_estimate BIGINT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

COMMIT;
