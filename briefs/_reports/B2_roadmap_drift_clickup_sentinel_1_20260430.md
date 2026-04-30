# B2 Completion Report — ROADMAP_DRIFT_CLICKUP_SENTINEL_1

**Brief:** `briefs/BRIEF_ROADMAP_DRIFT_CLICKUP_SENTINEL_1.md`
**Branch:** `b2/roadmap-drift-clickup-sentinel`
**Builder:** B2
**Date:** 2026-04-30
**Reviewer:** AI Head A (solo, non-trigger-class)

## Summary

Daily 06:00 UTC sentinel that compares `_ops/processes/cortex-roadmap-current.yml` last-edit timestamp on baker-vault main against PR merge cadence on baker-vault + baker-master. If ≥5 PRs merged since the YAML touch → posts a comment on recurring ClickUp task `86c9k6kau` (Cortex Backlog list, BAKER space). Silent on no-drift. NO Slack — Director rule 2026-04-30.

## Files

| File | Status | Purpose |
|---|---|---|
| `orchestrator/roadmap_drift_sentinel.py` | **NEW** | Drift detection + ClickUp write |
| `triggers/embedded_scheduler.py` | modified | Added APScheduler job + lazy-import wrapper |
| `tests/test_roadmap_drift_sentinel.py` | **NEW** | 12 tests covering brief §"Test plan" (a)–(d) + lock contention |

## Coordination — advisory_lock key

Re-grepped `pg_try_advisory*` post-B3 PR #108 merge as instructed. Confirmed key registry:

```
8004     memory_consolidator           (xact)
8005     trend_detector                (xact)
867531   fireflies                     (session)
867532   plaud_trigger                 (session)
8800100  scheduler_lease               (session, singleton)
900100   risk_detector                 (xact)
900201   cadence_tracker               (xact)
900300   financial_detector            (xact)
900400   sentiment_scorer              (xact)
900500   convergence_detector          (xact)
900600   obligation_generator          (xact, also bridge tick)
900700   action_completion_detector    (xact)
900800   initiative_engine             (xact)  ← B3 PR #108 renumbered from 900300
900900   roadmap_drift_sentinel        (xact)  ← THIS BRIEF
```

`900900` is free. Locked.

## Implementation notes

1. **Pure helpers** (`get_yaml_last_edit`, `list_merged_prs_since`, `format_drift_comment`) are mockable + unit-testable in isolation. The runner just composes them and handles status reporting.
2. **GitHub auth:** reuses `GITHUB_TOKEN` (same PAT as `vault_mirror`). Headers include `Accept: application/vnd.github+json` + `X-GitHub-Api-Version: 2022-11-28`. Fails graceful on missing token (public PR list still works for `baker-master`; `baker-vault` PR fetch fails → `"pr_fetch_failed"`).
3. **PR pagination:** single page, `per_page=100`, `sort=updated direction=desc`. Drift threshold is 5, so even a months-stale YAML produces correct DRIFT verdict (100 ≥ 5).
4. **Filtering:** only PRs with non-null `merged_at` count (closed-without-merge ignored), and `merged_at > yaml_last_edit` (older PRs ignored). Both edge cases covered in tests.
5. **Advisory lock:** belt-and-suspenders only. The scheduler-singleton lock (`8800100`) already gates one job invocation per Render container. The xact-scoped `900900` adds a Postgres-level gate against a misconfigured manual `run_roadmap_drift_sentinel()` racing with the cron tick.
6. **ClickUp client:** uses `ClickUpClient._get_global_instance()` (the singleton). Did NOT call `reset_cycle_counter()` to avoid clobbering `clickup_trigger.run_clickup_poll`'s in-flight cycle counter. Worst case: another sentinel exhausts the 10-write-per-cycle cap → our comment fails today + retries tomorrow. Acceptable for a daily job.
7. **Sentinel-health reporting:** wired `report_success` / `report_failure` for each terminal status, mirroring `_run_movie_am_lint` / `_ai_head_weekly_audit_job` patterns.
8. **Env gate:** `ROADMAP_DRIFT_SENTINEL_ENABLED` (default `true`) for kill-switch without redeploy.
9. **Cron slot:** `0 6 * * *` UTC. Coexists with `daily_briefing` (also 06:00 UTC) and other Mon-only 06:00 UTC jobs — APScheduler `max_instances=1` + `coalesce=True` per job; jobs run on separate worker threads.
10. **Test path:** brief specified `tests/orchestrator/test_roadmap_drift_sentinel.py`. Repo convention is flat `tests/test_*.py` (no subdirectory exists). Filed at `tests/test_roadmap_drift_sentinel.py` to match convention. **Flag for AI Head A** — minor deviation from brief.

