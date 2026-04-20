# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning, post-handover refresh)
**Status:** OPEN — DASHBOARD_COST_ALIAS_RENAME polish

---

## Task: DASHBOARD_COST_ALIAS_RENAME — rename `total_usd` → `total_eur` in dashboard cost-rollup

Polish queue item #6 from AI Head handover 2026-04-20. Target PR: TBD. Branch: `dashboard-cost-alias-rename`. Base: `main`. Reviewer: B2.

### Why

`outputs/dashboard.py:10926` aliases `COALESCE(SUM(cost_usd), 0) AS total_usd` in the `/api/kbl/cost-rollup` endpoint, but **`cost_usd` ledger column stores EUR values per the same module's contract** (see comment at line 10913). Frontend formats the number with €. The `_usd` suffix is a cosmetic drift left over from pre-cost_ledger code and invites future misreads. Align the alias name with the actual currency so whoever reads the SQL next doesn't misinterpret it.

**Scope is the ALIAS only — not the column name.** `cost_usd` is a schema column across multiple modules; renaming the column is out of scope for this PR.

### Scope

**In scope:**

1. `outputs/dashboard.py` — change `AS total_usd` to `AS total_eur` on the SQL alias (around line 10926).
2. Same query (around line 10932): `ORDER BY total_usd DESC` → `ORDER BY total_eur DESC`.
3. Downstream Python reader: any `row["total_usd"]` / `row.get("total_usd")` / dict-access in the same function that consumed the alias must be updated to `total_eur`.
4. Frontend consumer: if any JS in `outputs/templates/` or equivalent reads `total_usd` from the JSON response for the `/api/kbl/cost-rollup` endpoint, update to `total_eur`.

**Out of scope:**

- Renaming `cost_usd` ledger column (schema change — separate migration, Tier B).
- Renaming any OTHER `total_usd` aliases (grep the file; if they exist in different endpoints, scope is this endpoint only unless they also store EUR per the contract comment).
- Touching `kbl_cost_ledger` migration.

### Acceptance criteria

1. `grep -n 'total_usd' outputs/dashboard.py` inside the cost-rollup endpoint returns zero matches after the change. (Matches outside cost-rollup are fine if they truly refer to USD values — which they shouldn't, per the contract, but scope is one endpoint.)
2. Manual smoke: `curl -sS https://baker-master.onrender.com/api/kbl/cost-rollup -H "X-Baker-Key: ..."` returns shape with `total_eur` key (not `total_usd`). Test against local preview if you have one; otherwise rely on B2 review + post-merge verification.
3. `pytest tests/test_dashboard_kbl_endpoints.py -xvs` green. If a test asserts on `total_usd` key, update the assertion in the same PR.
4. No schema changes. No migration file added.

### Trust markers (lesson #40)

- **What in production would reveal a bug:** frontend cost widget either breaks (key not found) or silently misreports in the wrong currency label. Post-merge verification: open the dashboard cost widget and confirm the number still renders AND the header still says €.
- **Risk of silent breakage:** medium. Any consumer reading `total_usd` that we miss will KeyError on next request.

### PR message template

```
DASHBOARD_COST_ALIAS_RENAME: align cost-rollup SQL alias with actual EUR currency

The `cost_usd` ledger column stores EUR (contract comment at line 10913). The
`AS total_usd` alias was cosmetic drift inviting future misreads. Rename the
alias and all downstream consumers within this endpoint to `total_eur`.

Scope limited to one endpoint + its Python + frontend consumers. Column name
`cost_usd` stays — schema rename is Tier B and separate.

Co-Authored-By: AI Head <ai-head@brisengroup.com>
```

Expected time: 20-30 min including verification. Ping B2 for review when CI green.
