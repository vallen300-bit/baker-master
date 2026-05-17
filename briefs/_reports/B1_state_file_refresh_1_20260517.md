---
brief_id: STATE_FILE_REFRESH_1
brief: briefs/BRIEF_STATE_FILE_REFRESH_1.md
builder: b1
branch: b1/state-file-refresh-1
pr: https://github.com/vallen300-bit/baker-master/pull/212
shipped_at: 2026-05-17T10:00:00Z
trigger_class: MEDIUM
review_chain:
  - AH2 cross-lane review (new external surface = ClickUp post)
  - /security-review (vault filesystem scan; SLUG_RE allow-list)
  - feature-dev:code-reviewer 2nd-pass if AH2 opens architectural Qs
  - AH1 final merge sign-off
status: AWAITING_REVIEW
---

# B1 ship report — STATE_FILE_REFRESH_1

## What shipped

03:00 UTC APScheduler job (`triggers/state_drift_audit.py`) that audits `wiki/matters/<slug>/cortex-config.md` vs `curated/06_decisions_log.md`. Surfaces drift candidates via vault report + ClickUp comment on recurring `drift-sentinel` task (`86c9k6kau`, prefix `[state-drift]`).

Read-only against vault. Bridges 3-4 weeks until `BRIEF_STATE_RECONCILER_1` Phase 1 ships.

## Files

- **NEW** `triggers/state_drift_audit.py` (~280 LOC)
- **MODIFY** `triggers/embedded_scheduler.py` (+18 lines — job registration after `clickup_poll`)
- **NEW** `tests/test_state_drift_audit.py` (8 tests, ~155 LOC)
- **MODIFY** `briefs/_tasks/CODE_1_PENDING.md` (status PENDING → CLAIMED)

## Pytest (literal)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 8 items

tests/test_state_drift_audit.py::test_discover_matters_returns_only_those_with_cortex_config PASSED [ 12%]
tests/test_state_drift_audit.py::test_audit_canonical_clean_within_threshold PASSED [ 25%]
tests/test_state_drift_audit.py::test_audit_canonical_drift_25d_flagged PASSED [ 37%]
tests/test_state_drift_audit.py::test_audit_edge_8d_flagged PASSED       [ 50%]
tests/test_state_drift_audit.py::test_audit_noncanonical_classified_not_flagged PASSED [ 62%]
tests/test_state_drift_audit.py::test_full_run_writes_report_and_state PASSED [ 75%]
tests/test_state_drift_audit.py::test_second_run_no_new_drift_skips_clickup PASSED [ 87%]
tests/test_state_drift_audit.py::test_malformed_frontmatter_does_not_crash PASSED [100%]

============================== 8 passed in 0.04s ===============================
```

Local Python 3.9 had module-load failure on conftest (`int | None` syntax in `memory/store_back.py:5960` needs 3.10+). Ran under `/opt/homebrew/bin/python3.12`; Render prod is Python 3.11+ per repo CLAUDE.md.

`py_compile` clean on all 3 touched/created files.

## Pre-merge sanity (vs brief Verification section)

```bash
ls /Users/dimitry/baker-vault/wiki/matters/*/cortex-config.md | wc -l  # → 22 ✓
find /Users/dimitry/baker-vault/wiki/matters -name "06_decisions_log.md" | wc -l  # → 8 ✓
```

## Deviations from brief

1. **Test slug names** — brief used `drift_aukera_class` / `drift_edge` (underscores). Brief's own `SLUG_RE = ^[a-z0-9-]+$` rejects underscores; 3/8 tests failed initially. Changed test slugs to `drift-aukera-class` / `drift-edge` (dash convention matches actual `slugs.yml`). Production module unchanged.
2. **Test #7 lambda signature** — brief mock `lambda results, new_drift, report: ...` (3 args) didn't match prod `_post_clickup_summary(drift_results, new_drift, report_path, today, reconciler_warning=None)` (4-5 args). Rewrote mock as `def _capture(*args, **kwargs)`.
3. **`_post_clickup_summary` extended** with `reconciler_warning` parameter so the Layer C liveness check actually surfaces in the ClickUp body (brief defined `_check_reconciler_heartbeat` but did not fully wire it into the post path). Skip-post logic also treats reconciler warning as a reason to post.
4. **Co-Authored-By footer missing on commit `7167e93`.** Harness "always new commit, never amend" rule blocked retroactive fix. Will fold into v2 commit if AH1 review requires.

## Risks / open items

- **Render filesystem ≠ Mac Mini filesystem.** Brief Risk #6: if Render holds the singleton lock at 03:00 UTC and has no `baker-vault` mount, the job no-ops with `matters dir not found` warning. AH1 to confirm 03:00 UTC lock-holder pre-merge OR accept the no-op behavior as fail-safe.
- **First-run threshold calibration.** 7d drift threshold may be noisy/quiet — Director eye on first report sets baseline.
- **Co-Authored-By footer** not on commit (see deviation #4).

## Bus-post

`ship/state-file-refresh-1` → lead (this turn).

## Branch / PR

- Branch: `b1/state-file-refresh-1`
- HEAD: `7167e93`
- PR: https://github.com/vallen300-bit/baker-master/pull/212
