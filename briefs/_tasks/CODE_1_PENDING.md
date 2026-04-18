# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #11 STEP3-EXTRACT-IMPL shipped at `ee7036a`. Ready for next task.
**Task posted:** 2026-04-18 (late afternoon)
**Status:** OPEN — Director-ratified Phase 1 unblock

---

## Task: STATUS-CHECK-EXPAND-1 — Expand `signal_queue.status` CHECK constraint

### Why

Director ratified path (b) from B2's PR #10 S1. KBL-A's CHECK constraint only permits the original 8 status values; PR #7/#8/#10/#11 all write KBL-B per-step states (`triage_running`, `resolve_running`, `extract_running`, etc.) that violate the constraint. First real signal crashes the worker. Ship this migration FIRST, then PRs #7/#8/#10/#11 become mergeable.

Two-track §5.1 migration (new `stage` + `state` columns) deferred to Phase 2 burn-in cleanup per KBL-B §5.7 sunset framing — not in scope here.

### Scope

**IN**

1. **`migrations/20260418_expand_signal_queue_status_check.sql`** — idempotent migration:
   - `ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;`
   - `ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check CHECK (status IN (...));` — full set below
   - Guard against re-run: use `DO $$ ... $$` block or `IF NOT EXISTS` pattern consistent with other KBL-A/B migrations
   - File timestamp prefix `20260418` matches PR #11 convention

2. **Full status set (34 values):** Preserve KBL-A 8 + add KBL-B 26.

   ```sql
   CHECK (status IN (
       -- KBL-A legacy (preserved)
       'pending', 'processing', 'done', 'failed', 'expired',
       'classified-deferred', 'failed-reviewed', 'cost-deferred',
       -- KBL-B Layer 0
       'dropped_layer0',
       -- KBL-B Step 1 triage
       'awaiting_triage', 'triage_running', 'triage_failed', 'triage_invalid',
       'routed_inbox',
       -- KBL-B Step 2 resolve
       'awaiting_resolve', 'resolve_running', 'resolve_failed',
       -- KBL-B Step 3 extract
       'awaiting_extract', 'extract_running', 'extract_failed',
       -- KBL-B Step 4 classify
       'awaiting_classify', 'classify_running', 'classify_failed',
       -- KBL-B Step 5 opus
       'awaiting_opus', 'opus_running', 'opus_failed', 'paused_cost_cap',
       -- KBL-B Step 6 finalize
       'awaiting_finalize', 'finalize_running', 'finalize_failed',
       -- KBL-B Step 7 commit
       'awaiting_commit', 'commit_running', 'commit_failed',
       -- KBL-B terminal
       'completed'
   ))
   ```

3. **Naming reconciliation (naming call I'm making per B2 pre-flag):** Brief §3.2 used mixed naming (`triaging`, `resolving`, `extracting`, `classifying`, `committing` alongside `opus_running`, `finalize_running`). Standardize on **`<step>_running`** pattern across the board — matches your existing PR #8/#10/#11 writes + brief's own `opus_running`/`finalize_running`. Use the list above verbatim. No impl code touches needed; your existing PRs already write these names.

4. **Test** — `tests/test_migrations.py` (or new file if pattern mandates) — `@requires_db` round-trip test:
   - Apply migration to a live PG test instance
   - INSERT a signal with each new status value → asserts success
   - INSERT with a bogus status (e.g., `'garbage_state'`) → asserts `CheckViolation` raised
   - Skip-on-absence if `DATABASE_URL` not set (same pattern as other live-PG tests)

5. **Runtime apply** — ensure your migration runner (whatever KBL-A uses — check `memory/store_back.py` for the pattern) picks this up on next Render deploy. If Render already auto-runs `migrations/*.sql` on boot, nothing to wire. If manual, document the apply command in the PR body.

### CHANDA pre-push

- **Q1 Loop Test:** migration is purely infrastructure. Does not touch Leg 1 (Gold-read), Leg 2 (ledger-write), or Leg 3 (Step 1 reads). Pass.
- **Q2 Wish Test:** serves wish — unblocks the pipeline that serves the loop. Pure convenience would be path (c) (collapse to 8 values, lose observability). This keeps observability. Pass.
- **Inv 1** (zero-Gold safe): unaffected.
- **Inv 9** (Mac Mini single writer): migration runs on Render but only modifies schema, not content. Preserved.
- **Inv 10** (pipeline prompts don't self-modify): n/a.

### Branch + PR

- Branch: `status-check-expand-1`
- Base: `main`
- PR title: `STATUS-CHECK-EXPAND-1: expand signal_queue.status CHECK for KBL-B per-step states`
- Target PR number: #12

### Reviewer

B2.

### Timeline

~30-45 min (one migration file + one round-trip test + deploy verification).

### Dispatch back

> B1 STATUS-CHECK-EXPAND-1 shipped — PR #12 open, branch `status-check-expand-1`, head `<SHA>`, <N>/<N> tests green, migration verified on local PG. Ready for B2 review.

### After this task (for context)

On B2 APPROVE + merge of PR #12, these 4 PRs unblock in sequence:
1. PR #7 (LAYER0-IMPL) — already APPROVE'd, will auto-merge
2. PR #8 (STEP1-TRIAGE-IMPL) — B2 reviewing
3. PR #10 (STEP2-RESOLVE-IMPL) — 4 nice-to-haves tracked for follow-up; S1 resolved by this migration
4. PR #11 (STEP3-EXTRACT-IMPL) — B2 reviewing

Next dispatch to you (after these land): **STEP4-CLASSIFY-IMPL** — deterministic classifier, small task (~30 min), spec in KBL-B §4.5.

---

*Posted 2026-04-18 (late afternoon) by AI Head. Director ratification of path (b) received.*
