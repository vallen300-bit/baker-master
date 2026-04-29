# BRIEF — CORTEX_PHASE5_STATUS_RECONCILE_1

**Author:** AI Head A (sole orchestrator)
**Builder:** B3
**Reviewer:** B1 (RA-24 trigger — DB migration + cross-capability state writes)
**Drafted:** 2026-04-29T~10:00Z
**Director authorization:** "B" (Director ratified Path B 2026-04-29 morning, post first real cycle reject test that exposed defect)
**Trigger class:** HIGH

## Problem (proven on cycle 7dc3201b today 09:47Z)

After Phase 4 posts proposal card, `cortex_runner.py:389` sets `cycle.status='tier_b_pending'` and persists. But all 4 Phase 5 handlers (`cortex_approve` / `reject` / `edit` / `refresh`) call `_cas_lock_cycle(... from_status="proposed", ...)`. CAS finds no row matching `WHERE status='proposed'` → returns `warning="already_actioned"` → handler bails silently with 200 OK + decision footer. Cycle stays at `tier_b_pending` forever. **Every button click on every future AO cycle hits this.**

Director hand-flipped status `tier_b_pending → proposed` to test reject end-to-end today. That manual flip cannot be the production pattern.

Compounding defect surfaced same hour: PR #75 introduced `_cas_lock_cycle` writing transient `*ing` statuses (`approving`/`rejecting`/`editing`/`refreshing`) into `cortex_cycles.status` column, but the CHECK constraint at `migrations/20260428_cortex_cycles.sql:25` never received those values. CAS write failed with `cortex_cycles_status_check` violation. Fixed live via direct ALTER (Director session 09:47Z) but no migration file checked in.

## Goal

Make Phase 5 handlers correctly transition cycles from BOTH `proposed` AND `tier_b_pending` into the matching `*ing` transient state, and lock in the schema change permanently.

## Scope (3 work units)

### 1. `_cas_lock_cycle` accepts multiple from_statuses

In `orchestrator/cortex_phase5_act.py`:

- Change `_cas_lock_cycle` signature from `from_status: str` to `from_statuses: tuple[str, ...] | str` (accept either for backwards-compat).
- SQL changes from `WHERE cycle_id=%s AND status=%s` to `WHERE cycle_id=%s AND status = ANY(%s)`.
- Update the 4 handler call sites at lines `178, 268, 319, 384`:
  - Replace `from_status="proposed"` with `from_statuses=("proposed", "tier_b_pending")`.
- Keep the docstring rationale: Phase 4 lands at `tier_b_pending` (post-Slack DM), legacy direct-test path lands at `proposed`. Both are valid pre-button states.

### 2. NEW migration — pin transient statuses into CHECK constraint

`migrations/20260429_cortex_cycles_add_transient_statuses.sql`:

```sql
-- Adds the 4 transient *ing statuses introduced by PR #75 (CORTEX_PHASE5_IDEMPOTENCY_1)
-- to the CHECK constraint. Status values 'approving'/'rejecting'/'editing'/'refreshing'
-- are written by _cas_lock_cycle in orchestrator/cortex_phase5_act.py and were
-- failing CHECK violation in production until 2026-04-29 09:47Z manual ALTER.
--
-- Idempotent: DROP IF EXISTS + ADD; safe to re-run.

BEGIN;
ALTER TABLE cortex_cycles DROP CONSTRAINT IF EXISTS cortex_cycles_status_check;
ALTER TABLE cortex_cycles ADD CONSTRAINT cortex_cycles_status_check
    CHECK (status IN (
        'in_flight', 'awaiting_reason', 'proposed', 'tier_b_pending',
        'approved', 'rejected', 'modified', 'failed', 'superseded', 'abandoned',
        'archive_failed',
        'approving', 'rejecting', 'editing', 'refreshing'
    ));
COMMIT;
```

