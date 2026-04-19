# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening)
**Status:** OPEN — production migration apply, P0 unblocker

---

## Task: KBL_MIGRATIONS_APPLY_P1 — apply 9 missing migrations + 3 PR #16 ALTERs to production Neon

### Context

Shadow mode flipped at ~18:17. AI Head discovered during dashboard verification that the production Neon DB is in **KBL-A schema state**, not KBL-B. 9 migration files in `migrations/` were shipped-but-never-executed on production. Consequence: `signal_queue` has 25 columns (should be ~35+), and critical tables `kbl_cost_ledger`, `kbl_cross_link_queue`, `kbl_log`, `kbl_feedback_ledger` are missing. Every pipeline step past Step 1 would explode on first signal.

**No active damage** — signal_queue is empty; pipeline_tick is no-op'ing cleanly. Apply window is wide open.

Director authorized via "yes" at 2026-04-19 evening in response to AI Head's "Shall I apply the 9 migrations + 3 ad-hoc ALTERs?" This is a Tier B action under the bank-model rule (`feedback_ai_head_communication.md`).

### Scope

Apply, in this exact order, to production Neon (via `DATABASE_URL` — available on Render env or Mac Mini `~/.kbl.env`; `op` fetch from 1Password also works):

1. `migrations/20260418_expand_signal_queue_status_check.sql`
2. `migrations/20260418_loop_infrastructure.sql`
3. `migrations/20260418_step1_signal_queue_columns.sql`
4. `migrations/20260418_step2_resolved_thread_paths.sql`
5. `migrations/20260418_step3_signal_queue_extracted_entities.sql`
6. `migrations/20260418_step4_signal_queue_step5_decision.sql`
7. `migrations/20260419_step5_signal_queue_opus_draft.sql`
8. `migrations/20260419_step6_kbl_cross_link_queue.sql`
9. `migrations/20260419_step6_signal_queue_final_markdown.sql`

(`20260419_mac_mini_heartbeat.sql` is already applied — do NOT re-run; it IS idempotent, but skip for clarity.)

Then apply these 3 ad-hoc `ALTER TABLE` statements that PR #16 Step 7 normally adds at first invocation (`kbl/steps/step7_commit.py:253`). Pre-applying unblocks the dashboard `/silver-landed` endpoint before the first signal reaches Step 7:

```sql
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS target_vault_path TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS commit_sha TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ;
```

### Execution pattern

```bash
# Fetch DATABASE_URL from Mac Mini env (cleanest source; or pull from Render API via 1Password):
DATABASE_URL=$(ssh macmini 'grep "^export DATABASE_URL=" ~/.kbl.env | sed "s/^export DATABASE_URL=//;s/^\"//;s/\"$//"')

# Apply each migration with transaction + verification:
for f in \
  migrations/20260418_expand_signal_queue_status_check.sql \
  migrations/20260418_loop_infrastructure.sql \
  migrations/20260418_step1_signal_queue_columns.sql \
  migrations/20260418_step2_resolved_thread_paths.sql \
  migrations/20260418_step3_signal_queue_extracted_entities.sql \
  migrations/20260418_step4_signal_queue_step5_decision.sql \
  migrations/20260419_step5_signal_queue_opus_draft.sql \
  migrations/20260419_step6_kbl_cross_link_queue.sql \
  migrations/20260419_step6_signal_queue_final_markdown.sql; do
    echo "=== applying $f ==="
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f" || { echo "FAILED: $f"; exit 1; }
done

# Apply 3 ad-hoc PR #16 ALTERs:
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS target_vault_path TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS commit_sha TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ;
SQL
```

### Post-apply verification (paste output into report)

```sql
-- All expected KBL tables present?
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' AND (table_name LIKE 'kbl_%' OR table_name IN ('signal_queue','mac_mini_heartbeat'))
ORDER BY table_name;

-- signal_queue column inventory (should be ~35+)
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema='public' AND table_name='signal_queue'
ORDER BY ordinal_position;

-- kbl_cost_ledger exists + shape
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema='public' AND table_name='kbl_cost_ledger'
ORDER BY ordinal_position;

-- kbl_cross_link_queue exists + shape
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema='public' AND table_name='kbl_cross_link_queue'
ORDER BY ordinal_position;

-- CHECK constraint values on signal_queue.status (should be 34)
SELECT pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid='signal_queue'::regclass AND contype='c';
```

### Expected tables post-apply

`kbl_alert_dedupe`, `kbl_cost_ledger`, `kbl_cross_link_queue`, `kbl_feedback_ledger` (if in loop_infrastructure), `kbl_log` (if separate), `kbl_runtime_state`, `mac_mini_heartbeat`, `signal_queue`. Report any discrepancy — if loop_infrastructure doesn't create feedback_ledger/log, flag for Director (CHANDA §2 Leg 2 depends on feedback_ledger).

### Hard constraints

- **Read-only on existing data.** Every migration uses `IF NOT EXISTS`; re-runs are no-ops. Zero risk of data loss on existing rows.
- **Do not touch code** — this is a DB-only operation. No code change, no PR.
- **Do not push to repo** — report is the deliverable, not a commit.
- **One script, one transaction per migration** — `-v ON_ERROR_STOP=1` halts on first error. Do NOT batch all 9 into a single transaction; if one fails mid-way we need the prior successes persisted.

### Deliverable

Short report at `briefs/_reports/B1_kbl_migrations_apply_20260419.md` containing:
- Timestamp of apply.
- `psql` exit code per file (expect 0 / 0 / 0...).
- The 5 post-apply verification query results (table list + signal_queue columns + kbl_cost_ledger shape + kbl_cross_link_queue shape + CHECK constraint).
- Any discrepancies flagged.
- Dispatch-back one-liner.

### Timeline

~15-25 min. Most of it is pasting verification output.

### Reviewer

B2 — sanity-check schema matches expected (B2's mailbox has the parallel task queued).

### Dispatch back

> B1 KBL_MIGRATIONS_APPLY_P1 shipped — report at briefs/_reports/B1_kbl_migrations_apply_20260419.md, commit <SHA>. 9 migrations + 3 ALTERs applied, all psql exit 0. signal_queue now has <N> columns, kbl_cost_ledger + kbl_cross_link_queue present, CHECK constraint shows 34 values. Ready for B2 sanity-check.

---

## Working-tree reminder

Work in `~/bm-b1`. Quit tab after apply + report push — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Discovered during post-flip dashboard verification. Director-authorized Tier B action delegated to B1 per new economize-AI-Head-tokens rule.*
