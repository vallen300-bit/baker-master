---
brief_id: M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1
status: PENDING
to: b1
from: lead
created: 2026-06-25
tier: A
depends_on: BAKER_M365_ATTACHMENT_READ_SURFACE_1 (PR #421 — tool/read surface; merge first)
---

# M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1

## Problem (diagnosed, root cause confirmed — b2 bus #4257)
M365/Graph messages whose id is in **AAQk-form (immutable-id / alternate namespace)**
have their **attachments silently skipped at ingest**, while the message **body persists**.
Evidence:
- AAMk-form ids (older, e.g. ingested 06-15): attachments persist correctly; live
  `GET /users/{u}/messages/{id}` by-id read SUCCEEDS.
- AAQk-form ids (newer, ingested 06-18 → 06-24): 0 attachment rows; live by-id Graph
  read FAILS both raw and URL-encoded (`%3D`) — not an encoding artifact.
- `triggers/graph_mail_trigger.py` fetches attachments via a per-message **by-id Graph
  call**. For AAQk-form messages that call fails → `_insert_live_attachment` never runs →
  attachments silently skipped. Body+attachments share the same AAQk id in one poll pass,
  so 0 attachments sit under the same id the body is keyed by.
- AAQk ids are NOT addressable by `GET /users/{u}/messages/{id}` as-is. They are the
  immutable-id form — require `Prefer: IdType="ImmutableId"` header OR id normalization /
  translateExchangeIds.

This is a silent-skip class bug (cf. Lesson #107 marketing-skip; G3 F1 on PR #421). It must
fail loud or handle the id-form, not drop attachments.

## Scope
1. **Ingest fix** — `triggers/graph_mail_trigger.py`: handle AAQk/immutable-id-form messages
   so the per-message attachment Graph call succeeds (set `Prefer: IdType="ImmutableId"` on
   the attachment fetch, OR normalize/translate the id). Whichever is correct per Graph docs —
   verify against live Graph behaviour, not assumption.
2. **Fail-loud** — if an attachment fetch fails for any reason, log + mark, NEVER silently
   skip. A message with `hasAttachments=true` and 0 persisted rows must be surfaced
   (counter / warning / requeue), never look identical to a true-empty message.
3. **Targeted backfill** — after the ingest fix, backfill attachments for the 6 known
   load-bearing AAQk-form messages (lilienmatt/financing-aukera): n39, n42, n44, n46, n54,
   n55 (full ids in bus #4247 / relayed #4250). Prod write — requires lead go before execute;
   propose-then-execute.
4. **Confirm** — re-fetch the 6 through the merged `baker_email_attachment_read` tool (PR
   #421); confirm bytes present (or honest true-empty if a doc genuinely has none).

## Out of scope
- The read tool itself (PR #421 — merge first).
- Re-architecting the poll pipeline.
- Localizing the M365 app signing cert onto a B-code box (over-privileged for diagnostics —
  b2 correctly declined #4257). Use the deployed env / app-auth path that already holds the
  cert for any live hasAttachments check.

## Acceptance criteria
- AC1: AAQk-form message ingested AFTER this fix persists its attachments (live or
  test-shaped proof).
- AC2: attachment-fetch failure is logged/surfaced, never silently dropped (regression test
  simulating a failed by-id fetch).
- AC3: the 6 backfilled messages return bytes via `baker_email_attachment_read` (or honest
  documented true-empty), confirmed post-backfill.
- AC4: applied migrations untouched; surgical diff (graph_mail_trigger + backfill script +
  tests).
- AC5: fault-tolerant — all Graph/DB calls in try/except, no raise to caller path.

## Gate plan
G2 codex (effort HIGH — ingest + prod-write surface) → G3 deputy AC → G4 lead (backfill is a
prod write; lead authorizes the 6-row backfill execution explicitly before it runs) → merge →
POST_DEPLOY_AC_VERDICT.

## Tests first
Reproduce the skip: a test that feeds an AAQk-form message through the attachment-fetch path
and asserts (pre-fix) attachments are dropped, (post-fix) attachments persist + failure is
surfaced.