Match the bootstrap CHECK in `memory/store_back.py` (drift defense — same pattern as PR #82 §6 fold-in: any new status value MUST appear in BOTH the migration + the bootstrap `_ensure_cortex_cycles_table` CHECK).

### 3. Memory feedback file — capture Render env-var regression

`memory/feedback_render_envvar_paginated_put.md`:

```yaml
---
name: render_envvar_paginated_put_regression
description: NEVER raw PUT /v1/services/{id}/env-vars without paginating the GET. Render's GET endpoint default page size is 20; PUTting that array deletes everything beyond page 1. Use ?limit=100 OR per-key endpoint OR MCP merge mode.
type: feedback
---

**Rule:** Render env-var PUT replaces the entire array. Never PUT without first
fetching ALL pages of the GET. Default GET page size is 20 — silently
truncates the live env state.

**Why:** 2026-04-29 09:14Z, AI Head A added `SLACK_SIGNING_SECRET` via raw PUT
on Render. The GET that fed the merge returned only 20 of ~100 env vars.
Resulting PUT wiped 80 vars including `BAKER_API_KEY` (MCP auth),
`POSTGRES_PASSWORD`, `QDRANT_API_KEY`, `ANTHROPIC_API_KEY`, all `NEON_*`,
all `BAKER_*` URLs, etc. System ran on cached secrets in process memory
until next restart, which broke MCP auth + DB writes systemwide.

Recovery cost: ~45 min, regenerated 32 vars from local `.env` + 1Password +
hard-coded defaults. Some non-critical vars (cost thresholds, behavior
flags) are still operating on code-default fallbacks.

**How to apply:**
- Render env-var ops: ALWAYS use `?limit=100` on the GET (Render's max page
  size is 100), OR use the per-key endpoint `PUT /v1/services/{id}/env-vars/{key}`,
  OR use MCP merge mode per `.claude/rules/python-backend.md` (which I missed
  on 04-29 — surfaced post-incident).
- Defense in depth: before any env-var PUT, log `len(current_array)` and
  `len(merged_array)` and ABORT if `merged_count < current_count`. The PUT
  should only ever ADD or KEEP, never reduce.
- Pair with the existing `.claude/rules/python-backend.md` rule. Consider
  hard-stop hook on raw PUT to env-vars endpoint.
```

Index entry in `memory/MEMORY.md`:
- `[Render env-var paginated PUT regression](feedback_render_envvar_paginated_put.md) — never raw PUT without ?limit=100; default page is 20, silently wipes vars beyond page 1`

## Files modified (4)

- MOD `orchestrator/cortex_phase5_act.py` — `_cas_lock_cycle` signature + 4 call-site updates (~12 line touches)
- MOD `memory/store_back.py` — `_ensure_cortex_cycles_table` CHECK to include all 15 status values (drift defense)
- NEW `migrations/20260429_cortex_cycles_add_transient_statuses.sql`
- NEW `memory/feedback_render_envvar_paginated_put.md`
- MOD `memory/MEMORY.md` — append index entry (one line)

## Files NOT touched

- `triggers/slack_interactivity.py` — handler dispatch unchanged
- `triggers/cortex_stuck_cycle_sentinel.py` — not affected (V1 enum doesn't include `*ing`)
- All Phase 1/2/3/4 paths

## Test plan (Lesson #47 literal stdout)

```
pytest tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py -v
pytest tests/test_cortex_runner_phase126.py tests/test_cortex_pre_review_gate.py tests/test_cortex_slack_interactivity.py
python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase5_act.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
```

Add 2 new tests (or extend existing `test_cortex_phase5_idempotency.py`):
1. `test_cas_lock_cycle_accepts_proposed` — cycle at `proposed`, CAS to `approving` → succeeds
2. `test_cas_lock_cycle_accepts_tier_b_pending` — cycle at `tier_b_pending`, CAS to `approving` → succeeds (NEW behavior)
3. (optional) `test_cas_lock_cycle_rejects_random_state` — cycle at `failed`, CAS to `approving` → returns `already_actioned` (no false transition)

## Pass criteria

- 2+ new tests PASS literally
- All existing phase5 + phase5_idempotency + slack_interactivity + runner_phase126 + pre_review_gate tests PASS literally (no regression)
- py_compile clean on both modified .py files
- Migration SQL parses (verify with `psql --dry-run` or `python -c "import sqlparse; sqlparse.parse(open('migrations/20260429_...').read())"`)

## STOP criteria

- Any test fails or any "by inspection" claim
- `_cas_lock_cycle` accepts a state outside the 4 valid pre-button statuses (must be exactly `proposed` + `tier_b_pending` for V1)
- Migration runs but constraint definition wrong on `\d cortex_cycles`
- store_back bootstrap CHECK doesn't match migration CHECK exactly

## Post-merge — A executes

1. `/security-review` (Lesson #52 mandatory)
2. B1 structural review (RA-24 trigger: DB migration + cross-capability state writes)
3. Both clear → A squash-merge
4. Render redeploy
5. Verify `pg_get_constraintdef` matches new CHECK on prod DB
6. Director-side smoke deferred (next REAL AO cycle naturally exercises the path; no need to fire a $4 test cycle just to retest)

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
