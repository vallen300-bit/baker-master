---
status: CLAIMED
claimed_at: 2026-05-18T15:05:00Z
claimed_by: b4
last_heartbeat: 2026-05-18T15:05:00Z
brief: briefs/BRIEF_STALE_CYCLE_NUDGE_SENTINEL_1.md
brief_id: STALE_CYCLE_NUDGE_SENTINEL_1
target_repo: baker-master
matter_slug: baker-internal
cross_matter_usage: [all-matters — catches stalled tier_b_pending on any matter]
dispatched_at: 2026-05-18T15:00:00Z
dispatched_by: lead
director_auth: 2026-05-18 chat — "go" on AH1 recommendation (punch-list item #7; russo_fr finding from f2954da4 + c4242a20 10-day-stall scar)
trigger_class: LOW
gate_chain_required:
  gate_1_ah2_static: REQUIRED
  gate_2_security_review: REQUIRED
  gate_3_picker_architect: NOT_REQUIRED
  gate_4_2nd_pass_code_reviewer: NOT_REQUIRED
items:
  - F1: migration — cortex_cycles.last_nudge_at TIMESTAMPTZ NULL (additive, idempotent)
  - F2: triggers/stale_cycle_nudge_sentinel.py — daily APScheduler entry, 3-day threshold + 7-day re-nudge window + LIMIT 10 + readonly guard
  - F3: scheduler wiring in triggers/embedded_scheduler.py at 07:00 UTC daily
estimated_loc: ~120
estimated_tests_added: 6
branch: b4/stale-cycle-nudge-sentinel-1
commit_identity: Code Brisen #4 <b4@brisengroup.com>
ship_report_to: lead
ship_report_topic: ship/stale-cycle-nudge-sentinel-1
prior_complete:
  brief_id: BAKER_WA_PULL_API_1
  pr: https://github.com/vallen300-bit/baker-master/pull/218
  merge_commit: 5190706
  archived_to: briefs/_tasks/CODE_4_COMPLETE.md
---

# Dispatch — STALE_CYCLE_NUDGE_SENTINEL_1

Brief: `briefs/BRIEF_STALE_CYCLE_NUDGE_SENTINEL_1.md`. Build daily sentinel that catches `tier_b_pending` Cortex cycles older than 3 days, emits ClickUp tasks to BAKER space list 901521426367, re-nudges every 7 days.

**Scope:** F1 migration + F2 sentinel module + F3 scheduler wiring. ~120 LOC, 6 tests, all baker-master. No new external surface; ClickUp write inside existing BAKER-space allowlist with readonly-guard respect.

**Trigger class:** LOW. Gate-1 (AH2 static) + Gate-2 (/security-review) required; Gate-3 + Gate-4 NOT required.

**Real-scar anchor:** Oskolkov cycle c4242a20 sat tier_b_pending 10 days (2026-05-05 → 2026-05-15). This sentinel would have caught it on day 3.

**Standard contract:** branch `b4/stale-cycle-nudge-sentinel-1`, commit identity `Code Brisen #4 <b4@brisengroup.com>`, no `--no-verify`.

**Ship-report routing:** bus-post `ship/stale-cycle-nudge-sentinel-1` to `lead` on PR open.

Open the brief + go.
