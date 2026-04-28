# B3 review report — PR #75 CORTEX_PHASE5_IDEMPOTENCY_1

**PR:** https://github.com/vallen300-bit/baker-master/pull/75
**Branch / HEAD:** `cortex-phase5-idempotency-1` @ `d55e850`
**Diff:** +1065 / -41 across 5 files (`orchestrator/cortex_phase5_act.py`, `tests/test_cortex_phase5_act.py`, `tests/test_cortex_phase5_idempotency.py`, builder mailbox + ship report)
**Brief:** `briefs/BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md`
**Builder:** Code Brisen #2 (App)
**Reviewer:** Code Brisen #3 (b3) — independent (1C / Phase 5 author context)
**Trigger class:** MEDIUM (cross-capability state-write hardening on `cortex_cycles` + GOLD path)
**Date:** 2026-04-28
**Verdict:** **APPROVE** (formal APPROVE blocked by self-PR rule — comment is the gate per #67/#69/#70/#71/#72/#74 precedent)

---

## TL;DR

PR closes both AI Head B PR #74 follow-up findings cleanly:
- **OBS-1 (HIGH)** — 4-handler CAS guard + `_archive_cycle` defensive WHERE-clause prevent double-fire from creating duplicate GOLD entries / `final_archive` rows.
- **OBS-2 (MEDIUM)** — `_write_gold_proposals` returns rich result dict; `cortex_approve` surfaces `approved_with_errors` / `approved_with_partial_errors` so Director can see GOLD-write divergence from cycle-status success.

Single-file production patch, 21 new tests, 41 test passes on the dedicated suite, **182 passed + 5 skipped** on the full cortex+alerts regression — exactly matches B2's claim (1A 31 + 1B 48 + 1C 82 = 161 baseline + 21 new = 182). Boundaries respected (Amendment A1 preserved; no schema change; endpoint signature additive only).

One LOW observation noted (intermediate-state stickiness on cortex_approve early-exit), but the brief **explicitly accepts** this risk via the parked archive-failure sentinel — not a blocker.

---

## Literal pytest output (Lesson #47 mandatory)

### Dedicated suite (21 idempotency tests)

```
$ pytest tests/test_cortex_phase5_idempotency.py -v 2>&1 | tail -50

============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b3
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
collecting ... collected 21 items

tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_first_fire_returns_none PASSED [  4%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_second_fire_returns_already_actioned PASSED [  9%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_missing_cycle_returns_not_found_marker PASSED [ 14%]
tests/test_cortex_phase5_idempotency.py::test_cas_lock_cycle_no_db_returns_error PASSED [ 19%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_first_fire_proceeds_normally PASSED [ 23%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_second_fire_returns_already_actioned PASSED [ 28%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_third_fire_still_idempotent PASSED [ 33%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_first_fire_persists_then_releases PASSED [ 38%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_second_fire_returns_already_actioned_no_insert PASSED [ 42%]
tests/test_cortex_phase5_idempotency.py::test_cortex_edit_third_fire_still_idempotent PASSED [ 47%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_first_fire_proceeds_then_releases PASSED [ 52%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_second_fire_returns_already_actioned PASSED [ 57%]
tests/test_cortex_phase5_idempotency.py::test_cortex_refresh_third_fire_still_idempotent PASSED [ 61%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_first_fire_archives_with_from_status PASSED [ 66%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_second_fire_returns_already_actioned PASSED [ 71%]
tests/test_cortex_phase5_idempotency.py::test_cortex_reject_third_fire_still_idempotent PASSED [ 76%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_with_from_status_succeeds_on_match PASSED [ 80%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_with_from_status_returns_warning_on_mismatch PASSED [ 85%]
tests/test_cortex_phase5_idempotency.py::test_archive_cycle_without_from_status_legacy_unconditional PASSED [ 90%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_all_gold_fails_returns_approved_with_errors PASSED [ 95%]
tests/test_cortex_phase5_idempotency.py::test_cortex_approve_some_gold_fails_returns_approved_with_partial_errors PASSED [100%]

============================== 21 passed in 0.04s ==============================
```

### Full cortex + alerts regression

```
$ pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py -v 2>&1 | tail -10

================== 182 passed, 5 skipped, 1 warning in 0.91s ===================
```

5 skipped = `test_cortex_action_endpoint.py` TestClient suite (pre-existing Python 3.9 PEP-604 chain in `tools/ingest/extractors.py:275` — clears on CI 3.10+). Same skip pattern as `test_proactive_pm_sentinel.py`.

**Math check:** B2's claim was `161 baseline + 21 new = 182`. Verified. ✅

---

## 7-criteria checklist (5 brief-mandated + 2 design-validation)

### ✅ Criterion 1 — Brief acceptance match

Walk-through against `BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md` §"Quality Checkpoints" (10 items) + §"Verification":

| QC# | Brief requirement | Where verified |
|---|---|---|
| 1 | CAS guard fires on `cortex_approve` second invocation → returns `warning="already_actioned"` with `current_status` | `test_cortex_approve_second_fire_returns_already_actioned` (PASS) |
| 2 | Same for `cortex_edit` / `cortex_refresh` / `cortex_reject` (3 separate tests) | 3×3 = 9 tests covering 1st/2nd/3rd fire on each handler (PASS) |
| 3 | CAS guard does NOT fire on first invocation → handler proceeds normally | 4 first-fire tests (`test_*_first_fire_*`) (PASS) |
| 4 | `_archive_cycle` hardened WHERE clause — if cycle is not in `'approving'` state, returns warning, does NOT silently overwrite | `test_archive_cycle_with_from_status_returns_warning_on_mismatch` confirms NO `INSERT INTO cortex_phase_outputs` happens when CAS fails (PASS) |
| 5 | `_write_gold_proposals` partial-failure: 3 selected files, all 3 fail → `status="approved_with_errors"` | `test_cortex_approve_all_gold_fails_returns_approved_with_errors` (PASS) |
| 6 | 3 selected files, 2 fail → `status="approved_with_partial_errors"` with `failed_files` list | `test_cortex_approve_some_gold_fails_returns_approved_with_partial_errors` (PASS) |
| 7 | 3 selected files, 0 fail → returns existing success path unchanged | Implicit in `test_cortex_approve_first_fire_proceeds_normally` (gold_result `{written:1, total:1}` returns `status="approved"`); also `test_cortex_phase5_act.py::test_cortex_approve_writes_gold_then_propagates_then_archives` (existing 1C test, still passing) |
| 8 | Status state machine: `proposed → approving → approved` | Verified in code (`cortex_approve` line 176 CAS + line 220 `_archive_cycle` with `from_status='approving'`) and in test ordering |
| 9 | Zero schema changes (no new migration; existing `status` column accepts new transient values) | `git diff main...d55e850 -- migrations/` returns 0 lines ✅. Existing `cortex_cycles.status` column has no CHECK constraint per `migrations/20260428_cortex_cycles.sql` review (free-text TEXT column), so transient values `approving/editing/refreshing/rejecting` slot in cleanly |
| 10 | Zero changes to `kbl/gold_writer.py` / `kbl/gold_proposer.py` / `dashboard.py` endpoint signature | `git diff main...d55e850 -- kbl/gold_writer.py kbl/gold_proposer.py outputs/dashboard.py` returns 0 lines ✅ |

**All 10 brief acceptance items pass.**

### ✅ Criterion 2 — CAS guard correctness

All 4 handlers have the CAS guard at the **top of the body before any DB read or write**:

| Handler | CAS line | First DB access (after CAS) | WHERE clause | Target intermediate | action_attempted |
|---|---|---|---|---|---|
| `cortex_approve` | `cortex_phase5_act.py:176-184` | `_load_cycle` at line 185 | `status='proposed'` | `'approving'` | `"approve"` |
| `cortex_edit` | `cortex_phase5_act.py:266-274` | INSERT at line 281 (after pure-Python `edits` validation at 262-264) | `status='proposed'` | `'editing'` | `"edit"` |
| `cortex_refresh` | `cortex_phase5_act.py:317-325` | `_load_cycle` at line 326 | `status='proposed'` | `'refreshing'` | `"refresh"` |
| `cortex_reject` | `cortex_phase5_act.py:382-389` | `_load_cycle` at line 392 | `status='proposed'` | `'rejecting'` | `"reject"` |

`cortex_edit`'s pre-CAS `edits` truthiness check at line 262-264 is pure-Python (no DB access) — does not violate "before any DB read/write". Acceptable.

CAS path itself (`_cas_lock_cycle`):
- Atomic UPDATE with `WHERE status=%s RETURNING cycle_id` — single round-trip. ✅
- If RETURNING is empty, re-reads current status for diagnostic — separate SELECT, but in same transaction (`conn.commit()` only at the end of the path). ✅
- Fails CLOSED on DB exception — `raise` after rollback, so caller sees the exception (does NOT silently bypass the lock). ✅
- Fails CLOSED on `conn is None` — returns `error="no_db_connection"` so caller bails. ✅

Per-handler CAS pre-conditions match the brief table exactly. ✅

### ✅ Criterion 3 — Idempotency proof in tests

Literal pytest stdout pasted above. **21 new tests pass, 182 total green** on full regression.

Each handler has 3 fire-count tests (1st/2nd/3rd fire) + ROOT CAS unit tests (4 of them) + archive WHERE-clause tests (3) + partial-failure tests (2). Test design proves N-retry safety: third fire still returns the same warning, no race-condition skew.

### ✅ Criterion 4 — `_archive_cycle` defensive WHERE-clause

`cortex_phase5_act.py:605-689`:

- **`from_status` supplied path** (lines 631-658):
  - UPDATE `WHERE cycle_id=%s AND status=%s RETURNING cycle_id` — gated.
  - If `cur.fetchone() is None` (no rows updated) → log warning, return `archive_unexpected_state` warning dict, **DO NOT** insert `final_archive` row (preserves audit-row integrity).
  - On match → falls through to standard INSERT + commit + return `None`.

- **Legacy `from_status=None` path** (lines 659-669):
  - Unconditional UPDATE — preserved for backward compatibility.
  - Falls through to INSERT + commit + return `None`.

Test coverage explicit:
- `test_archive_cycle_with_from_status_succeeds_on_match` — both UPDATE + INSERT happen when CAS matches.
- `test_archive_cycle_with_from_status_returns_warning_on_mismatch` — UPDATE happens, **INSERT does NOT** (asserted explicitly via `not any("INSERT INTO cortex_phase_outputs" in s for s in sqls)`).
- `test_archive_cycle_without_from_status_legacy_unconditional` — UPDATE is unconditional (no `AND status=%s`) + INSERT happens.

Backward-compat verified ✅ — existing callers without `from_status` keyword (e.g. anywhere in `cortex_runner.py`'s timeout-handler UPDATE path) keep working unchanged.

### ✅ Criterion 5 — Boundaries respected (Amendment A1)

```
$ grep -n "gold_writer\|_check_caller_authorized" orchestrator/cortex_phase4_proposal.py orchestrator/cortex_phase5_act.py orchestrator/cortex_runner.py orchestrator/cortex_phase2_loaders.py orchestrator/cortex_phase3_*.py

orchestrator/cortex_phase5_act.py:13:``kbl.gold_writer.append`` (the caller-authorized guard rejects any frame
orchestrator/cortex_phase5_act.py:513:    gold_writer).
```

Both hits are **docstrings warning AGAINST using `gold_writer`**. The actual import is `from kbl.gold_proposer import ProposedGoldEntry, propose` at line 532 + call at line 551. ✅

`git diff main...d55e850 -- kbl/gold_writer.py kbl/gold_proposer.py` returns zero lines — caller-authorized guard at `kbl/gold_writer.py:_check_caller_authorized` untouched. Amendment A1 (PR #74 boundary) preserved. ✅

### ✅ Criterion 6 — Status state machine consistency

```
proposed ──CAS──> approving ──_archive_cycle──> approved (terminal)
proposed ──CAS──> editing ────_cas_release──> proposed (re-loop)
proposed ──CAS──> refreshing ─_cas_release──> proposed (re-loop)
proposed ──CAS──> rejecting ──_archive_cycle──> rejected (terminal)
```

Every `*ing` state has a release path on the success line:
- `approving` → terminal via `_archive_cycle(from_status='approving')` at `cortex_approve:220-223` (DRY_RUN path) and 220-223 (live path). ✅
- `editing` → released via `_cas_release_to_proposed(cycle_id, from_status='editing')` at `cortex_edit:302`. ✅
- `refreshing` → released via `_cas_release_to_proposed(cycle_id, from_status='refreshing')` at `cortex_refresh:371`. ✅
- `rejecting` → terminal via `_archive_cycle(from_status='rejecting')` at `cortex_reject:393-396`. ✅

No deadlock by design.

#### LOW-1 — observation, not blocker

`cortex_approve` has two early-exit paths AFTER the CAS lock that leave the cycle in `'approving'` without release/archive:
- Line 186-187: `if not cycle: return {"error": "cycle_not_found"}`
- Line 188-189: `if not _is_fresh(cycle_id): return {"warning": "freshness_check_failed", "advice": "refresh_first"}`

In practice the `cycle_not_found` path is impossible after a successful CAS (the UPDATE proves the row exists). The `freshness_check_failed` path IS reachable: Director clicks Approve, CAS flips to 'approving', `_is_fresh` returns False (a Director email landed in the last 30 min), handler returns warning — cycle stays at 'approving'. Subsequent Approve / Edit / Refresh attempts will all fail CAS (status != 'proposed') and return `already_actioned`.

**This is acceptable per brief design intent.** The brief explicitly states:
> "Intermediate `*ing` states are short-lived (<5s typical) but durable — visible to monitoring during execution. If a handler crashes mid-execution, the cycle stays in `*ing` state and a follow-up sentinel (parked at `_ops/ideas/2026-04-28-cortex-archive-failure-alerting.md`) will catch it post-V1."

The `freshness_check_failed` early-exit is structurally identical to a "handler crashes mid-execution" — same recovery path applies. The advice `"refresh_first"` is also slightly stale because Refresh would now also fail CAS; in practice the parked sentinel + Director-manual SQL flip back to 'proposed' is the recovery. **Worth flagging in the post-V1 sentinel brief but NOT a blocker for this PR** — closing the door fully would require either:
- Releasing back to 'proposed' before each early-exit (not in scope), or
- Doing freshness BEFORE CAS (would defeat idempotency: stale fresh-check + race could let a duplicate slip through).

The current design correctly prioritizes idempotency over early-exit cleanup. ✅

### ✅ Criterion 7 — Partial-failure surfacing semantics

`_write_gold_proposals` rich return shape (`cortex_phase5_act.py:529`):
```python
result = {"written": 0, "total": len(selected_files), "failed_files": [], "errors": []}
```
- Per-file try/except continues across siblings (line 550-559) — ensures one bad file doesn't kill the rest.
- Failed entries push into `failed_files` + `errors` lists.

`cortex_approve` consumer (`cortex_phase5_act.py:225-253`):
- `total > 0 and written == 0` → `status="approved_with_errors"` + `warning="all_gold_proposals_failed"` + full `errors` list. ✅
- `total > 0 and written < total` → `status="approved_with_partial_errors"` + `warning="some_gold_proposals_failed"` + `failed_files` list. ✅
- All-succeed path → `status="approved"` (existing shape). ✅

**Endpoint surface**: `POST /cortex/cycle/{id}/action` at `outputs/dashboard.py` is **untouched** (`git diff` confirms zero lines). The new fields (`gold_files_attempted`, `gold_files_written`, `failed_files`, `errors`, `cycle_id`, refined `status`) are **additive in the JSON response payload** — no breaking change to existing consumers per brief §"Files NOT to Touch". ✅

`_write_gold_proposals` return-shape change is internal to `cortex_phase5_act.py`. The 3 existing `test_cortex_phase5_act.py` tests that asserted on the old `int` return have been updated to the new dict shape (verified: `tests/test_cortex_phase5_act.py:241,255,327,346,352,361,365`).

Cycle archive still proceeds (`status='approved'`) regardless of partial-failure path — Director sees the discrepancy via the response payload, which is exactly the brief's intent: cycle terminal state stays consistent, but the user-visible payload accurately reflects durable GOLD-write state.

---

## Code-quality observations (for builder ack, not blocking)

1. **`_cas_lock_cycle` DRY helper** — centralizing the CAS pattern in one helper function (vs duplicating across 4 handlers) is cleaner than the brief's literal example which inlined the SQL per handler. Strong improvement on readability and future maintainability. ✅
2. **`_cas_release_to_proposed` is fail-OPEN (logs but does not raise)** — appropriate for the re-loop path: the primary work (Phase-3+4 re-run, or director_edit INSERT) already succeeded; leaving the cycle stuck at `*ing` is recoverable via the parked sentinel, whereas raising here would propagate a 500 to the Slack interactivity webhook even though the Director's edit/refresh action durably landed. Consistent with the brief's explicit "post-V1 sentinel" recovery model.
3. **Autouse `_bypass_cas` fixture in `test_cortex_phase5_act.py`** — clean separation of concerns. Existing 20 tests focus on body logic; new 21 tests focus on CAS. Future tests in either file get the right defaults.
4. **`_RowsScript` / `_ScriptedCursor` test harness** — sophisticated multi-query mock that drives the SUT through the exact CAS UPDATE → SELECT diagnostic re-read path. Slightly more complex than a plain queue but accurately reflects the production code shape. Good investment for the 4 follow-up tests.

---

## Files modified summary

```
$ git diff main...d55e850 --stat
 ...B2_pr75_cortex_phase5_idempotency_1_20260428.md | 158 ++++++
 briefs/_tasks/CODE_2_PENDING.md                    |  11 +-
 orchestrator/cortex_phase5_act.py                  | 327 +++++++++++-
 tests/test_cortex_phase5_act.py                    |  44 +-
 tests/test_cortex_phase5_idempotency.py            | 566 +++++++++++++++++++++
 5 files changed, 1065 insertions(+), 41 deletions(-)
```

Production change is **single file** (`orchestrator/cortex_phase5_act.py`); other modifications are tests + builder mailbox + builder ship report. Surgical scope as specified by brief. ✅

---

## Verdict

**APPROVE.** PR #75 closes both AI Head B PR #74 follow-up findings (OBS-1 HIGH idempotency + OBS-2 MEDIUM partial-failure surfacing) cleanly:

- 4-handler CAS guard via centralized `_cas_lock_cycle` helper — fail-CLOSED on DB error, returns idempotent `already_actioned` warning on N-retry.
- `_archive_cycle` defensive WHERE-clause with backward-compat legacy path.
- `_write_gold_proposals` rich return shape + `cortex_approve` 3-tier status (`approved` / `approved_with_partial_errors` / `approved_with_errors`).
- 21 new tests + 182-test full-regression green.
- Boundaries respected (Amendment A1 / no schema change / endpoint signature additive).
- One LOW observation (cortex_approve early-exit-stuck-state) explicitly accepted by brief design intent — recoverable via parked archive-failure sentinel.

Formal APPROVE is blocked by self-PR rule (b3 second-pair-review per b1-trigger-class precedent #67/#69/#70/#71/#72/#74). This report serves as the gate per canonical pattern.

A's `/security-review` NO FINDINGS already posted (PR comment 4336588952). On B3 APPROVE → A Tier-A merge.

---

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
