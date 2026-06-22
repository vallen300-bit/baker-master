---
status: PARKED (superseded in b2 mailbox by AI_HOTEL_LAB_PROJECTION_ADMIN_STORE_1 2026-06-22; reclaimable)
brief_id: STARTUP_NOISE_DEADLINES_VIP_FIX_1
to: b2
from: lead
dispatched_by: lead
dispatched: 2026-06-16
task_class: bug-fix
tier: A (cleanup; pre-authorized)
harness_v2: applies
---

# CODE_2_PENDING — STARTUP_NOISE_DEADLINES_VIP_FIX_1

Single contained defect. Independent of b1's health-endpoint brief — work in parallel.

**RACI:** accountable=lead, responsible=b2, consulted=codex (G3).

## Context Contract
- Repo: baker-master, branch off `main`. Deploy = Render auto on merge.
- **Read the REAL boot exception text. Do not guess the cause.**
- DB schema discipline (Lessons #2/#3/#37): verify column/constraint names via
  `information_schema` before relying on them.

## Defect — startup noise: deadlines + VIP-seed FK errors each boot
**Source:** b3 side-obs #2921 — deadlines table-creation + VIP-seed FK errors each boot.

**Where:** `models/deadlines.py` — `seed_vip_contacts()` (~line 137, called at module
load line 560) does `DELETE FROM vip_contacts` then re-INSERT when row-count != 11. A
`contacts` VIEW depends on `vip_contacts` (created ~line 127); a DB-level FK/constraint
may make the DELETE (or the table ALTERs at line 77+) error every boot. Static grep
found no in-repo FK — so reproduce and read the actual error.

**Task:** reproduce the actual logged error (boot the app locally, or exercise
`create_tables()` + `seed_vip_contacts()` against TEST_DATABASE_URL). Root-cause it.
Likely fixes (pick what the evidence supports):
- FK references `vip_contacts` → DELETE-then-reinsert is wrong; switch to UPSERT
  (`INSERT ... ON CONFLICT (<unique col>) DO UPDATE`) keyed on a stable unique column
  (`email` or `whatsapp_id`; add the UNIQUE constraint if absent) so rows are never deleted.
- Noise is the `ALTER TABLE`/view-recreate firing every boot → gate it to log at INFO
  only when it actually changes something.
- Net goal: clean boot log — no ERROR lines from `models/deadlines.py`.
- Keep `conn.rollback()` in except before any retry (python-backend rule); preserve
  the existing fault-tolerant try/except wrapping.

## AC
**AC2:** Fresh boot (or seed exercised against live PG) produces zero ERROR-level log
lines from `models/deadlines.py`. Paste before (error) + after (clean) log lines.

## Gate plan
- G1: `pytest` literal green (paste tail).
- Syntax check before commit.
- G3: request codex gate after PR open (bus-post `lead`, topic `gate-request/prNNN`).
- Post-deploy: emit `POST_DEPLOY_AC_VERDICT v1` covering AC2 after merge.
- Bus-post on ship + gate-request + post-deploy per agent-bus-posting-contract.

## Done rubric
DONE = AC2 clean-boot-log + pytest green + codex G3 PASS + post-deploy AC verdict posted.
"Compile-clean" is NOT done (Lesson #8).

## Do NOT touch
- Defect scope = deadlines/VIP seed boot path only. b1 owns the health endpoint.
- Don't edit applied migrations; new migration only if a UNIQUE constraint is truly
  required for the UPSERT (then new migration, never edit an applied one).
