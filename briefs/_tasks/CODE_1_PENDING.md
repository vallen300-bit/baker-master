---
status: PENDING
brief_id: LOWPRI_CLEANUP_PAIR_1
to: b1
from: lead
dispatched_by: lead
dispatched: 2026-06-16
task_class: bug-fix (pair)
tier: A (cleanup; pre-authorized)
harness_v2: applies
---

# CODE_1_PENDING — LOWPRI_CLEANUP_PAIR_1

Two independent, contained real defects. Fix both in one PR (both small). Fail-loud:
if either turns out larger than scoped, ship the clean one and surface the other to lead.

**RACI:** accountable=lead, responsible=b1, consulted=codex (G3).

## Context Contract
- Repo: baker-master, branch off `main`. Deploy = Render auto on merge.
- Both are recurring/observed real defects (sources cited), NOT cosmetic.
- **DB schema discipline (Lessons #2/#3/#37):** verify EVERY column name against the live
  DB with `SELECT column_name FROM information_schema.columns WHERE table_name='X'`
  before changing or asserting it. Do not trust this brief's column claims blind.
- On Defect 2: read the REAL boot exception text. Do not guess the cause.

---

## DEFECT 1 — /api/memory/health schema mismatch
**Source:** b3 side-obs #2921 — `column "received_at" does not exist`; endpoint untouched since aed793d.

**Root cause (lead-diagnosed, verify):** `outputs/dashboard.py:13974` queries
`whatsapp_messages WHERE received_at > NOW() - INTERVAL '90 days'`. Real column is
`timestamp` — 5 other call sites use `MAX(timestamp) FROM whatsapp_messages`
(`triggers/sentinel_health.py:759`, `triggers/briefing_trigger.py:214`). Only this
endpoint uses `received_at`, so the whole single-SELECT Tier-1 query fails and the
endpoint returns `{"error": ...}`.

**Fix:** confirm the real column via `information_schema`, then change `received_at`
→ correct name at line 13974. Same SELECT also refs `email_messages.received_date`,
`alerts.created_at`, `conversation_memory.created_at` — verify each exists on live;
fix any that also mismatch (note: `email_messages` is a known outlier table — Lesson #37).

**AC1:** `GET /api/memory/health` (X-Baker-Key) returns the tier1/tier2/tier3/archive
stats object, NOT `{"error": ...}`. Paste the live curl output in the ship report.

---

## DEFECT 2 — startup noise: deadlines + VIP-seed FK errors each boot
**Source:** b3 side-obs #2921 — deadlines table-creation + VIP-seed FK errors each boot.

**Where:** `models/deadlines.py` — `seed_vip_contacts()` (~line 137, called at module
load line 560) does `DELETE FROM vip_contacts` then re-INSERT when row-count != 11. A
`contacts` VIEW depends on `vip_contacts`; a DB-level FK/constraint may make the DELETE
(or the table ALTERs at line 77+) error every boot. Static grep found no in-repo FK —
so read the REAL boot exception, don't guess.

**Task:** reproduce the actual logged error (boot the app locally, or exercise
`create_tables()` + `seed_vip_contacts()` against TEST_DATABASE_URL). Root-cause it.
Likely fixes (pick what the evidence supports):
- FK references `vip_contacts` → DELETE-then-reinsert is wrong; switch to UPSERT
  (`INSERT ... ON CONFLICT (<unique col>) DO UPDATE`) keyed on a stable unique column
  (`email` or `whatsapp_id`; add the UNIQUE constraint if absent) so rows are never deleted.
- Noise is the `ALTER TABLE`/view-recreate firing every boot → gate it to log at INFO
  only when it actually changes something.
- Net goal: clean boot log — no ERROR lines from `models/deadlines.py`.
- Every except keeps `conn.rollback()` before any retry (python-backend rule); current
  code commits-or-errors — preserve fault-tolerance.

**AC2:** Fresh boot (or seed exercised against live PG) produces zero ERROR-level log
lines from `models/deadlines.py`. Paste before (error) + after (clean) log lines.

---

## Gate plan
- G1: `pytest` literal run green (paste tail). Add a cheap regression test for Defect 1
  — SQL-assertion test asserting the canonical column appears in the query string
  (Lesson #44 `_FakeCursor.execute` monkey-patch pattern is the cheap version).
- Syntax check both files: `python3 -c "import py_compile; py_compile.compile('<f>', doraise=True)"`.
- G3: request codex gate after PR open (bus-post `lead`, topic `gate-request/prNNN`).
- Post-deploy: emit `POST_DEPLOY_AC_VERDICT v1` covering AC1 + AC2 after merge.
- Bus-post on ship + gate-request + post-deploy per agent-bus-posting-contract.

## Done rubric
DONE = AC1 live-curl clean + AC2 clean-boot-log + pytest green + codex G3 PASS +
post-deploy AC verdict posted. "Compile-clean" is NOT done (Lesson #8).

## Do NOT touch
- Don't widen scope to other endpoints/tables. Two defects only.
- Don't edit applied migrations. Prefer an app-code fix; a new migration only if a
  UNIQUE constraint is genuinely required for the UPSERT (then new migration, never edit).
