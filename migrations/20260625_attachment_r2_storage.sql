-- == migrate:up ==
-- BAKER_M365_LARGE_ATTACHMENT_FETCH_1: R2 object-storage for large attachments.
--
-- Additive extension of email_attachments (20260610, applied — NOT edited here).
-- kbl/attachment_store.py caps Neon-inline payloads at MAX_INLINE_BYTES (5 MiB):
-- payloads >5 MiB were stored metadata_only (data NULL) and were unreadable.
-- Director ratified EAGER-STORE (#4415) + deputy-codex architecture fix (#4421):
-- large payloads now live in Cloudflare R2 (kbl/object_storage.py), Neon keeps
-- metadata + <=5 MiB inline payloads only. New rows:
--   storage='r2'           -- >5 MiB bytes are in R2, not Neon (data stays NULL)
--   object_key             -- deterministic content-addressed R2 key
--   fetched_at             -- when the raw bytes were fetched + persisted
--   provider_attachment_id -- Graph attachment id the bytes were fetched by
--
-- NOTE: content_type from the brief's column list is satisfied by the EXISTING
-- mime_type column (20260610) — not duplicated, to avoid a two-column drift.
-- 'r2' simply joins 'db' | 'metadata_only' as a storage value (free-text TEXT,
-- no CHECK constraint on storage in 20260610 — nothing to alter there).

BEGIN;

ALTER TABLE email_attachments ADD COLUMN IF NOT EXISTS object_key TEXT;
ALTER TABLE email_attachments ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ;
ALTER TABLE email_attachments ADD COLUMN IF NOT EXISTS provider_attachment_id TEXT;

-- Find r2-stored rows fast when reconciling / verifying object coverage.
CREATE INDEX IF NOT EXISTS idx_email_attachments_storage
    ON email_attachments (storage);

COMMIT;

-- == migrate:down ==
-- BEGIN;
-- DROP INDEX IF EXISTS idx_email_attachments_storage;
-- ALTER TABLE email_attachments DROP COLUMN IF EXISTS provider_attachment_id;
-- ALTER TABLE email_attachments DROP COLUMN IF EXISTS fetched_at;
-- ALTER TABLE email_attachments DROP COLUMN IF EXISTS object_key;
-- COMMIT;
