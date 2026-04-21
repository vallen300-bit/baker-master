---
role: B3
kind: review
brief: bridge_hot_md_match_type_repair
pr: https://github.com/vallen300-bit/baker-master/pull/33
branch: bridge-hot-md-match-type-repair-1
base: main
commits: [cb37867, 1d650b1]
ship_report: briefs/_reports/B2_bridge_hot_md_match_type_repair_20260421.md
verdict: APPROVE
tier: A
date: 2026-04-21
tags: [bridge, hot_md_match, type-drift, self-heal, migration, cortex-t3-gate1, review]
---

# B3 — review of PR #33 `BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1`

**Verdict: APPROVE.** Tier A auto-merge greenlit. Zero blocking issues, zero gating nits. The three-layer fix (migration + bootstrap column type + self-heal reconciliation) addresses the full drift class cleanly, idempotently, and with real symmetry to the existing status-CHECK re-assertion pattern. Closes today's 4-bug column-drift cluster.

---

## Focus items — 7/7 green

### 1. ✅ Migration idempotency + ordering

**DO-block guard is correct:**
```sql
IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'signal_queue'
       AND column_name = 'hot_md_match'
       AND data_type  = 'boolean'
) THEN
    ALTER TABLE signal_queue
        ALTER COLUMN hot_md_match TYPE TEXT
        USING hot_md_match::text;
END IF;
```

- Re-apply on already-TEXT DB: `IF EXISTS (... data_type='boolean')` returns false → DO-block skips the ALTER entirely. No error-swallow (the ALTER is never issued). ✓
- Re-apply on fresh DB (column absent): the leading `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` creates it TEXT, then the DO-block's predicate is also false. ✓
- First apply on legacy BOOLEAN DB: ADD COLUMN IF NOT EXISTS no-ops (column already exists as BOOLEAN), DO-block predicate is true, ALTER COLUMN TYPE TEXT fires. ✓

**Ordering via lex-sort in `config/migration_runner.py:219` (`files = sorted(mig_dir.glob("*.sql"))`):**

ASCII comparison at position 8 of the two filenames:
- `20260421_signal_queue_hot_md_match.sql` → char[8] = `_` (0x5F = 95)
- `20260421b_alter_hot_md_match_to_text.sql` → char[8] = `b` (0x62 = 98)

`_` (95) < `b` (98), so the original migration sorts first, the repair sorts second. Python's `sorted()` on `Path` objects is lex. ✓ Parse-level test `test_migration_sorts_after_original` enforces this, so even a future rename accidentally breaking the order will fail CI.

One extra note on the runner's sha256-drift defense (lines 225-229 of `migration_runner.py`): editing the applied migration after it lands would abort startup with `migration sha256 drift`. That's the right behavior here — once `20260421_signal_queue_hot_md_match.sql` has been claimed on any replica, the separate `_b` file is the only safe way to flip the type. B2's decision to add a new file rather than edit the old one is correct per the runner's explicit contract.

### 2. ✅ Bootstrap edit at `memory/store_back.py:6213`

Only functional edit in `_ensure_signal_queue_base`:
```diff
-                    hot_md_match      BOOLEAN,
+                    hot_md_match      TEXT,
```

**Grep-mandatory drift-rule check** — confirmed no residual BOOLEAN declaration:
```
$ grep -n "hot_md_match\|hot_md" memory/store_back.py
6213:                    hot_md_match      TEXT,          # bootstrap column def (TEXT) ✓
6260: # Reconcile hot_md_match type if a legacy bootstrap DDL          # comment only
6264: # caused `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` in         # comment only
6265: # 20260421_signal_queue_hot_md_match.sql to silently no-op.      # comment only
6267: # 20260421b_alter_hot_md_match_to_text.sql migration: even if    # comment only
6278:                           AND column_name = 'hot_md_match'       # info_schema WHERE clause
6282:                            ALTER COLUMN hot_md_match TYPE TEXT   # self-heal ALTER → TEXT ✓
6283:                            USING hot_md_match::text;             # self-heal USING cast ✓
```

Two functional touch points. Both land on TEXT. Zero residual BOOLEAN for this column in store_back.py. Drift-rule compliant.

**Adjacent-column grep** — checked all remaining BOOLEAN columns in `store_back.py` for similar drift risk:

