# Ship Report — CORTEX_PHASE5_IDEMPOTENCY_1

**B-code:** B2 (App tab)
**Brief:** `briefs/BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md`
**Branch:** `cortex-phase5-idempotency-1` (cut from `main` post PR #74 merge `97f26b1`)
**Reviewer:** b3 (second-pair-review per MEDIUM trigger class — Phase 5 hottest context post-1C build)
**Authority:** AI Head A dispatch 2026-04-28T14:50Z (relayed Director RA 2026-04-28T14:35Z accepting AI Head B's PR #74 OBS-1+OBS-2 follow-up).
**Date:** 2026-04-28

---

## What shipped

Two surgical changes in `orchestrator/cortex_phase5_act.py` closing AI Head B's PR #74 structural-design findings:

1. **OBS-1 (HIGH)** — `cortex_approve` (and the 3 sibling handlers `cortex_edit` / `cortex_refresh` / `cortex_reject`) is now idempotent. New `_cas_lock_cycle` helper performs `UPDATE cortex_cycles SET status=<*ing> WHERE cycle_id=%s AND status='proposed' RETURNING cycle_id` at the **very top** of each handler body. On 0-rows-affected → re-reads current status and returns `{"warning":"already_actioned", "current_status": ..., "cycle_id": ..., "action_attempted": ...}` with HTTP 200 (idempotent retry, not an error). Director double-click / Slack proxy retry no longer creates duplicate `ProposedGoldEntry` rows or duplicate `final_archive` audit rows.

   New transient statuses `'approving'` / `'editing'` / `'refreshing'` / `'rejecting'` per Brief §"Status state machine":

   ```
   proposed → approving  → approved   (Phase 6 archive)
   proposed → editing    → proposed   (re-loop, _cas_release_to_proposed)
   proposed → refreshing → proposed   (re-loop, _cas_release_to_proposed)
   proposed → rejecting  → rejected   (terminal)
   ```

   `_archive_cycle` now accepts optional `from_status` param; when supplied (`'approving'` for approve / `'rejecting'` for reject), the UPDATE gates on `WHERE status=<from_status>` and uses `RETURNING cycle_id`. On 0-rows-affected the function logs a warning and **returns WITHOUT inserting a duplicate `final_archive` row**. `from_status=None` preserves the legacy unconditional path for any unmigrated caller.

2. **OBS-2 (MEDIUM)** — `_write_gold_proposals` now returns a rich result dict `{"written", "total", "failed_files", "errors"}` instead of a bare int. `cortex_approve` branches on the dict to surface partial-failure to Director:
   - all-fail (`total>0, written==0`) → `status="approved_with_errors"` + `warning="all_gold_proposals_failed"` + `errors` list
   - some-fail (`0<written<total`) → `status="approved_with_partial_errors"` + `warning="some_gold_proposals_failed"` + `failed_files` list
   - all-ok (`written==total`) → existing `status="approved"` path

   Cycle archive still proceeds (status='approved') in all three branches — Director sees the discrepancy in the response payload (which surfaces in the dashboard's Slack DM update).

## Files modified

- `orchestrator/cortex_phase5_act.py` — +124 LOC. Added `_cas_lock_cycle` (49 LOC) + `_cas_release_to_proposed` (33 LOC); patched 4 handlers (CAS at top + edit/refresh release-back); refactored `_write_gold_proposals` to return rich dict; hardened `_archive_cycle` with optional `from_status` + RETURNING.
- `tests/test_cortex_phase5_idempotency.py` — **NEW, 21 tests:**
   - 4 `_cas_lock_cycle` direct unit tests (success / already_actioned / not_found / no_db)
   - 12 handler idempotency tests (3 per handler × 4 handlers: first-fire / second-fire / third-fire)
   - 3 `_archive_cycle` hardening tests (success-on-match / warning-on-mismatch / legacy-unconditional)
   - 2 partial-failure surfacing tests in `cortex_approve` (all-fail / some-fail)
- `tests/test_cortex_phase5_act.py` — +1 autouse `_bypass_cas` fixture (existing tests now bypass CAS via monkeypatch — they test other behavior); 3 `_write_gold_proposals` tests updated to new dict return shape; `test_cortex_approve_writes_gold_then_propagates_then_archives` updated to return the new dict shape from monkeypatched `_write_gold_proposals`.

**Net diff:** 3 files, +260 / −38 LOC vs main.

## Files NOT touched (per brief §"Files NOT to Touch")

- `orchestrator/cortex_phase4_proposal.py` ✓
- `orchestrator/cortex_runner.py` ✓
- `migrations/*.sql` ✓ (zero schema change — `status` column accepts new values via existing absence of CHECK constraint)
- `kbl/gold_writer.py` / `kbl/gold_proposer.py` ✓ (Amendment A1 boundary preserved)
- `outputs/dashboard.py` endpoint signature ✓ (additive JSON fields only, no breaking changes)
- `scripts/cortex_rollback_v1.sh` ✓

## Quality Checkpoint #1 — pytest 41/41 dedicated suite green

```
$ python3 -m pytest tests/test_cortex_phase5_idempotency.py tests/test_cortex_phase5_act.py -v
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
collecting ... collected 41 items

tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_first_fire_returns_none PASSED [  2%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_second_fire_returns_already_actioned PASSED [  4%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_missing_cycle_returns_not_found_marker PASSED [  7%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_no_db_returns_error PASSED [  9%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_first_fire_proceeds_normally PASSED [ 12%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_second_fire_returns_already_actioned PASSED [ 14%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_third_fire_still_idempotent PASSED [ 17%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_first_fire_persists_then_releases PASSED [ 19%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_second_fire_returns_already_actioned_no_insert PASSED [ 21%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_third_fire_still_idempotent PASSED [ 24%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_first_fire_proceeds_then_releases PASSED [ 26%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_second_fire_returns_already_actioned PASSED [ 29%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_third_fire_still_idempotent PASSED [ 31%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_first_fire_archives_with_from_status PASSED [ 34%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_second_fire_returns_already_actioned PASSED [ 36%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_third_fire_still_idempotent PASSED [ 39%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_with_from_status_succeeds_on_match PASSED [ 41%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_with_from_status_returns_warning_on_mismatch PASSED [ 43%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_without_from_status_legacy_unconditional PASSED [ 46%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_all_gold_fails_returns_approved_with_errors PASSED [ 48%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_some_gold_fails_returns_approved_with_partial_errors PASSED [ 51%]
tests/test_cortex_phase5_act.py::test_archive_cycle_updates_and_inserts PASSED [ 53%]
tests/test_cortex_phase5_act.py::test_feedback_ledger_uses_canonical_columns PASSED [ 56%]
tests/test_cortex_phase5_act.py::test_feedback_ledger_payload_includes_cycle_id PASSED [ 58%]
tests/test_cortex_phase5_act.py::test_cortex_reject_archives_and_writes_feedback PASSED [ 60%]
tests/test_cortex_phase5_act.py::test_cortex_reject_default_reason_when_missing PASSED [ 63%]
tests/test_cortex_phase5_act.py::test_cortex_edit_persists_edited_text PASSED [ 65%]
tests/test_cortex_phase5_act.py::test_cortex_edit_no_edits_returns_warning PASSED [ 68%]
tests/test_cortex_phase5_act.py::test_cortex_approve_returns_freshness_warning_when_not_fresh PASSED [ 70%]
tests/test_cortex_phase5_act.py::test_cortex_approve_dry_run_skips_execute PASSED [ 73%]
tests/test_cortex_phase5_act.py::test_cortex_approve_writes_gold_then_propagates_then_archives PASSED [ 75%]
tests/test_cortex_phase5_act.py::test_cortex_approve_no_cycle_returns_error PASSED [ 78%]
tests/test_cortex_phase5_act.py::test_is_fresh_fails_open_on_db_error PASSED [ 80%]
tests/test_cortex_phase5_act.py::test_is_fresh_returns_false_when_recent_email_matches PASSED [ 82%]
tests/test_cortex_phase5_act.py::test_write_gold_proposals_calls_gold_proposer_propose PASSED [ 85%]
tests/test_cortex_phase5_act.py::test_write_gold_proposals_continues_on_individual_failure PASSED [ 87%]
tests/test_cortex_phase5_act.py::test_write_gold_proposals_empty_returns_zero PASSED [ 90%]
tests/test_cortex_phase5_act.py::test_propagate_logs_only_when_mac_mini_host_unset PASSED [ 92%]
tests/test_cortex_phase5_act.py::test_propagate_skips_when_no_staged_files PASSED [ 95%]
tests/test_cortex_phase5_act.py::test_cortex_refresh_returns_new_proposal_id PASSED [ 97%]
tests/test_cortex_phase5_act.py::test_cortex_refresh_no_cycle PASSED     [100%]

============================== 41 passed in 0.04s ==============================
```

**Brief minimum:** 12 idempotency + 2 partial-failure = 14 new tests. **Delivered:** 21 new tests (4 CAS-direct + 12 handler idempotency + 3 _archive_cycle hardening + 2 partial-failure). Existing 20 phase5_act tests still pass = 41 total in dedicated suite.

## Quality Checkpoint #2 — full cortex+alerts regression green

```
$ python3 -m pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py
================== 182 passed, 5 skipped, 1 warning in 0.96s ===================
```

**Math vs brief baseline:** 1A 31/31 + 1B 48/48 + 1C 82/82 = 161 + new 21 = 182 ✓ (exact match against brief §"Verification").

**5 skipped** = pre-existing integration tests requiring live Postgres (`needs_live_pg` markers). Not new on this branch.

## Quality Checkpoint #3 — syntax check

```
$ python3 -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['orchestrator/cortex_phase5_act.py', 'tests/test_cortex_phase5_idempotency.py', 'tests/test_cortex_phase5_act.py']]; print('compile OK')"
compile OK
```

## Acceptance criteria from brief — verified

| # | Criterion | Verified by |
|---|---|---|
| 1 | CAS guard fires on `cortex_approve` second invocation → `warning="already_actioned"` | `test_cortex_approve_second_fire_returns_already_actioned` |
| 2 | Same for `cortex_edit` / `cortex_refresh` / `cortex_reject` | 3 `*_second_fire_*` tests |
| 3 | CAS does NOT fire on first invocation → handler proceeds | 4 `*_first_fire_*` tests |
| 4 | `_archive_cycle` hardened WHERE → warning on state mismatch, NO duplicate INSERT | `test_archive_cycle_with_from_status_returns_warning_on_mismatch` |
| 5 | `_write_gold_proposals` partial-fail: 3/3 fail → `status="approved_with_errors"` | `test_cortex_approve_all_gold_fails_returns_approved_with_errors` |
| 6 | `_write_gold_proposals` partial-fail: 1/3 fail → `status="approved_with_partial_errors"` | `test_cortex_approve_some_gold_fails_returns_approved_with_partial_errors` |
| 7 | `_write_gold_proposals` 0/3 fail → existing success path unchanged | `test_cortex_approve_writes_gold_then_propagates_then_archives` (now asserts `"warning" not in result`) |
| 8 | Status state machine: `proposed → approving → approved` transitions visible | CAS test + `_archive_cycle_with_from_status_succeeds_on_match` |
| 9 | Zero schema changes | `git diff main..HEAD --stat` shows no `migrations/*.sql` |
| 10 | Zero changes to `kbl/gold_writer.py` / `kbl/gold_proposer.py` / `dashboard.py` | `git diff main..HEAD --name-only` lists 3 files only |

## Lessons applied

- **Lesson #34 / #42 / #44 / #47** — literal pytest stdout in ship report (no "by inspection").
- **Lesson #50** — review-in-flight pre-check N/A (this is a build, not a review).
- **Lesson #52** — `/security-review` MANDATORY before merge. Trigger class MEDIUM (cross-capability state-write hardening) → b3 second-pair-review pre-merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md` THEN AI Head A `/security-review`. Self-PR rule reminder: PR comments only, AI Head A Tier-A direct squash-merge after both clear.
- **Lesson #37** (migration-vs-bootstrap drift) — N/A (zero DDL added; CAS uses existing `status` column).
- **Lesson #48** (paste-block strict) — handoff to AI Head A via paste-block at end of session.

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
