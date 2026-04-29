# CODE_1 — B1: PR #83 STRUCTURAL REVIEW (CORTEX_PHASE5_STATUS_RECONCILE_1)

**Status:** OPEN
**Dispatched:** 2026-04-29T~10:30Z
**Dispatched by:** ai-head-a (sole orchestrator)
**Director authorization:** "B" (Director ratified Path B post-cycle-7dc3201b reject test)
**Builder under review:** b3 (≠ b1 ✓)
**Trigger class:** HIGH
**PR:** https://github.com/vallen300-bit/baker-master/pull/83
**Branch:** `cortex-phase5-status-reconcile-1`
**Brief:** `briefs/BRIEF_CORTEX_PHASE5_STATUS_RECONCILE_1.md`
**B3 ship report:** `briefs/_reports/B3_cortex_phase5_status_reconcile_20260429.md`

## What B3 shipped

Three bundled fixes:
1. `_cas_lock_cycle` kwarg renamed `from_status` → `from_statuses` (tuple|list|str). SQL switched to `status = ANY(%s)`. 4 handler call sites pass `("proposed", "tier_b_pending")`.
2. NEW migration `migrations/20260429_cortex_cycles_add_transient_statuses.sql` pinning the 4 *ing transient statuses (drift-defense match in `memory/store_back.py` bootstrap).
3. NEW `memory/feedback_render_envvar_paginated_put.md` + MEMORY.md index entry.

Files modified (8): orchestrator/cortex_phase5_act.py, memory/store_back.py, NEW migration, NEW feedback memory, MEMORY.md, NEW test, mailbox flip, ship report.

## Execution

```bash
cd ~/bm-b1/01_build
git fetch origin && git checkout cortex-phase5-status-reconcile-1 && git pull -q
git log --oneline main..HEAD

# Re-run ship gate locally on PR head (Lesson #48)
pytest tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py -v
pytest tests/test_cortex_runner_phase126.py tests/test_cortex_pre_review_gate.py tests/test_cortex_slack_interactivity.py
python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase5_act.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"

gh pr view 83 --json files --jq '.files[].path'
```

## Review sections (10) — verdict per section + evidence (file:line)

### A — `_cas_lock_cycle` signature evolution
- New kwarg `from_statuses` accepts `tuple | list | str` (str for backward-compat fallback)
- Internal coerce to tuple before SQL
- SQL uses `status = ANY(%s)` not `status IN (...)` interpolation (param-bound)
- Docstring updated: documents BOTH `proposed` and `tier_b_pending` as valid pre-button states

### B — 4 handler call sites updated correctly
- `cortex_approve` (line ~178): `from_statuses=("proposed", "tier_b_pending")`
- `cortex_reject` (line ~384): same
- `cortex_edit` (line ~268): same
- `cortex_refresh` (line ~319): same
- No site accidentally accepts a status outside the 2 valid pre-button states

### C — Existing direct callers of `_cas_lock_cycle` updated
- B3 ship report claims 4 existing direct callers updated. Confirm via `grep -n "_cas_lock_cycle" orchestrator/cortex_phase5_act.py` finds only the 4 handler dispatches + the function def itself
- Test direct callers (in `tests/test_cortex_phase5_idempotency.py`) updated to new kwarg shape

### D — Migration SQL correctness
- File: `migrations/20260429_cortex_cycles_add_transient_statuses.sql`
- Wrapped in `BEGIN; … COMMIT;` (atomic)
- `DROP CONSTRAINT IF EXISTS` (idempotent on re-run)
- `ADD CONSTRAINT` enumerates exactly 15 statuses (11 pre-existing + `archive_failed` + 4 *ing transient)
- Constraint name preserved: `cortex_cycles_status_check`

### E — store_back.py drift-defense match
- `_ensure_cortex_cycles_table` CHECK enumerates exactly the same 15 statuses
- Pattern matches PR #82 fold-in for `archive_failed` (drift defense lesson)
- No other places that reference the status enum out-of-sync

### F — `feedback_render_envvar_paginated_put.md` shape
- Frontmatter: name, description (one-line), type=feedback
- Lead with the rule, then **Why:** + **How to apply:** lines per memory format
- Cites the 09:14Z incident concretely (vars wiped, recovery cost, hard-stop suggestion)

### G — `MEMORY.md` index entry
- One line, ≤200 chars
- Format: `- [Title](file.md) — one-line hook`
- Placed in appropriate section

### H — Test integrity
- 3 new tests minimum (per brief): `cas_lock_cycle_accepts_proposed`, `cas_lock_cycle_accepts_tier_b_pending`, optional `cas_lock_cycle_rejects_random_state`
- All PASS literally on PR head
- Existing 41/41 phase5 + idempotency PASS literally (B3 reports 44/44 — verify)
- Cross-cap regression: runner_phase126 + pre_review_gate + slack_interactivity PASS literally
- No `pytest.skip` / `xfail` / "by inspection" claims (Lesson #50)

### I — Scope discipline
- `gh pr view 83 --json files --jq '.files[].path'` returns ONLY:
  - `orchestrator/cortex_phase5_act.py`
  - `memory/store_back.py`
  - `migrations/20260429_cortex_cycles_add_transient_statuses.sql`
  - `memory/feedback_render_envvar_paginated_put.md`
  - `memory/MEMORY.md`
  - `tests/test_cortex_phase5_idempotency.py`
  - `briefs/_tasks/CODE_3_PENDING.md`
  - `briefs/_reports/B3_cortex_phase5_status_reconcile_20260429.md`
- `triggers/slack_interactivity.py`, `triggers/cortex_stuck_cycle_sentinel.py`, all Phase 1-4 paths UNTOUCHED

### J — Render deploy survival
- Migration is additive (DROP + ADD same constraint name) — won't break existing rows
- Existing `proposed`/`approved`/etc rows continue to validate
- No new third-party dep
- B3's prod-runtime hot-fix (Director session 09:47Z direct ALTER) means migration is essentially a no-op on current prod, but mandatory for fresh prod / replica

## STOP criteria

- `_cas_lock_cycle` accepts a state outside `proposed` + `tier_b_pending` (e.g. accidentally accepts `failed`, `approved`, etc.)
- Migration changes the constraint NAME (would orphan the live constraint added 09:47Z)
- store_back bootstrap CHECK has a different enum than the migration CHECK (drift)
- Tests fail or any "by inspection" / `pytest.skip` claims
- Files outside the 8-file scope modified
- Pre-existing handler logic in `cortex_phase5_act.py` semantically changed beyond the kwarg + SQL evolution
- The new feedback memory file has values that look like real secrets (the original ~80 wiped vars must be referenced by NAME only, never by value)

## Output

`briefs/_reports/B1_pr83_review_20260429.md`:
- §0: literal stdout for ship-gate commands
- §A–§J: per-section verdict (PASS / FAIL) + evidence
- §K: non-blocking observations (note-only)
- Final verdict line: `**OVERALL: PASS / REQUEST_CHANGES**`

If PASS: comment-fallback approval on PR #83 (self-PR rule precedent).

Mailbox flips OPEN → IN_PROGRESS on claim → COMPLETE on report committed.

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
