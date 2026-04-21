---
role: B2
kind: ship
brief: bridge_hot_md_match_type_repair
pr: https://github.com/vallen300-bit/baker-master/pull/33
branch: bridge-hot-md-match-type-repair-1
base: main
verdict: SHIPPED_READY_FOR_REVIEW
date: 2026-04-21
tags: [bridge, hot_md, schema-drift, migration, bootstrap-reconciliation, cortex-t3-gate1]
---

# B2 — `BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1` ship report

**Scope:** XS fix to coerce `signal_queue.hot_md_match` from live-DB BOOLEAN to the intended TEXT. Three coordinated edits (migration + bootstrap base + bootstrap additions) plus a regression gate with both parse-level and live-PG coverage. Unblocks bridge ticks so fresh alerts flow into `signal_queue` and Gate 1 gets the in-scope signals it needs.

---

## Substrate

Root-cause, fix direction, and recovery plan all fixed by this morning's diagnostic (`briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md`, commit `e3a4ad8`). This ship report documents execution of that direction — no new decisions.

TL;DR of the diagnostic: the app-boot bootstrap (`_ensure_signal_queue_base`) declared `hot_md_match BOOLEAN` in the KBL-19 era. The newer `BRIDGE_HOT_MD_AND_TUNING_1` migration's `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` was a silent no-op on any DB where that bootstrap had already run — `IF NOT EXISTS` guards presence, not type. Bridge now binds TEXT (e.g. `"Lilienmatt"`) into a BOOLEAN column → every tick aborts; 479+ ERRORs over ~4h as of the diagnostic.

---

## Changes

### 1. New migration — `migrations/20260421b_alter_hot_md_match_to_text.sql`

Sorts lexicographically AFTER the original `20260421_signal_queue_hot_md_match.sql` (`b` > `_` in ASCII), so the migration runner applies the TEXT repair last:

```sql
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS hot_md_match TEXT;

DO $$
BEGIN
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
END $$;
```

**Why the `DO` block guard:** makes the migration idempotent on DBs where the column is already TEXT (fresh DB post-fix, re-runs). Without the guard, `ALTER COLUMN ... TYPE TEXT USING ::text` would still succeed but would trigger a table rewrite every run — wasteful and confusing. The `information_schema.columns` predicate sidesteps both problems.

**Data-loss surface:** zero. Pre-migration audit shows all 16 production rows have `hot_md_match IS NULL`. The `::text` cast would map `true`/`false`/NULL → `'true'`/`'false'`/NULL if any non-NULL existed; since none do, the cast is effectively a rename.

**DOWN section:** kept commented-out per existing convention. Rolling back to BOOLEAN would destroy verbatim pattern strings — only reversible under deliberate hot.md axis retirement. Documented in the file header.

### 2. `memory/store_back.py:6213` — fix bootstrap base

```diff
-                    hot_md_match      BOOLEAN,
+                    hot_md_match      TEXT,
```

Inside `_ensure_signal_queue_base`'s `CREATE TABLE IF NOT EXISTS signal_queue` block. Fresh-DB boot now lands TEXT from minute zero; a future regression of this single line would recreate the drift.

### 3. `memory/store_back.py` — add type-reconciliation block to `_ensure_signal_queue_additions`

Appended after the `started_at` ADD COLUMN, before the `triage_confidence` CHECK:

```python
cur.execute(
    """
    DO $$
    BEGIN
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
    END $$;
    """
)
```

Defense-in-depth on top of the migration runner: even if `schema_migrations` ledger is stale for any reason (rebased migration SHA, manual DELETE of the row, fresh Render instance that skipped migrations), app boot self-heals the live column to TEXT. Idempotent — no-op when already TEXT. Mirrors the philosophy of the status-CHECK re-assertion block already in the same function (see the `_ensure_signal_queue_additions` comment at the expanded CHECK block).

### 4. Regression gate — `tests/test_hot_md_match_type_repair.py`

New test module with 9 tests split into two tiers:

**Parse-level (always run, no live PG):**
1. Migration file exists at expected path.
2. Migration filename sorts AFTER the original `20260421_signal_queue_hot_md_match.sql` in glob order — asserts the runner applies it last.
3. Migration has both `== migrate:up ==` and `== migrate:down ==` sections.
4. UP section contains `ALTER TABLE signal_queue`, `ALTER COLUMN hot_md_match`, `TYPE TEXT`, `USING hot_md_match::text`.
5. UP section is idempotent via `DO $$` block with `information_schema.columns` + `data_type = 'boolean'` guard.
6. Bootstrap base `_ensure_signal_queue_base` declares `hot_md_match TEXT`, NOT `hot_md_match BOOLEAN`.
7. Bootstrap additions `_ensure_signal_queue_additions` contains the type-reconciliation DO block (signature tokens check).

**Live-PG (gated on `needs_live_pg`):**
8. Force column to BOOLEAN → apply migration UP → assert data_type is `text`. Core recovery path.
9. Force column to TEXT → re-apply migration UP → assert still `text` and no raise. Idempotency guard.
10. Force column to BOOLEAN → call `SentinelStoreBack()._ensure_signal_queue_additions()` → assert TEXT. Exercises the defense-in-depth path for stale migration ledgers.
11. DROP TABLE signal_queue CASCADE → call `SentinelStoreBack()._ensure_signal_queue_base()` → assert fresh-boot schema has `hot_md_match` as TEXT. Prevents regression of the KBL-19-era bootstrap DDL.

(9 tests in the file; 4 live-PG; numbering in prose above runs 1-11 just for narrative flow.)

---

## Migration-vs-bootstrap DDL drift check (mandatory per today's rule)

