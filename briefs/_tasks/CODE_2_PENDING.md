# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning)
**Status:** OPEN — PR #21 review, then queued PR #23 review

---

## Task 1 (NOW): PR #21 DASHBOARD_COST_ALIAS_RENAME review

B1 shipped at `6198feb` on branch `dashboard-cost-alias-rename`. Scope = rename SQL alias `total_usd` → `total_eur` in `/api/kbl/cost-rollup` endpoint of `outputs/dashboard.py` (around line 10926) + `ORDER BY` + downstream Python consumer + `app.js` consumer + 3 test fixture refs + 1 assertion. Column name `cost_usd` unchanged.

**PR URL:** https://github.com/vallen300-bit/baker-master/pull/21

### Verdict focus

- `grep -n 'total_usd' outputs/dashboard.py` inside the cost-rollup endpoint: zero matches post-change. Other endpoints left alone.
- JS consumer in `outputs/templates/` (or wherever the frontend reads the JSON) updated — no `data.total_usd` references left that feed the cost widget.
- 3 test fixture refs + 1 assertion update present — verify assertions actually key on the new `total_eur` name.
- `pytest tests/test_dashboard_kbl_endpoints.py -xvs` reported green by B1 (9/9). Re-run locally.
- Header still says `€` in the frontend template — cosmetic guard against accidentally flipping the currency label.
- Schema untouched.

Report to `briefs/_reports/B2_pr21_review_<YYYYMMDD>.md` — APPROVE / REDIRECT / REQUEST_CHANGES. If APPROVE, AI Head auto-merges.

Expected: 10-15 min.

---

## Task 2 (QUEUED, do after Task 1 + after B3 reports CI-workflow-drop on PR #23 branch): PR #23 CONFTEST_NEON_EPHEMERAL_FIXTURE review

B3 shipped at `c7f1381` on branch `conftest-neon-ephemeral-fixture`. Scope = new `tests/conftest.py` with `ephemeral_neon_db` (session, urllib-only) + `needs_live_pg` (function) fixtures; 4 test files migrated off raw `TEST_DATABASE_URL` skipif. Brief: `briefs/_tasks/CODE_3_PENDING.md` head commit.

**PR URL:** https://github.com/vallen300-bit/baker-master/pull/23

### Important — DO NOT start this review until:

1. Task 1 (PR #21 review) complete.
2. B3 has pushed a follow-up commit to the same branch dropping `.github/workflows/pytest.yml` (the workflow scope was too wide — fires entire test suite against no-secrets CI; 40s failure on first run). AI Head dispatched B3 separately for this drop. You'll see a new commit on top of `c7f1381` authored by B3 before this task becomes actionable.
3. The branch's latest CI run is absent (workflow file deleted) or green.

### Verdict focus (once unblocked)

- `tests/conftest.py` has two fixtures: `ephemeral_neon_db` session-scoped with `NEON_API_KEY` + `NEON_PROJECT_ID` check yielding `None` when absent (no raise); `needs_live_pg` function-scoped returning `TEST_DATABASE_URL` > ephemeral URL > skip.
- Neon REST API calls use `urllib.request` only — no new dependency added.
- Branch creation `POST /api/v2/projects/{id}/branches`, poll until `primary_endpoint.current_state == "active"` with ≤60s deadline + 2s interval, teardown `DELETE` is idempotent (404/410 logged as WARN not ERROR).
- 4 test files migrated: `test_migration_runner.py`, `test_layer0_dedupe.py`, `test_migrations.py`, `test_status_check_expand_migration.py`. The raw `TEST_DATABASE_URL` skipif pattern is GONE from all 4. Each now uses `needs_live_pg`.
- Local `pytest tests/` reported 43 passed, 5 skipped by B3 with unified skip message — verify one of the 5 skips emits the expected "no live-PG connection available" text (not the old raw "TEST_DATABASE_URL unset" text).
- The `.github/workflows/pytest.yml` file is ABSENT from the final branch head (verify with `git ls-tree HEAD .github/workflows/`).

Report to `briefs/_reports/B2_pr23_review_<YYYYMMDD>.md`. APPROVE / REDIRECT / REQUEST_CHANGES.

Expected: 20-30 min.
