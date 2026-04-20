# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning, post-handover refresh)
**Status:** OPEN — STORE_BACK_DEAD_CODE_AND_DB_ENV_FALLBACK polish

---

## Task: STORE_BACK_DEAD_CODE_AND_DB_ENV_FALLBACK — two small Python cleanups

Polish queue items #4 + #5 from AI Head handover 2026-04-20. Target PR: TBD. Branch: `store-back-dead-code-and-db-env-fallback`. Base: `main`. Reviewer: B1.

### Why

Two independent leftovers from the MIGRATION_RUNNER_1 + cost_ledger shipping cycle. Both are lesson #36 (DATABASE_URL vs POSTGRES_* env drift) / #37 (DDL embedded in `_ensure_*` never runs on Render) countermeasures. Close them while the context is fresh.

---

### Part A — Delete dead `_ensure_kbl_cost_ledger` + `_ensure_kbl_log` from `memory/store_back.py`

**Files:**
- `memory/store_back.py`

**Current state (verified by AI Head against tip of main):**
- Line 193: `self._ensure_kbl_cost_ledger()` (caller)
- Line 194: `self._ensure_kbl_log()` (caller)
- Line 6505: `def _ensure_kbl_cost_ledger(self):` (definition with bare `((ts::date))` immutability bug — lesson #38)
- Line 6552: `def _ensure_kbl_log(self):` (definition with same bug)
- Line 6379: comment `MUST run before _ensure_kbl_cost_ledger / _ensure_kbl_log because …`

**Why dead:** DDL for both tables now lives in `migrations/20260419_add_kbl_cost_ledger_and_kbl_log.sql` (grandfathered in runner). The `_ensure_*` methods never ran on Render (wrong code path — lesson #37), only on Mac Mini. Mac Mini schema matches Render after MIGRATION_RUNNER_1. No remaining caller needs them.

**Actions:**

1. Delete both method definitions (around lines 6505-6551 and 6552-~6600 — find exact ranges).
2. Delete both call sites (lines 193-194).
3. Delete the precedence comment at line 6379 (it references methods that will no longer exist).
4. Grep the full repo for `_ensure_kbl_cost_ledger` and `_ensure_kbl_log` after deletion — should return zero matches.

**Non-negotiable:** DO NOT touch any other `_ensure_*` method in the file — several ARE still live (e.g. Qdrant collection ensures). Scope is exactly these two.

**Acceptance:**
- `grep -rn "_ensure_kbl_cost_ledger\|_ensure_kbl_log" .` returns zero matches (including tests).
- `pytest tests/test_1m_storeback_verify.py -xvs` green. If a test calls either method, DELETE the test (it's also dead).
- `pytest tests/ -xvs` full suite green.

---

### Part B — Add `POSTGRES_*` split env fallback to `kbl/db.py`

**File:** `kbl/db.py` (currently ~32 lines; short module).

**Current state:**
```python
conn = psycopg2.connect(os.environ["DATABASE_URL"])
```

Fails hard if only the split form (`POSTGRES_HOST` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT`) is set. Render uses `DATABASE_URL`; Mac Mini's `~/.kbl.env` uses split form. Env-convention drift has already burned us once (lesson #36, PR #19 hotfix).

**Change:**

```python
def _build_dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    required = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"neither DATABASE_URL nor POSTGRES_* fallback available; missing: {missing}"
        )
    host = os.environ["POSTGRES_HOST"]
    user = os.environ["POSTGRES_USER"]
    pw = os.environ["POSTGRES_PASSWORD"]
    db = os.environ["POSTGRES_DB"]
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"
```

Then `get_conn()` calls `psycopg2.connect(_build_dsn())`.

**URL-quote the password** (use `urllib.parse.quote_plus`) to handle special chars. Add one unit test for `_build_dsn()` covering: (a) DATABASE_URL wins when both are set, (b) split form builds expected URL, (c) missing split var raises clear error.

**Acceptance:**
- New file (or addition to existing) `tests/test_kbl_db.py` with the three cases above.
- Existing KBL tests still green.
- No runtime behavior change on Render (where DATABASE_URL is set).

---

### Out of scope for this PR

- Any `kbl_cost_ledger` or `kbl_log` schema change.
- Migrating other modules to the fallback pattern (separate PR per module to keep review cycles small).
- Rotating / adding env vars on Render or Mac Mini.

### PR message template

```
STORE_BACK_DEAD_CODE_AND_DB_ENV_FALLBACK: remove two dead _ensure_* methods + add POSTGRES_* fallback to kbl/db.py

Part A: DDL for kbl_cost_ledger + kbl_log now lives in the migration file
(grandfathered in MIGRATION_RUNNER_1). The `_ensure_*` methods were dead path
(lesson #37). Delete both + their callers + dependent tests.

Part B: kbl/db.py hard-required DATABASE_URL. Add POSTGRES_* split-form
fallback so Mac Mini dev envs work without DATABASE_URL re-export (lesson #36).
URL-quotes password. Three-case unit test added.

No schema changes. No env changes on Render.

Co-Authored-By: AI Head <ai-head@brisengroup.com>
```

Expected time: 30-45 min. Ping B1 for review when CI green.
