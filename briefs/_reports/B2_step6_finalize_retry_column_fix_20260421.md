---
role: B2
kind: ship
brief: step6_finalize_retry_column_fix
pr: (populated after `gh pr create`)
branch: step6-finalize-retry-column-fix-1
base: main
verdict: SHIPPED_READY_FOR_REVIEW
date: 2026-04-21
tags: [step6-finalize, column-drift, self-heal, cortex-t3-gate1]
---

# B2 — `STEP6_FINALIZE_RETRY_COLUMN_FIX_1` ship report

**Scope:** XS fix for Step 6's `_fetch_signal_row` SELECTing `finalize_retry_count` before any code path can create the column, plus a live-PG regression gate (drop-column + re-run). Fourth member of today's column-drift cluster (raw_content → hot_md_match → related_matters → this).

---

## Root cause confirmed

Live DB schema query (via `mcp__baker__baker_raw_query` on `information_schema.columns`):

- **35 columns present** on `signal_queue`.
- **`finalize_retry_count` NOT among them.**
- All other Step 6/7 columns (`opus_draft_markdown`, `step_5_decision`, `triage_score`, `triage_confidence`, `final_markdown`, `target_vault_path`, `committed_at`, `commit_sha`) are present — Step 7's defensive ALTERs (`_mark_completed` lines 247-258) have run at least once historically.

Step 6's execution order was:

1. `finalize(signal_id, conn)` called from `_process_signal_remote`.
2. `_fetch_signal_row` runs `SELECT ... COALESCE(finalize_retry_count, 0) FROM signal_queue WHERE id = %s` — **first DB hit** on the column.
3. psycopg2 raises `UndefinedColumn`; the SELECT aborts.
4. `_process_signal_remote` catches, rolls back the step's writes — but the claim-time `status='processing'` commit from `pipeline_tick.claim_one_signal` (line 104) persists.
5. `_increment_retry_count`'s self-healing `ADD COLUMN IF NOT EXISTS` at line 426 is never reached — it only runs on a subsequent explicit `_route_validation_failure` path, which by now is out of reach because the SELECT never succeeded.

Chicken-and-egg: the self-heal only fires after Step 6 has already failed with the opposite class of problem, not on the missing-column failure itself.

---

## Fix

Pattern match on Step 7's `_mark_completed` (lines 247-258): defensive `ADD COLUMN IF NOT EXISTS` inline at the top of the first cursor block that touches the column, before any SELECT/UPDATE that depends on it. Same transaction, same cursor, idempotent.

### `kbl/steps/step6_finalize.py` — `_fetch_signal_row`

```diff
 def _fetch_signal_row(conn: Any, signal_id: int) -> _SignalRow:
     """One SELECT pulls every column Step 6 needs. Raises ``LookupError``
     on missing row — pipeline_tick catches and routes to inbox.
+
+    ``finalize_retry_count`` was intentionally NOT part of a formal
+    migration (see ``_increment_retry_count`` docstring for the R3
+    rationale). Live DBs booted before Step 6 ever ran are missing the
+    column, which used to abort this SELECT before the self-healing
+    ALTER in ``_increment_retry_count`` could ever execute. Run the
+    defensive ALTER here — matches Step 7's inline
+    ``_mark_completed`` pattern (lines 247-258): ADD COLUMN first,
+    SELECT/UPDATE second, one transaction, idempotent.
     """
     with conn.cursor() as cur:
+        cur.execute(
+            "ALTER TABLE signal_queue "
+            "ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0"
+        )
         cur.execute(
             "SELECT opus_draft_markdown, step_5_decision, "
             "       triage_score, triage_confidence, "
             "       COALESCE(finalize_retry_count, 0) "
             "FROM signal_queue WHERE id = %s",
             (signal_id,),
         )
```

**What I deliberately did NOT change:**
- The existing `ADD COLUMN IF NOT EXISTS` inside `_increment_retry_count` stays. It's now belt-and-suspenders — no-op when the column already exists, protects any future caller that reaches `_increment_retry_count` through an unusual path (e.g. a hypothetical unit test or direct invocation). Cost is one idempotent DDL statement per retry-failure branch: trivial.
- No migration file added. Step 6's decision to keep `finalize_retry_count` out of the formal migration set (R3 coordination with Step 5 — see `_increment_retry_count` docstring, lines 419-422) is preserved. If that decision is revisited later, a formal migration can land alongside; the defensive ALTER here will become a harmless no-op across all environments.
- No touch to `pipeline_tick.py`, no touch to step consumers, no schema changes to any column other than `finalize_retry_count`. Per brief constraints.