```
410: ALTER TABLE document_extractions ... validated BOOLEAN      — unrelated table
481: active BOOLEAN DEFAULT TRUE                                  — baker_insights, bool semantic
519: active BOOLEAN DEFAULT TRUE                                  — baker_corrections, bool semantic
688: baker_writable BOOLEAN DEFAULT FALSE                         — clickup table, bool semantic
700: success BOOLEAN DEFAULT TRUE                                 — clickup table, bool semantic
963: is_director BOOLEAN DEFAULT FALSE                            — whatsapp_messages, bool semantic
2258: active BOOLEAN DEFAULT TRUE                                 — bool semantic
2269: use_thinking BOOLEAN DEFAULT FALSE                          — capability_sets, bool semantic
4746: dismissed BOOLEAN DEFAULT FALSE                             — bool semantic
6222: ayoniso_alert BOOLEAN DEFAULT FALSE                         — signal_queue, STILL BOOLEAN (correct — bool in prod, no writer sends TEXT)
```

None of these have the drift shape (writer binding TEXT into BOOLEAN column). `signal_queue.ayoniso_alert` is the only adjacent BOOLEAN on signal_queue itself, and `cross_link_hint` (the other BOOLEAN on signal_queue per earlier schema query) is written in `kbl/steps/step4_classify.py:244` as a Python `bool`, matching the column. Clean.

### 3. ✅ `_ensure_signal_queue_additions` reconciliation helper

**Idempotency:** the DO-block is identical to the migration's. Both guard on `data_type='boolean'`. Repeated boots with an already-TEXT column: predicate is false, ALTER never fires, zero side-effect. ✓

**Advisory-lock / `pg_typeof` guard structure:** the tests use `information_schema.columns.data_type` rather than `pg_typeof(col)` — this is more correct, not a gap. `pg_typeof` inspects a value's runtime type; `information_schema.data_type` inspects the column's schema type. Schema type is what we're reconciling, so info_schema is the authoritative source. The ship report's mention of `pg_typeof` in focus-item phrasing is loose; the implementation's choice is better. Non-blocking.

**Symmetry with the status-CHECK re-assertion pattern** — real, not prose-only. Lines 6302-6303 in the same function:
```python
cur.execute("ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check")
cur.execute("""ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check CHECK (status IN (...))""")
```
Philosophy: mirror the migration, re-assert on boot so the migration can't be silently reverted by a manual intervention or a stale replica. The new hot_md_match DO-block follows the same philosophy: mirror `20260421b_alter_hot_md_match_to_text.sql`, re-assert at boot. Structure differs (CHECK → DROP-then-ADD; column type → DO-block with guard) because CHECK constraints re-assert cleanly by name while ALTER COLUMN TYPE needs a conditional guard to avoid unnecessary table rewrites on already-TEXT DBs. **Same philosophy, different idiom per constraint-kind requirements.** ✓

### 4. ✅ Migration-vs-bootstrap DDL drift rule compliance

Per `memory/feedback_migration_bootstrap_drift.md`: migrations declare the source of truth; bootstrap becomes an assert-or-create shim that errors loudly on type drift. This PR delivers exactly that:

- **Migration:** `20260421b_alter_hot_md_match_to_text.sql` → source of truth, flips BOOLEAN → TEXT, idempotent.
- **Bootstrap (`_ensure_signal_queue_base`):** CREATE TABLE with `hot_md_match TEXT` — matches what the migration produces. A fresh DB starts correctly.
- **Bootstrap (`_ensure_signal_queue_additions`):** inline reconciliation DO-block — catches the "migration ledger stale / replica booted against older schema" failure mode and self-heals at app boot.

Three layers, each independently idempotent, covering three failure modes (fresh DB, migrated DB, legacy DB with stale migration ledger). This is the clean "defense in depth" pattern the drift rule prescribes.

**No other columns adjacent to this change are affected.** Grep of BOOLEAN declarations (above in §2) shows every remaining BOOLEAN is legitimately a boolean-semantic column bound to a Python bool. No other writer sends TEXT into a BOOLEAN column. No other reader expects BOOLEAN from a TEXT column.

### 5. ✅ Tests (`tests/test_hot_md_match_type_repair.py`) — 7 parse + 4 live-PG

