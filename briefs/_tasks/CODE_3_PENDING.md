---
status: PENDING
brief_id: M365_QDRANT_EMBED_GAP_DIAGNOSE_1
dispatch: M365_QDRANT_EMBED_GAP_DIAGNOSE_1
to: b3
dispatched_by: lead
priority: HIGH
Harness-V2: applies (production ingestion/embedding pipeline) — Context Contract + task class + done rubric + gate plan below
---

# M365_QDRANT_EMBED_GAP_DIAGNOSE_1 — post-migration M365 mail not in Qdrant; semantic search + Cortex blind

## Context (Context Contract)

Sibling to `M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1` (b2, in flight). b2 + Codex Reviewer both confirmed: M365/Outlook mail IS ingested into Postgres `email_messages` (Spanyi 6 Jun present, ~200 rows since 2026-06-03), but is **absent from Qdrant semantic search**. Evidence: prod `/api/search` (unified semantic) at threshold 0.0 returns ZERO for the Spanyi hearing email; the freshest email/conversation content in Qdrant is Feb–Mar 2026. b2's note: `_process_email_threads` runs `pipeline.run()` (embed) + `store_email_message` (Postgres) — the Postgres mirror works, but the Qdrant side looks like it's missing all post-migration mail.

**Why it matters (broader than the tool bug):** any semantic-search-dependent surface — `baker_search` / `/api/search/unified`, Cortex Phase 1 sense, dashboard scans — is silently blind to post-6/3 mail. b2's PR fixes the MCP tool surface (Postgres read); this brief fixes the embedding pipeline so semantic surfaces see recent mail again.

## Problem

Post-migration M365 mail reaches Postgres `email_messages` but does not land in Qdrant, so semantic search / Cortex cannot retrieve it. Diagnose why, then fix.

## Phase 1 — DIAGNOSIS (read-only, NO code changes, report first)

Trace the embedding path for a graph_mail-sourced thread and find where it drops:

1. `_process_email_threads` (`triggers/email_trigger.py` ~838-850) calls both `pipeline.run()` (embed → Qdrant) and `store_email_message` (Postgres). Confirm the actual code path: does `pipeline.run()` actually execute + embed for graph_mail-sourced threads, or is there an early-return / branch / exception that skips embedding while the Postgres mirror still writes?
2. Compare a Gmail-sourced thread (pre-6/3, IS in Qdrant) vs a Graph-sourced thread (post-6/3, NOT in Qdrant) through the same path — what differs (payload shape, source field, classification gate, dedup, an exception swallowed)?
3. Check Qdrant directly: are there ANY points for post-6/3 email content? What collection, what filter. Is the embed call failing silently (caught exception, rolled back) or never invoked?
4. Confirm scope: is this email-only, or are other post-migration sources (e.g. graph-sourced anything) also missing from Qdrant?

**STOP after Phase 1.** Bus-post `lead` findings + smallest fix plan (and whether a backfill of the ~200 post-6/3 rows into Qdrant is needed once the forward path is fixed). Do NOT implement until lead greenlights. Coordinate with b2 on the bus if your code paths touch (`_process_email_threads` is shared).

## Current State

To be established by Phase 1 — diagnosis-first. Do not assume; reproduce the Qdrant absence (prod `/api/search` for the Spanyi email) before forming the fix.

## Phase 2 — FIX (only on lead greenlight)

Scope set by Phase 1. Likely: repair the embed path for graph-sourced mail (forward fix) + a one-time backfill of post-6/3 `email_messages` into Qdrant. Tests first (reproduce the gap with a failing test). Backfill must be Postgres-read → embed in bounded batches (no OOM — see lessons.md startup-backfill OOM anti-pattern); run once, not on every deploy.

## Files Modified (Phase 2, expected — confirm in Phase 1)

- `triggers/email_trigger.py` — `_process_email_threads` embed path
- `kbl/` / `memory/` — pipeline.run() / retriever embedding wiring
- possibly a one-shot backfill script under `scripts/`

## Do NOT Touch

- The Postgres `email_messages` write path — it works; do not destabilize it.
- b2's MCP tool-surface PR (`baker_email_search`) — separate PR, separate lane.
- Outbound/send paths — read/ingestion only.

## Verification (done rubric — task class: cross-layer production bugfix)

NOT "tests pass". Done =
1. Prod `/api/search` (semantic) returns the Spanyi 6 Jun email after the fix + backfill.
2. A NEW M365 email becomes semantically searchable within one ingestion cycle (forward path proven, not just backfill).
3. Qdrant point count for post-6/3 email content > 0 and tracks `email_messages`.
4. POST_DEPLOY_AC_VERDICT v1 posted with live evidence.

## Quality Checkpoints

1. AC1: Phase 1 findings on bus `lead` with command outputs (no "by inspection").
2. AC2: Spanyi email semantically findable post-fix (live prod evidence).
3. AC3: forward embed path proven on new mail (not just backfill).
4. AC4: backfill bounded-batch, run-once, no deploy-time OOM.

## Verification SQL / probes

```sql
-- Postgres side (works): post-6/3 graph mail present
SELECT COUNT(*), MAX(received_at) FROM email_messages WHERE received_at > '2026-06-03' LIMIT 1;
```
Qdrant side: probe the collection for any post-6/3 email points (confirm collection name in Phase 1).

## Gate plan

G0 codex on diagnosis + fix plan → lead reviews Phase 1 → G2 /security-review on the Phase 2 diff → G3 codex on implementation → lead merges → POST_DEPLOY_AC live-verified (semantic Spanyi find).

## Escalation

- If the root cause is shared with b2's path and the two fixes must land together → flag to lead for sequencing; do not merge conflicting edits to `_process_email_threads` independently.