### Option selection (from the brief's menu)

The brief offered: **(a)** module-level init, **(b)** formal migration file, **(c)** add to `_ensure_signal_queue_base` bootstrap.

I chose a variant of (a), matching Step 7's exact pattern rather than introducing a new init function. Rationale:

- **(a) variant shipped** — inline in `_fetch_signal_row`. Symmetric with Step 7's `_mark_completed`. Zero new module-level state, zero new entry points to remember. A reviewer who knows Step 7 immediately understands Step 6.
- **(b) rejected** — the brief itself notes "intentional per code comment" (`_increment_retry_count` docstring line 419). Reversing that decision is out of scope; if it's to be reversed, that's a separate architectural call, not a 45-min fix.
- **(c) rejected** — adding to `_ensure_signal_queue_base` (store_back.py) pushes us back toward the same drift trap that bit `hot_md_match` this morning: bootstrap DDL declaring one type/shape, migrations (or here, step-defensive ALTERs) declaring another, with `IF NOT EXISTS` guards hiding the delta. Keeping the source-of-truth in one place — the defensive ALTER owned by the step that cares about the column — is the safer pattern.

---

## Audit — other potentially un-migrated columns referenced by step writers

Scanned all `kbl/steps/*.py` UPDATE SET blocks and `SELECT` column lists, cross-referenced against the live 35-column schema:

| Step | Columns WRITTEN | All present live? |
|---|---|---|
| step1_triage | `primary_matter, related_matters, status, triage_confidence, triage_score, triage_summary, vedana` | ✓ |
| step2_resolve | `resolved_thread_paths, status` | ✓ |
| step3_extract | `extracted_entities, status` | ✓ |
| step4_classify | `cross_link_hint, status, step_5_decision` | ✓ |
| step5_opus | `opus_draft_markdown, status` | ✓ |
| step6_finalize | `final_markdown, status, target_vault_path` + `finalize_retry_count` (self-heal) | **`finalize_retry_count` — fixed here** |
| step7_commit | `commit_sha, committed_at, status` (self-heal inline) | ✓ (post-first-run) |

**No other un-migrated columns** referenced in step UPDATE writers. The drift is isolated to `finalize_retry_count`. Step 7's two inline ALTERs for `committed_at` / `commit_sha` have already run at least once (both columns are now live), so that path is self-healed — but same pattern, different column: if the DB were ever re-created from a partial baseline, step 7's ALTERs would run again on first Step 7 call. The defensive pattern is working as designed for step 7. After this fix it will be working the same way for step 6.

---

## Regression gates added

Two live-PG tests appended to `tests/test_step6_finalize.py`, both gated on `needs_live_pg` (skip cleanly without Neon branch / `TEST_DATABASE_URL`):

1. **`test_fetch_signal_row_self_heals_missing_finalize_retry_count`** — DROPs the column explicitly, asserts it's gone via `information_schema`, seeds a signal with valid `opus_draft_markdown` + telemetry, calls `_fetch_signal_row`, then asserts: (a) call succeeded, (b) column now exists with type `integer`, (c) returned `finalize_retry_count == 0` (COALESCE on the freshly-created DEFAULT 0 column), (d) other columns (`step_5_decision`, `triage_score`, `triage_confidence`) round-trip intact. Cleans up kbl_cost_ledger + kbl_log + signal_queue in `finally`.

2. **`test_fetch_signal_row_idempotent_when_column_already_exists`** — second-invocation guard. Ensures the column exists, pre-sets `finalize_retry_count=2` on the row, calls `_fetch_signal_row` twice in a row, asserts both calls return `retry_count=2` and neither raises. Protects against a future accidental non-idempotent change (e.g. dropping the `IF NOT EXISTS` clause).

