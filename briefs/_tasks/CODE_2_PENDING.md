# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance, prep-work + eval-scripts author, committed 7+ tasks 2026-04-17)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution

---

## Task: Schema-Draft FK Reconciliation

### Context

KBL-A brief (commit `942c347`, §5 "Phase 1 — Schema Migrations") locks the FK reconciliation for `kbl_cost_ledger.signal_id` and `kbl_log.signal_id`:

- **Type:** `INTEGER` (matches `signal_queue.id = SERIAL`, not `BIGINT` as currently in your draft)
- **Constraint:** `FOREIGN KEY REFERENCES signal_queue(id) ON DELETE SET NULL`
- **Rationale:** `ON DELETE SET NULL` preserves cost ledger + log rows after signal purge (30-day TTL on `done`/`classified-deferred`), losing the per-signal join but keeping aggregate rollups.

Your current draft (`briefs/_drafts/KBL_A_SCHEMA.sql` committed `c275ffe`) flagged this as "FK pending ID-type reconciliation" — the reconciliation is now locked in KBL-A brief §5.

### What to do

1. **Read** KBL-A brief §5 (Phase 1 — Schema Migrations) — especially the FK reconciliation block.
2. **Validate** the proposed reconciliation is correct against your understanding of `signal_queue.id` type (should be `SERIAL` / `INTEGER` per KBL-19). If your reading differs, FLAG IT — don't silently change. We want the type to reflect reality, not wishful thinking.
3. **Update** `briefs/_drafts/KBL_A_SCHEMA.sql`:
   - Change `kbl_cost_ledger.signal_id BIGINT` → `INTEGER`
   - Change `kbl_log.signal_id BIGINT` → `INTEGER`
   - Add FK constraints for both columns with `ON DELETE SET NULL`
   - Remove the "FK pending ID-type reconciliation" comment; replace with link to KBL-A brief §5
4. **Add the new `kbl_alert_dedupe` table** (KBL-A brief §5 introduces it — not in your current draft). Spec:
   ```sql
   CREATE TABLE IF NOT EXISTS kbl_alert_dedupe (
       alert_key   TEXT PRIMARY KEY,
       first_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       last_sent   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       send_count  INTEGER NOT NULL DEFAULT 1
   );
   ```
5. **Update header comment** at top of file: bump version to reflect this revision; reference KBL-A brief commit `942c347` as the canonical source.
6. **Commit + push.**

### Acceptance

- `briefs/_drafts/KBL_A_SCHEMA.sql` runs clean in a test transaction:
  ```bash
  psql $DATABASE_URL -c "BEGIN; \i briefs/_drafts/KBL_A_SCHEMA.sql; ROLLBACK;"
  ```
  Returns 0 exit, no constraint errors.
- File diff shows exactly: 2 type changes (BIGINT → INTEGER), 2 FK additions, 1 new table (`kbl_alert_dedupe`), header version bump, caveat comment removed.

### Report

When complete, reply with:

```
Schema reconciliation complete.
Commit: <SHA>
Changes:
- kbl_cost_ledger.signal_id: BIGINT → INTEGER + FK ON DELETE SET NULL
- kbl_log.signal_id: BIGINT → INTEGER + FK ON DELETE SET NULL
- NEW: kbl_alert_dedupe (alert_key PK, first_seen, last_sent, send_count)
- Header updated, "pending reconciliation" caveat removed
psql dry-run: <pass|fail>
Concerns: <none | list>
```

### Time budget

~15 minutes.

### What to do AFTER this task

Standing by. Next work likely depends on Code Brisen #1's R1 review verdict on KBL-A brief:
- **R1 clean →** Director ratifies KBL-A → dispatch implementation to you or B1
- **R1 has blockers →** wait for AI Head to revise v2
- **Director starts D1 eval labeling →** you might be asked to run `scripts/run_kbl_eval.py --compare-qwen` on macmini and report results

Check this file again after R1 review returns.

---

*Task posted by AI Head 2026-04-17. Overwritten when next task lands for Code Brisen #2.*
