---
dispatch: SCHEDULER_JOB_LIVENESS_1
to: b1
from: lead
dispatched_by: lead
status: CLAIMED
dispatched_at: 2026-05-30T14:50:00Z
claimed_at: 2026-05-30T15:01:00Z
claimed_by: b1
brief_version: v2 (codex PASS-WITH-NITS bus #1401, all 3 nits folded)
codex_pre_review: PASS-WITH-NITS bus #1401
prior_design_iterations:
  - v1 bus #1392 → codex FAIL-LIGHT #1395 (4 findings: registry literals + cold-start global MIN + missing jobs + dynamic intervals)
  - v2 bus #1399 → codex PASS-WITH-NITS #1401 (3 nits: import + side-effect-safe pre-flight + in-process restart caveat)
authored: 2026-05-30
brief_path: /Users/dimitry/bm-aihead1/briefs/BRIEF_SCHEDULER_JOB_LIVENESS_1.md
target_repo: baker-master
estimated_time: ~4h
complexity: Medium
reply_to: lead
ship_topic: ship/scheduler-job-liveness-1
anchor_chat: Director 2026-05-30 — "author brief for scheduler" after PR #271 (WAHA_SESSION_POLL_HARDEN_1) shipped. Codex pre-review chain caught wrong literals + cold-start bug; final design uses dynamic registry built by embedded_scheduler.py + process-local _MODULE_LOAD_TIME with explicit reset hook.
supersedes: WAHA_SESSION_POLL_HARDEN_1 (PR #271 shipped 2f2a1a9)
---

# b1 dispatch — SCHEDULER_JOB_LIVENESS_1

Read `briefs/BRIEF_SCHEDULER_JOB_LIVENESS_1.md` end-to-end before any code.

Brief landed after **two codex review iterations**. v1 → FAIL-LIGHT 4 findings → v2 → PASS-WITH-NITS 3 nits → final brief folds all 7. No further pre-write review.

**Scope:** new `triggers/scheduler_liveness_sentinel.py` (dynamic registry built at startup via `register_expected_job()` + `_MODULE_LOAD_TIME` cold-start anchor + `reset_cold_start_anchor()` for in-process restart) + patch `triggers/embedded_scheduler.py` to call `register_expected_job` after every IntervalTrigger add_job + 14 pytest cases.

**Critical pre-flight (MANDATORY before opening PR):** run the AST pairing check in Verification section. Script must print `OK: N interval jobs paired, M cron jobs cleanly skipped`. Do NOT boot `_register_jobs()` — that has side effects (vault_scanner Slack DM + mirror writes).

**Reply target:** lead. Ship report to `briefs/_reports/B1_SCHEDULER_JOB_LIVENESS_1_<YYYYMMDD>.md` + bus-post to `lead` with topic `ship/scheduler-job-liveness-1`.
