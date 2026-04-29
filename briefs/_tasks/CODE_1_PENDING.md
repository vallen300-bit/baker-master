# CODE_1 — PR-OPEN (CORTEX_MANUAL_INVOKE_1)

**Status:** PR-OPEN — awaiting AI Head A `/security-review` + AI Head B cross-lane review (RA-24 dual-clear)
**Brief:** `briefs/BRIEF_CORTEX_MANUAL_INVOKE_1.md`
**Wave:** 1 / Track 1 (V3 rev 4 roadmap)
**Trigger class:** HIGH (external API + auth + cost-bearing)

**PR:** https://github.com/vallen300-bit/baker-master/pull/88
**Branch:** `b1/cortex-manual-invoke-1`
**Ship report:** `briefs/_reports/B1_cortex_manual_invoke_1_20260429.md`

## What shipped

- `outputs/cortex_run_stream.py` — NEW (263 LOC). Pure SSE helpers + rate-limit + cost-warn + cycle snapshot.
- `outputs/dashboard.py` — MOD (+133 LOC). `CortexRunRequest`, `POST /api/cortex/run`, Scan `cortex_run_action` branch.
- `orchestrator/action_handler.py` — MOD (+57 LOC). `_quick_cortex_run_detect` regex fast-path + extended LLM `_INTENT_SYSTEM` schema.
- 3 NEW test files (24 tests total): `test_cortex_run_stream.py`, `test_cortex_run_endpoint.py`, `test_scan_cortex_intent.py`.

## Tests

- 24/24 PASS new suite (`tests/test_cortex_run_stream.py` + `tests/test_cortex_run_endpoint.py` + `tests/test_scan_cortex_intent.py`)
- 143/143 PASS across 10 cortex/pipeline/scan suites (regression)
- `bash scripts/check_singletons.sh` clean
- 3 modified production files compile clean

## Director action required

Set the 3 optional Render env vars (defaults shipped, override if desired):

| Env var | Default | Purpose |
|---|---|---|
| `CORTEX_RUN_POLL_INTERVAL` | `0.5` | seconds between phase-snapshot polls |
| `CORTEX_RUN_RATE_LIMIT` | `5` | manual runs/hour/matter cap (HTTP 429 over) |
| `CORTEX_COST_WARN_SPECIALIST_PER_DAY` | `30` | specialist invocations/24h/matter that triggers Slack DM warn |

No required env vars. `BAKER_VAULT_PATH` (already required by PR #85) gates the whitelist.

## Post-merge verification

1. Render redeploys → curl smoke (config-rich + config-less matters) — full snippets in ship report §10
2. Scan UI smoke: "run cortex on oskolkov — quick smoke"
3. SQL: `SELECT cycle_id, status, cost_dollars FROM cortex_cycles WHERE triggered_by IN ('director_manual','scan_intent') ORDER BY started_at DESC LIMIT 5;`

## Side findings (non-blocking, surfaced for tracker)

1. **Pre-existing test pollution** at `tests/test_cortex_action_endpoint.py:62` — global `app.dependency_overrides[verify_api_key]=lambda: None` never cleaned up. Confirmed via clean-main repro. Hardened MY tests defensively; trigger-test fix out of scope (surgical edits).
2. **Pre-existing main failures** — 3× `tests/test_scan_endpoint.py` + 1× `tests/test_scan_prompt.py`. Unrelated to this PR.
3. **Schema deviation from brief** (Lesson #40 cousin): brief named `capability_runs` for specialist counter; that table has no `matter_slug` column. Implementation uses `cortex_phase_outputs JOIN cortex_cycles` filtered by `artifact_type='specialist_invocation'`. Documented in `outputs/cortex_run_stream.py` docstring.

## Prior CODE_1 task

SCHEDULER_SINGLETON_HARDEN_1 (PR #84) merged + production-verified 2026-04-29T18:15Z. Mailbox overwrite per §3 hygiene; ship report preserved at `briefs/_reports/B1_scheduler_singleton_harden_20260430.md`.

## Mailbox hygiene

On PR merge: overwrite this file with `COMPLETE` + post-deploy verification status.
