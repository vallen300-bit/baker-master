# Ship Report — CORTEX_NOTIFICATION_DEFER_1 (B4 / Wave 2 #3)

- **Brief:** `briefs/BRIEF_CORTEX_NOTIFICATION_DEFER_1.md`
- **Branch:** `b4/cortex-notification-defer-1`
- **Trigger class:** LOW (no RA-24 dual-clear required)
- **Wave/Track:** Wave 2 / Track 3 (demoted from #1 → #3 after F-2 Scan UI render took priority and shipped as PR #90 + #91 on 2026-04-30)
- **Director directive:** V7 — let Cortex run silently with cost gate auto-approving
- **Date:** 2026-04-30
- **Author:** Code Brisen #4 (b4)

---

## What changed

Two opt-out surfaces gate the cost-warn Slack DM at `outputs/dashboard.py` `cortex_run_stream` endpoint:

1. **Per-invoke** — `CortexRunRequest.defer_notification: bool = False` (new request body field).
2. **Per-matter** — `notification_defer: true` in `cortex-config.md` frontmatter, read via new `matter_notification_deferred()` helper that mirrors the `_read_cost_estimate` line-based YAML-free parse.

The cost-warn block was rewritten so:
- `logger.info` ALWAYS fires when the threshold is hit (observability preserved regardless of defer flags) — emits matter, count, threshold, defer_invoke, defer_matter.
- Slack `post_to_channel` is gated on `not (req.defer_notification or defer_matter)`.
- When suppressed, a second `logger.info` records the suppression with both flags so `actions_log.md` retroactive review is possible.

Default behaviour **unchanged**: a request with no `defer_notification` field on a matter without `notification_defer: true` still posts the DM.

## Files modified

```
 outputs/dashboard.py                 | 62 +++++++++++++++++++++++--------
 tests/test_cortex_pre_review_gate.py | 71 ++++++++++++++++++++++++++++++++++++
 tests/test_cortex_run_endpoint.py    | 64 ++++++++++++++++++++++++++++++++
 triggers/cortex_pre_review_gate.py   | 40 ++++++++++++++++++++
 4 files changed, 221 insertions(+), 16 deletions(-)
```

- `outputs/dashboard.py` — appended `defer_notification` Field to `CortexRunRequest`; replaced cost-warn block in `cortex_run_stream` with logger-first / Slack-gated form.
- `triggers/cortex_pre_review_gate.py` — added `matter_notification_deferred(matter_slug: str) -> bool` immediately after `_read_cost_estimate`, identical parse pattern, fail-closed (returns False on vault-unset / config-missing / field-absent / parse error), accepts truthy spellings `true / yes / on / 1` (case-insensitive).
- `tests/test_cortex_run_endpoint.py` — appended parametrised `test_cortex_run_cost_warn_defer_matrix` covering the 4 (defer_invoke × defer_matter) combinations.
- `tests/test_cortex_pre_review_gate.py` — appended 4 helper-level tests: `_true`, `_false_when_field_absent`, `_false_when_config_missing` (also covers empty slug), `_truthy_spellings` (yes/on/1/True/TRUE all → True; false/no/off/0/blank all → False).

No DDL, no env vars, no DB writes added. No singleton risk.

## Files NOT touched (per brief)

- `outputs/cortex_run_stream.py`
- `outputs/slack_notifier.py`
- `outputs/dashboard.py:7854-7886` (Scan branch — inherits per-invoke flag from body if Director ever wires Scan UI through)
- `outputs/dashboard.py:4220-4269` (`trigger_cortex_cycle` sync endpoint — no DM there)
- `triggers/cortex_pre_review_gate.py::_read_cost_estimate` and signing/verify machinery
- `wiki/matters/*/cortex-config.md` (vault writes are out of scope — Director adds `notification_defer: true` per-matter via the gold-comment workflow)

## Pre-flight verification

```
$ grep -n "Cost guardrail\|specialist_calls_today\|class CortexRunRequest" outputs/dashboard.py | head -5
361:class CortexRunRequest(BaseModel):
4283:    Cost guardrail: ≥30 specialist invocations/24h/matter posts a Slack DM
4292:        specialist_calls_today,
4327:    # Cost guardrail: warn-only Slack DM at threshold, run proceeds
4328:    n_specialist = specialist_calls_today(req.matter_slug)

$ grep -n "_read_cost_estimate\|matter_has_cortex_config\|matter_notification_deferred\|DIRECTOR_DM_CHANNEL" triggers/cortex_pre_review_gate.py | head -5
37:DIRECTOR_DM_CHANNEL = "D0AFY28N030"
65:def matter_has_cortex_config(matter_slug: str) -> bool:
80:def _read_cost_estimate(matter_slug: str) -> float:
316:    if not matter_has_cortex_config(matter_slug):
```

Brief line citations 361-373, 4327-4345, 65, 80 still correct after PR #91 merge.

## Ship gate — literal pytest tail

Command:

```
$ .venv-b3/bin/python -m pytest tests/test_cortex_run_endpoint.py tests/test_cortex_pre_review_gate.py tests/test_cortex_run_stream.py tests/test_scan_cortex_intent.py -v 2>&1 | tail -80
```

Output (verbatim):

```
tests/test_cortex_run_endpoint.py::test_cortex_run_cost_warn_defer_matrix[False-True-False] PASSED [ 17%]
tests/test_cortex_run_endpoint.py::test_cortex_run_cost_warn_defer_matrix[True-True-False] PASSED [ 19%]
tests/test_cortex_pre_review_gate.py::test_sign_verify_roundtrip PASSED  [ 21%]
tests/test_cortex_pre_review_gate.py::test_verify_expired PASSED         [ 23%]
tests/test_cortex_pre_review_gate.py::test_verify_bad_signature PASSED   [ 25%]
tests/test_cortex_pre_review_gate.py::test_verify_unknown_action PASSED  [ 26%]
tests/test_cortex_pre_review_gate.py::test_secret_unset_disables_gate PASSED [ 28%]
tests/test_cortex_pre_review_gate.py::test_already_decided_returns_prior PASSED [ 30%]
tests/test_cortex_pre_review_gate.py::test_gate_decide_endpoint_approve_flow PASSED [ 32%]
tests/test_cortex_pre_review_gate.py::test_record_decision_claim_then_loser PASSED [ 34%]
tests/test_cortex_pre_review_gate.py::test_gate_decide_endpoint_race_loser_does_not_fire_cycle PASSED [ 36%]
tests/test_cortex_pre_review_gate.py::test_post_gate_disables_slack_unfurl PASSED [ 38%]
tests/test_cortex_pre_review_gate.py::test_matter_has_cortex_config_positive PASSED [ 40%]
tests/test_cortex_pre_review_gate.py::test_matter_has_cortex_config_negative PASSED [ 42%]
tests/test_cortex_pre_review_gate.py::test_matter_has_cortex_config_no_vault PASSED [ 44%]
tests/test_cortex_pre_review_gate.py::test_read_cost_estimate_from_frontmatter PASSED [ 46%]
tests/test_cortex_pre_review_gate.py::test_read_cost_estimate_default PASSED [ 48%]
tests/test_cortex_pre_review_gate.py::test_post_gate_skips_no_config PASSED [ 50%]
tests/test_cortex_pre_review_gate.py::test_post_gate_fires_with_config_and_cost PASSED [ 51%]
tests/test_cortex_pre_review_gate.py::test_matter_notification_deferred_true PASSED [ 53%]
tests/test_cortex_pre_review_gate.py::test_matter_notification_deferred_false_when_field_absent PASSED [ 55%]
tests/test_cortex_pre_review_gate.py::test_matter_notification_deferred_false_when_config_missing PASSED [ 57%]
tests/test_cortex_pre_review_gate.py::test_matter_notification_deferred_truthy_spellings PASSED [ 59%]
tests/test_cortex_run_stream.py::test_sse_format_single_data_block PASSED [ 61%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_returns_count PASSED [ 63%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_db_unavailable_returns_zero PASSED [ 65%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_returns_count PASSED [ 67%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_db_unavailable_returns_zero PASSED [ 69%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_dict PASSED [ 71%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_no_cycle PASSED [ 73%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_db_unavailable PASSED [ 75%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_emits_full_sequence PASSED [ 76%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_failed_on_exception PASSED [ 78%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_timeout PASSED [ 80%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_disambiguates_concurrent_taps PASSED [ 82%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_concurrent_isolation PASSED [ 84%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_run_on PASSED [ 86%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_fire_for PASSED [ 88%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_review_on PASSED [ 90%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_no_match PASSED [ 92%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_hyphenated_slug PASSED [ 94%]
tests/test_scan_cortex_intent.py::test_classify_intent_fast_path_skips_llm PASSED [ 96%]
tests/test_scan_cortex_intent.py::test_scan_branch_rejects_matter_without_config PASSED [ 98%]
tests/test_scan_cortex_intent.py::test_cortex_run_yields_typed_events_for_ui PASSED [100%]

=============================== warnings summary ===============================
tests/test_cortex_run_endpoint.py::test_run_endpoint_unauthorized
  /Users/dimitry/bm-b4/outputs/dashboard.py:526: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

tests/test_cortex_run_endpoint.py::test_run_endpoint_unauthorized
tests/test_cortex_run_endpoint.py::test_run_endpoint_unauthorized
  /Users/dimitry/bm-b4/.venv-b3/lib/python3.12/site-packages/fastapi/applications.py:4598: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)  # ty: ignore[deprecated]

tests/test_cortex_run_endpoint.py::test_run_endpoint_unauthorized
  /Users/dimitry/bm-b4/outputs/dashboard.py:577: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("shutdown")

tests/test_cortex_run_endpoint.py::test_run_endpoint_unauthorized
  /Users/dimitry/bm-b4/.venv-b3/lib/python3.12/site-packages/qdrant_client/qdrant_remote.py:288: UserWarning: Failed to obtain server version. Unable to check client-server compatibility. Set check_compatibility=False to skip version check.
    show_warning(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 52 passed, 5 warnings in 1.51s ========================
```

(`tail -80` lops the first eight tests off the visible list — full collection was 52 tests.
Earlier-percentile lines in the same run included `test_run_endpoint_unauthorized [  1%]` …
`test_cortex_run_cost_warn_defer_matrix[False-False-True] PASSED [ 15%]` —
all green; the final `52 passed` summary above is the authoritative line.)

All four target test files green. The 4 new defer-matrix cases hit the matrix exactly:

| `defer_invoke` | `defer_matter` | Slack post calls | Expected |
|---|---|---|---|
| False | False | 1 | DM fires (default) |
| True | False | 0 | per-invoke suppresses |
| False | True | 0 | per-matter suppresses |
| True | True | 0 | both suppress |

## Singleton check

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

No new constructor calls; new helper is a pure file-read.

## Import + route smoke

```
$ .venv-b3/bin/python -c "from outputs.dashboard import app; print(any(getattr(r, 'name', '') == 'cortex_run_stream' for r in app.routes))"
True
```

Same as pre-merge — no route regressions.

## Pydantic model smoke (per-invoke field)

```
$ .venv-b3/bin/python -c "from outputs.dashboard import CortexRunRequest; \
  print(CortexRunRequest(matter_slug='test', director_question='this is at least 10 chars', defer_notification=True).defer_notification); \
  print(CortexRunRequest(matter_slug='test', director_question='this is at least 10 chars').defer_notification)"
True
False
```

Default `False` preserved; explicit `True` accepted.

## Helper smoke (per-matter field) — synthetic vault

```
$ BAKER_VAULT_PATH=/tmp/vault_smoke .venv-b3/bin/python -c "...write smoke-defer + smoke-no-defer cortex-config.md, then import + assert..."
helper smoke OK
```

Asserts:
- `matter_notification_deferred("smoke-defer")` → True (`notification_defer: true` in frontmatter)
- `matter_notification_deferred("smoke-no-defer")` → False (field absent)
- `matter_notification_deferred("ghost")` → False (no config)
- `matter_notification_deferred("")` → False (empty slug)

## Curl smoke — deferred for post-deploy

The brief's curl smokes A (defer=true → no Slack DM) + B (no field → DM fires) require Render deploy + a matter at `specialist_calls_today >= 30`. AI Head A will run them after PR merge + Render deploy. Locally we instead verified the same matrix via the parametrised endpoint test, which:

- forces `specialist_calls_today` → 42 (above `COST_WARN_SPECIALIST_PER_DAY = 30`),
- patches `matter_notification_deferred` per-case,
- counts `outputs.slack_notifier.post_to_channel` calls,
- asserts exactly 1 call iff `(defer_invoke OR defer_matter)` is False.

This is the deterministic equivalent of the live curl smokes — `pass-by-inspection` is NOT relied on.

## Quality checkpoints (vs brief)

| # | Checkpoint | Status |
|---|---|---|
| 1 | pytest 4 files literal green | ✅ 52 passed |
| 2 | `scripts/check_singletons.sh` clean | ✅ |
| 3 | `cortex_run_stream` route still registered | ✅ True |
| 4 | Curl smoke A (per-invoke defer) | Deferred to AI Head A post-deploy (deterministic equivalent passes via `[True-False-False]` parametrise case) |
| 5 | Curl smoke B (no defer → DM fires regression) | Deferred to AI Head A post-deploy (deterministic equivalent passes via `[False-False-True]` parametrise case) |
| 6 | `matter_notification_deferred` returns True from a real cortex-config.md | ✅ helper smoke + 4 unit tests |
| 7 | JS console clean | N/A — no frontend changes |
| 8 | Logger trail on every threshold hit | ✅ logger.info now ALWAYS fires; suppression also logged |
| 9 | No new env vars / DDL / schema | ✅ |
| 10 | Backward compat (no flag → DM fires) | ✅ verified by `[False-False-True]` case + existing `test_run_endpoint_cost_warn_posts_slack_and_runs` (still green) |

## Cost / blast radius

- **Cost:** lower API spend when defer is set (Slack post suppressed; logger.info free). No new LLM calls.
- **Blast radius:** worst case = false-True from `matter_notification_deferred` silently suppresses a DM that should fire. Mitigation = fail-closed default (vault unset / config missing / parse error → False → DM fires) + the always-on `logger.info` makes regression visible in <60s of Render log review.
- **Rollback:** revert dashboard.py block to unconditional post; helper becomes dead code if not called. Minimal surface.

## Lessons / notes

- Brief line citations stayed accurate post PR #91 merge — confirmed via the two `grep -n` commands the brief asked for. `class CortexRunRequest` at 361 (unchanged); cost-warn block now starts at 4327 (matches brief's 4327-4345 range).
- Local Python 3.9 in `/usr/bin/python3` cannot import the codebase (`tools/ingest/extractors.py:275` uses `str | None` syntax = 3.10+). The b4 worktree's `.venv-b3` (Python 3.12.12) is the canonical test interpreter — `pytest-asyncio` was missing and was installed (1.3.0) before pass-on-second-run; not a code change.
- Deferred curl smokes (live Render against a matter at threshold) were replaced with a deterministic 4-case parametrise that asserts the same matrix without relying on a live state machine. Per Lesson #48 / Lesson #8 these are NOT pass-by-inspection — they exercise the actual `cortex_run_stream` endpoint via TestClient.

## Ready to merge

Branch: `b4/cortex-notification-defer-1` (4 files, +221/-16). Commit + PR pending Director / AI Head A authorization.
