---
status: PENDING
brief_id: EMAIL_ATTACHMENT_STORE_1
to: b3
from: lead
dispatched_by: lead
dispatched_at: 2026-06-10
reply_target: lead (bus)
task_class: backend feature — new table + store module + read endpoint
gate_plan: G1 pytest literal -> G3 codex code gate (lead posts ask) -> lead merge -> POST_DEPLOY_AC after deploy
arc: EMAIL_HISTORY_BACKFILL (5 lanes; this lane ships FIRST — b1/b2/deputy-codex build against this schema)
---

# EMAIL_ATTACHMENT_STORE_1 — attachment persistence (schema + store + read endpoint)

## Context

Director-ratified 2026-06-10: historical backfill of bluewin + brisengroup mailboxes INCLUDING attachments. No attachment persistence exists today (tools/gmail.py reads live via API only). This lane builds the shared layer; b1 (IMAP backfill), b2 (Graph backfill), deputy-codex (forward parity) consume it. Schema LOCKED by lead — objections via bus, do not redesign.

## Problem

email_messages stores bodies only. Attachments need a durable, deduped, size-capped store with an authenticated retrieval path.

## Files Modified

- migrations/<next-number>_email_attachments.sql — NEW (follow existing numbering)
- kbl/attachment_store.py — NEW
- outputs/dashboard.py — ONE endpoint GET /api/attachments/{id} (X-Baker-Key auth; bytes + mime; 404 metadata_only/missing; 401 unauth). SURGICAL — grep an existing simple GET route and mirror; never page the file.
- tests/test_attachment_store.py — NEW

## Locked schema

CREATE TABLE IF NOT EXISTS email_attachments (
  id BIGSERIAL PRIMARY KEY,
  message_id TEXT NOT NULL,
  source TEXT NOT NULL,                -- 'bluewin' | 'graph' | 'email'
  filename TEXT, mime_type TEXT, size_bytes BIGINT,
  content_sha256 TEXT NOT NULL,
  storage TEXT NOT NULL DEFAULT 'db',  -- 'db' | 'metadata_only' (>5MB)
  data BYTEA,                          -- NULL when metadata_only
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (message_id, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_email_attachments_message ON email_attachments (message_id);
CREATE TABLE IF NOT EXISTS email_backfill_progress (
  source TEXT PRIMARY KEY, cursor TEXT,
  done_count BIGINT DEFAULT 0, total_estimate BIGINT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

Store API (exact): insert_attachment(message_id, source, filename, mime_type, payload_bytes) -> int|None (sha256 computed; >5MB -> metadata_only, data=NULL; ON CONFLICT DO NOTHING -> existing id) · get_attachment(att_id) -> dict|None · attachment_exists(message_id, sha256) -> bool. All DB calls try/except. Plain functions + existing pool helper (mirror kbl/ pattern, no new singletons).

## Verification

pytest tests/test_attachment_store.py -v literal green (TEST_DATABASE_URL live-PG; auto-skip intact). Round-trip: insert 2 (one >5MB synthetic -> metadata_only), endpoint fetch with auth, 401 without.

## Acceptance criteria

- AC1: migration applies clean (IF NOT EXISTS) on fresh + existing DB.
- AC2: dedup proven by test (same payload twice -> one row).
- AC3: endpoint bytes + content-type correct; 404 metadata_only; 401 unauth.
- AC4: literal pytest output in ship report.

## Done rubric / done-state class

Done = PR open + G3 codex pass + literal pytest green + ship report on bus to lead carrying done-state class ("merged-pending-deploy" vs "deployed"). NOT done at "code written".

## Context-economy rules (HARD — no auto-compaction exists)

- Read ONLY files named above + one mirrored route. Never page dashboard.py.
- Command output to /tmp files; read tails only. No log dumps in context.
- If context >70%: commit, push branch, bus handoff to lead, STOP.
