---
status: PENDING
brief: briefs/BRIEF_BAKER_CORTEX_BUS_HEARTBEAT_1.md
brief_id: BAKER_CORTEX_BUS_HEARTBEAT_1
target_repo: baker-master
matter_slug: baker-internal
cross_matter_usage: [all-matters — observability for any cortex cycle]
dispatched_at: 2026-05-18T14:55:00Z
dispatched_by: cowork-ah1
director_auth: 2026-05-18 chat via deputy bus #440 — Director ratified plan; deputy routed dispatch to cowork-ah1
trigger_class: LOW (no new external surface, no auth/DB schema change, no MCP tool, no Render env flip; ≤80 LOC delta expected; emits to existing brisen-lab /msg/ with existing cortex slug)
gate_chain_required:
  gate_1_ah2_static: REQUIRED
  gate_2_security_review: REQUIRED
  gate_3_picker_architect: NOT_REQUIRED (LOW trigger class)
  gate_4_2nd_pass_code_reviewer: NOT_REQUIRED (LOW trigger class)
sequenced_after:
  brief: STATE_RECONCILER_2
  pr: https://github.com/vallen300-bit/baker-vault/pull/98
  merge_commit: 87b23c0
  merged_at: 2026-05-18T14:50:00Z
  merged_by: ai-head-1 (AH1, lead)
  note: STATE_RECONCILER_2 merged baker-vault 87b23c0 by lead while this brief was being authored. Different repo, no file overlap. B3 truly free now. Prior COMPLETE record archived to briefs/_tasks/CODE_3_COMPLETE.md.
related_brief_pending:
  brief_id: BAKER_CORTEX_CARD_DRILLDOWN_1 (Fix #2)
  sequenced_after_this_pr_merges: true
  note: Fix #2 = card click → modal listing tier_b_pending cycles; brisen-lab + baker-master pair. Brief authored by cowork-ah1 after this PR merges.
estimated_loc: ~80
estimated_tests_added: 7
branch: b3/cortex-bus-heartbeat-1
commit_identity: Code Brisen #3 <b3@brisengroup.com>
ship_report_to: deputy
ship_report_topic: dispatch/cortex-card-fixes/ship-1
---

# Dispatch — BAKER_CORTEX_BUS_HEARTBEAT_1 (Fix #1 of cortex-card-fixes pair)

Brief: `briefs/BRIEF_BAKER_CORTEX_BUS_HEARTBEAT_1.md`. Add `_emit_cortex_heartbeat()` helper to `orchestrator/cortex_runner.py` + emit at every phase boundary in `run_cycle()` + emit `ratify-required` topic on Phase 4 success. Best-effort, never blocks phase progression.

**Scope:** ~80 LOC delta, 7 new tests, all in baker-master. No DDL, no new MCP tool, no Render env flip. Auth via existing `BRISEN_LAB_TERMINAL_KEY_CORTEX` env var (1P key already provisioned, `bus.py` budget cap already includes `cortex` slug at 5/cycle).

**Trigger class:** LOW. Gate-1 (AH2 static) + Gate-2 (/security-review) required; Gate-3 + Gate-4 NOT required.

**Standard contract:** branch `b3/cortex-bus-heartbeat-1`, commit identity `Code Brisen #3 <b3@brisengroup.com>`, no `--no-verify`.

**Ship-report routing:** bus-post topic `dispatch/cortex-card-fixes/ship-1` to `deputy` on PR open (deputy will cross-lane review + surface to Director; merge under standing Tier A by cowork-ah1).

**Mailbox-state note:** your prior brief STATE_RECONCILER_2 merged at baker-vault `87b23c0` 14:50Z. COMPLETE record archived to `briefs/_tasks/CODE_3_COMPLETE.md`. Stand down on STATE_RECONCILER_2; pick this up.

Open the brief + go.
