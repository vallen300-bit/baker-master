# B4 Ship Report — BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1 (V0.2)

**Date:** 2026-05-05
**Builder:** B4
**Brief:** baker-master `briefs/BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1.md` (V0.2 amendment, Director-ratified 2026-05-05)
**Status:** SHIPPED — 3 PRs open, awaiting 4-gate review chain.

---

## PRs

| Repo | PR | Branch | Files | Net | Tests |
|---|---|---|---|---|---|
| brisen-lab | [#3](https://github.com/vallen300-bit/brisen-lab/pull/3) | `b4/brisen-lab-surface-6a-partial-unique-index-1` | db.py, bus.py, conftest.py, +test | +234 / -1 | 4 new (40 passed, 1 skipped overall) |
| baker-master | [#161](https://github.com/vallen300-bit/baker-master/pull/161) | `b4/baker-master-surface-6a-hook-retry-1` | hook + test | +132 / -12 | 3 new (33 passed overall) |
| baker-vault | [#85](https://github.com/vallen300-bit/baker-vault/pull/85) | `b4/baker-vault-surface-6a-cutover-runbook-1` | runbook | +143 / -0 | n/a (docs) |

**Merge order (mandatory):** brisen-lab #3 → baker-master #161 → baker-vault #85 (any time).

---

## Acceptance criteria (V0.2 amendment)

| AC | Description | Status |
|---|---|---|
| A1' | `SCHEMA_V2_SQL` contains UNIQUE index + DROP INDEX of old | ✅ db.py edited inline |
| A2 | UniqueViolation caught + returns 409 | ✅ bus.py + import added |
| A3 | 4 regression tests GREEN | ✅ literal pytest below |
| A4 | brisen-lab full suite GREEN (no regressions) | ✅ 40 passed, 1 skipped |
| A5 | feature-dev:code-reviewer pass | ⏳ awaiting AH1 |
| A6 | Cutover runbook landed in baker-vault | ✅ PR #85 |
| A7 | `BRISEN_LAB_V2_ENABLED=false` UNCHANGED on Render | ✅ not touched |
| A8' | Post-deploy schema verify (`\d` shows UNIQUE) | ⏳ post-merge step (cutover §1) |
| A9' | Post-deploy duplicate-detect SELECT returns 0 rows | ⏳ post-merge step (cutover §1) |
| A10 | Hook retry-on-409 lands in baker-master | ✅ PR #161 |
| A11' | Bootstrap-pattern rollback documented | ✅ runbook §4 |
| A12 | 409 observability emits to stderr | ✅ bus.py print line + AC test verifiable post-deploy |

A1, A8, A9, A11 dropped per V0.2 amendment (migration-runner-specific). A8'/A9'/A11' replace.

---

## Literal pytest output (Lesson #52)

### brisen-lab — Surface 6a tests only

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b4-brisen-lab
plugins: mock-3.15.1, asyncio-1.3.0, anyio-4.13.0
collected 4 items

tests/test_surface6a_partial_unique_index.py::test_concurrent_registration_only_one_winner PASSED [ 25%]
tests/test_surface6a_partial_unique_index.py::test_sequential_registration_succeeds PASSED [ 50%]
tests/test_surface6a_partial_unique_index.py::test_different_workers_no_conflict PASSED [ 75%]
tests/test_surface6a_partial_unique_index.py::test_partial_unique_index_rejects_second_active_row PASSED [100%]

=================== 4 passed, 2 warnings in 69.30s (0:01:09) ===================
```

### brisen-lab — full regression suite

```
collected 41 items

tests/test_a10_a14_lifecycle.py .....                                    [ 12%]
tests/test_a13_otel.py ..                                                [ 17%]
tests/test_a1_routes.py .                                                [ 19%]
tests/test_a21_h7_auth.py ......s.                                       [ 39%]
tests/test_a2_schema.py ......                                           [ 53%]
tests/test_a3_a8_a9_bus.py ......                                        [ 68%]
tests/test_review_fixes_2026_05_05.py .....                              [ 80%]
tests/test_surface6_session_keys_cleanup.py ....                         [ 90%]
tests/test_surface6a_partial_unique_index.py ....                        [100%]

============ 40 passed, 1 skipped, 2 warnings in 307.03s (0:05:07) =============
```

### baker-master — hook tests (target suite for the hook change)

```
collected 33 items

tests/test_brisen_lab_user_prompt_submit_hook.py::test_v2_disabled_silent_noop PASSED [  3%]
tests/test_brisen_lab_user_prompt_submit_hook.py::test_v2_enabled_unset_silent_noop PASSED [  6%]
tests/test_brisen_lab_user_prompt_submit_hook.py::test_non_ah_roles_skip_auth_chain[b1] PASSED [  9%]
… (29 more passed) …
tests/test_brisen_lab_user_prompt_submit_hook.py::test_register_409_retried_once_then_succeeds PASSED [ 54%]
tests/test_brisen_lab_user_prompt_submit_hook.py::test_register_409_twice_fails_open_no_jwt PASSED [ 57%]
tests/test_brisen_lab_user_prompt_submit_hook.py::test_register_500_no_retry_immediate_fail_open PASSED [ 60%]
… …
============================== 33 passed in 0.13s ==============================
```

---

## Notes

- 20× concurrent loop with `threading.Barrier(2)` proved deterministic — observed both `(200, 200)` (serialized) and `(200, 409)` (race-loser caught by index) outcomes, never duplicate active rows.
- Bootstrap-pattern verified by re-running `db.bootstrap()` between every iteration via `_wipe_session_keys()` helper — index re-applies idempotently.
- Hook retry tests stub `time.sleep` via `monkeypatch.setattr(hook_mod.time, "sleep", lambda *_: None)` so the 50–150ms jitter doesn't slow the suite.

## Cross-repo notes

- baker-vault checkout was on a stale `b3/bb-finance-ben-phase0-install-1` branch when I opened the session (peer agent had switched it). Recovered via `git fetch origin main && git checkout main && git pull --ff-only && git checkout -b b4/baker-vault-surface-6a-cutover-runbook-1`. Mid-session a sibling switched it back to main; I switched back to my b4 branch (staged file preserved) and committed cleanly. Lesson #57 (baker-vault shared-FS race) — confirmed still in effect; per-agent worktree fix still parked.

---

## 4-gate review chain (per brief)

1. ✅ Live pytest GREEN both repos (this report)
2. ⏳ AH2 `/security-review`
3. ⏳ Architect spot-check
4. ⏳ `feature-dev:code-reviewer` 2nd-pass

Awaiting AH1 dispatch of gates 2-4.
