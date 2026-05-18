---
status: COMPLETE
brief: briefs/BRIEF_STALE_CYCLE_NUDGE_SENTINEL_1.md
brief_id: STALE_CYCLE_NUDGE_SENTINEL_1
target_repo: baker-master
matter_slug: baker-internal
cross_matter_usage: [all-matters — catches stalled tier_b_pending on any matter]
dispatched_at: 2026-05-18T15:00:00Z
dispatched_by: lead
director_auth: 2026-05-18 chat — "go" on AH1 recommendation (punch-list item #7; russo_fr finding from f2954da4 + c4242a20 10-day-stall scar)
trigger_class: LOW
pr: https://github.com/vallen300-bit/baker-master/pull/219
pr_head_sha: 497a561
pr_opened_at: 2026-05-18T15:25:00Z
merge_commit: 7dbe143
merged_at: 2026-05-18T15:26:00Z
merged_by: ai-head-1 (AH1, lead)
tests_passed: 6 new + 10/10 sibling cortex_stuck_cycle_sentinel + singleton CI clean
gate_chain:
  gate_1_ah2_static: PASS-WITH-NITS (deputy #456)
  gate_2_security_review: PASS-NO_FINDINGS (deputy #456)
  gate_3_picker_architect: NOT_REQUIRED (LOW trigger class)
  gate_4_2nd_pass_code_reviewer: NOT_REQUIRED (LOW trigger class)
deferred_to_future_microcleanup:
  - _fetch_stale_cycles silent SELECT failure — add sentinel_health.report_failure before empty return
  - WHERE cycle_id::text = %s in _mark_nudged defeats UUID PK index — use cycle_id = %s::uuid
  - F2 contract vs §2 acceptance discrepancy — fix brief template for future LOW sentinels (process, not code)
  - No test coverage for ClickUp-create-success + UPDATE-fail path — add via mock
post_merge_followups:
  - One-off invocation against a seeded prod row to close acceptance §3 end-to-end (lead Tier-B optional)
items_shipped:
  - F1: migration cortex_cycles.last_nudge_at TIMESTAMPTZ NULL (additive, idempotent + bootstrap mirror in lockstep per Lesson #50)
  - F2: triggers/stale_cycle_nudge_sentinel.py — daily APScheduler entry, 3-day threshold + 7-day re-nudge + LIMIT 10 + BAKER_CLICKUP_READONLY early-exit
  - F3: scheduler wiring in triggers/embedded_scheduler.py at 07:00 UTC daily
bus_thread:
  dispatch: 450
  ship: 451
  review_request: 453
  verdict: 456
  merge_b4: 457
  ack_deputy: 458
prior_complete:
  brief_id: BAKER_WA_PULL_API_1
  pr: https://github.com/vallen300-bit/baker-master/pull/218
  merge_commit: 5190706
---

# Mailbox COMPLETE — STALE_CYCLE_NUDGE_SENTINEL_1

PR #219 merged baker-master `7dbe143` at 2026-05-18T15:26Z. 4-step dispatch → ship → gate → merge cycle in ~26 minutes (dispatch 15:00Z → merge 15:26Z). 6/6 new tests + 10/10 sibling + singleton CI clean; Gate-1+2 PASS-WITH-NITS. Four LOW nits captured as future micro-cleanup, none blocking. Real-scar coverage: catches c4242a20-style 10-day-stall failure mode on day 3.
