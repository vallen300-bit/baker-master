---
status: PENDING
brief_id: HEALTH_ENDPOINT_COLUMN_FIX_1
to: b1
from: lead
dispatched_by: lead
dispatched: 2026-06-16
task_class: bug-fix
tier: A (cleanup; pre-authorized)
harness_v2: applies
---

# CODE_1_PENDING — HEALTH_ENDPOINT_COLUMN_FIX_1

Single contained defect. Independent of b2's boot-noise brief — work in parallel.

**RACI:** accountable=lead, responsible=b1, consulted=codex (G3).

## Context Contract
- Repo: baker-master, branch off `main`. Deploy = Render auto on merge.
- **DB schema discipline (Lessons #2/#3/#37):** verify EVERY column name against the live
  DB with `SELECT column_name FROM information_schema.columns WHERE table_name='X'`
  before changing it. Do not trust this brief's column claims blind. `email_messages`
  is a known outlier table (Lesson #37) — verify it too.

## Defect — /api/memory/health schema mismatch
**Source:** b3 side-obs #2921 — `column "received_at" does not exist`; endpoint untouched since aed793d.

**Root cause (lead-diagnosed, verify):** `outputs/dashboard.py:13974` queries
`whatsapp_messages WHERE received_at > NOW() - INTERVAL '90 days'`. Real column is
`timestamp` — 5 other call sites use `MAX(timestamp) FROM whatsapp_messages`
(`triggers/sentinel_health.py:759`, `triggers/briefing_trigger.py:214`). Only this
endpoint uses `received_at`, so the whole single-SELECT Tier-1 query fails and the
endpoint returns `{"error": ...}`.

**Fix:** confirm the real column via `information_schema`, then change `received_at`
→ correct name at line 13974. Same SELECT also refs `email_messages.received_date`,
`alerts.created_at`, `conversation_memory.created_at` — verify each exists; fix any mismatch.

## AC
**AC1:** `GET /api/memory/health` (X-Baker-Key) returns the tier1/tier2/tier3/archive
stats object, NOT `{"error": ...}`. Paste the live curl output in the ship report.

## Gate plan
- G1: `pytest` literal green (paste tail). Add a cheap SQL-assertion regression test
  asserting the canonical column appears in the query (Lesson #44 `_FakeCursor.execute`
  monkey-patch pattern).
- Syntax check before commit.
- G3: request codex gate after PR open (bus-post `lead`, topic `gate-request/prNNN`).
- Post-deploy: emit `POST_DEPLOY_AC_VERDICT v1` covering AC1 after merge.
- Bus-post on ship + gate-request + post-deploy per agent-bus-posting-contract.

## Done rubric
DONE = AC1 live-curl clean + pytest green + codex G3 PASS + post-deploy AC verdict posted.
"Compile-clean" is NOT done (Lesson #8).

## Do NOT touch
- Defect scope = this one endpoint only. b2 owns the deadlines/VIP boot-noise defect.
- Don't edit applied migrations.
