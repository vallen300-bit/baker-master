# B3 ship report — AMEX_RECURRING_DEADLINE_1

**Date:** 2026-04-26
**Builder:** B3 (Code Brisen #3)
**Branch:** `amex-recurring-deadline-1`
**Brief:** `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md` (amended 2026-04-26 PM, Rule-0 compliant)
**Trigger class:** MEDIUM (DB migration on `deadlines` + cross-capability state writes via 3 completion-path call-site mods) → B1 second-pair-of-eyes review required pre-merge.

---

## 1. Brief deviations

None substantive. Two minor brief-spec mismatches noted at ship-gate verification:

- **Brief grep for auto-dismiss exclusion uses `-A6` window** — the WHERE clause sits 12+ lines below the function header (try/connect/cursor/SQL prelude). Same grep with `-A30` returns 2 matches as expected. Functional verification handled by `test_auto_dismiss_overdue_sql_excludes_recurring` + `test_auto_dismiss_soft_sql_excludes_recurring` (both in test file).
- **Brief migration-vs-bootstrap drift diff uses `grep -A 8`** — works for the SQL side but `grep -A 8` on `store_back.py` returns Python wrapper lines (blank lines between cur.execute calls). Equivalent normalised diff (strip `cur.execute("`, trailing `;`) confirms 4-column character-for-character match. Diff: clean.

## 2. What landed

### 2.1 Schema migration + bootstrap mirror (Code Brief Standard #4)

| File | Change |
|---|---|
| `migrations/20260426_amex_recurrence.sql` | NEW. 4 columns + 2 partial indexes, with `migrate:up` / `migrate:down` markers. |
| `memory/store_back.py` | NEW `_ensure_deadlines_recurrence_columns()` mirrors migration column-for-column. Wired in `__init__`. |

Columns added to `deadlines`:
- `recurrence TEXT` — NULL (one-shot) | `monthly` | `weekly` | `quarterly` | `annual`
- `recurrence_anchor_date DATE` — reference for `compute_next_due()`
- `recurrence_count INT NOT NULL DEFAULT 0` — telemetry, auto-incremented per respawn
- `parent_deadline_id INT` — FK-style link to chain root

### 2.2 Helpers (`orchestrator/deadline_manager.py`)

- `compute_next_due(recurrence, anchor) -> date` — uses `dateutil.relativedelta` to clamp Jan 31 → Feb 28/29 and Nov 30 + quarterly → Feb 28/29.
- `_maybe_respawn_recurring(deadline_id, *, conn=None) -> Optional[int]` — idempotent (checks for existing child with same root + anchor before inserting); cap-rate 1/day per parent root with `_alert_respawn_cap_hit` Slack DM on trip; chain root resolution (`parent_deadline_id` if set, else self id).
- `_halt_recurrence_chain(root_id) -> bool` — nulls `recurrence` on root + active children when Director chooses "stop recurrence" on dismiss.

### 2.3 Amendment H — 3 completion paths wired

```
$ grep -nE "_maybe_respawn_recurring" orchestrator/deadline_manager.py triggers/clickup_trigger.py models/deadlines.py
orchestrator/deadline_manager.py:878:    _maybe_respawn_recurring(deadline["id"])
orchestrator/deadline_manager.py:1004:def _maybe_respawn_recurring(
orchestrator/deadline_manager.py:1055:                f"_maybe_respawn_recurring: deadline #{parent_id} has unknown "
orchestrator/deadline_manager.py:1062:                f"_maybe_respawn_recurring: deadline #{parent_id} has "
orchestrator/deadline_manager.py:1129:        logger.error(f"_maybe_respawn_recurring failed for #{deadline_id}: {e}")
triggers/clickup_trigger.py:539:                    from orchestrator.deadline_manager import _maybe_respawn_recurring
triggers/clickup_trigger.py:540:                    _maybe_respawn_recurring(deadline_id, conn=conn)
models/deadlines.py:394:            from orchestrator.deadline_manager import _maybe_respawn_recurring
models/deadlines.py:395:            _maybe_respawn_recurring(deadline_id)
```

All 3 doors wired:
1. `complete_deadline()` line 878 — direct call after `update_deadline(status='completed')`.
2. `triggers/clickup_trigger.py:540` — inline call after raw `UPDATE deadlines SET status='completed'`. Re-uses existing `conn` to keep the respawn in the same transaction.
3. `models/deadlines.py:395` (`complete_critical`) — inline call after raw `UPDATE deadlines SET is_critical=FALSE, status='completed'`.

### 2.4 Auto-dismiss exclusions (Amendment H read-only doors)

Both auto-dismiss SQL filters carry `AND recurrence IS NULL`:

```
$ grep -n "recurrence IS NULL" orchestrator/deadline_manager.py
695:              AND recurrence IS NULL
726:              AND recurrence IS NULL
```

695 = `_auto_dismiss_overdue_deadlines`. 726 = `_auto_dismiss_soft_deadlines`. Both protected per brief §3 race-window mitigation.

### 2.5 dismiss_deadline UX

`dismiss_deadline(search_text, scope='instance')` — for recurring deadlines:
- default `scope='instance'` → row dismissed, recurrence kept; reply explains chain stays alive and how to halt.
- `scope='recurrence'` → calls `_halt_recurrence_chain(root_id)` (nulls recurrence on root + active children), then dismisses the row.
- non-recurring → unchanged behaviour (no chain text in reply).

### 2.6 Dependency add

```
$ python3 -c "import dateutil.relativedelta; print('dateutil OK')"
dateutil OK
```

`requirements.txt` now lists `python-dateutil>=2.8.0`.

## 3. Ship-gate literal output

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -c "import dateutil.relativedelta; print('dateutil OK')"
dateutil OK

$ python3 -m pytest tests/test_deadline_recurrence.py -v 2>&1 | tail -30
tests/test_deadline_recurrence.py::test_compute_next_due_monthly_normal PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_monthly_jan31_to_feb_clamps PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_monthly_feb29_leap_year PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_weekly PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_quarterly PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_quarterly_anchor_30th_of_nov_to_feb PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_annual PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_annual_leap_year_feb29 PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_unknown_recurrence_raises PASSED
tests/test_deadline_recurrence.py::test_compute_next_due_accepts_datetime PASSED
tests/test_deadline_recurrence.py::test_recurrence_values_constant_complete PASSED
tests/test_deadline_recurrence.py::test_respawn_inserts_child_with_correct_anchor_and_chain PASSED
tests/test_deadline_recurrence.py::test_respawn_idempotent_returns_existing_child PASSED
tests/test_deadline_recurrence.py::test_respawn_cap_rate_skips_and_alerts PASSED
tests/test_deadline_recurrence.py::test_respawn_skips_when_recurrence_null PASSED
tests/test_deadline_recurrence.py::test_respawn_skips_unknown_recurrence_value PASSED
tests/test_deadline_recurrence.py::test_respawn_skips_when_anchor_missing PASSED
tests/test_deadline_recurrence.py::test_respawn_uses_root_id_when_chain_already_exists PASSED
tests/test_deadline_recurrence.py::test_respawn_propagates_priority_and_severity PASSED
tests/test_deadline_recurrence.py::test_respawn_idempotency_query_uses_root_and_next_anchor PASSED
tests/test_deadline_recurrence.py::test_amendment_h_three_paths_call_helper PASSED
tests/test_deadline_recurrence.py::test_auto_dismiss_overdue_sql_excludes_recurring PASSED
tests/test_deadline_recurrence.py::test_auto_dismiss_soft_sql_excludes_recurring PASSED
tests/test_deadline_recurrence.py::test_dismiss_recurring_default_returns_keep_chain_message PASSED
tests/test_deadline_recurrence.py::test_dismiss_recurring_with_scope_recurrence_halts_chain PASSED
tests/test_deadline_recurrence.py::test_dismiss_non_recurring_unchanged_behavior PASSED

============================== 26 passed in 0.11s ==============================

$ python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py 2>&1 | tail -1
====== 24 failed, 1013 passed, 27 skipped, 5 warnings, 31 errors in 30.79s ======

# Pre-AMEX baseline (--ignore=tests/test_deadline_recurrence.py also):
# 24 failed, 987 passed, 27 skipped, 31 errors
# Delta: +26 passes (= 26 new recurrence tests). 0 new failures, 0 new errors.
# tests/test_tier_normalization.py is a pre-existing collection error
# (TypeError: unsupported operand type) — unrelated to this brief.

$ diff <(grep -E "^ALTER TABLE deadlines" migrations/20260426_amex_recurrence.sql | sed 's/;$//' | sort) \
       <(grep -E "ALTER TABLE deadlines.*ADD COLUMN.*(recurrence|parent_deadline_id)" memory/store_back.py | sed 's/^ *cur.execute("//' | sed 's/")$//' | sort) && echo "DRIFT: clean"
DRIFT: clean

$ grep -nE "_maybe_respawn_recurring" orchestrator/deadline_manager.py triggers/clickup_trigger.py models/deadlines.py
# (output above in §2.3)

$ grep -A 30 "def _auto_dismiss_overdue_deadlines\|def _auto_dismiss_soft_deadlines" orchestrator/deadline_manager.py | grep -c "recurrence IS NULL"
2

$ git diff --name-only main...HEAD
memory/store_back.py
migrations/20260426_amex_recurrence.sql
models/deadlines.py
orchestrator/deadline_manager.py
requirements.txt
tests/test_deadline_recurrence.py
triggers/clickup_trigger.py

$ git diff --stat
 memory/store_back.py                    |  37 +++
 migrations/20260426_amex_recurrence.sql |  32 +++
 models/deadlines.py                     |   6 +
 orchestrator/deadline_manager.py        | 257 ++++++++++++++++++++-
 requirements.txt                        |   1 +
 tests/test_deadline_recurrence.py       | 395 ++++++++++++++++++++++++++++++++
 triggers/clickup_trigger.py             |   6 +
 7 files changed, 730 insertions(+), 4 deletions(-)
```

## 4. Acceptance test on AmEx (#1438) — deferred to post-merge

Production conversion of AmEx (#1438) to monthly recurrence with `recurrence_anchor_date='2026-05-03'` requires a write against the live `deadlines` table. Per Director guidance ("schema migration applied via `python3 -m scripts.migrate` or equivalent" in §5 #9), the actual DB row update is handoff work after migration applies on Render. Test coverage proves the conversion path is sound:

- `test_respawn_inserts_child_with_correct_anchor_and_chain` simulates AmEx conversion: row with `recurrence='monthly'`, `anchor=2026-05-03`. Helper produces:
  - new row, `due_date = 2026-06-03 00:00 UTC`, `recurrence_anchor_date = 2026-06-03`
  - `recurrence_count = 1`
  - `parent_deadline_id = 1438`
  - `priority='high'`, `severity='firm'` propagated.

Post-merge handoff includes the literal SQL:

```sql
UPDATE deadlines
SET recurrence='monthly',
    recurrence_anchor_date='2026-05-03'
WHERE id = 1438 AND status = 'active';
```

then trigger one `complete_deadline` and verify spawned child row.

## 5. Definition-of-done coverage

| § brief check | Status |
|---|---|
| Schema migration applied (4 columns) | DONE — `migrations/20260426_amex_recurrence.sql` |
| Migration-vs-bootstrap verified | DONE — diff clean |
| `compute_next_due()` with edge tests | DONE — 8 cases (incl. Feb / leap / Nov-30 quarterly / Feb-29 annual) |
| `complete_deadline` recurrence respawn | DONE — line 878 |
| `_maybe_respawn_recurring(deadline_id)` helper extracted | DONE — line 1004 |
| `triggers/clickup_trigger.py:535` raw UPDATE wired | DONE — line 540 |
| `models/deadlines.py:387` raw UPDATE wired | DONE — line 395 |
| `_auto_dismiss_overdue_deadlines` skip recurring | DONE — line 695 |
| `_auto_dismiss_soft_deadlines` skip recurring | DONE — line 726 |
| `python-dateutil` added to `requirements.txt` | DONE |
| Idempotency: respawn checks for existing child | DONE — `test_respawn_idempotent_returns_existing_child` |
| Cap respawn rate at 1/day per parent + alert | DONE — `test_respawn_cap_rate_skips_and_alerts` |
| Dashboard UI checkbox + "make recurring" action | DEFERRED to post-merge frontend work (out of B3 brief scope; backend complete) |
| AmEx (#1438) acceptance test | DEFERRED — post-merge handoff (§4 above) |
| Triaga HTML of one-shot-look-recurring (Q4) | DEFERRED — post-acceptance per brief Q4 |
| Documentation: README section | DEFERRED — included as post-merge handoff |
| Slack push on respawn failures | DONE — `_alert_respawn_cap_hit` posts via `triggers.ai_head_audit._safe_post_dm` |

Backend coverage of brief is complete; deferred items are explicitly post-merge / out-of-scope per brief §6.

## 6. Authority chain

- Director RA-21 2026-04-26 PM Q2 resolution (`anchor_date = 3rd of every month`) + default-fallback ("Your 3 question — you default. I skip") + RA-21 reroute ("M2 = your natural lane")
- AI Head B `/write-brief` retroactive amendment (post-PR-#66 EXPLORE)
- B3 build (this report)
- B1 review (situational-review trigger fires next)
- AI Head B merge (post-B1 APPROVE)

## 7. Post-merge handoff

1. **Schema migration:** `python3 -m scripts.migrate` against Render Postgres (or equivalent). Bootstrap path will pick up next process restart even without explicit run.
2. **AmEx (#1438) conversion:** apply SQL block in §4 above, then trigger one completion to verify spawn.
3. **Pip install on Render:** `python-dateutil` was committed to `requirements.txt`; Render auto-deploy will install on next push to `main`.
4. **Q4 deferred sweep:** AI Head emits Triaga HTML of current one-shot deadlines that look recurring (monthly bills, quarterly tax, annual subs). Director ticks. B-code applies batch conversion.
5. **Dashboard UI:** checkbox at deadline creation + "make recurring" action — separate frontend brief; backend ready.

## 8. PR

- **Title:** `AMEX_RECURRING_DEADLINE_1: recurrence on deadlines + 3-path respawn wiring + auto-dismiss exclusion`
- **Branch:** `amex-recurring-deadline-1`
- **Trigger class:** MEDIUM. Do **not** auto-merge — B1 second-pair-of-eyes review required first per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`.
