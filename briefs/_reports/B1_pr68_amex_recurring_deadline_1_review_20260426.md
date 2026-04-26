# B1 Review Report — PR #68 AMEX_RECURRING_DEADLINE_1

**Date:** 2026-04-26
**Reviewer:** B1
**Builder:** B3 (`amex-recurring-deadline-1` branch, commit `0dfed74`)
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/68
**Brief:** `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md` (Rule-0 amended 2026-04-26 PM)
**Trigger class:** MEDIUM (DB migration on `deadlines` + cross-capability state writes via 3 completion-path call-site mods)
**Verdict:** **APPROVE — 14/14 checks green.**

---

## #1. Scope lock — exactly 8 files ✓

```
$ git fetch origin main
$ git diff --name-only origin/main...HEAD
briefs/_reports/B3_amex_recurring_deadline_1_20260426.md
memory/store_back.py
migrations/20260426_amex_recurrence.sql
models/deadlines.py
orchestrator/deadline_manager.py
requirements.txt
tests/test_deadline_recurrence.py
triggers/clickup_trigger.py
```

8 files exact match. No auth/secrets module touched. Single commit on the
branch (`0dfed74`).

(Note: `git diff --name-only main...HEAD` against stale local `main` showed
24 files because PR #66 squash merge `95d99f3` was missing locally; resolved
after `git fetch origin main`. Origin/main now `c9eb165`.)

## #2. Python syntax on all .py files ✓

```
$ for f in $(git diff --name-only origin/main...HEAD | grep '\.py$'); do
    python3 -c "import py_compile; py_compile.compile('$f', doraise=True)"
  done
  memory/store_back.py OK
  models/deadlines.py OK
  orchestrator/deadline_manager.py OK
  tests/test_deadline_recurrence.py OK
  triggers/clickup_trigger.py OK
```

## #3. Migration ↔ bootstrap drift ✓

```
$ diff <(grep -E "^ALTER TABLE deadlines.*ADD COLUMN.*(recurrence|parent_deadline_id)" \
          migrations/20260426_amex_recurrence.sql | sed -E 's/;$//' | sort) \
       <(grep -E "ALTER TABLE deadlines ADD COLUMN.*(recurrence|parent_deadline_id)" \
          memory/store_back.py | sed -E 's/^ *cur\.execute\("//; s/"\)$//' | sort) \
  && echo "DRIFT: clean"
DRIFT: clean
```

4 columns mirror character-for-character:
- `recurrence TEXT`
- `recurrence_anchor_date DATE`
- `recurrence_count INT NOT NULL DEFAULT 0`
- `parent_deadline_id INT`

Plus 2 partial indexes (`idx_deadlines_recurrence`, `idx_deadlines_parent`)
mirrored in both files. `migrate:up` / `migrate:down` markers present in SQL.

## #4. Amendment H — 3 completion paths wired ✓ **[CRITICAL CHECK]**

```
$ grep -nE "_maybe_respawn_recurring" \
    orchestrator/deadline_manager.py triggers/clickup_trigger.py models/deadlines.py
orchestrator/deadline_manager.py:878:    _maybe_respawn_recurring(deadline["id"])
orchestrator/deadline_manager.py:1004:def _maybe_respawn_recurring(...)
triggers/clickup_trigger.py:539:                    from orchestrator.deadline_manager import _maybe_respawn_recurring
triggers/clickup_trigger.py:540:                    _maybe_respawn_recurring(deadline_id, conn=conn)
models/deadlines.py:394:            from orchestrator.deadline_manager import _maybe_respawn_recurring
models/deadlines.py:395:            _maybe_respawn_recurring(deadline_id)
```

**Door-by-door verification by direct read:**

1. **`orchestrator/deadline_manager.py:878`** (`complete_deadline()`):
   direct call after `update_deadline(status='completed')`. Scan / WhatsApp
   `/done` path. Comment `# Amendment H path 1/3` present.
2. **`triggers/clickup_trigger.py:540`** (ClickUp mark-done sync):
   inline call after raw `UPDATE deadlines SET status = 'completed'` (line
   535), reusing existing `conn` so the respawn participates in the same
   transaction. Wrapped in try/except so respawn failure is non-fatal to the
   ClickUp sync. Comment `# Amendment H path 2/3` present.
3. **`models/deadlines.py:395`** (`complete_critical()`):
   inline call after raw `UPDATE deadlines SET is_critical = FALSE,
   status = 'completed'` (line 387). Try/except non-fatal wrapper. Comment
   `# Amendment H path 3/3` present.

Test `test_amendment_h_three_paths_call_helper` (line 288) reads all 3
files and asserts the helper name appears in each — runtime guard against
future regressions.

**All 3 doors wired. Amendment H discharged.**

## #5. Auto-dismiss exclusions — both paths ✓

```
$ grep -n "recurrence IS NULL" orchestrator/deadline_manager.py
695:              AND recurrence IS NULL
726:              AND recurrence IS NULL
```

