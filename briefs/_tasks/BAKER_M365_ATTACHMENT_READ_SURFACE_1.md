# BRIEF: BAKER_M365_ATTACHMENT_READ_SURFACE_1 — expose (don't rebuild) M365/Graph email attachment bytes

dispatched_by: lead
assignee: b2
effort: medium
recommended_codex_g3_effort: high  # new prod read tool exposing email attachment BYTES = security surface
task_class: feature-production (new MCP read tool + possible backfill)

## Harness V2
- **Context Contract:** baden-baden-desk (#4240) is building the Lilienmatt/Aukera financing project room. It can read M365 email BODIES (baker_email_search/read, store) but cannot pull attachment BYTES. ~8 load-bearing attachments for active case 46/2026 (June 2026): Erstentwurf Darlehensvertrag + Anlage 10, Aukera fee letter, Grundbuchauszüge per 16.06.2026, Anlage 4 zum Kaufvertrag, LILIENMATT 2025 annual statements, Kaufverträge of sold units, debt-model xlsx. Dropbox holds only stale 2020-2022 versions.
- **task class:** feature-production.
- **done rubric:** the desk can retrieve the named attachment bytes/text for M365 mail through an auth-gated Baker tool; gate chain green; POST_DEPLOY_AC PASS-live.
- **gate plan:** G2 (codex/deputy) → G3 (deputy AC) → G4 lead /security-review (MANDATORY — exposes email attachment bytes) → merge → POST_DEPLOY_AC_VERDICT v1.

## CRITICAL — the backend is LARGELY BUILT. Verify + expose, do NOT rebuild.
AH1 pre-flight (2026-06-25) found:
- `migrations/20260610_email_attachments.sql` → table `email_attachments` (already exists).
- `kbl/attachment_store.py` → `insert_attachment(...)` (bytes), `insert_attachment_meta(...)`, `get_attachment(att_id)` (READ), `attachment_exists(message_id, sha256)`.
- `triggers/graph_mail_trigger.py` → `_ATTACHMENT_SELECT = "id,name,contentType,size,contentBytes,isInline"` + `_insert_live_attachment()` persists when `hasAttachments`. NOTE the non-fatal `_attachment_store_missing_logged` warning path ("Graph attachment store unavailable") — if that fired in prod, attachments were silently skipped.
- `GraphClient(GraphConfig())` exists (graph_mail_trigger.py line ~183).
- Analog to mirror: `tools/gmail.py` `baker_gmail_attachment_read` (Gmail-only, PR #257).

## Task
**STEP 1 — investigate (read-only, post findings to lead first):**
1. In PROD, is `email_attachments` populated for the desk's target messages (the 66 Aukera/Annaberg financing emails)? Row count, message_id coverage.
2. Did the "attachment store unavailable" warning fire in prod (was the 20260610 migration applied? store reachable)? Determine root cause: gap = (a) no read surface only, (b) store empty for target msgs → needs backfill, or (c) both.
3. Post the diagnosis. Then proceed to build.

**BUILD — the read surface:**
4. Add `baker_email_attachment_read` MCP tool: list attachments for a `message_id` + return bytes/text for a named/indexed attachment, reading from `kbl.attachment_store` / `email_attachments`. Mirror `baker_gmail_attachment_read`'s shape. Source-aware (store holds Gmail + M365/Graph mail). Register in the tool registry + MCP surface.

**BACKFILL — only if STEP 1 shows the store is empty for target msgs:**
5. Re-fetch attachments for the specific target message_ids via the EXISTING `GraphClient` + `graph_mail_trigger` attachment path; persist via `insert_attachment`. Do NOT re-architect ingest. If the migration was never applied in prod, apply it first (follow the migration hard rules).

## Constraints (hard)
- REUSE the existing table, store, GraphClient, and graph_mail_trigger attachment path. Do NOT rebuild Graph fetch or the schema.
- SECURITY: the new tool exposes email attachment BYTES — gate behind the same `X-Baker-Key` auth as other tools; fail-closed on missing/forged/expired; no unauth read path. (Lesson: this is why G4 /security-review is mandatory before merge.)
- All DB/API calls in try/except; fault-tolerant; never break ingest.
- Editing the applied 20260610 migration is forbidden — create a new migration if a schema change is needed.

## Acceptance criteria
- AC1: STEP-1 prod diagnosis posted (email_attachments coverage for target msgs + root cause).
- AC2: `baker_email_attachment_read` returns the attachment list for a message_id + bytes/text for a named/indexed attachment, for M365/store mail.
- AC3: the desk's named load-bearing attachments are retrievable (backfilled first if absent).
- AC4: auth-gated; read-token required; fail-closed on missing/forged; no unauth attachment read (security-review verified).
- AC5: tests added; full gate chain; `POST_DEPLOY_AC_VERDICT v1` posted, done_state DONE, writeback to briefs/_reports/.

## Reply target
Bus-post all state changes to `lead` (STEP-1 findings, gate requests, blockers, ship). Reply-target = lead.
