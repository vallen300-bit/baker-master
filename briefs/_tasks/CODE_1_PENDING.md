---
status: PENDING
brief_id: CORTEX_RETIRE_PHASE1_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-07-23 ~18:05Z
reply_target: lead (bus topic ship/cortex-retire-phase1-1; file fallback briefs/_reports/)
task_class: production backend, reversible guard, one repo (baker-master)
note: file-drop delivery (established b1 channel); full brief is in-repo — no bus dependency
---

# CODE_1_PENDING — b1: CORTEX_RETIRE_PHASE1_1

Director ratified Cortex retirement 2026-07-23. Full brief:
`briefs/BRIEF_CORTEX_RETIRE_PHASE1_1.md` @3e55927d (this repo, main — pull first).
Decision memo: `briefs/_plans/CORTEX_RETIREMENT_MEMO_2026-07-23.md`.

Summary: (1) `CORTEX_RETIRED` env guard, DEFAULT TRUE — 410 `cortex_retired` on
`POST /api/cortex/trigger`, `POST /api/cortex/run`, and the gate-decide fire path
(background helper: log+return, never crash); (2) gate stuck-cycle sentinel
registration off when retired; (3) new migration closes the 2 `tier_b_pending`
rows to `rejected` (memo cited); (4) tests: 410 default + flag-off rollback
variants. Do NOT touch `orchestrator/cortex_*` (Phase 2), applied migrations,
GET cortex routes, or the history tables.

Ship: branch `b1/cortex-retire-phase1-1`, receipt on bus to lead with
repo+branch+sha (ls-remote confirmed, never PR numbers). Codex gate follows;
lead merges on PASS.
