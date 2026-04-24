# CODE_2_PENDING — PROACTIVE_PM_SENTINEL_1 wrong_thread fix-back — 2026-04-24

**Dispatcher:** AI Head #2 (Team 2)
**Working dir:** `~/bm-b2`
**Target branch:** `proactive-pm-sentinel-rethread-fix-1` (NEW — cut fresh from post-merge main)
**Complexity:** Low (~30 min)

**Supersedes:** PROACTIVE_PM_SENTINEL_1 build dispatch — shipped as PR #58, merged squash `611d499` 2026-04-24 13:48 UTC, deploy gate CP1-4 GREEN. Mailbox reset.

---

## Why this brief

B1 flagged (non-blocking, in §6C second-pair review of PR #58) and AI Head #2 verified end-to-end: the **`wrong_thread` dismiss chain is broken**. Director approved fix-back dispatch.

**Broken flow:**
```
1. Director clicks "Dismiss: wrong thread" on a sentinel alert
2. /api/sentinel/feedback returns rethread_hint.turn_id_hint = None
   (dashboard.py:11439 — hardcoded)
3. JS calls /api/pm/threads/re-thread with turn_id: null
   (app.js:10459)
4. Phase 2 re-thread endpoint guards: if not turn_id: return 400
   (dashboard.py:11241)
5. → 400 "turn_id required" — one of 6 dismiss presets is dead
```

**Root cause:** sentinel alert's `source_id` = `thread_id` (the whole thread is quiet). Phase 2 re-thread endpoint takes a specific `turn_id`. Different primary keys. Sentinel doesn't know which specific turn is "misplaced" when flagging a quiet *thread*.

**Other 5 dismiss presets (`waiting_for_counterparty` / `offline` / `low_priority` / `not_actionable` / `other`) + accept / snooze / reject are fully functional.** Only `wrong_thread` needs the fix.

---

## Working-tree setup

```bash
cd ~/bm-b2
git fetch origin && git checkout main && git pull --rebase origin main
git checkout -b proactive-pm-sentinel-rethread-fix-1
```

Confirm you are on post-merge main:
```bash
git log --oneline -2
# Expect top commit: 611d499 PROACTIVE_PM_SENTINEL_1: Phase 3 AO PM Continuity — quiet-thread sentinel + smart triage (#58)
```

---

## Changes (3 files)

### 1. `outputs/dashboard.py` — server-side turn lookup

At the `wrong_thread` rethread_hint block (currently lines 11435-11443), replace the hardcoded `turn_id_hint: None` with a lookup of the most-recent turn in the thread. Same cursor already open in the surrounding handler.

**Replace this block:**

```python
    # Upgrade 2 chain: wrong_thread dismiss → hint client to call re-thread UI.
    # alerts.source_id for a quiet-thread alert is the thread_id (UUID str).
    if verdict == "dismiss" and dismiss_reason == "wrong_thread":
        response["rethread_hint"] = {
            "turn_id_hint": None,
            "thread_id": row.get("source_id"),
            "pm_slug": row.get("matter_slug"),
            "rethread_endpoint": "/api/pm/threads/re-thread",
        }
```

**With:**

```python
    # Upgrade 2 chain: wrong_thread dismiss → hint client to call re-thread UI.
    # alerts.source_id for a quiet-thread alert is the thread_id (UUID str).
    # We look up the most-recent turn in that thread to pass as turn_id_hint,
    # since the Phase 2 re-thread endpoint operates on a turn_id (not thread_id).
    if verdict == "dismiss" and dismiss_reason == "wrong_thread":
        latest_turn_id = None
        try:
            cur.execute(
                """
                SELECT turn_id FROM capability_turns
                WHERE thread_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (row.get("source_id"),),
            )
            latest = cur.fetchone()
            if latest:
                latest_turn_id = str(latest[0])
        except Exception as e:
            conn.rollback()
            logger.warning(f"rethread_hint turn lookup failed: {e}")
        response["rethread_hint"] = {
            "turn_id_hint": latest_turn_id,
            "thread_id": row.get("source_id"),
            "pm_slug": row.get("matter_slug"),
            "rethread_endpoint": "/api/pm/threads/re-thread",
        }
```

Invariants:
- Must `conn.rollback()` in `except` per `.claude/rules/python-backend.md` (query failure otherwise poisons the surrounding transaction)
- `LIMIT 1` required per rule (unbounded query prohibited)
- Never raise — fall back to `latest_turn_id = None` and JS guard handles it
- Reuse the existing `cur` — do NOT open a new cursor/connection

### 2. `outputs/static/app.js` — null-turn user guard

Locate `_sentinelOpenRethreadFor` (around line 10445). Before the `bakerFetch` call, add a guard so Director isn't silently firing a 400.

**Before the existing `bakerFetch('/api/pm/threads/re-thread', ...)` call, insert:**

```javascript
    if (!hint.turn_id_hint) {
        alert('No turns found in this thread to re-thread — the alert has been dismissed, but nothing to move.');
        return;
    }
```

Cache-bust: bump `?v=108` → `?v=109` on the JS reference in `outputs/static/index.html` (one occurrence, keep CSS at `?v=73`).

### 3. `tests/test_proactive_pm_sentinel.py` — add 2 tests

Add two cases to the existing suite (keeps test-count delta tight):

```python
def test_wrong_thread_rethread_hint_populates_latest_turn_id():
    """wrong_thread dismiss should carry the most-recent turn_id in the thread."""
    # Arrange: mock a thread with 2 turns; dismiss with wrong_thread
    # Assert: rethread_hint.turn_id_hint == str(most_recent_turn_id)
    ...

def test_wrong_thread_rethread_hint_null_when_no_turns():
    """Empty thread → turn_id_hint is None, no exception raised."""
    # Arrange: thread exists but has no turns (edge case)
    # Assert: rethread_hint.turn_id_hint is None; response still 200
    ...
```

Follow the test patterns already in the file (the 13 existing tests use either mocks or `needs_live_pg` — match whichever is consistent with the feedback-endpoint tests already in there).

---

## Acceptance criteria

- `outputs/dashboard.py` diff is surgical (only the rethread_hint block changed) — no other route or helper touched
- `outputs/static/app.js` guard present with user-visible `alert()`
- Cache-bust bumped once (index.html JS reference only)
- 2 new tests pass locally (15 total in the file — 13 existing + 2 new)
- Full-suite regression vs `611d499` baseline: +2 passes, 0 new failures
- Zero new files (unless test fixture strictly requires — avoid)
- Literal `pytest` output pasted in PR body (no "pass by inspection")

---

## Ship gate (local, before push)

```bash
# 1. Syntax check (2 touched Python files)
python3 -c "import py_compile
for f in ['outputs/dashboard.py','tests/test_proactive_pm_sentinel.py']:
    py_compile.compile(f, doraise=True)
print('OK')"

# 2. Singleton check
bash scripts/check_singletons.sh

# 3. Dedicated suite
python3 -m pytest tests/test_proactive_pm_sentinel.py tests/test_proactive_pm_sentinel_h5.py -v
# Expect: 15 passed (13 prior + 2 new), 1 skipped (H5 integration if no live PG)

# 4. Full-suite regression delta vs post-merge main (611d499)
python3 -m pytest tests/ 2>&1 | tail -3
# Expect: +2 passes, 0 new failures, 0 new errors

# 5. JS parse check (node --check, no execution)
node --check outputs/static/app.js && echo "JS OK"

# 6. Cache-bust bump verified in index.html
grep -n 'app.js?v=' outputs/static/index.html
# Expect: app.js?v=109 (was ?v=108)
```

---

## B1 review trigger classification — NONE FIRE (AI Head #2 solo review)

Per `memory/feedback_ai_head_b1_review_triggers.md`:

- §2.1 Authentication — NO new route, NO new auth logic. Reuses existing `dependencies=[Depends(verify_api_key)]` on the two already-gated endpoints.
- §2.2 Database migrations — NO migration file.
- §2.3-2.7 Director-override / secrets / external API / financial / cross-capability state writes — none apply (surgical server-side lookup within an already-deployed handler).

**Ship flow:** B2 pushes → AI Head #2 runs `/security-review` → on CLEAN, auto-merge → CP1-2 lite deploy gate (endpoint still 401, no schema changes to verify) → surface to Director. No B1 hop.

---

## Ship report

Append new entry to `briefs/_reports/CODE_2_RETURN.md`:
`## PROACTIVE_PM_SENTINEL_1 rethread fix-back ship report — <date>`.

Keep the prior PROACTIVE_PM_SENTINEL_1 main-ship entry intact as history. Report format: literal ship-gate output, full-suite regression delta (baseline = main @ `611d499`), Files Modified cross-check (exactly 3), Do NOT Touch verified, pre-merge auth-still-gated curl output.

---

## Do NOT touch (explicit)

- `migrations/` — no migration needed
- `orchestrator/proactive_pm_sentinel.py` — fix is handler-side, not detector-side
- `triggers/embedded_scheduler.py` — no scheduler change
- `memory/store_back.py::store_correction` — no signature change
- Any other dashboard route besides the 10-line rethread_hint block
- Any CSS — JS-only cache bump

## Timebox

**30 min target, 60 min hard cap.** If >60 min, stop and report — likely the suite's existing `wrong_thread` test is stricter than expected or `capability_turns` rows in test fixtures need adjustment.

---

## Handoff

PR link + ship report → AI Head #2 on push.
AI Head #2 runs `/security-review` solo → on CLEAN, auto-merge per B1 trigger rule (no triggers fire).

— AI Head #2