Both tests use the shared `tests/fixtures/signal_queue.insert_test_signal` helper (consistent with PR #30 + PR #31 test patterns).

---

## Verification

- `ast.parse` on both edited files → syntactically valid.
- `from kbl.steps.step6_finalize import _fetch_signal_row` → imports cleanly.
- Existing `_mock_conn` mock tests are unaffected: the mock's `_execute` side-effect is substring-dispatched and records all calls into `conn._calls`. The added `ALTER TABLE` call lands in `_calls` but is not matched by any existing substring needle (`"final_markdown"`, `"insert into kbl_cross_link_queue"`, `("opus_failed", ...)` / `("finalize_failed", ...)` tuple params). All existing membership-based assertions continue to hold.
- Pytest not available locally (no venv on this machine); full run happens in Render CI on PR open and in reviewer's environment.

---

## Recovery (Tier A standing auth — not this PR's action)

Once merged + deployed (Render auto-deploy ~3 min), re-pend the rows stranded by this bug. The stranding pattern is the same "claim committed, step failed, status stuck at processing" that recovered the earlier drift victims:

```sql
UPDATE signal_queue
   SET status='awaiting_finalize',
       started_at=NULL
 WHERE stage IN ('finalize', 'opus')  -- adjust if stage differs
   AND status='processing'
   AND final_markdown IS NULL
   AND opus_draft_markdown IS NOT NULL;
```

AI Head to verify the exact `stage` value on affected rows before running (older ticks may have varied between `'finalize'`, `'opus'`, or left stage unchanged while flipping status). Idempotent — a row already at `status='awaiting_finalize'` is unaffected.

---

## Cross-reference — today's column-drift cluster

Four bugs, same family, all surfaced as Gate 1 progressed:

| # | Column | Class | Status |
|---|---|---|---|
| 1 | `raw_content` | Phantom column read by consumers (never in any schema) | ✓ PR #30 merged |
| 2 | `hot_md_match` | Live BOOLEAN; migration + code say TEXT | Diagnosed (B2 report `e3a4ad8`); fix deferred by AI Head |
| 3 | `related_matters` | JSONB column, write bound as `text[]` (missing cast) | ✓ PR #31 merged |
| 4 | `finalize_retry_count` | Column never migrated, SELECT precedes self-heal | **This PR** |

Common mechanism: each bug stalled the claim-transactionality rollback (every row stranded at `status='processing'`, `started_at IS NOT NULL`, step-result columns NULL). Each revealed once the prior one was fixed. Gate 1's progressive-reveal of column-level drift has been the single most useful signal today for understanding how the bootstrap-vs-migration-vs-self-heal tangle actually sits in the live DB.

### Broader-scope follow-up

B3 has already endorsed `STEP_WRITERS_JSONB_SHAPE_AUDIT_1` post-Gate-1. Recommend expanding scope to `STEP_SCHEMA_CONFORMANCE_AUDIT_1` covering both classes:

1. **JSONB shape drift** (this morning's concern) — every JSONB writer has paired `%s::jsonb` + `json.dumps(...)`; regression test per writer site asserts `jsonb_typeof` on the persisted value.
2. **Column-existence drift** (this afternoon's concern) — every column referenced in step SQL exists in the live schema OR is guarded by a defensive self-heal ALTER that runs BEFORE the first SELECT/UPDATE touching that column. A simple boot-time audit can assert this: for every `\bcolumn_name\b` reference inside an `SQL string` in `kbl/steps/`, check `information_schema.columns` at app boot.

A CI-side lint rule could catch both classes pre-merge:
- JSONB: grep `= %s::jsonb` in same statement as `%s` without a `json.dumps` on the corresponding param position → fail.
- Column existence: parse each step's SQL, assert every column referenced exists in a canonical schema manifest (or is wrapped by `ADD COLUMN IF NOT EXISTS` earlier in the same module).

Both checks are ~50 lines of Python each. Worth the investment after Gate 1 closes.

---

## Review request — B3

Branch: `step6-finalize-retry-column-fix-1` against `main`. Single logical change:
1. Defensive `ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0` added at the top of `_fetch_signal_row`, before the SELECT.
2. Two live-PG regression tests (drop-and-rerun; idempotency guard).
3. Ship report with the full cross-reference to the day's cluster.

Specific review asks:
1. Option-selection rationale (variant of (a), not (b) or (c)) — sanity-check.
2. Keeping the duplicate ALTER in `_increment_retry_count` as belt-and-suspenders — reasonable, or drop it for clean single-source-of-truth?
3. Confirm the mock-test analysis (`_mock_conn` handles the extra ALTER call without breakage).
4. Flag any concern about PG DDL-in-transaction semantics — the defensive ALTER runs inside the caller-owned tx; on caller rollback, the ALTER rolls back too. That's fine for correctness (next call re-runs idempotently), but note in the module docstring if you want it explicit.

AI Head — please dispatch B3 + handle the Tier A recovery UPDATE post-merge.
