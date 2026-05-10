---
status: SHIPPED_FOLD_OK
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
mandatory_2nd_pass: TRUE  # Triggers #2 (DB schema/migrations/atomicity) + #3 (concurrency-ordering) — 4-gate chain CLEARED post-fold
hard_ship_gate: PASS — 10/10 deterministic GREEN (post-fold), 21/21 Tier-B suite GREEN
shipped_pr: https://github.com/vallen300-bit/baker-master/pull/182
fold_commit: c64cc7f (isolation-set hard-fail edge case) + 6b13c14 (fold ship-report)
last_heartbeat: 2026-05-10T22:50Z (B3 surfaced SHIPPED_FOLD_OK; parallel AH1 instance dispatched fold earlier; this AH1 session reconciled mailbox state)
---

# UPDATE 2026-05-10T22:30Z — FOLD-FIX (post-4-gate review)

All 4 gates returned:
  - Gate 1 pytest: PASS (21/21 + 10/10 ship-gate, already verified)
  - Gate 2 AH2 /security-review: PASS (no security findings)
  - Gate 3 code-architecture-reviewer: PASS_WITH_CONCERNS
  - Gate 4 feature-dev:code-reviewer: PASS_WITH_CONCERNS

Atomicity argument independently verified SOUND by both reviewers.
Your store_back.py deviation independently verified LEGITIMATE.

ONE convergent MEDIUM (both reviewers, independent reads) to fold:

## Fold item 1 — Isolation-level fallback edge case

**File:** `orchestrator/tier_b_runtime.py:204-260` (the enforce() outer
try/finally + the isolation-setting block at lines 204-213).

**Problem:** If `conn.set_isolation_level(SERIALIZABLE)` raises AND the
in-txn `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` fallback ALSO
raises (e.g., `conn.cursor()` itself errors), the exception propagates
out of the first try/except, skips the second try block entirely, and
the connection is returned to the pool with neither isolation
restored nor rollback called. The outer `finally` (line 343 area) is
attached to the SECOND try block, which is never reached.

Even worse: if only the primary `set_isolation_level` raises but the
fallback succeeds, atomicity is currently preserved silently. But if
BOTH paths fail, the current code path eats the second exception
without surfacing — caller never learns isolation wasn't set, and
worst-case proceeds at READ COMMITTED, **silently defeating the
entire atomicity guarantee this brief just shipped.**

**Fix shape** (single try/finally collapse + explicit isolation_set
flag + hard-raise if both paths fail):

```python
conn = self._store._get_conn()
if conn is None:
    raise RuntimeError("no DB connection — cannot enforce Tier-B")
old_iso = conn.isolation_level
isolation_set = False
try:
    # Promote to SERIALIZABLE. If neither path succeeds, raise — running
    # at default isolation would silently defeat pool-wide atomicity.
    try:
        conn.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
        )
        isolation_set = True
    except Exception:
        try:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cur.close()
            isolation_set = True
        except Exception as fallback_err:
            raise RuntimeError(
                "Tier-B enforce: could not set SERIALIZABLE isolation "
                f"via primary or fallback path; refusing to run at "
                f"default isolation (atomicity defeat risk). Fallback "
                f"err: {fallback_err}"
            )

    # ... rest of enforce() body (the cur = conn.cursor() block + cap
    # reads + branch eval + INSERT + commit, exactly as currently
    # written) ...
except Exception:
    try:
        conn.rollback()
    except Exception:
        pass
    raise
finally:
    if isolation_set:
        try:
            conn.set_isolation_level(old_iso)
        except Exception:
            pass
    self._store._put_conn(conn)
```

**Net change:** ~12 lines re-arranged. No new SQL, no schema, no test
surface change. Logic is preserved bit-for-bit on the happy path.

## Fold item 2 — Trivial test-comment clarification

**File:** `tests/test_tier_b_atomicity.py:208-215`
(`test_concurrent_enforcers_one_passes_one_pauses` docstring).

The docstring as written can mislead a reader by mentioning
`test.synthetic` registry cost. Make explicit that the seed helper
uses `eur_cost=99.00` directly (override), not the registry value.
One-line comment add — cosmetic, but Gate 4 flagged 85% confidence.

Replace inside the docstring:
```
    Seed math: 5 × €99 = €495 committed today (NOT €499 — the cap-eval
    is strict-greater-than, so €499 + €5 = €504 would PAUSE both
    enforcers without ever exercising the race).
```
with:
```
    Seed math: 5 × €99 = €495 committed today. `seed_committed_today`
    inserts rows with eur_cost passed in directly (overrides registry
    cost), so the class_name="test.synthetic" arg only affects the
    action_class label, not the seeded €99 per row. We need exactly
    €495 (NOT €499 — the cap-eval is strict-greater-than, so €499 + €5
    = €504 would PAUSE both enforcers without ever exercising the
    race).
```

## What NOT to fold

The following were flagged at LOW or M-priority but are out of fold
scope (Phase 5 V2 / next-brief concerns, not blocking merge):

- **NOW() evaluated twice across day/month cap queries** (Gate 3 M2)
  — harmless at 15-min TTL; defer
- **confirm/cancel run at default READ COMMITTED** (Gate 3 M3) —
  caller-contract documentation; flag in Phase 5 V2 brief
- **Orphan-confirm-after-sweep audit semantic** (Gate 3 #5) — caller
  must handle `confirm_tier_b()` returning False post-sweep; flag in
  Phase 5 V2 brief
- **`f"... failed: {e}"` style log in sweep** (Gate 4 L2) — style nit
  only, defer
- **`_seed_reserved` JSONB literal style** (Gate 4 L1) — test-only,
  defer

## After fold

1. Re-run literal 10/10 ship-gate:
   ```bash
   for i in 1 2 3 4 5 6 7 8 9 10; do \
     pytest tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses -v \
       || break; \
   done
   ```
2. Re-run full Tier-B suite: `pytest tests/test_tier_b_runtime.py
   tests/test_tier_b_atomicity.py tests/test_tier_b_reset.py -v`
3. Push fold commit to `b3/cortex-tier-b-atomicity-v1` (same branch,
   additive commit).
4. Surface back: ship-report append, status flips to `SHIPPED_FOLD_OK`.
5. AH1 proposes merge to AID. AH2 already PASSed — no re-fire
   required by SKILL.md per narrow-fold-scope exemption (isolation
   change has no security surface; AH2 verdict held).

ETA: ~20 min (fold + 10/10 re-run + push).

— AH1


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
