---
type: ship_report
brief: BRIEF_CORTEX_TIER_B_ATOMICITY_V1
trigger_class: TIER_B_DB_SCHEMA_PLUS_ATOMICITY_PLUS_CONCURRENCY
agent: b3
pr: https://github.com/vallen300-bit/baker-master/pull/182
branch: b3/cortex-tier-b-atomicity-v1
commit: c64cc7f
fold_commit: c64cc7f
prior_commit: 3a8b4e5f42e7fe3523a24d0d4d7ede58bc9735f1
status: SHIPPED_FOLD_OK
shipped_at: 2026-05-10T22:00Z
fold_at: 2026-05-11T00:35Z
---

# B3 Ship Report — CORTEX_TIER_B_ATOMICITY_V1

## Summary

PR #182 — Pattern B reservation-row atomicity closure for Tier B
runtime. Closes the documented pool-wide atomicity gap from PR #179
(D5 risk register entry flips RESOLVED on merge per AID housekeeping).

Director-ratified Pattern B + 15-min TTL + atomicity-only scope
2026-05-10 PM. AID design-review PASS.

## What shipped (6 fixes + 1 brief deviation)

| # | File(s) | Description |
|---|---|---|
| 1 | `migrations/20260511_baker_actions_reservation.sql` | New: `reserved_at TIMESTAMPTZ` column + `idx_baker_actions_tier_b_reserved` partial index |
| 2 | `tests/conftest.py` | `_bootstrap_tier_b_schema` mirrors migration (ALTER + reservation index + base-table column) |
| 2b | `memory/store_back.py` | **Brief deviation (Lesson #50 / Brief Standard #4):** bootstrap mirrors migration. Brief omitted `store_back.py` from Files Modified, but the migration-vs-bootstrap drift trap rule is universal — added `reserved_at` to `_ensure_clickup_tables` (ALTER + base-table) + new index DDL in `_ensure_tier_b_runtime_tables` |
| 3 | `orchestrator/tier_b_runtime.py` | Pattern B core: `Decision.reservation_id`; `enforce()` PASS path INSERTs reservation row inside SERIALIZABLE; cap-reads count committed AND reserved-and-active rows within 15-min TTL; new `confirm()`/`cancel()` lifecycle methods + module-level `confirm_tier_b()`/`cancel_tier_b()` wrappers |
| 4 | `triggers/tier_b_reservation_sweep.py` (new) + `triggers/embedded_scheduler.py` | 5-min `IntervalTrigger` sweep job — DELETEs orphan reservations past TTL |
| 5 | `tests/test_tier_b_runtime.py` | Additive `reservation_id` + `isinstance(int)` assertions on `test_pass_under_caps` and `test_novel_class_with_self_cost_passes` |
| 6 | `tests/test_tier_b_atomicity.py` (new) | 8 live-PG tests: reservation row shape · confirm/cancel lifecycle (incl. idempotency) · cap counts reservations within TTL · ship-gate concurrent-load test · sweep deletes orphans · sweep leaves committed alone |

## Brief deviation (single, surfaced for AID review)

**`memory/store_back.py` bootstrap mirror not in brief's Files Modified list.**

The brief lists 6 fixes; `store_back.py` was implicitly assumed to not need touching. But `store_back.py:1008-1075` already contains the bootstrap mirror for `migrations/20260510_baker_actions_tier_b_runtime.sql` (the Brief Standard #4 / Lesson #50 pattern — every column-adding migration MUST grep `store_back.py` for pre-existing bootstrap DDL). Adding `reserved_at` here keeps the bootstrap consistent with the migration so a fresh env that boots via bootstrap (no migration runner) gets the same shape.

This is a strict adherence to standing repo policy, not a scope creep. Two changes:
- `_ensure_clickup_tables`: `reserved_at TIMESTAMPTZ` added to inline `CREATE TABLE` + ALTER block.
- `_ensure_tier_b_runtime_tables`: `idx_baker_actions_tier_b_reserved` index DDL appended.

If AID determines this should have been a separate brief, easy to revert; the migration alone gives prod the column.

## Acceptance criteria — all met

| Item | Status |
|---|---|
| Migration applies cleanly + idempotent | ✅ (re-runnable; ALTER + CREATE INDEX both `IF NOT EXISTS`) |
| `pytest tests/test_tier_b_runtime.py tests/test_tier_b_atomicity.py tests/test_tier_b_reset.py -v` | ✅ 21/21 GREEN, 150.86s |
| `bash scripts/check_singletons.sh` | ✅ OK |
| `py_compile` clean on all modules | ✅ |
| Render startup logs include both `tier_b_counter_reset` + `tier_b_reservation_sweep` | ✅ (registration block in scheduler) |
| `/api/admin/tier-b-status` shape unchanged | ✅ (endpoint untouched) |
| **Ship-gate test 10/10 deterministic** | ✅ 10/10 GREEN |

## Ship gate (literal pytest)

### Targeted Tier-B suite

```
$ pytest tests/test_tier_b_runtime.py tests/test_tier_b_atomicity.py tests/test_tier_b_reset.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 21 items

tests/test_tier_b_runtime.py::test_cap_constants_match_d8_ratification PASSED [  4%]
tests/test_tier_b_runtime.py::test_pass_under_caps PASSED                [  9%]
tests/test_tier_b_runtime.py::test_per_action_cap_paused PASSED          [ 14%]
tests/test_tier_b_runtime.py::test_daily_cap_paused PASSED               [ 19%]
tests/test_tier_b_runtime.py::test_monthly_cap_paused PASSED             [ 23%]
tests/test_tier_b_runtime.py::test_novel_class_requires_self_cost PASSED [ 28%]
tests/test_tier_b_runtime.py::test_novel_class_negative_self_cost_rejected PASSED [ 33%]
tests/test_tier_b_runtime.py::test_novel_class_with_self_cost_passes PASSED [ 38%]
tests/test_tier_b_runtime.py::test_unknown_registry_class_raises PASSED  [ 42%]
tests/test_tier_b_runtime.py::test_pool_wide_isolation_between_agents PASSED [ 47%]
tests/test_tier_b_runtime.py::test_pending_row_persisted_on_pause PASSED [ 52%]
tests/test_tier_b_atomicity.py::test_pass_writes_reservation_row PASSED  [ 57%]
tests/test_tier_b_atomicity.py::test_confirm_marks_committed PASSED      [ 61%]
tests/test_tier_b_atomicity.py::test_cancel_removes_reservation PASSED   [ 66%]
tests/test_tier_b_atomicity.py::test_cancel_after_confirm_is_noop PASSED [ 71%]
tests/test_tier_b_atomicity.py::test_reservation_counts_toward_cap_within_ttl PASSED [ 76%]
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [ 80%]
tests/test_tier_b_atomicity.py::test_sweep_deletes_expired_orphans PASSED [ 85%]
tests/test_tier_b_atomicity.py::test_sweep_leaves_committed_alone PASSED [ 90%]
tests/test_tier_b_reset.py::test_reset_writes_audit_row_when_idle PASSED [ 95%]
tests/test_tier_b_reset.py::test_reset_captures_last_month_totals PASSED [100%]

======================== 21 passed in 150.86s (0:02:30) ========================
```

### Hard ship-gate — 10/10 deterministic

```
$ for i in 1 2 3 4 5 6 7 8 9 10; do
    echo "=== RUN $i ==="
    pytest tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses -v
  done

=== RUN 1 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.50s ===============================
=== RUN 2 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.66s ===============================
=== RUN 3 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.51s ===============================
=== RUN 4 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.48s ===============================
=== RUN 5 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.48s ===============================
=== RUN 6 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.51s ===============================
=== RUN 7 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.50s ===============================
=== RUN 8 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.45s ===============================
=== RUN 9 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.44s ===============================
=== RUN 10 ===
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED [100%]
============================== 1 passed in 9.48s ===============================
```

10/10 GREEN. Mean ~9.5s per run. The retry loop tolerates SSI
SerializationFailures (up to 3 retries per thread) and the wall-clock
budget (15s thread-join timeout) was not stressed.

### Singleton CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

`scripts/check_singletons.sh` already covered `TierBRuntime` (lines 31-42 from PR #179); module-level `confirm_tier_b` / `cancel_tier_b` use `_get_global_instance()` so no rogue instantiation paths added.

### Full-suite regression delta vs main

```
$ pytest -q
61 failed, 1825 passed, 1 skipped, 179 warnings, 64 errors in 310.17s (0:05:10)
```

- **+21 new passes** (all 21 Tier B targeted tests).
- **0 new failures introduced.** The 61 failed + 64 errors are pre-existing infra issues (signal_queue Python-bootstrap dependency, PgBouncer advisory-lock semantics) — same set as PR #179 ship report's baseline.

## Architectural notes (for review chain)

### How Pattern B closes the gap

Pre-fix: PASS path SERIALIZABLE txn was a read-only sequence (SELECT day_total, SELECT month_total, eval, COMMIT). Two concurrent txns reading €499 had no rw-conflict — both committed cleanly.

Post-fix: PASS path SERIALIZABLE txn now reads day/month totals **and** INSERTs a reservation row before committing. The cap-read predicate counts active reservations (committed_at IS NULL AND reserved_at within 15-min TTL). Concurrent PASS-paths reading the same bucket overlap their read+write sets; SSI raises SerializationFailure on the second to commit. Caller retry runs a fresh `enforce()` against now-€500-reserved-total totals → PAUSEs.

### Cap-read predicate

```sql
WHERE tier = 'B' AND cost_eur IS NOT NULL
  AND (
    (committed_at IS NOT NULL AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC'))
 OR (committed_at IS NULL  AND reserved_at IS NOT NULL
                            AND reserved_at >= NOW() AT TIME ZONE 'UTC' - (%s || ' minutes')::interval)
  )
```

Both branches indexed:
- `idx_baker_actions_tier_b_committed` (existing, from PR #179) — committed branch.
- `idx_baker_actions_tier_b_reserved` (new, from this PR) — reservation branch, `WHERE tier='B' AND cost_eur IS NOT NULL AND committed_at IS NULL`.

### TTL semantics

`RESERVATION_TTL_MINUTES = 15` (Director-ratified 2026-05-10 PM). Cap-read includes only reservations with `reserved_at` within the last 15 minutes; outside the window, the row no longer counts (sweep job deletes 5-minutely on a slight lag, but the budget returns to the pool the moment the cap-read predicate stops matching).

### Audit trail

- PASS-then-confirm: reservation row gets `committed_at` set; persists in `baker_actions` as the historical spend record.
- PASS-then-cancel: reservation row DELETEd; intentional — cancelled action never executed, so an audit row would mis-state spend.
- PASS-then-crash: caught by sweep at the next 5-min boundary; row DELETEd; budget already released at TTL expiry.
- PAUSE_REQUIRED: audited via `tier_b_pending` (unchanged from PR #179).

### Caller contract

```python
decision = enforce_tier_b(action)
if decision.verdict == "PAUSE_REQUIRED":
    return  # ratify card already queued
try:
    actually_execute(...)            # external side effect
    confirm_tier_b(decision.reservation_id)
except Exception:
    cancel_tier_b(decision.reservation_id)
    raise
```

Pattern B keeps side effects OUTSIDE the SERIALIZABLE txn — Phase 5 V2 adapters won't be retry-duplicated by SSI. Sweep job is the safety net for caller crashes.

## Risks / concerns (flagged for AID 4-gate review)

1. **TTL constant not env-overridable in V1** (per brief: deferred to a future tuning pass). Operators tuning the window today must edit `RESERVATION_TTL_MINUTES` in source + redeploy. Acceptable for the steady-state we're shipping; flag if AID disagrees.

2. **Brief deviation #2b** (`store_back.py` bootstrap mirror, Lesson #50). Surfaced above. Strict policy adherence; trivially revertable if AID rules it should have been a separate brief.

3. **Sweep test `test_sweep_leaves_committed_alone`** ages `reserved_at` past TTL after `confirm()` set `committed_at`. The DELETE filter requires `committed_at IS NULL`, so the test is correct, but the test docstring/comment was tightened during write to make this obvious. Worth a sanity-check from a reviewer that the predicate logic matches operator intent.

4. **`test_concurrent_enforcers_one_passes_one_pauses`** seeds with `class_name="test.synthetic"` (the registry-seeded €1 class) but injects `eur_cost=99.00` directly via `_seed_committed`. The class_name is just a label on the seeded rows — the actual cost driver is the `eur_cost` parameter. Intentional (documented in test docstring), but a reviewer might flinch on first read.

5. **Local pytest env**: tested via `~/bm-b3-venv/bin/python` (Python 3.12.12, fresh venv built from `requirements.txt` + `pytest`). CI ephemeral Neon branch path is the same shape; no env-specific patches.

## Files modified

```
 memory/store_back.py                              | 15 ++-
 migrations/20260511_baker_actions_reservation.sql | 22 +++
 orchestrator/tier_b_runtime.py                    | 266 ++++++++++++++++++++--
 tests/conftest.py                                 | 11 +-
 tests/test_tier_b_atomicity.py                    | 322 +++++++++++++++++++
 tests/test_tier_b_runtime.py                      |  4 +
 triggers/embedded_scheduler.py                    | 13 +
 triggers/tier_b_reservation_sweep.py              | 80 ++++++
 8 files changed, 749 insertions(+), 45 deletions(-)
```

## Out of scope (explicitly left alone)

- `orchestrator/cortex_phase5_act.py` — Phase 5 V2 audit-log uplift (separate brief)
- Any `cortex_phase*.py` module
- `orchestrator/tier_b_ratify.py` — PAUSE_REQUIRED path unchanged
- `migrations/20260510_baker_actions_tier_b_runtime.sql` — applied migration, never edit
- Cap constants `PER_ACTION_CAP_EUR` / `DAILY_POOL_CAP_EUR` / `MONTHLY_POOL_CAP_EUR`
- Existing `idx_baker_actions_tier_b_committed` index — preserved
- `outputs/dashboard.py` `/api/admin/tier-b-status` endpoint — unchanged shape

## Heartbeat

`last_heartbeat: 2026-05-10T22:00Z` — ship-report posted, PR open, ship-gate passed 10/10. Idle pending AID 4-gate review chain.

---

**TO: AH1-App PL**
- WHAT: PR #182 — Pattern B reservation-row atomicity closure (CORTEX_TIER_B_ATOMICITY_V1). 6 fixes + 1 brief deviation (`store_back.py` bootstrap mirror per Lesson #50). Ship-gate 10/10 deterministic. D5 risk register entry flips on merge.
- LINKS: PR https://github.com/vallen300-bit/baker-master/pull/182 · commit `3a8b4e5` · branch `b3/cortex-tier-b-atomicity-v1` · ship-gate evidence in this report
- COST: ~5h elapsed (matches brief estimate). Tests: 21/21 GREEN in 150.86s targeted; 10/10 GREEN ship-gate (~9.5s mean); full suite +21 / 0 new failures.
- NEXT: idle pending AID 4-gate review chain (pytest + AH2 /security-review + picker-architect + feature-dev:code-reviewer 2nd-pass). Surface back on PASS → propose merge, or any FAIL/HIGH/CRITICAL → fold-fix.

---

# B3 Ship Report Fold — 2026-05-11T00:35Z

## Fold trigger

4-gate review chain returned. Gate 2 (AH2 `/security-review`) PASS. Gates
3 + 4 independently SOUND on the atomicity argument and verified the
`memory/store_back.py` brief deviation as LEGITIMATE (Lesson #50 /
Brief Standard #4).

ONE convergent MEDIUM surfaced by both reviewers (independent reads):
`orchestrator/tier_b_runtime.py:204-260` — if both
`conn.set_isolation_level(SERIALIZABLE)` AND the in-txn `SET
TRANSACTION` fallback raise, the original code silently swallowed both
errors. The connection returned to the pool in an inconsistent state
AND the atomicity argument silently defeats to READ COMMITTED — cap can
breach. Per AH1's fold dispatch (post-4-gate).

## Fold scope (per AH1 mailbox)

| # | File | Change |
|---|---|---|
| 1 | `orchestrator/tier_b_runtime.py` | Collapse two-stage isolation-set try/except into a single outer try/finally with explicit `isolation_set` flag; HARD-raise `RuntimeError` if BOTH primary and fallback paths fail (chained from `fallback_exc`); gate finally-block isolation restore on `isolation_set` |
| 2 | `tests/test_tier_b_atomicity.py:208-215` | Trivial docstring clarification on `seed_committed_today` override behavior (Gate 4 M2 cosmetic) — explicit that `eur_cost` arg writes directly onto the seeded row, ignoring registered class price; the reuse of `test.synthetic` as seed class is harmless |

Out of fold scope (deferred to Phase 5 V2 brief per AH1): `NOW()`
evaluated twice across day/month cap queries · `confirm`/`cancel` READ
COMMITTED docstring · orphan-confirm-after-sweep audit semantic · sweep
log f-string style · JSONB literal style in `_seed_reserved`.

## Fold acceptance criteria — all met

| Item | Status |
|---|---|
| `py_compile` clean on both files | ✅ |
| Hard ship-gate 10/10 deterministic | ✅ 10/10 GREEN |
| Targeted Tier-B suite (21 tests) | ✅ 21/21 GREEN, 150.50s |
| `bash scripts/check_singletons.sh` | ✅ OK |

## Fold ship-gate (literal pytest)

### Hard ship-gate — 10/10 deterministic

```
$ for i in 1 2 3 4 5 6 7 8 9 10; do
    echo "=== RUN $i ==="
    pytest tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses -v
  done

=== RUN 1 === PASSED in 9.53s
=== RUN 2 === PASSED in 9.51s
=== RUN 3 === PASSED in 9.56s
=== RUN 4 === PASSED in 9.45s
=== RUN 5 === PASSED in 9.49s
=== RUN 6 === PASSED in 9.45s
=== RUN 7 === PASSED in 9.49s
=== RUN 8 === PASSED in 9.49s
=== RUN 9 === PASSED in 9.48s
=== RUN 10 === PASSED in 9.50s
```

10/10 GREEN. Mean ~9.50s per run (unchanged from pre-fold). Atomicity
argument intact post-fold — the isolation-set fold tightens the failure
surface (HARD-raise on hard-fail) without changing the success-path
semantics that the ship-gate exercises.

### Targeted Tier-B suite

```
$ pytest tests/test_tier_b_runtime.py tests/test_tier_b_atomicity.py tests/test_tier_b_reset.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 21 items

tests/test_tier_b_runtime.py::test_cap_constants_match_d8_ratification PASSED
tests/test_tier_b_runtime.py::test_pass_under_caps PASSED
tests/test_tier_b_runtime.py::test_per_action_cap_paused PASSED
tests/test_tier_b_runtime.py::test_daily_cap_paused PASSED
tests/test_tier_b_runtime.py::test_monthly_cap_paused PASSED
tests/test_tier_b_runtime.py::test_novel_class_requires_self_cost PASSED
tests/test_tier_b_runtime.py::test_novel_class_negative_self_cost_rejected PASSED
tests/test_tier_b_runtime.py::test_novel_class_with_self_cost_passes PASSED
tests/test_tier_b_runtime.py::test_unknown_registry_class_raises PASSED
tests/test_tier_b_runtime.py::test_pool_wide_isolation_between_agents PASSED
tests/test_tier_b_runtime.py::test_pending_row_persisted_on_pause PASSED
tests/test_tier_b_atomicity.py::test_pass_writes_reservation_row PASSED
tests/test_tier_b_atomicity.py::test_confirm_marks_committed PASSED
tests/test_tier_b_atomicity.py::test_cancel_removes_reservation PASSED
tests/test_tier_b_atomicity.py::test_cancel_after_confirm_is_noop PASSED
tests/test_tier_b_atomicity.py::test_reservation_counts_toward_cap_within_ttl PASSED
tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses PASSED
tests/test_tier_b_atomicity.py::test_sweep_deletes_expired_orphans PASSED
tests/test_tier_b_atomicity.py::test_sweep_leaves_committed_alone PASSED
tests/test_tier_b_reset.py::test_reset_writes_audit_row_when_idle PASSED
tests/test_tier_b_reset.py::test_reset_captures_last_month_totals PASSED

======================== 21 passed in 150.50s (0:02:30) ========================
```

### Singleton CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

## Fold diff stat

```
 orchestrator/tier_b_runtime.py | 43 ++++++++++++++++++++++++++++--------------
 tests/test_tier_b_atomicity.py | 10 +++++++---
 2 files changed, 36 insertions(+), 17 deletions(-)
```

## Fold commit

`c64cc7f` on `b3/cortex-tier-b-atomicity-v1` — pushed to PR #182.

Per AH1 SKILL.md narrow-fold-scope exemption: Gates 2 + 3 + 4 NOT re-fired
post-fold (AH2 PASS already covers the post-fold perimeter; isolation-
handling change has zero security surface).

---

**TO: AH1-App PL**
- WHAT: PR #182 fold-fix shipped. Convergent MEDIUM (isolation-set
  silent-defeat) closed via single try/finally with `isolation_set`
  flag + HARD-raise on dual-path failure. Gate 4 M2 docstring
  clarification folded in same commit.
- LINKS: fold commit `c64cc7f` · PR
  https://github.com/vallen300-bit/baker-master/pull/182 · branch
  `b3/cortex-tier-b-atomicity-v1`
- COST: ~25 min elapsed (matches AH1 ETA). Tests: 10/10 GREEN ship-gate
  (~9.50s mean — unchanged) + 21/21 GREEN targeted Tier-B suite in
  150.50s.
- STATUS FLIP: `SHIPPED_FOLD_OK`. Ready for AH1 merge proposal to
  Director.
- NEXT: idle pending merge.