## Test plan results

```
$ .venv312/bin/pytest tests/test_roadmap_drift_sentinel.py -v
============================= test session starts ==============================
collected 12 items

tests/test_roadmap_drift_sentinel.py::test_format_drift_comment_deterministic_shape PASSED
tests/test_roadmap_drift_sentinel.py::test_format_drift_comment_handles_empty_repo_list PASSED
tests/test_roadmap_drift_sentinel.py::test_run_no_drift_below_threshold PASSED   # case (a)
tests/test_roadmap_drift_sentinel.py::test_run_drift_writes_clickup_comment PASSED   # case (b)
tests/test_roadmap_drift_sentinel.py::test_run_yaml_fetch_failure_no_clickup_write PASSED   # case (c-1)
tests/test_roadmap_drift_sentinel.py::test_run_pr_fetch_failure_no_clickup_write PASSED   # case (c-2)
tests/test_roadmap_drift_sentinel.py::test_run_clickup_post_failure_does_not_crash PASSED   # case (d-1)
tests/test_roadmap_drift_sentinel.py::test_run_clickup_post_raises_does_not_crash PASSED   # case (d-2)
tests/test_roadmap_drift_sentinel.py::test_run_skips_when_advisory_lock_contended PASSED
tests/test_roadmap_drift_sentinel.py::test_lock_key_is_900900 PASSED
tests/test_roadmap_drift_sentinel.py::test_drift_threshold_is_five PASSED
tests/test_roadmap_drift_sentinel.py::test_drift_task_id_is_recurring_clickup_task PASSED

============================== 12 passed in 0.87s ==============================
```

Singleton-pattern CI guard:

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

Pre-existing failures on `main` (unrelated, verified via stash):
- `tests/test_clickup_client.py::TestWriteSafety::*` (5) — stale tests; ClickUpClient relaxed BAKER-space-only rule on Director auth 2026-03-25
- `tests/test_clickup_integration.py::*` (3) — voyageai infra (VOYAGE_API_KEY unset locally)

## Manual smoke

Per brief §"Test plan" #3, manual smoke needs a Render shell or debug endpoint to fire `run_roadmap_drift_sentinel()` once and verify the comment appears on task `86c9k6kau`. **Not executed locally** — requires production Render env (GITHUB_TOKEN + CLICKUP_API_KEY) and would post a real comment to a live ClickUp task. **Recommend AI Head A run this once post-merge** via Render shell:

```python
from orchestrator.roadmap_drift_sentinel import run_roadmap_drift_sentinel
print(run_roadmap_drift_sentinel())
```

If current state has ≥5 PRs since YAML last edit → live comment lands on `86c9k6kau`. If <5 → `{"status": "no_drift", ...}` and no write.

## Done definition checklist

- [x] PR opened with code + tests
- [x] Pytest green (12/12 new tests pass; pre-existing failures unrelated)
- [x] Singleton CI guard green
- [ ] Manual smoke (deferred to AI Head A — Render shell needed)
- [ ] AI Head A reviews + merges (non-trigger-class)
