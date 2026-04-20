# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning, post-handover refresh)
**Status:** OPEN — CONFTEST_NEON_EPHEMERAL_FIXTURE polish

---

## Task: CONFTEST_NEON_EPHEMERAL_FIXTURE — unblock TEST_DATABASE_URL-gated tests in CI

Polish queue item #2 from AI Head handover 2026-04-20. Target PR: TBD. Branch: `conftest-neon-ephemeral-fixture`. Base: `main`. Reviewer: B2.

### Why

Several tests currently skip when `TEST_DATABASE_URL` is unset (`tests/test_migration_runner.py` Test #6 + Test #8, `tests/test_layer0_dedupe.py`, `tests/test_migrations.py`, `tests/test_status_check_expand_migration.py`). This means the **most load-bearing tests run only locally**, not in CI. Lesson #42 meta-pattern: "a claim that held locally but failed silently against production because nothing exercised the production code path in a gated way."

A pytest fixture that provisions an **ephemeral Neon branch** for a test session — then drops it at session end — closes this gap. Cheap (branches in Neon are copy-on-write; seconds to create; free up to limits) and means our live-PG round-trip tests run every PR.

### Scope

**New file: `tests/conftest.py`**

Session-scoped fixture `ephemeral_neon_db` that:

1. Reads `NEON_API_KEY` + `NEON_PROJECT_ID` from env. **If either is missing, yield `None` — DO NOT raise.** Tests must still SKIP locally without env set; fixture just provides the URL when CI does set them.
2. Calls Neon REST API (`POST https://console.neon.tech/api/v2/projects/{project_id}/branches`) to create a branch named `ci-pytest-<random-8>` from `main`.
3. Polls `GET /projects/{project_id}/branches/{branch_id}` until `primary_endpoint.current_state == "active"` (≤60s with 2s interval — fail test run if timeout).
4. Yields connection URL built from the branch's primary endpoint + project-level credentials.
5. Teardown: `DELETE /projects/{project_id}/branches/{branch_id}` — idempotent; log warn if 404/410.

**Then, in each affected test file:**

Replace
```python
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL unset ..."
)
```

with a new `needs_live_pg` fixture (also in conftest.py) that returns either `os.environ.get("TEST_DATABASE_URL")` or the ephemeral fixture's URL if Neon env is set — and skips otherwise.

**Four files to migrate:**

1. `tests/test_migration_runner.py` — Test #6 + Test #8
2. `tests/test_layer0_dedupe.py`
3. `tests/test_migrations.py`
4. `tests/test_status_check_expand_migration.py`

All four currently use the same pattern. Migration is mechanical.

### GitHub Actions wiring

Add env block to the pytest workflow (`.github/workflows/*.yml` — find the one that runs pytest):

```yaml
env:
  NEON_API_KEY: ${{ secrets.NEON_API_KEY }}
  NEON_PROJECT_ID: ${{ secrets.NEON_PROJECT_ID }}
```

**DO NOT commit Neon secrets to the repo.** Director adds them as GitHub repo secrets separately (Tier B — flag in PR description so Director knows to add them before merge). PR can merge with the env block present but secrets absent; tests will still skip locally-style on first run until secrets land — identical to today's behavior, just with the fixture infrastructure in place.

### Acceptance criteria

1. `tests/conftest.py` exists with two fixtures: `ephemeral_neon_db` (session-scoped) and `needs_live_pg` (function-scoped, depends on `ephemeral_neon_db` + `TEST_DATABASE_URL`).
2. All four test files use `needs_live_pg` instead of raw `TEST_DATABASE_URL` check. The skipif pattern is gone from those files.
3. Local run with neither env var set: all 4 test files skip (same behavior as today).
4. Local run with `TEST_DATABASE_URL` set: live-PG tests run (same as today).
5. CI run with `NEON_API_KEY` + `NEON_PROJECT_ID` secrets set: fixture provisions branch, live-PG tests run, branch dropped at end.
6. `pytest tests/ -xvs` full suite green locally.

### Out of scope

- Modifying existing test assertions.
- Running pytest-xdist / parallelization (branch-per-worker) — scope is one branch per session.
- Caching branches across CI runs — session-scoped, fresh each time.

### Trust markers (lesson #40)

- **What in production would reveal a bug:** a migration PR passes CI because the live-PG test was skipped. We caught this exact pattern tonight (lesson #35). Fixture closes it.
- **Risk:** if fixture implementation has a bug, CI either false-passes (bug) or false-fails (noise). Fixture MUST fail loud on any API error — never silently yield None except when env is missing by-design.

### PR message template

```
CONFTEST_NEON_EPHEMERAL_FIXTURE: auto-provision Neon branch for TEST_DATABASE_URL-gated CI tests

Closes lesson #35 + #42 failure mode: live-PG round-trip tests ran only locally,
never in CI. Fixture provisions an ephemeral Neon branch per pytest session,
yields its URL, drops the branch at teardown.

Migrates 4 test files (test_migration_runner.py, test_layer0_dedupe.py,
test_migrations.py, test_status_check_expand_migration.py) from raw
TEST_DATABASE_URL skipif to a `needs_live_pg` fixture that unifies the two
sources.

Requires Director to add NEON_API_KEY + NEON_PROJECT_ID as GitHub secrets
before CI picks up the coverage. Without them, tests skip (same behavior as
today) — safe to merge pre-secrets.

Co-Authored-By: AI Head <ai-head@brisengroup.com>
```

Expected time: 60-90 min (substantive, single task). Ping B2 for review when CI green.
