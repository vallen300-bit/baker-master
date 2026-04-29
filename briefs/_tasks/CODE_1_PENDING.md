# CODE_1 — DISPATCH (CORTEX_MANUAL_INVOKE_1)

**Status:** PENDING — B1 build
**Brief:** `briefs/BRIEF_CORTEX_MANUAL_INVOKE_1.md`
**From:** AI Head A (cross-lane assist drafted by B1-prior-session per AI Head A request, 2026-04-29)
**Wave:** 1 / Track 1 (V3 rev 4 roadmap)
**Trigger class:** HIGH (external API + auth + cost-bearing trigger → RA-24 review required)

**Prior CODE_1 task** SCHEDULER_SINGLETON_HARDEN_1 (PR #84) merged + production-verified 2026-04-29T18:15Z. Mailbox overwrite per §3 hygiene; ship report preserved at `briefs/_reports/B1_scheduler_singleton_harden_20260430.md`.

## Scope (TL;DR)

`outputs/dashboard.py` + new helper module + intent-classifier extension:
1. NEW `outputs/cortex_run_stream.py` — SSE helpers + rate-limit + cost-warn
2. `POST /api/cortex/run` — streams Phase 1-6 events as SSE; spawns `maybe_run_cycle` in background
3. `/api/scan` branch — route `cortex_run_action` intent to streaming endpoint
4. Intent classifier — add `cortex_run_action` shape: `{type, matter_slug, question}`
5. Rate limit: **5 runs/hour/matter** (HTTP 429 over)
6. Cost guardrail: **30 specialist invocations/day/matter** → Slack DM warning (observability only)
7. 8 new tests (`tests/test_cortex_run_endpoint.py`)

## Working dir

`~/bm-b1`

```bash
cd ~/bm-b1 && git checkout main && git pull -q
cat briefs/BRIEF_CORTEX_MANUAL_INVOKE_1.md
```

## Order of work

1. Read brief end-to-end
2. Baseline: `pytest tests/test_cortex_action_endpoint.py tests/test_cortex_runner_phase126.py -v` (current PASS)
3. Implement `outputs/cortex_run_stream.py`
4. Add endpoint + Pydantic model + Scan branch in `outputs/dashboard.py`
5. Extend intent classifier (likely `kbl/anthropic_helper.py` — verify via grep)
6. Add 8 tests; verify PASS literal
7. Regression: full cortex test suite PASS
8. `bash scripts/check_singletons.sh` clean
9. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` + same for new file
10. Push to `b1/cortex-manual-invoke-1` branch + PR

## Pass criteria

- `/api/cortex/run` returns `text/event-stream` with ≥3 SSE chunks for AO matter
- 8/8 new tests PASS literal (no "by inspection" — Lesson #48)
- Rate limit returns 429 on 6th run/hour for same matter
- Cost-warn fires Slack DM at 30 specialists/day; cycle still proceeds
- Existing `/api/cortex/trigger` unchanged (regression-clean)
- `req.director_question` not info-logged anywhere new (grep diff)

## Lane rule

- **Out of scope:** `triggers/cortex_pre_review_gate.py` (Brief 2 / Track 2 / B3 owns it — do not race)
- **Out of scope:** `orchestrator/cortex_runner.py` signature, timeouts, error semantics
- **Out of scope:** Frontend / static — no UI work

## Ship report target

`briefs/_reports/B1_cortex_manual_invoke_1_<YYYYMMDD>.md` — include all 8 QC outputs + post-deploy SSE smoke curl output + Scan smoke transcript ("run cortex on oskolkov" → SSE chunks visible) + grep evidence that `director_question` is NOT info-logged.

## Review path (Tier A — HIGH)

PR opens → AI Head A `/security-review` + structural + B-code peer review (B3 or B2 depending on availability) → Tier A merge on dual clear.

**Note on builder/reviewer concentration:** AI Head A dispatch assigns B1 as builder. If AI Head A judges the B1-builder ↔ B1-was-original-drafter concentration unacceptable, the reassignment option is to swap builder to B2 and have B1 do formal review of B2's PR.

## Coordination with parallel tracks

- **Track 2 (B3) — CORTEX_MULTI_MATTER_GATE_1:** independent file scope (`triggers/cortex_pre_review_gate.py` only); zero overlap. Both can ship concurrently.
- **Tracks 3+4 (B2 App / AI Head 2 App) — `cortex-config.md` seeds:** baker-vault repo, no overlap.
- **Track 5 (idle B-code) — `hot.md` regen:** baker-vault repo, no overlap. Track 5 ship before Track 1+2 deploy gives day-1 value.

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
