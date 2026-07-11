# B2 SHIP REPORT — STARTUP_NOISE_DEADLINES_VIP_FIX_1

- **Date:** 2026-06-16
- **PR:** #370 (branch `b2/startup-noise-deadlines-vip-fix-1`, base `main`)
- **Brief:** `briefs/_tasks/CODE_2_PENDING.md` (dispatched by lead, commit e2c115f)
- **Bus:** gate-request #3128 → lead (topic `gate-request/pr370`)
- **Status:** shipped, awaiting codex G3 + lead merge

## Defect
`models/deadlines.py` runtime bootstrap (`ensure_tables()` + `seed_vip_contacts()` at
module load) logged two ERROR-level lines on every boot.

## Root cause — confirmed against the live prod schema (read-only via baker_raw_query)
Two independent ERROR sources, both firing every boot:

1. **`ensure_tables()`** ran `CREATE OR REPLACE VIEW contacts AS SELECT * FROM vip_contacts`
   unconditionally. In production `contacts` is now an **independent table** (people-intel,
   673 rows / 19 cols), not a view → `ERROR: "contacts" is not a view` every boot.
2. **`seed_vip_contacts()`** wiped + reseeded whenever `count != 11`. `vip_contacts` is the
   live contacts store (**531 rows**, 29 cols), referenced by two FKs:
   `contact_interactions.contact_id` (5193 rows, 135 distinct contacts) and
   `trip_contacts.contact_id`. The count was never 11 → `DELETE FROM vip_contacts` fired
   every boot → **rejected by the FK** → ERROR. The FK was the only thing preventing the
   DELETE from destroying 520 real contacts with interaction history.

The brief's static grep found no in-repo FK because both FKs were added out-of-band
(people-intel / trips features); only reading the live schema surfaced them.

## Fix (surgical — `models/deadlines.py` only, no migration)
1. Gate the compatibility view behind `to_regclass('public.contacts')` — create the view
   only when no `contacts` relation exists (fresh DB). Production skips it.
2. Replace DELETE-then-reinsert with an **idempotent per-row upsert keyed on `email`**:
   UPDATE in place; INSERT only when a seed VIP is missing. Never DELETEs; never touches
   the other contacts. No UNIQUE constraint / migration added — 482/531 rows have NULL
   email and non-null emails contain duplicates, so a unique constraint would fail, and any
   DELETE re-introduces the FK error.
3. Added `conn.rollback()` in the except before logging (python-backend rule); preserved
   the existing fault-tolerant try/except.

## Evidence — reproduced locally against PostgreSQL 16 (prod-like state)
**Before** (current code, repeats every boot):
```
ERROR baker.models.deadlines: deadlines: table creation failed: "contacts" is not a view
ERROR baker.models.deadlines: deadlines: VIP seed failed: update or delete on table "vip_contacts" violates foreign key constraint "contact_interactions_contact_id_fkey" on table "contact_interactions"
```
**After** (fixed, every boot):
```
INFO baker.models.deadlines: deadlines: tables verified (deadlines, vip_contacts)
```
Integrity verified: 0 rows deleted, FK-referenced row preserved, `contacts` table untouched
(`relkind=r`), a deleted seed VIP correctly re-inserted (exactly 1), idempotent on re-run.

## Gates
- **AC2:** clean boot — zero ERROR lines from `models/deadlines.py`. ✅ (before/after above)
- **G1:** `tests/test_vip_seed_boot_noise.py` (new, live-PG gated, isolated schema) — 2 passed
  against local PG, skips cleanly without a DB. Deadline/VIP modules: 67 passed, 8 skipped.
  Wider local suite has 233 pre-existing failures — environment-only (missing optional `mcp`
  dep, no live PG/network); identical with this change reverted (verified by stash baseline).
  **Zero failures introduced by this PR.**
- **Syntax check:** clean.
- **G3:** codex gate requested (bus #3128). Pending.
- **Post-deploy:** will emit `POST_DEPLOY_AC_VERDICT v1` covering AC2 after merge.

## Scope discipline
Touched only `models/deadlines.py` + new test. No applied-migration edits. b1 owns the
`/api/memory/health` endpoint (separate brief).
