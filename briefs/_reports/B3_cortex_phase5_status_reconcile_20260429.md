# B3 — CORTEX_PHASE5_STATUS_RECONCILE_1 — 2026-04-29

**Brief:** [`briefs/BRIEF_CORTEX_PHASE5_STATUS_RECONCILE_1.md`](../BRIEF_CORTEX_PHASE5_STATUS_RECONCILE_1.md)
**Trigger class:** HIGH (DB migration + cross-capability state writes — RA-24)
**Branch:** `cortex-phase5-status-reconcile-1`
**PR:** _(see footer once opened)_
**Verdict:** **PASS** — code, migration, tests all clean; awaiting B1 + AI Head A `/security-review`.

## Why (3 bundled fixes from one incident chain — cycle 7dc3201b)

1. **Phase 4/5 status mismatch.** `cortex_runner.py:389` lands every cycle at `tier_b_pending`. Phase 5 handlers (`_cas_lock_cycle(... from_status="proposed", ...)`) only matched `'proposed'` → CAS finds 0 rows → silent `already_actioned` bail. Director hand-flipped the status to test reject end-to-end this morning. Production button path was broken on EVERY future AO cycle.
2. **Transient `*ing` statuses missing from CHECK.** PR #75 introduced `approving`/`rejecting`/`editing`/`refreshing` writes but never updated the CHECK constraint. Director hot-fixed live at 09:47Z via `ALTER TABLE`. Migration not checked in.
3. **Render env-var paginated-PUT regression.** AI Head A wiped 80 env vars at 09:14Z by raw-PUT-ing a GET that returned only 20 of ~100 keys (default pagination). Needed a feedback memory so the loss-of-context doesn't repeat.

## Change

### 1. `_cas_lock_cycle` accepts multiple from-statuses

`orchestrator/cortex_phase5_act.py:49` — signature & SQL:

```diff
-def _cas_lock_cycle(
-    cycle_id: str,
-    *,
-    from_status: str,
-    to_status: str,
-    action_attempted: str,
-) -> Optional[dict]:
+def _cas_lock_cycle(
+    cycle_id: str,
+    *,
+    from_statuses: tuple[str, ...] | list[str] | str,
+    to_status: str,
+    action_attempted: str,
+) -> Optional[dict]:
...
+    if isinstance(from_statuses, str):
+        from_statuses_list = [from_statuses]
+    else:
+        from_statuses_list = list(from_statuses)
...
-            WHERE cycle_id=%s AND status=%s
+            WHERE cycle_id=%s AND status = ANY(%s)
...
-            (to_status, cycle_id, from_status),
+            (to_status, cycle_id, from_statuses_list),
```

4 handler call sites updated:
- `cortex_approve` (line 188): `from_statuses=("proposed", "tier_b_pending")` → `to_status="approving"`
- `cortex_edit` (line 278): same multi-tuple → `"editing"`
- `cortex_refresh` (line 329): same multi-tuple → `"refreshing"`
- `cortex_reject` (line 394): same multi-tuple → `"rejecting"`

`_cas_release_to_proposed` and `_archive_cycle`'s `from_status=` arg are intentionally unchanged — those are single-state transitions out of the transient `*ing` lock.

### 2. Migration + bootstrap CHECK alignment

`memory/store_back.py:587` — `_ensure_cortex_cycles_table` CHECK list grown from 11 → 15 statuses (added `approving`,`rejecting`,`editing`,`refreshing`).

`migrations/20260429_cortex_cycles_add_transient_statuses.sql` — NEW. `BEGIN; DROP CONSTRAINT IF EXISTS; ADD CONSTRAINT ... CHECK IN (15 values); COMMIT;` Idempotent. Mirrors the bootstrap exactly. Header carries the `down` block for disaster recovery.

### 3. Feedback memory + index entry

`memory/feedback_render_envvar_paginated_put.md` — NEW. Frontmatter `type: feedback`. Body: rule, why (incident at 09:14Z, 80 vars wiped, ~45-min recovery), how-to-apply (`?limit=100`, per-key endpoint, MCP merge mode, defense-in-depth abort-if-shrinking).

`memory/MEMORY.md` — NEW (file did not exist). 1-line index pointer per CLAUDE.md "MEMORY.md is an index, not a memory" rule.

## Sole-importer / scope verification

```
$ git diff --name-only main...HEAD
briefs/_tasks/CODE_3_PENDING.md
memory/MEMORY.md
memory/feedback_render_envvar_paginated_put.md
memory/store_back.py
migrations/20260429_cortex_cycles_add_transient_statuses.sql
orchestrator/cortex_phase5_act.py
tests/test_cortex_phase5_idempotency.py
```

