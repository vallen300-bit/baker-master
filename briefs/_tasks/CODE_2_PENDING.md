# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2
**Task posted:** 2026-04-21 (post PR #31 merge — first Gate 1 flow partially working)
**Status:** OPEN — STEP6_FINALIZE_RETRY_COLUMN_FIX_1

---

## Context

Pipeline is now flowing for the first time today. PR #30 (step consumers) + PR #31 (JSONB cast) are live. 2 signals successfully triaged at Step 1, 4 Ollama calls landed in kbl_cost_ledger. Mechanics work.

Next blocker surfaced at Step 6 (finalize):

```
unexpected exception in _process_signal_remote:
column "finalize_retry_count" does not exist
LINE 1: ... triage_score, triage_confidence, ...
```

## Root cause (my initial read — verify)

`kbl/steps/step6_finalize.py:356` SELECTs `COALESCE(finalize_retry_count, 0)` on signal_queue. Column doesn't exist in production.

There IS a self-healing `ADD COLUMN IF NOT EXISTS finalize_retry_count` at line 426 — but it's inside `_bump_retry`, which only runs AFTER a Step 6 call already failed with unrelated conditions. The initial SELECT aborts before `_bump_retry` is ever reached. Chicken-and-egg.

Same pattern family as this afternoon's hot_md_match drift (`memory/feedback_migration_bootstrap_drift.md`). Step 6 assumes a column that was never migrated or bootstrapped into live DB.

## Scope — DIAGNOSTIC THEN FIX (go straight to PR if clear)

1. **Confirm:** query `information_schema.columns` via `mcp__baker__baker_raw_query` — does `signal_queue.finalize_retry_count` exist in live DB? Expected: no.

2. **Check bootstrap DDL:** grep `memory/store_back.py::_ensure_signal_queue_base` + any `kbl/db/migrations/*` for `finalize_retry_count`. Determine where it SHOULD have been declared.

3. **Fix direction (pick the cleanest):**
   - **(a)** Move the self-healing `ADD COLUMN IF NOT EXISTS` from `_bump_retry` to a module-level init function (called at import or first Step 6 invocation, before any SELECT).
   - **(b)** Add a formal migration file `migrations/NNN_add_finalize_retry_count.sql`.
   - **(c)** Add the column to the `_ensure_signal_queue_base` bootstrap.
   
   Match whatever pattern the codebase already uses for other runtime-added columns. Probably (a) + (c) to prevent future drift — check step 7's approach (it has a similar self-healing ALTER per line 250 comment).

4. **Grep for other un-migrated columns** Step 6/7/other-stage writers reference. Silent drift like hot_md_match + finalize_retry_count tends to cluster. Document findings in the ship report (follow-up brief if pattern is systemic).

5. **Regression test** at `tests/test_step6_finalize.py` — live-PG test that drops the column, calls Step 6, asserts it self-heals AND completes without error.

## Recovery (AI Head handles post-merge)

- Recovery UPDATE flips 16 stranded rows back to pending → Tier A standing auth.
- Then watch kbl_cost_ledger + signal_queue for signals advancing all the way to `stage='committed'`.
- Gate 1 closes when ≥5-10 signals reach terminal stage with `target_vault_path` + `commit_sha` populated.

## Deliverable

- PR on baker-master branch `step6-finalize-retry-column-fix-1`, reviewer B3.
- Ship report at `briefs/_reports/B2_step6_finalize_retry_column_fix_20260421.md`.
- Include: root-cause explanation, grep of other un-migrated columns (NONE / list), regression test output.

## Cross-reference

Today's three adjacent drift bugs now form a cluster:
- `raw_content` (phantom column read by steps) — PR #30
- `hot_md_match` (wrong type in live DB vs migration intent) — bug open, fix deferred
- `related_matters` (JSONB write without cast) — PR #31
- `finalize_retry_count` (column never migrated) — this brief

B3 endorsed `STEP_WRITERS_JSONB_SHAPE_AUDIT_1` as a post-Gate-1 brief. Consider expanding scope to also cover column-existence drift — single audit covering both classes.

## Constraints

- **XS effort (<1h).** If you hit >1h, surface to AI Head.
- **No schema changes to columns other than finalize_retry_count.**
- **No touch to pipeline_tick.py or step consumers.**
- **Timebox: 45 min.**

## Working dir
`~/bm-b2`. `git pull -q` before starting.

— AI Head
