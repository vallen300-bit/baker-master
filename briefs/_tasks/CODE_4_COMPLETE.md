---
status: PENDING
dispatched_at: 2026-05-25T14:15:00Z
dispatched_by: lead
target: b4
brief: briefs/BRIEF_CAPABILITY_RUNNER_COST_FIX_1.md
brief_id: CAPABILITY_RUNNER_COST_FIX_1
type: backend defect fix (Option A from b4 diagnostic)
target_repo: baker-master (single repo)
matter_slug: baker-internal
peer_brief: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1 (diagnostic shipped 13:46Z; report at briefs/_reports/B4_capability_runner_cost_runaway_diagnostic_1_20260525.md — your own root-cause work)
reply_target: lead (AH1)
expected_time: ~30-45 min
complexity: Low (5-10 LOC + 1 unit test)
heartbeat_cadence: 15 min (small brief — flag if not shipped within 1h)
gate_chain: Gate-1+2 lead | Gate-3 SKIP (≤15 LOC) | Gate-4 SKIP | Gate-5 lead merge AFTER Director ratifies the trade-off documented in brief Context | post-merge lead observes Render logs 30 min for fromMe self-chat drop events + cost_monitor daily total drop
---

# DISPATCH: CAPABILITY_RUNNER_COST_FIX_1 → b4

Read brief at: `briefs/BRIEF_CAPABILITY_RUNNER_COST_FIX_1.md`

Your diagnostic was the unlock — Option A direct from your report §5. Implementation is the 14-LOC guard in `triggers/waha_webhook.py` between current lines 1117 and 1118, plus 1 unit test appended to `tests/test_waha_outbound_capture.py` (which already has fromMe=True fixtures at line 132+).

**Note the Context trade-off** — the guard drops Director's own phone-typed self-chat messages too. Lead is gating the merge at Gate-5 on Director ratification of that regression. You should implement Option A regardless; the merge gate handles the strategic call.

**4 reviewer invariants** documented at bottom of brief — same shape as your V1+V2 visibility patches.

Ship report to lead via topic `ship/capability-runner-cost-fix-1`. Literal pytest output required (no "pass by inspection"). Heartbeat every 15 min if >30 min.
