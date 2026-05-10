---
status: COMPLETE
brief: briefs/BRIEF_CORTEX_TIER_B_RUNTIME_V1.md
trigger_class: TIER_B_DB_SCHEMA_PLUS_ATOMICITY_PLUS_EXTERNAL_SURFACE
dispatched_at: 2026-05-10
dispatched_by: ai-head-1 (AH1)
target: b3
director_ratification: D8 ratified 2026-05-10 via D3+D8 Triaga (Conservative caps locked); AID-resolved 7 clarifications 2026-05-10 (pool-wide, mixed-cost-source, dedicated-tier-b-pending, 00:00 UTC reset)
priority: P1
unblocks:
  - I5 (first Cortex auto-trigger cycle, STUCK since 2026-05-03)
  - B4 (6-phase loop runtime — adopts enforce_tier_b)
  - B5 (substrate push runtime — adopts enforce_tier_b)
expected_pr_count: 1 (baker-master)
expected_branch_name: b3/cortex-tier-b-runtime-v1
expected_complexity: medium (~6-8h)
mandatory_2nd_pass: TRUE  # Triggers #2 (DB schema/migrations/atomicity) + #3 (concurrency-ordering) + #4 (external-surface endpoint)
last_heartbeat: 2026-05-10T17:23Z (ship report)
shipped_pr: https://github.com/vallen300-bit/baker-master/pull/179
shipped_commit: c5c5e4198253716e2b758a82f99df69adca032f7
shipped_at: 2026-05-10T17:23Z
ship_report: briefs/_reports/B3_cortex_tier_b_runtime_v1_20260510.md
gate_1_pytest: GREEN (15 passed, 4 warnings, 87s)
gate_2_security_review: pending
gate_3_picker_architect: pending
gate_4_code_reviewer: pending
---

# CODE_3_PENDING — BRIEF_CORTEX_TIER_B_RUNTIME_V1 — 2026-05-10

**Brief:** `briefs/BRIEF_CORTEX_TIER_B_RUNTIME_V1.md` (read first — full spec, 6 fixes, copy-pasteable code blocks, test plan, ship gate)
**Working dir:** `~/bm-b3`
**Working branch:** `b3/cortex-tier-b-runtime-v1`
**Repo:** `vallen300-bit/baker-master`

## Summary

Build forward-looking Tier-B autonomous-action budget enforcement runtime. Caps: €100/action, €500/day, €2500/mo (pool-wide); reset 1st calendar month 00:00 UTC. 6 fixes:
1. Schema extension on `baker_actions` (6 new nullable columns) + 3 new tables (`tier_b_action_classes`, `tier_b_pending`, `tier_b_counter_resets`) + seed registry. Migration `migrations/20260510_baker_actions_tier_b_runtime.sql` + matching `_ensure_*` bootstrap update in `memory/store_back.py`.
2. `orchestrator/tier_b_runtime.py` — `enforce_tier_b(action) → Decision` singleton with SERIALIZABLE-txn counter check-and-pause.
3. `orchestrator/tier_b_ratify.py` — pause-handler + ratify card prep (visual reuse from GOLD card; separate workflow domain).
4. `triggers/tier_b_reset.py` + register in `triggers/embedded_scheduler.py` — APScheduler cron, day=1, hour=0, minute=0, timezone="UTC".
5. `outputs/dashboard.py` — `GET /api/admin/tier-b-status` audit endpoint.
6. Tests: `tests/test_tier_b_runtime.py` + `tests/test_tier_b_reset.py` + `tests/test_tier_b_status_endpoint.py` (PG-required, skip-if-no-TEST_DATABASE_URL pattern).

## Pre-requisites
- `baker_actions` table exists (bootstrap `memory/store_back.py:1036` — verified)
- GOLD ratify workflow exists (PR #66 — verified for visual template reuse)
- D8 caps ratified 2026-05-10
- `TEST_DATABASE_URL` env (CI ephemeral Neon branch — auto-provisioned)

## Acceptance criteria
- All 6 fixes implemented per spec.
- Migration creates 3 new tables + 6 new columns on baker_actions; bootstrap updated to match (Brief Standard #4).
- All caps enforce correctly (pytest scenarios in Fix 6 cover edge cases).
- Calendar-month reset fires at 1st 00:00 UTC (cron registered, verifiable in logs).
- `/api/admin/tier-b-status` returns valid JSON shape.
- No false-positive pauses (action below cap → PASS).
- No false-negative passes (action above cap → PAUSE_REQUIRED).
- Pool-wide isolation: AH1 spend visible to B3's enforce check.
- Singleton: `TierBRuntime._get_global_instance()` only; pre-push hook `scripts/check_singletons.sh` passes.
- All DB calls in try/except with rollback; all SELECTs have LIMIT.

## Ship gate
**Literal `pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v` output GREEN — no "pass by inspection."**

Plus full suite: `pytest` exit-0 (no regressions on existing baker_actions write paths).

## Mandatory review chain (4 gates per SKILL.md §Code-reviewer 2nd-pass Protocol)

This PR fires multiple triggers — full chain required pre-merge:

1. **Gate 1 — pytest GREEN** (B3 ships report w/ literal output)
2. **Gate 2 — AH2 `/security-review`** (atomicity + external-surface scrutiny)
3. **Gate 3 — picker-architect** (architectural soundness)
4. **Gate 4 — `feature-dev:code-reviewer` 2nd-pass** (mandatory: triggers #2 DB/migration/atomicity + #3 concurrency-ordering + #4 external-surface endpoint)

REQUEST_CHANGES on any FAIL or HIGH/CRITICAL findings. Re-fire chain on each fold-fix commit.

## Heartbeat policy (per SKILL.md §B-code stall chase)

Minimum heartbeat every 12h while actively building. Acceptable formats:
- Mailbox UPDATE entry in this file with ISO timestamp
- Ship-report file at `briefs/_reports/...`
- Commit-msg heartbeat on `b3/cortex-tier-b-runtime-v1` (`mailbox(b3): heartbeat <ISO> — <where>` pattern)

Two consecutive 12h misses → AH1 auto-surfaces stall to Director.

## Out of scope (do NOT implement)
- Wiring `enforce_tier_b()` into Cortex Phase 5 / B4 6-phase loop / B5 substrate push (those briefs adopt this runtime when they ship)
- Anthropic API token-cost cap (D4 risk action, AID owns, target 2026-05-31)
- Tier C definition (separate brief if needed)
- Slack push of ratify card actual-send (B3 prepares card payload + DB transitions; B4 wires Slack push)

## PL ship-report contract

End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract":

```
**TO: AH1-App PL**
- WHAT: <one-line summary>
- LINKS: <PR # / commit SHA / file paths / Render deploy ID>
- COST: <$X / time / N cycles, or "n/a">
- NEXT: <next blocker, dispatch, or "ready for next">
```