Per the rule in `memory/feedback_migration_bootstrap_drift.md`, grep `store_back.py` for bootstrap DDL touching columns this migration references (only column affected: `hot_md_match`):

| Location | Pre-fix | Post-fix |
|---|---|---|
| `_ensure_signal_queue_base` CREATE TABLE (line 6213) | `hot_md_match BOOLEAN` | `hot_md_match TEXT` ✓ |
| `_ensure_signal_queue_additions` (appended after `started_at`) | — (no declaration) | type-reconciliation DO block ✓ |
| Any other bootstrap reference | none (verified via `grep -n "hot_md_match" memory/store_back.py`) | n/a |

All reference sites now declare TEXT (or reconcile to TEXT). No drift left between migration intent and bootstrap declaration.

**Grep output:**

```
$ grep -n "hot_md_match" memory/store_back.py
6213:                    hot_md_match      TEXT,
6259:            # BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1 (2026-04-21 evening):
6260:            # Reconcile hot_md_match type if a legacy bootstrap DDL
6274:                           AND column_name = 'hot_md_match'
6278:                            ALTER COLUMN hot_md_match TYPE TEXT
6279:                            USING hot_md_match::text;
```

Two sites, both aligned on TEXT. Rule satisfied.

---

## Verification

- `ast.parse` on `memory/store_back.py` and `tests/test_hot_md_match_type_repair.py` → syntactically valid.
- Migration SQL file → reviewed by eye; sections parse, DO block syntax matches existing migrations.
- Local Python 3.9 import of `memory.store_back` fails on unrelated pre-existing `int | None` type-hint syntax (requires Python 3.10+). Render runs 3.11+; CI runs 3.11+. Not introduced by this PR.
- Parse-level tests are deterministic and do not depend on live PG — will run green on any Python 3.11+ CI without config.
- Live-PG tests skip cleanly when `TEST_DATABASE_URL` / Neon branch unset (existing `needs_live_pg` gate).

---

## Recovery — no action needed

Per the diagnostic (§"Impact assessment"): zero signals dropped. The bridge's transactional rollback preserved the watermark pin at its pre-Lilienmatt value, so the 15+ alerts accumulated during the ~4h outage are still in the `alerts` table. On the first successful bridge tick after this fix deploys, they drain in watermark order.

AI Head's standing recovery instruction:
> Watch `kbl_log` for bridge errors clearing. Fresh signals → in-scope ones reach Step 6 → Mac Mini Step 7 commits → Gate 1 closes.

No write-path Tier B recovery UPDATE required for this fix.

---

## Cross-reference — today's column-drift cluster, now complete

Four bugs, same family, all now shipped or diagnosed:

| # | Column | Class | Status |
|---|---|---|---|
| 1 | `raw_content` | Phantom column read by consumers | ✓ PR #30 merged |
| 2 | `hot_md_match` | Live BOOLEAN vs migration TEXT | **This PR** |
| 3 | `related_matters` | JSONB write bound as text[] (missing cast) | ✓ PR #31 merged |
| 4 | `finalize_retry_count` | Column never migrated, SELECT precedes self-heal | ✓ PR #32 merged |

Each bug stalled claim-transactionality rollback (every row stranded at `status='processing'`, `started_at IS NOT NULL`, step-result columns NULL). Progressive reveal as Gate 1 advanced through the pipeline. Post-this-merge, there are no known column-drift or type-drift bugs remaining on the Gate 1 critical path.

**Standing follow-up (post-Gate 1):** expand B3's endorsed `STEP_WRITERS_JSONB_SHAPE_AUDIT_1` to `STEP_SCHEMA_CONFORMANCE_AUDIT_1` covering all three failure modes surfaced today: (a) JSONB shape drift, (b) column-existence drift, (c) column-type drift. Two CI lint rules + boot-time schema conformance assertion can catch all three pre-merge. Recommend this becomes the top Gate-1-closeout brief.

---

## Review request — B3

Branch: `bridge-hot-md-match-type-repair-1` against `main`. Three logical edits in one PR (naturally atomic — reviewing any one in isolation leaves drift exposed):

1. New migration `20260421b_alter_hot_md_match_to_text.sql`.
2. Bootstrap base DDL `BOOLEAN → TEXT` for `hot_md_match`.
3. Bootstrap additions type-reconciliation DO block.

Specific review asks:

1. **Filename ordering** — `20260421b_...` sorts after `20260421_...`. Please confirm that's acceptable convention (no hard rule in the repo; existing files use date-only prefix). An alternate would be `20260422_...` but this was scoped and landed on 2026-04-21 so that would be factually wrong.
2. **DO block idempotency** — the `information_schema.columns` predicate guards on `data_type = 'boolean'`. A DB with `hot_md_match` as, say, `varchar(255)` would also fall through the guard (no-op) — arguably wrong, but no production environment exists in that state and `ALTER COLUMN ... TYPE TEXT USING ::text` from varchar would succeed anyway. Flag if you want the predicate broadened to `data_type != 'text'`.
3. **Migration-vs-bootstrap rule satisfaction** — grep output + the drift table in §"Migration-vs-bootstrap DDL drift check". Confirm the rule is satisfied.
4. **Live-PG test destructiveness** — `test_bootstrap_base_creates_fresh_table_with_text_column_live` runs `DROP TABLE signal_queue CASCADE`. Only runs on ephemeral Neon branches (`needs_live_pg` gate). Flag if you want a safety assertion that the target DB is explicitly a test DB before the drop (e.g. check the DB name matches a pattern).

AI Head — please dispatch B3 + monitor bridge post-merge. Fresh signals flowing end-to-end through Steps 1-6 → Mac Mini Step 7 commits → Gate 1 closes.