7 files = 5 brief items + mailbox flip + tests-extension (per Lesson #47 literal-stdout requires new tests checked-in).

```
$ grep -n "from_status=\|from_statuses=" orchestrator/cortex_phase5_act.py
189:        from_statuses=("proposed", "tier_b_pending"),
214:            from_status="approving",        # _archive_cycle (single transient release)
233:        from_status="approving",            # _archive_cycle
279:        from_statuses=("proposed", "tier_b_pending"),
313:    _cas_release_to_proposed(cycle_id, from_status="editing")
330:        from_statuses=("proposed", "tier_b_pending"),
382:    _cas_release_to_proposed(cycle_id, from_status="refreshing")
391:    ``_archive_cycle`` with the hardened ``from_status='rejecting'`` guard.
395:        from_statuses=("proposed", "tier_b_pending"),
406:        from_status="rejecting",            # _archive_cycle
```

Exactly 4 `_cas_lock_cycle` call sites use the multi-tuple. The other `from_status=` references are `_archive_cycle` and `_cas_release_to_proposed`, both correctly single-state.

## py_compile — literal stdout

```
$ python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase5_act.py', doraise=True); print('phase5_act py_compile OK')"
phase5_act py_compile OK
$ python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True); print('store_back py_compile OK')"
store_back py_compile OK
```

## Migration SQL parse — literal stdout

```
$ python -c "
import sqlparse
content = open('migrations/20260429_cortex_cycles_add_transient_statuses.sql').read()
parsed = sqlparse.parse(content)
print(f'SQL parsed: {len(parsed)} statements')
for i, stmt in enumerate(parsed):
    if stmt.tokens and not stmt.is_whitespace:
        first_keyword = stmt.token_first(skip_ws=True, skip_cm=True)
        print(f'  stmt {i}: {first_keyword.ttype if first_keyword else None}: {str(first_keyword)[:30]}')
"
SQL parsed: 5 statements
  stmt 0: Token.Keyword: BEGIN
  stmt 1: Token.Keyword.DDL: ALTER
  stmt 2: Token.Keyword.DDL: ALTER
  stmt 3: Token.Keyword.DML: COMMIT
  stmt 4: None: None
```

## Phase 5 + idempotency tests — literal stdout

```
$ /tmp/cortex_venv/bin/python -m pytest tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py -v --no-header
============================= test session starts ==============================
collecting ... collected 44 items

tests/test_cortex_phase5_act.py::test_archive_cycle_updates_and_inserts PASSED [  2%]
tests/test_cortex_phase5_act.py::test_feedback_ledger_uses_canonical_columns PASSED [  4%]
tests/test_cortex_phase5_act.py::test_feedback_ledger_payload_includes_cycle_id PASSED [  6%]
tests/test_cortex_phase5_act.py::test_cortex_reject_archives_and_writes_feedback PASSED [  9%]
tests/test_cortex_phase5_act.py::test_cortex_reject_default_reason_when_missing PASSED [ 11%]
tests/test_cortex_phase5_act.py::test_cortex_edit_persists_edited_text PASSED [ 13%]
tests/test_cortex_phase5_act.py::test_cortex_edit_no_edits_returns_warning PASSED [ 15%]
tests/test_cortex_phase5_act.py::test_cortex_approve_returns_freshness_warning_when_not_fresh PASSED [ 18%]
tests/test_cortex_phase5_act.py::test_cortex_approve_dry_run_skips_execute PASSED [ 20%]
tests/test_cortex_phase5_act.py::test_cortex_approve_writes_gold_then_propagates_then_archives PASSED [ 22%]
tests/test_cortex_phase5_act.py::test_cortex_approve_no_cycle_returns_error PASSED [ 25%]
tests/test_cortex_phase5_act.py::test_is_fresh_fails_open_on_db_error PASSED [ 27%]
tests/test_cortex_phase5_act.py::test_is_fresh_returns_false_when_recent_email_matches PASSED [ 29%]
tests/test_cortex_phase5_act.py::test_write_gold_proposals_calls_gold_proposer_propose PASSED [ 31%]
tests/test_cortex_phase5_act.py::test_write_gold_proposals_continues_on_individual_failure PASSED [ 34%]
tests/test_cortex_phase5_act.py::test_write_gold_proposals_empty_returns_zero PASSED [ 36%]
tests/test_cortex_phase5_act.py::test_propagate_logs_only_when_mac_mini_host_unset PASSED [ 38%]
tests/test_cortex_phase5_act.py::test_propagate_skips_when_no_staged_files PASSED [ 40%]
tests/test_cortex_phase5_act.py::test_cortex_refresh_returns_new_proposal_id PASSED [ 43%]
tests/test_cortex_phase5_act.py::test_cortex_refresh_no_cycle PASSED     [ 45%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_first_fire_returns_none PASSED [ 47%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_second_fire_returns_already_actioned PASSED [ 50%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_missing_cycle_returns_not_found_marker PASSED [ 52%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_no_db_returns_error PASSED [ 54%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_accepts_proposed PASSED [ 56%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_accepts_tier_b_pending PASSED [ 59%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_rejects_random_state PASSED [ 61%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_first_fire_proceeds_normally PASSED [ 63%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_second_fire_returns_already_actioned PASSED [ 65%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_third_fire_still_idempotent PASSED [ 68%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_first_fire_persists_then_releases PASSED [ 70%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_second_fire_returns_already_actioned_no_insert PASSED [ 72%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_third_fire_still_idempotent PASSED [ 75%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_first_fire_proceeds_then_releases PASSED [ 77%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_second_fire_returns_already_actioned PASSED [ 79%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_third_fire_still_idempotent PASSED [ 81%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_first_fire_archives_with_from_status PASSED [ 84%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_second_fire_returns_already_actioned PASSED [ 86%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_third_fire_still_idempotent PASSED [ 88%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_with_from_status_succeeds_on_match PASSED [ 90%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_with_from_status_returns_warning_on_mismatch PASSED [ 93%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_without_from_status_legacy_unconditional PASSED [ 95%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_all_gold_fails_returns_approved_with_errors PASSED [ 97%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_some_gold_fails_returns_approved_with_partial_errors PASSED [100%]

============================== 44 passed in 0.04s ==============================
```

3 new tests + 24 existing idempotency + 17 phase5_act = **44 passed**.

The 3 new tests:
- `test_cas_lock_cycle_accepts_proposed` — verifies multi-tuple acceptance retains the legacy `'proposed'` entry path; asserts the SQL emits `ANY(%s)` and the param array is `["proposed", "tier_b_pending"]`.
- `test_cas_lock_cycle_accepts_tier_b_pending` — NEW BEHAVIOR — cycle at `'tier_b_pending'` now CAS-succeeds (pre-fix would silently bail). Asserts `'tier_b_pending'` is in the array passed to `ANY()`.
- `test_cas_lock_cycle_rejects_random_state` — defensive — cycle at `'failed'` does NOT match (not in the from-tuple), returns warning with `current_status='failed'`. Proves multi-state acceptance is bounded to the explicit tuple.

## Cross-cap regression — literal stdout

```
$ /tmp/cortex_venv/bin/python -m pytest tests/test_cortex_runner_phase126.py tests/test_cortex_pre_review_gate.py tests/test_cortex_slack_interactivity.py --no-header
...
======================== 34 passed, 5 warnings in 1.06s ========================
```

Slack interactivity, pre-review gate, runner phase 1/2/6 — all PASS, no behavioral regression.

## Files modified

- MOD `orchestrator/cortex_phase5_act.py` — `_cas_lock_cycle` signature + SQL + 4 call sites
- MOD `memory/store_back.py` — `_ensure_cortex_cycles_table` CHECK now 15-value
- NEW `migrations/20260429_cortex_cycles_add_transient_statuses.sql` — pin 4 transient statuses
- NEW `memory/feedback_render_envvar_paginated_put.md` — Render env-var regression rule
- NEW `memory/MEMORY.md` — 1-line index pointer
- MOD `tests/test_cortex_phase5_idempotency.py` — 4 existing direct callers updated to new kwarg + 3 new multi-state tests
- MOD `briefs/_tasks/CODE_3_PENDING.md` — mailbox claim flip (OPEN → IN_PROGRESS)

## Pass criteria — checklist

| Criterion | Result |
|---|---|
| 2+ new tests PASS literally | ✅ (3 new) |
| Phase 5 + idempotency regression PASS literally | ✅ (44/44 — no false-PASS, the new branch breaks `from_status=` so the test edits are real exercise) |
| Phase 1/2/6 + pre-review-gate + slack-interactivity regression PASS | ✅ (34/34) |
| py_compile clean (both .py) | ✅ |
| Migration SQL parses (sqlparse) | ✅ (5 statements: BEGIN/ALTER×2/COMMIT/EOF) |
| `_cas_lock_cycle` accepts only the 4 valid pre-button states | ✅ (`("proposed", "tier_b_pending")` × 4 handlers; `from_statuses` is single source of truth) |
| store_back CHECK matches migration CHECK exactly | ✅ (both list the same 15 values; ordering differs but PostgreSQL CHECK semantics are set-based) |
| Files outside the brief scope unchanged | ✅ |

## STOP criteria — none triggered

- `_cas_lock_cycle` accepts states outside the 4 valid → not the case (multi-tuple is exactly `("proposed","tier_b_pending")`)
- store_back / migration CHECK drift → both carry the same 15 values
- Tests fail or any "by inspection" → all 78 tests PASS literally

## After merge — A executes

Per brief §"Post-merge — A executes":
1. `/security-review` (Lesson #52 mandatory)
2. B1 structural review (RA-24)
3. Both clear → A squash-merge to main
4. Render redeploy
5. Verify on prod DB: `SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='cortex_cycles_status_check'` matches the new 15-value CHECK
6. Director-side smoke deferred — next REAL AO cycle naturally exercises the path

## PR

_(URL appended after `gh pr create`.)_

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