- Line 695: `_auto_dismiss_overdue_deadlines` (cutoff = NOW() - 3 days,
  status = 'active'). Recurring rows excluded from auto-dismiss → prevents
  3-day-overdue race against Director's manual completion + child respawn.
- Line 726: `_auto_dismiss_soft_deadlines` (cutoff = NOW() - 3 days,
  status = 'pending_confirm'). Same protection.

Tests `test_auto_dismiss_overdue_sql_excludes_recurring` +
`test_auto_dismiss_soft_sql_excludes_recurring` (both pass) statically
parse function bodies and assert presence.

## #6. `python-dateutil` dependency added ✓

```
$ grep -n "dateutil" requirements.txt
30:python-dateutil>=2.8.0     # AMEX_RECURRING_DEADLINE_1: relativedelta for ...

$ python3 -c "import dateutil.relativedelta; print('dateutil OK')"
dateutil OK
```

Used by `compute_next_due()` for monthly/quarterly/annual relativedelta
clamping (e.g. Jan 31 → Feb 28/29).

## #7. `_maybe_respawn_recurring()` defenses ✓

Read of `orchestrator/deadline_manager.py:1004-1133` confirms:
- `recurrence IS NULL` → no-op return None (line 1050)
- unknown recurrence value → log warning + return None (line 1053)
- `recurrence_anchor_date IS NULL` → log warning + return None (line 1060)
- **idempotency:** SELECT child WHERE `parent_deadline_id = root_id AND
  recurrence_anchor_date = next_anchor` → return existing child id (line 1080)
- **cap-rate:** any child of root in last 24h → fire `_alert_respawn_cap_hit`
  + return None (line 1092)
- chain root resolution: `parent_deadline_id` if set, else self (line 1068)
- conn parameter for transaction-scoped reuse (ClickUp path)
- rollback in except, `put_conn` in finally (only when `own_conn`)

Tests `test_respawn_idempotent_returns_existing_child`,
`test_respawn_cap_rate_skips_and_alerts`,
`test_respawn_uses_root_id_when_chain_already_exists`,
`test_respawn_skips_when_recurrence_null`,
`test_respawn_skips_unknown_recurrence_value`,
`test_respawn_skips_when_anchor_missing` all pass.

## #8. `_alert_respawn_cap_hit()` uses canonical Slack helper ✓

```
$ grep -n "from triggers.ai_head_audit import _safe_post_dm" orchestrator/deadline_manager.py
1145:        from triggers.ai_head_audit import _safe_post_dm
```

