# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning)
**Status:** OPEN — PR #22 STORE_BACK_DEAD_CODE_AND_DB_ENV_FALLBACK review

---

## Task: PR #22 review

B2 shipped at `84f15db` on branch `store-back-dead-code-and-db-env-fallback`. Scope = Part A delete dead `_ensure_kbl_cost_ledger` + `_ensure_kbl_log` + callers + precedence comment; Part B `kbl/db.py` `_build_dsn()` with `DATABASE_URL` precedence + `POSTGRES_*` fallback + `quote_plus` on user/password. Brief: `briefs/_tasks/CODE_2_PENDING.md` head commit.

**PR URL:** https://github.com/vallen300-bit/baker-master/pull/22

### Verdict focus

**Part A — dead code removal:**

- `grep -rn "_ensure_kbl_cost_ledger\|_ensure_kbl_log" .` returns zero matches post-change (incl. tests).
- No OTHER `_ensure_*` method touched. Qdrant-collection ensures + signal_queue additions ensure etc. must still be intact.
- Precedence comment at ex-line 6379 removed (it named methods that no longer exist).
- Callers at ex-lines 193-194 removed from `__init__` or wherever they were called — no dangling `self.` reference.

**Part B — `kbl/db.py` env fallback:**

- `_build_dsn()` correctly prefers `DATABASE_URL` when set; falls back to `POSTGRES_*` split form only when `DATABASE_URL` is absent.
- Missing required `POSTGRES_*` var (HOST/USER/PASSWORD/DB) raises `RuntimeError` with clear message naming the missing keys. NOT a bare `KeyError`.
- `urllib.parse.quote_plus` applied to BOTH user and password fields — not just password. Passwords with `@`, `/`, `:`, `?` are common in cloud Postgres.
- `POSTGRES_PORT` defaults to `5432` when absent.
- Unit tests in `tests/test_kbl_db.py` cover at least: (a) DATABASE_URL wins, (b) split form builds expected URL with quote_plus applied, (c) missing required var raises clear error. B2 added a 4th default-port case — verify it's not over-fitting.

**Cross-cutting:**

- No schema changes.
- No Render env changes required to deploy.
- `pytest tests/` full suite: B2 flagged 10 failures in `tools/ingest/extractors.py` path as pre-existing py3.9 PEP-604 landmine, confirmed on pre-change tree. Spot-check one or two of those failures — confirm they are py3.9-only and unrelated to this PR.

### Output

Report to `briefs/_reports/B1_pr22_review_<YYYYMMDD>.md` — APPROVE / REDIRECT / REQUEST_CHANGES with inline citations to the PR head SHA. If APPROVE, AI Head auto-merges per Tier A protocol.

Expected time: 15-20 min.
