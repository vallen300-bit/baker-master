# Ship Report — CORTEX_ARCHIVE_FAILURE_ALERTING_1

**Brief:** `briefs/BRIEF_CORTEX_ARCHIVE_FAILURE_ALERTING_1.md` (rev 2 — 2026-04-29T~06:25Z)
**Builder:** AI Head B (aihead2 lane)
**Branch:** `cortex-archive-failure-alerting-1`
**Trigger class:** MEDIUM (DB sentinel + Slack writes; A solo /security-review, no B-code review per RA-24)

---

## §0 Literal stdout

### Test 1 — new sentinel suite (`pytest tests/test_cortex_stuck_cycle_sentinel.py -v`)

```
collected 10 items

tests/test_cortex_stuck_cycle_sentinel.py::test_happy_path_no_stuck_no_alerts PASSED [ 10%]
tests/test_cortex_stuck_cycle_sentinel.py::test_one_stuck_cycle_emits_alert_and_dedup PASSED [ 20%]
tests/test_cortex_stuck_cycle_sentinel.py::test_two_stuck_cycles_two_alerts PASSED [ 30%]
tests/test_cortex_stuck_cycle_sentinel.py::test_already_alerted_dedup_honored PASSED [ 40%]
tests/test_cortex_stuck_cycle_sentinel.py::test_archive_failed_cycle_emits_alert_with_correct_action_type PASSED [ 50%]
tests/test_cortex_stuck_cycle_sentinel.py::test_mixed_one_stuck_one_archive_one_deduped PASSED [ 60%]
tests/test_cortex_stuck_cycle_sentinel.py::test_format_alert_text_stuck_mode PASSED [ 70%]
tests/test_cortex_stuck_cycle_sentinel.py::test_format_alert_text_archive_failed_mode PASSED [ 80%]
tests/test_cortex_stuck_cycle_sentinel.py::test_record_alert_returns_true_on_insert_false_on_dedup PASSED [ 90%]
tests/test_cortex_stuck_cycle_sentinel.py::test_detect_query_filters_by_status_and_excludes_already_alerted PASSED [100%]

============================== 10 passed in 1.57s ==============================
```

10/10 PASS — 6 brief-required scenarios + 4 helper unit tests.

### Test 2 — regression (`pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase5_act.py tests/test_cortex_pre_review_gate.py -v`)

```
======================== 46 passed, 6 warnings in 1.79s ========================
```

46/46 PASS. Warnings are pre-existing (FastAPI on_event deprecation, qdrant version-check, regex escape) — not introduced by this PR.

### Test 3-5 — py_compile

```
cortex_runner.py: clean
cortex_stuck_cycle_sentinel.py: clean
embedded_scheduler.py: clean
store_back.py: clean
```

All 4 modified Python files compile cleanly.

---

## §1 What shipped + file list

**6 files** (5 brief-scoped + 1 drift-defense, see §4):

| File | Status | Lines | Purpose |
|---|---|---|---|
| `migrations/20260429_cortex_cycles_add_archive_failed_status.sql` | NEW | 65 | ALTER CHECK constraint to allow `archive_failed` |
| `triggers/cortex_stuck_cycle_sentinel.py` | NEW | 277 | 5-min sentinel; Detector A (stuck) + B (archive_failed); Slack DM + dedup |
| `orchestrator/cortex_runner.py` | MOD | +37 net | Phase 6 archive-failed status persist + 4 logger.error → structured `extra={}` conversions |
| `triggers/embedded_scheduler.py` | MOD | +20 | Sentinel registration with `CORTEX_STUCK_CYCLE_SENTINEL_ENABLED` env gate |
| `tests/test_cortex_stuck_cycle_sentinel.py` | NEW | 287 | 6 brief scenarios + 4 helper unit tests |
| `memory/store_back.py` | MOD | +1 | Drift-defense: bootstrap CHECK now includes `archive_failed` (Lesson §migration-vs-bootstrap-trap) |

---

## §2 Ship-gate verification table

