---
status: PENDING
dispatched_at: 2026-05-25T13:08:00Z
dispatched_by: lead
target: b4
brief: briefs/BRIEF_CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1.md
brief_id: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1
type: READ-ONLY DIAGNOSTIC (no code changes — investigate + propose only)
target_repo: baker-master (single repo)
matter_slug: baker-internal
peer_brief: GMAIL_ATTACHMENT_VISIBILITY_V2_1 (PR #261 merged 12:19:58Z — gmail polling visibility chain closed; this brief addresses orthogonal cost-runaway defect on capability_runner LLM spend)
reply_target: lead (AH1)
expected_time: ~1-2h
complexity: Low (read-only investigation)
heartbeat_cadence: 30 min
gate_chain: lead reads diagnostic on ship, no PR (read-only), sizes follow-up CAPABILITY_RUNNER_COST_FIX_1 from findings
---

# DISPATCH: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1 → b4

Read brief at: briefs/BRIEF_CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1.md

Pre-flight signal (already gathered by lead): capability_runner = 80% of daily LLM spend; finance + legal capability_ids = 97% of that; ALL calls have matter_slug = NULL; concentration overnight 00:00Z-05:40Z UTC cron-pattern burst.

Read-only. Ship report goes to lead via bus topic `ship/capability-runner-cost-runaway-diagnostic-1`.
