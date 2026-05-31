---
dispatch: JOB_LISTENER_HARDEN_1
to: b1
from: lead
dispatched_by: lead
status: PENDING
dispatched_at: 2026-05-31T06:35:00Z
authored: 2026-05-31
brief_path: /Users/dimitry/bm-aihead1/briefs/BRIEF_JOB_LISTENER_HARDEN_1.md
target_repo: baker-master
estimated_time: ~2h
complexity: Low-Medium
brief_version: v1 (codex PASS-WITH-NITS bus #1421, factual NIT + dispatch hint folded into brief)
codex_pre_review: PASS-WITH-NITS bus #1421
reply_to: lead
ship_topic: ship/job-listener-harden-1
anchor_chat: Director 2026-05-31 — "go" after PINNED top-pick recommendation. Resume after PR #273 (SCHEDULER_JOB_LIVENESS_1) merged 522775f; deputy bus #1418 found scheduler_job_liveness + slack_poll fired but zero rows in scheduler_executions. Root cause: triggers/embedded_scheduler.py::_job_listener:47-50 silently returns on store._get_conn() == None.
supersedes: SCHEDULER_JOB_LIVENESS_1 (PR #273 shipped 522775f)
---

# b1 dispatch — JOB_LISTENER_HARDEN_1

Read `briefs/BRIEF_JOB_LISTENER_HARDEN_1.md` end-to-end before any code.

Brief cleared codex pre-review #1421 on v1 (PASS-WITH-NITS, no blockers). One factual NIT (line 59 wording about audit_sentinel writing dedupe-anchor rows) + one dispatch hint (patch `triggers.embedded_scheduler.get_listener_drop_counts` not a non-existent sentinel attr) — both folded into the brief commit `<see next push>`. No further pre-write review required.

**Scope:** patch `triggers/embedded_scheduler.py` (add `_listener_drop_count` dict + lock + `get_listener_drop_counts()` + `_record_listener_drop()` helpers; modify `_job_listener` lines 47-50 with 100ms sleep + one retry then drop-record) + patch `triggers/scheduler_liveness_sentinel.py` (local-import + append drop-hint line to alert body for both branches) + NEW `tests/test_job_listener_harden.py` (4 tests). No DB migration. No schema change.

**Test patch-target hint (per codex #1421):** for Test 3.1 / 3.2, patch `triggers.embedded_scheduler.get_listener_drop_counts` — sentinel calls it via local `from triggers.embedded_scheduler import get_listener_drop_counts` inside its alert-emit `try` block, so the sentinel module never holds a reference to monkey-patch.

**Test isolation:** clear `triggers.embedded_scheduler._listener_drop_count` in pytest fixture per test (process-local dict; otherwise leaks between cases).

**ACs:** AC1 (Render log or scheduler_executions row within 30min of deploy), AC2 (PR #273 AC1 query re-runnable), AC3 (4 PASSED literal pytest tail). NO pass-by-inspection.

**Reply target:** lead. Ship report to `briefs/_reports/B1_JOB_LISTENER_HARDEN_1_<YYYYMMDD>.md` + bus-post to `lead` with topic `ship/job-listener-harden-1`.