No phantom `push_to_director`. Same canonical helper used by GOLD audit
sentinel (PR #66 baseline). Wrapped in try/except — DM failure does not
break the cap-rate guard.

## #9. `dismiss_deadline` UX (instance vs recurrence) ✓

`orchestrator/deadline_manager.py:779` — signature `dismiss_deadline(search_text, scope='instance')`:
- recurring + `scope='recurrence'` → calls `_halt_recurrence_chain(root_id)`
  (nulls `recurrence` on root + active children, line 832), dismisses row,
  reply confirms chain stopped.
- recurring + default `scope='instance'` → row dismissed, recurrence
  preserved, reply explains chain remains and how to halt
  (`dismiss "..." stop`).
- non-recurring → unchanged behaviour, no chain text.

Tests `test_dismiss_recurring_default_returns_keep_chain_message`,
`test_dismiss_recurring_with_scope_recurrence_halts_chain`,
`test_dismiss_non_recurring_unchanged_behavior` all pass.

## #10. `compute_next_due()` edge cases ✓

`orchestrator/deadline_manager.py:974` — uses `dateutil.relativedelta`:
- `monthly` → `+relativedelta(months=+1)` (clamps Jan 31 → Feb 28/29)
- `weekly` → `+timedelta(days=7)`
- `quarterly` → `+relativedelta(months=+3)` (clamps Nov 30 → Feb 28/29)
- `annual` → `+relativedelta(years=+1)` (Feb 29 leap → Feb 28 next year)
- unknown recurrence → `ValueError` (defensive at boundary)
- accepts both `date` and `datetime` (auto-coerce via `.date()`)

Tests for all 4 types + Feb-clamp + Feb-29-leap + Nov-30-quarterly +
unknown-raises + datetime-coerce pass.

## #11. 26/26 recurrence tests ✓

```
$ python3 -m pytest tests/test_deadline_recurrence.py -v 2>&1 | tail -3
tests/test_deadline_recurrence.py::test_dismiss_non_recurring_unchanged_behavior PASSED [100%]

============================== 26 passed in 0.07s ==============================
```

26/26 PASSED in 0.07s. Matches ship report claim.

## #12. Full-suite regression delta ✓

```
$ python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py 2>&1 | tail -1
====== 24 failed, 1013 passed, 27 skipped, 5 warnings, 31 errors in 15.07s ======

# Pre-AMEX baseline (also --ignore=tests/test_deadline_recurrence.py):
====== 24 failed, 987 passed, 27 skipped, 5 warnings, 31 errors in 14.66s ======

# Delta: +26 passes (= 26 new recurrence tests). 0 new failures, 0 new errors.
```

`tests/test_tier_normalization.py` is a pre-existing collection error
(`TypeError: unsupported operand type` at import) unrelated to this brief —
present on baseline as well. Same skip strategy as PR #66 review.

Regression delta exactly matches B3 ship report claim: **+26, 0 new
failures, 0 new errors.**

## #13. Singletons clean ✓

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

`SentinelStoreBack._get_global_instance()` factory pattern preserved when
adding `_ensure_deadlines_recurrence_columns()` to `__init__` (line 213).

## #14. AmEx #1438 conversion deferred (post-merge handoff) ✓

```
$ grep -nE "1438|amex|AmEx" \
    orchestrator/deadline_manager.py memory/store_back.py models/deadlines.py \
    triggers/clickup_trigger.py migrations/20260426_amex_recurrence.sql \
    tests/test_deadline_recurrence.py
memory/store_back.py:626:        Mirrors migrations/20260426_amex_recurrence.sql. ...
migrations/20260426_amex_recurrence.sql:4:-- Anchor case: AmEx (#1438) — Director note ...
migrations/20260426_amex_recurrence.sql:5:-- to avoid missing payment." Builder spec ...
tests/test_deadline_recurrence.py:74:    id_: int = 1438,
tests/test_deadline_recurrence.py:75:    description: str = "Pay AmEx",
tests/test_deadline_recurrence.py:78:    source_snippet: str = "AmEx monthly",
tests/test_deadline_recurrence.py:162:    new_id = _maybe_respawn_recurring(1438, conn=_FakeConn(cur))
tests/test_deadline_recurrence.py:171:    assert params[0] == "Pay AmEx"
tests/test_deadline_recurrence.py:178:    assert params[11] == 1438
tests/test_deadline_recurrence.py:188:    new_id = _maybe_respawn_recurring(1438, conn=_FakeConn(cur))
```

`1438` appears only in (a) migration file header comment citing the anchor
case, and (b) test fixture id (`_make_row(id_=1438)` at line 74) +
assertions on root chain link. **No live `UPDATE deadlines` against #1438
in this PR.** Per ship report §4, the production AmEx conversion is
explicitly deferred to AI Head B's Tier B handoff post-merge:

```sql
UPDATE deadlines
SET recurrence='monthly', recurrence_anchor_date='2026-05-03'
WHERE id = 1438 AND status = 'active';
```

Acceptance-test logic is fully covered by
`test_respawn_inserts_child_with_correct_anchor_and_chain` (anchor →
2026-06-03, count → 1, parent_deadline_id → 1438, priority + severity
propagated).

---

## Recommendation

**APPROVE** — `gh pr merge 68 --squash --delete-branch`.

Post-merge handoff (per ship report §7):
1. Migration applies via `python3 -m scripts.migrate` against Render
   Postgres (or via bootstrap on next process restart).
2. AI Head B applies the AmEx (#1438) conversion SQL → triggers one
   `complete_deadline` → verifies child row spawned at 2026-06-03.
3. Q4 deferred sweep (Triaga HTML of one-shot-look-recurring deadlines)
   remains with AI Head B, post-acceptance.
4. Dashboard UI (checkbox + "make recurring" action) is a separate
   frontend brief — backend ready.

## Non-blocking observations

1. **Brief grep windows in B3 ship-gate output (`-A6` / `-A8`)** were too
   narrow for the surrounding Python wrappers — B3 flagged this in §1
   under "minor brief-spec mismatches" and confirmed equivalent verification
   with wider windows + per-test coverage. Future migration briefs may
   prefer `grep -A 30` or AST-based comparators for body-of-function checks.
2. **`complete_critical()` (`models/deadlines.py:379`)** lacks the
   `from triggers.ai_head_audit import _safe_post_dm`-style observability
   that `_alert_respawn_cap_hit` has. If respawn fails inside the
   `complete_critical` path, the warning logs but no Director alert fires.
   Currently mitigated by the `_alert_respawn_cap_hit` Slack DM on
   cap-rate trips, which is the more dangerous failure mode. Out of scope
   for this PR; flag for the deadline-recurrence-failures-table sub-brief
   referenced in DoD §brief 5 #3 (deferred per ship report §5).
3. **Cross-process race on identical anchor:** the idempotency check
   (line 1072) + cap-rate guard (line 1085) both rely on `SELECT` →
   `INSERT` ordering. If two instances of `complete_deadline` race on the
   same parent before commit, both could `SELECT` empty and `INSERT`
   distinct child rows. In practice the 24h cap-rate guard catches the
   second insert at the next pass and the duplicate is detectable via
   `parent_deadline_id + recurrence_anchor_date` uniqueness. Recommendation
   for V2: add a partial unique index `(parent_deadline_id, recurrence_anchor_date)
   WHERE parent_deadline_id IS NOT NULL`.

None of the above blocks merge.