**7 parse-level tests** (always run):
1. `test_migration_file_exists` — presence
2. `test_migration_sorts_after_original` — lex-sort verifies `_b` > `_` (tests ordering contract against runner)
3. `test_migration_has_up_and_down_sections` — UP + DOWN both present
4. `test_migration_up_contains_alter_column_type_text` — semantic tokens: `alter table signal_queue`, `alter column hot_md_match`, `type text`, `using hot_md_match::text`
5. `test_migration_up_is_idempotent_on_already_text` — parse-level: `do $$` + `information_schema.columns` + `data_type` + `boolean` present
6. `test_bootstrap_base_declares_hot_md_match_as_text` — CREATE TABLE block has TEXT, has NO residual `hot_md_match BOOLEAN`
7. `test_bootstrap_additions_has_type_reconciliation_block` — DO-block signatures present in `_ensure_signal_queue_additions`

**4 live-PG tests** (skip cleanly via `needs_live_pg`):

| Focus-5 requirement | Test function | Assertion |
|---|---|---|
| (a) fresh DB path ends TEXT | `test_bootstrap_base_creates_fresh_table_with_text_column_live` | DROP TABLE CASCADE → `_ensure_signal_queue_base()` → `data_type='text'` |
| (b) legacy BOOLEAN DB path self-heals to TEXT | `test_bootstrap_additions_self_heals_boolean_to_text_live` | force BOOLEAN → `_ensure_signal_queue_additions()` → `data_type='text'` |
| (b') legacy BOOLEAN DB path via migration | `test_migration_up_flips_boolean_to_text_live` | force BOOLEAN → execute migration UP section → `data_type='text'` |
| idempotency | `test_migration_up_idempotent_on_text_column_live` | column already TEXT → execute migration UP → still TEXT, no raise |

Focus item 5's (c) "`pg_typeof` post-ensure-chain assertion" is covered by `information_schema.columns.data_type` assertions — stronger guarantee (schema type vs runtime value type). ✓

Focus item 5's (d) "bridge INSERT of TEXT value succeeds" is NOT a dedicated test here, but is covered implicitly:
- All three post-condition paths assert `data_type='text'`, which by definition accepts string INSERTs.
- `test_bridge_pipeline_integration.py` (from PR #30) already exercises the actual bridge INSERT path against a real DB.
- Adding a redundant INSERT test would be low value given the column-type assertions are the tighter gate.

Local smoke: 7 passed + 4 skipped under py3.9 + fallback pytest. The 4 skips are exactly the live-PG tests as designed.

**Cleanup:** all 4 live-PG tests close their connections in `finally`. No lingering resources. The two `patch.dict(os.environ, {"DATABASE_URL": needs_live_pg})` tests also reset `SentinelStoreBack._instance = None` before the override — correctly guards against a cached pool pointing at a different DB.

### 6. ✅ Data-loss surface confirmed

Live query via `mcp__baker__baker_raw_query`:
```sql
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE hot_md_match IS NULL) AS null_count,
       COUNT(*) FILTER (WHERE hot_md_match IS NOT NULL) AS nonnull_count
  FROM signal_queue;
-- total: 16, null_count: 16, nonnull_count: 0
```

16/16 rows have `hot_md_match IS NULL`. Zero non-NULL values in the column. The `USING hot_md_match::text` cast has zero data-loss surface — it's effectively a column rename.

The assertion is present in:
- The migration file itself (`migrations/20260421b_alter_hot_md_match_to_text.sql`, lines 17-21).
- The ship report (`B2_bridge_hot_md_match_type_repair_20260421.md`).
- Both cite the pre-migration audit with the exact 16/16 count.

✓ Assertion holds.

### 7. ✅ No scope creep

`git diff main...HEAD --name-only`:
```
briefs/_reports/B2_bridge_hot_md_match_type_repair_20260421.md   — ship report
memory/store_back.py                                              — bootstrap (2 edits)
migrations/20260421b_alter_hot_md_match_to_text.sql               — new migration
tests/test_hot_md_match_type_repair.py                            — new tests
```

`git diff main...HEAD -- kbl/bridge/alerts_to_signal.py kbl/pipeline_tick.py kbl/steps/` → **0 lines.** No bridge code, no pipeline_tick, no step consumers touched. Per brief constraint. ✓

---

## Non-blocking observations (for the post-Gate-1 audit brief)

**N1.** The DO-block SQL is physically duplicated between `migrations/20260421b_alter_hot_md_match_to_text.sql` (§UP) and `memory/store_back.py:6271-6287`. Per the project's established pattern — see the status-CHECK constant comment ("Mirror of migrations/20260418_expand_signal_queue_status_check.sql — the two MUST stay in sync") — this is the accepted trade-off: duplication over indirection. The two sites read as prose-adjacent enough that a maintainer editing one will see the other. Non-blocking.

**N2.** The bootstrap reconciliation block is placed between `started_at TIMESTAMPTZ` (line 6257) and the `triage_confidence_range` CHECK constraint (line 6291). Logically fine, but as additional type-repair blocks land over time, the function will grow. A future refactor could extract a `_ensure_signal_queue_type_reconciliations` helper grouping all `ALTER COLUMN TYPE` DO-blocks, symmetric to how `_ensure_signal_queue_additions` groups additive ALTERs. Not worth the churn today; raise if a third or fourth type-repair lands.

**N3.** The migration's `-- == migrate:down ==` section is documentation-only (paste-into-psql) rather than executable. Per the runner (`config/migration_runner.py`) there's no `down` path in production, so the text body is effectively a comment. Consistent with existing migrations (e.g. `20260421_signal_queue_hot_md_match.sql` also has a doc-only down). Non-blocking.

---

## Recommendation

**Tier A auto-merge OK.**

Post-merge sequence (Tier A standing auth per memory/actions_log.md):
1. Merge PR #33 to main.
2. Render auto-deploys (~3 min). Migration runner acquires advisory lock, applies `20260421b_alter_hot_md_match_to_text.sql`, flips the live column BOOLEAN → TEXT. `schema_migrations` gets a new row.
3. `_ensure_signal_queue_additions` self-heal DO-block runs on every subsequent boot as a no-op (column is already TEXT) — defense-in-depth for stale-ledger scenarios.
4. Bridge resumes emitting — next tick's `INSERT INTO signal_queue (..., hot_md_match) VALUES (..., 'Lilienmatt')` succeeds with TEXT.
5. Watch `kbl_log` for zero new ERROR rows with the `invalid input syntax for type boolean` signature.
6. Watch `signal_queue` for the post-bridge-resume flow: expect Layer 0 dedupe → Step 1 triage → Step 2 → ... → Step 7 commit, now that all four of today's drift bugs are resolved.

**Gate 1 status:** with this merge, the 4-bug column-drift cluster is closed:
- ✓ PR #30: raw_content phantom column (step consumers)
- ✓ PR #31: related_matters text[] → JSONB
- ✓ PR #32: finalize_retry_count never-migrated
- ✓ PR #33: hot_md_match BOOLEAN → TEXT

Pipeline should now be end-to-end healthy. Gate 1 closes when ≥5-10 signals reach terminal stage (`done` / `paused_cost_cap` / `routed_inbox` / `committed_to_vault`) with `target_vault_path` + `commit_sha` populated for the committed subset.

**Post-Gate-1 follow-ups to schedule (reiterating from PR #32 review, no new asks):**
- `STEP_SCHEMA_CONFORMANCE_AUDIT_1` — expanded scope (shape drift + existence drift + **type drift**, now with the hot_md_match case as the third drift class).
- `PIPELINE_TICK_STRANDED_ROW_REAPER_1` — optional, separate brief.

Suggest adding the hot_md_match type-drift case to the audit brief's fixture set as a third example alongside raw_content (existence) and related_matters (shape). Three real-world drift classes, three fixtures, one CI lint framework.

---

## Environment notes

- Review done on worktree `/tmp/bm-b3-pr33` against `origin/bridge-hot-md-match-type-repair-1@1d650b1`.
- Live schema + row-count audit via `mcp__baker__baker_raw_query` against `information_schema.columns` and `signal_queue`.
- Local py3.9 + fallback pytest: 7 passed, 4 skipped (the 4 live-PG gates, as designed).
- Worktree cleanup: `git worktree remove /tmp/bm-b3-pr33 --force` on tab close per §8.

Tab quitting per §8.

— B3
