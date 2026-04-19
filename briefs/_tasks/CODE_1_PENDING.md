# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening, post-migrations-apply)
**Status:** OPEN — tiny hotfix PR

---

## Task: KBL_DASHBOARD_COST_ROLLUP_HOTFIX — `created_at` → `ts` column rename in 2 SQL queries

### Context

AI Head just applied `kbl_cost_ledger` to production (migration file `migrations/20260419_add_kbl_cost_ledger_and_kbl_log.sql`, committed + pushed). Post-apply dashboard test found one remaining bug: `/api/kbl/cost-rollup` queries reference column `created_at`, but `kbl_cost_ledger` has column name `ts` (per `store_back.py` canonical definition and B2's sanity-check report).

B2's review file at `briefs/_reports/B2_kbl_migrations_sanity_20260419.md` already flags this: *"kbl_cost_ledger.ts (not created_at) is already correctly indexed via ((ts::date)) for the daily-window query."* PR #17 shipped with the wrong column reference; tests used fixtures so B2's PR review couldn't catch it.

### Scope

Two-line SQL fix in `outputs/dashboard.py`, lines 10887 and 10897:

**Before:**
```python
WHERE created_at > NOW() - INTERVAL '24 hours'
```

**After:**
```python
WHERE ts > NOW() - INTERVAL '24 hours'
```

Both occurrences inside `kbl_cost_rollup()` endpoint (lines 10866-10911).

### Audit for siblings

While you're in there, grep `outputs/dashboard.py` for any OTHER `kbl_cost_ledger` query — if there's one I missed, apply the same `created_at` → `ts` rename. Also grep every SELECT/INSERT/WHERE touching `kbl_log` and `kbl_cost_ledger` to ensure no other drift (column names in those tables are `ts` not `created_at`, `message` not `body`, `component` not `source`).

### Tests

Add/update one test in `tests/test_dashboard_kbl_endpoints.py`:
- `test_cost_rollup_against_real_table_shape` — use a real table (not fixture), insert one row via `ts=NOW()`, call the endpoint, assert response shape + value. This exercises the actual column name against actual Neon schema and prevents future drift from passing CI.

Alternative if test fixture infra doesn't easily allow real-table testing: update existing `test_kbl_cost_rollup_*` fixtures to use `ts` column name (matches what will actually be in production). Note the gap remains though — fixture-only testing won't catch schema drift.

### Delivery

- New branch `kbl-cost-rollup-hotfix`.
- PR title: `KBL_DASHBOARD_COST_ROLLUP_HOTFIX: rename created_at → ts to match kbl_cost_ledger schema`.
- Target PR: #19.
- Reviewer: B2.
- ~10-15 min.

### Dispatch back

> B1 KBL_DASHBOARD_COST_ROLLUP_HOTFIX shipped — PR #19 open, branch kbl-cost-rollup-hotfix, head <SHA>, tests green. Fixed 2 lines in outputs/dashboard.py; grepped for other drift (found 0 / found X other matches). Ready for B2 review.

---

## Working-tree reminder

Work in `~/bm-b1`. Quit Terminal tab after PR opens — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Tiny hotfix, clean process (not direct push) to keep reviewer-separation matrix intact. Also preserves audit trail: this bug was born in PR #17 merge, died in PR #19 merge.*
