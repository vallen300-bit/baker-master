# B2 — REPORT_SUCCESS_ARITY_FIX_1 (ship + post-deploy)

**Dispatch:** bus #3292 from `lead` (GO), 2026-06-18. Diagnosis origin: SENTINEL_HEALTH_INFRA_DIAGNOSE_1 (#3281/#3289).
**PR:** #378 — merged to `main` as `e074c7c1`. Fix commit `6cba7205`.
**Branch:** `b2/report-success-arity-fix-1`.

## Change
`triggers/sentinel_health.py` — widened `def report_success(source: str)` →
`def report_success(source: str, payload: "dict | None" = None)`. Backward-compatible;
`payload` accepted and ignored (string annotation keeps Python 3.9 happy). Fixes all 4
two-arg callers at once:
- `orchestrator/roadmap_drift_sentinel.py:223` (`roadmap_drift_sentinel`)
- `triggers/embedded_scheduler.py:1515/1530/1550` (`wiki_lint`, `ao_pm_lint`, `movie_am_lint`)

The 1-arg caller (`embedded_scheduler.py:386` `waha_restart`) is preserved by the default.
PR #374 (`95a4f8b`) `last_error_msg = NULL` recovery-clearing preserved.

## Root cause (recap)
`report_success` took 1 positional arg; 4 sites passed a 2nd observability `payload`.
Each raised `TypeError` swallowed by the caller's bare `except`, so successes were silently
lost and any source that had ever failed stayed wedged `down` forever. `roadmap_drift_sentinel`
froze at its 2026-05-20 `clickup_post_failed` and showed `down` on `/api/health` for a month
despite the daily ClickUp post to `86c9k6kau` succeeding every day since.

## Test — `tests/test_report_success_arity.py`
```
4 passed in 0.03s   (python3.12)
```
- `test_signature_accepts_optional_payload`
- `test_two_arg_call_does_not_raise_and_writes_healthy` (asserts `status='healthy'` + `consecutive_failures = 0` + `last_error_msg = NULL`)
- `test_all_four_known_caller_shapes`
- `test_one_arg_call_still_works`

## Post-deploy AC — PASS (live evidence)
`GET /api/health` 2026-06-18: `roadmap_drift_sentinel` → `status=healthy`, `fail_count=0`,
`issue=""`, `last_poll=2026-06-18T06:00:04Z`. Self-healed on the first 06:00 run after
deploy, no manual DB write — exactly as diagnosed. Verdict posted to `lead` (#3319) cc
`deputy` (#3320), topic `post-deploy-ac/report-success-arity-fix-1`.

## Remaining (separate, not this brief)
`/api/health` overall still `degraded` — sole remaining genuine `down` is `todoist`
(401 Unauthorized since 2026-05-17, fail_count=18). That is SENTINEL_HEALTH_INFRA_DIAGNOSE_1
Sentinel-1: needs a new `TODOIST_API_TOKEN` from Director → Render env merge-PUT. No code
fix possible. Surfaced again in the #3319/#3320 `next_action`.

**Done rubric:** PR merged + pytest green + post-deploy AC verdict PASS posted. DONE.