| Gate | Status |
|---|---|
| 6+ unit tests PASS literally | ✅ 10/10 (above brief minimum of 6) |
| Regression cortex_runner + phase5_act + gate PASS literally | ✅ 46/46 |
| py_compile clean on all modified Python files | ✅ 4/4 |
| Sentinel scheduled with `max_instances=1, coalesce=True` (matches gold_audit_sentinel) | ✅ confirmed at `embedded_scheduler.py` registration |
| Dedup uses canonical INSERT…SELECT WHERE NOT EXISTS RETURNING pattern (PR #80 precedent) | ✅ confirmed in `_record_alert` |
| Structured `extra` schema consistent across all converted log sites | ✅ `{cycle_id, phase, error_class, matter_slug}` everywhere |
| No log line includes proposal text / matter context payload / signal body | ✅ confirmed (logs carry IDs + classes only) |
| `archive_failed` status-persist is best-effort (won't worsen existing failure) | ✅ wrapped in nested try/except with empty `pass` fallback |
| `tier_b_pending` accidentally included in Detector A | ✅ NOT included — explicit V1 exclusion (tested by `test_detect_query_filters_by_status_and_excludes_already_alerted`) |
| Files outside scope modified | ⚠️ +1 file (memory/store_back.py) — see §4 deviation |
| New status `archive_failed` added to CHECK constraint | ✅ migration drops + re-adds; companion bootstrap also updated |

---

## §3 Quality checkpoints (brief §"Quality checkpoints")

| # | Checkpoint | Status |
|---|---|---|
| 1 | py_compile clean on all 3 modified files | ✅ (now 4 — see §4) |
| 2 | 6+ unit tests PASS literally | ✅ 10 |
| 3 | Regression cortex_runner + phase5_act + gate PASS literally | ✅ 46 |
| 4 | Sentinel scheduled with `max_instances=1, coalesce=True` (matches gold_audit_sentinel pattern) | ✅ |
| 5 | Dedup uses canonical try/rollback/raise per PR #80 gate precedent | ✅ |
| 6 | Structured `extra` schema consistent across all converted log sites | ✅ |
| 7 | No log line includes proposal text / matter context / payload body | ✅ |
| 8 | `archive_failed` status-persist is best-effort (won't worsen existing failure) | ✅ |

---

## §4 Deviations from brief

### D1 — Added 6th file (`memory/store_back.py`) for drift defense

**Brief scope:** 5 files. **Shipped:** 6 files.

**Why:** `memory/store_back.py:587` carries the `cortex_cycles` CREATE TABLE definition with the OLD 10-value CHECK constraint. Per the migration-vs-bootstrap drift trap (Lesson, surfaced 2026-04-21 via BRIDGE_HOT_MD_AND_TUNING_1), if a fresh DB ever spins up (e.g., new Neon branch for `TEST_DATABASE_URL`, recovery scenario), the bootstrap creates `cortex_cycles` with the OLD CHECK and any subsequent INSERT of `archive_failed` would raise CheckViolation until the migration runs.

**Fix shipped:** appended `,'archive_failed'` to the bootstrap CHECK list at line 587. One-character defensive addition. Fully consistent with the prior signal_queue pattern (`_ensure_signal_queue_additions` at line 6700+ which re-asserts its expanded CHECK on every boot). Existing production DBs are unaffected because `CREATE TABLE IF NOT EXISTS` is a no-op when the table exists.

**Why not in brief:** brief scoped to 5 files; the drift trap defense was discovered during preflight inside this build and is materially safer to ship together than as a follow-up.

**Files NOT touched** stays clean (none of the brief's "Do NOT touch" list — `cortex_phase5_act.py`, `slack_interactivity.py`, `slack_events.py`, KBL/Stage 2/Wiki — were modified).

### D2 — Scheduler trigger uses `IntervalTrigger(minutes=5)` not `trigger="interval", minutes=5`

**Brief snippet (line 131-136):**
```python
scheduler.add_job(
    run_cortex_stuck_cycle_sentinel,
    trigger="interval", minutes=5,
    ...
)
```

**Shipped:**
```python
scheduler.add_job(
    run_cortex_stuck_cycle_sentinel,
    IntervalTrigger(minutes=5),
    ...
)
```

**Why:** every other interval job in `embedded_scheduler.py` uses the `IntervalTrigger(...)` object form (e.g. `clickup_poll`, `expire_browser_actions`, `scheduler_heartbeat`, `memory_watchdog`). Both forms are valid APScheduler API. Keeping the codebase pattern consistent.

### D3 — Replaced fictitious `_set_cycle_status` with raw UPDATE pattern (rev 2 fix already in brief)

Brief rev 2 already corrected this. No additional deviation; documenting for completeness.

### D4 — Structured-logging audit converted 4 sites, not just `_phase6_archive`

Brief §"Scope 1" said: "every `logger.error` call in `_phase6_archive` (line 398+) and Phase 3 cycle-status update paths" + "Any other `logger.error(f"...")` you find".

Converted 4 sites in `cortex_runner.py`:
- Line 86 — `Cortex cycle timed out` (Phase TimeoutError handler)
- Line 111 — `Failed to mark timed-out cycle as failed` (timeout-recovery)
- Line 173 — `Phase 4 failed` (propose phase)
- Line 182 — `Cortex cycle failed` (top-level cycle exception)
- Line 189 — `Phase 6 archive itself failed` (the canonical brief-named site)
- Line 397 — `Phase 3 failed` (reason phase)

Phase 3, 4, and 6 are explicitly named in the brief. Lines 86 and 111 (top-level timeout + recovery) and 182 (top-level cycle failure) were folded in for consistency — all are cycle-status update paths and benefit from the same `{cycle_id, phase, error_class, matter_slug}` schema. `_phase6_archive` itself (line 436+) has no `logger.error` call (it uses raise/rollback) — confirmed via grep.

---

## §5 PR URL

(Pending — push + `gh pr create` after this report commits.)

---

## Co-Authored-By

```
Co-authored-by: AI Head B <aihead-b@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
