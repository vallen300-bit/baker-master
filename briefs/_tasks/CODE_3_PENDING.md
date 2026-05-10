---
status: PENDING
brief: briefs/BRIEF_CORTEX_TIER_B_ATOMICITY_V1.md
trigger_class: TIER_B_DB_SCHEMA_PLUS_ATOMICITY_PLUS_CONCURRENCY
dispatched_at: 2026-05-10
dispatched_by: ai-head-1 (AH1)
target: b3
director_ratification: Pattern B (reservation-row) + 15-min TTL + atomicity-only scope ratified 2026-05-10 PM (re-scoped from B4 6-phase-loop dispatch after AH1 surfaced 6-phase loop is substantially shipped). AID design-review PASS 2026-05-10 PM.
priority: P1
unblocks:
  - D5 risk register flip → RESOLVED on this merge (per AID housekeeping: B4 precursor redirected — D5 flips on THIS brief's merge, not B4)
  - B5 (substrate push runtime) — natural next caller post-atomicity
expected_pr_count: 1 (baker-master)
expected_branch_name: b3/cortex-tier-b-atomicity-v1
expected_complexity: medium (~5h)
mandatory_2nd_pass: TRUE  # Triggers #2 (DB schema/migrations/atomicity) + #3 (concurrency-ordering)
hard_ship_gate: test_concurrent_enforcers_one_passes_one_pauses must pass deterministically 10/10 runs (Brief Quality Checkpoint #8)
last_heartbeat: 2026-05-10T21:00Z (dispatch)
---

# B3 dispatch — CORTEX_TIER_B_ATOMICITY_V1 (Pattern B reservation-row)

## Why this brief

B3's `CORTEX_TIER_B_RUNTIME_V1` (PR #179, merged 2026-05-10) shipped with
a documented atomicity gap: PASS path commits SERIALIZABLE without
writing anything, so SSI cannot detect concurrent rw-anti-dependencies
on the day/month cap-bucket. Two enforcers at €495 day-total can both
PASS a €5 candidate, breaching the €500 daily cap to €505. Director
ratified Path A on 2026-05-10 AM (defer to B4); Path A is now closed
THIS brief, not B4 (per AID housekeeping — B4 precursor note redirected).

Pattern B (reservation-row) chosen over Pattern C (callable-injection)
for external-side-effect safety: future Phase 5 V2 will call email /
Render API / CRM adapters; Pattern C's SSI-retry semantics would
duplicate those external actions. Pattern B keeps side effects OUTSIDE
the SERIALIZABLE txn — the reservation row claims the budget atomically;
sweep job reclaims orphans on caller crash.

15-min TTL ratified 2026-05-10 PM. Tighter pressures slow callers;
looser ties up cap on crash. 15 min is generous for any realistic
external API call latency.

## Brief location

`briefs/BRIEF_CORTEX_TIER_B_ATOMICITY_V1.md`

The brief includes 6 copy-paste-ready fixes:
  1. New migration: `migrations/20260511_baker_actions_reservation.sql`
  2. conftest schema mirror (`tests/conftest.py` ALTER block extension)
  3. Pattern B refactor of `orchestrator/tier_b_runtime.py` (full file
     replacement provided)
  4. New `triggers/tier_b_reservation_sweep.py` + APScheduler 5-min
     registration in `triggers/embedded_scheduler.py`
  5. Update 2 existing tests in `tests/test_tier_b_runtime.py`
     (additive `reservation_id` assertions)
  6. New `tests/test_tier_b_atomicity.py` (7 tests, including the
     ship-gate concurrent-load test)

## Out of scope (do NOT touch)

- `orchestrator/cortex_phase5_act.py` — Phase 5 V2 audit-log uplift
  is a SEPARATE brief, not this one
- Any `orchestrator/cortex_phase*.py` module
- `orchestrator/tier_b_ratify.py` — PAUSE_REQUIRED path unchanged
- `migrations/20260510_baker_actions_tier_b_runtime.sql` — already
  applied; never edit applied migrations
- Cap constants (D8 Director-ratified values)
- The existing `idx_baker_actions_tier_b_committed` index — both old
  and new indices serve different branches of the cap-read OR
- `outputs/dashboard.py` `/api/admin/tier-b-status` endpoint — should
  still return 200 with same JSON shape post-merge

## Hard ship-gate

Quality Checkpoint #8 in the brief: the concurrent-load test must pass
10 consecutive times deterministically before merge. Run:

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do \
  pytest tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses -v \
    || break; \
done
```

If any iteration fails, the Pattern-B SSI argument is invalidated and
the brief reverts to architectural re-think. Do not paper over a flaky
result with retries — flakiness here means the cap can be breached.

## Branch + PR

- Branch: `b3/cortex-tier-b-atomicity-v1`
- PR title: `feat(tier-b): Pattern B reservation-row atomicity closure (CORTEX_TIER_B_ATOMICITY_V1)`
- PR body should explicitly state: "Closes D5 risk register entry per
  AID housekeeping" so AID can flip on merge.

## Post-merge endpoint smoke

The existing `/api/admin/tier-b-status` endpoint should still work.
After Render auto-deploys, polling it should show:

```bash
curl -H 'X-Baker-Key: <key>' \
  https://baker-master.onrender.com/api/admin/tier-b-status
```

Expected JSON shape (unchanged from B3's ship):
```json
{
  "caps": {"per_action_eur": 100.0, "daily_pool_eur": 500.0,
           "monthly_pool_eur": 2500.0},
  "current": {"day_total_eur": 0.0, "month_total_eur": 0.0,
              "day_remaining_eur": 500.0,
              "month_remaining_eur": 2500.0},
  "pending": [],
  "recent_committed": []
}
```

Optionally add a `recent_reserved` array to the endpoint if you want
operator visibility into in-flight reservations — that's a nice-to-have,
not a hard requirement. If you add it: list active (un-swept)
reservations with id/cost/age. Surface in ship-report so AID notices.

## Ship-report contract

After PR opens + 10/10 ship-gate passes, paste the standard PL ship
report block back here (or update this mailbox with `status: SHIPPED`
and the PR link). AID then fires the 4-gate review chain per usual:

  1. pytest (10/10 ship-gate + full suite)
  2. AH2 /security-review
  3. picker-architect
  4. feature-dev:code-reviewer 2nd-pass

Surface back on (a) all-PASS → propose merge, or (b) any FAIL / HIGH /
CRITICAL → fold-fix dispatch.

— AH1
