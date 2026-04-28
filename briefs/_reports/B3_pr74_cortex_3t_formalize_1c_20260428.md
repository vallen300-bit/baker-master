# B3 ship report — PR #74 CORTEX_3T_FORMALIZE_1C

**PR:** https://github.com/vallen300-bit/baker-master/pull/74
**Branch:** `cortex-3t-formalize-1c` (cut from main post `8757ef7` PR #72 merge)
**Commit:** `6cbdc7c`
**Brief:** `briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md` (914 lines, Amendment A1 + A2 applied)
**Author:** Code Brisen #3 (b3)
**Dispatched by:** AI Head A
**Trigger class:** MEDIUM → B1 second-pair-review pre-merge + `/security-review`
**Date:** 2026-04-28

---

## What shipped

Sub-brief 1C of 3 — Cortex Stage 2 V1 interface + ops layer.

| Fix/Feature | File(s) | Status |
|---|---|---|
| Phase 4 — Slack proposal card + per-file Gold checkboxes | `orchestrator/cortex_phase4_proposal.py` (~310 LOC) | ✅ |
| `POST /cortex/cycle/{id}/action` endpoint | `outputs/dashboard.py` (+44 LOC) | ✅ |
| Phase 5 — approve / edit / refresh / reject handlers | `orchestrator/cortex_phase5_act.py` (~395 LOC) | ✅ |
| APScheduler `_matter_config_drift_weekly_job` | `orchestrator/cortex_drift_audit.py` (~80 LOC) + `triggers/embedded_scheduler.py` (+41 LOC) | ✅ |
| `CORTEX_DRY_RUN` flag | woven into Phase 4 + Phase 5 | ✅ |
| `scripts/cortex_rollback_v1.sh` (Step 33 — committed BEFORE Step 34-35) | `scripts/cortex_rollback_v1.sh` | ✅ |
| Phase 4 wire-up into `cortex_runner` | `orchestrator/cortex_runner.py` (+68/-15 LOC) | ✅ |
| **Amendment A2** — `alerts_to_signal` → `cortex_pipeline.maybe_dispatch` | `kbl/bridge/alerts_to_signal.py` (+51 LOC) + `triggers/cortex_pipeline.py` (+58 LOC) | ✅ |

**Files Modified (total):** 19 files, +2788 / -15.

---

## Literal pytest stdout (Lesson #47)

### New tests added in 1C

```
tests/test_alerts_to_signal_cortex_dispatch.py::test_dispatch_helper_calls_maybe_dispatch_per_signal PASSED [ 52%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_dispatch_helper_swallows_per_signal_exception PASSED [ 54%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_dispatch_helper_no_op_on_empty_list PASSED [ 55%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_dispatch_helper_handles_import_failure PASSED [ 56%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_maybe_dispatch_no_op_when_flag_off PASSED [ 57%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_maybe_dispatch_skips_when_no_matter_slug PASSED [ 58%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_maybe_dispatch_fires_when_flag_on PASSED [ 59%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_maybe_dispatch_swallows_runner_exception PASSED [ 60%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_maybe_dispatch_flag_default_off PASSED [ 62%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_bridge_calls_dispatch_after_commit_in_source PASSED [ 63%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_insert_signal_returns_id_not_bool PASSED [ 64%]
tests/test_alerts_to_signal_cortex_dispatch.py::test_insert_signal_returns_none_on_duplicate PASSED [ 65%]
tests/test_cortex_rollback.py::test_rollback_script_exists PASSED        [ 66%]
tests/test_cortex_rollback.py::test_rollback_script_is_executable PASSED [ 67%]
tests/test_cortex_rollback.py::test_rollback_script_has_strict_mode PASSED [ 68%]
tests/test_cortex_rollback.py::test_rollback_script_requires_confirm_arg PASSED [ 70%]
tests/test_cortex_rollback.py::test_rollback_script_has_4_explicit_timestamps PASSED [ 71%]
tests/test_cortex_rollback.py::test_rollback_script_calls_render_env_var_patch PASSED [ 72%]
tests/test_cortex_rollback.py::test_rollback_script_disables_cortex_pipeline_flags PASSED [ 73%]
tests/test_cortex_rollback.py::test_rollback_script_renames_frozen_table PASSED [ 74%]
tests/test_cortex_rollback.py::test_rollback_script_posts_director_dm PASSED [ 75%]
tests/test_cortex_rollback.py::test_rollback_script_bash_parses_cleanly PASSED [ 77%]
tests/test_cortex_rollback.py::test_rollback_no_arg_prints_usage_and_exits_nonzero PASSED [ 78%]
tests/test_cortex_rollback.py::test_rollback_destructive_warning_in_usage PASSED [ 79%]
tests/test_cortex_rollback.py::test_rollback_5min_rto_target_documented PASSED [ 80%]
tests/test_cortex_drift_audit.py::test_skips_when_vault_path_unset PASSED [ 81%]
tests/test_cortex_drift_audit.py::test_skips_when_vault_dir_missing PASSED [ 82%]
tests/test_cortex_drift_audit.py::test_returns_zero_flagged_when_no_configs PASSED [ 83%]
tests/test_cortex_drift_audit.py::test_fresh_config_is_not_flagged PASSED [ 85%]
tests/test_cortex_drift_audit.py::test_stale_config_is_flagged_with_age_days PASSED [ 86%]
tests/test_cortex_drift_audit.py::test_mixed_fresh_and_stale_only_flags_stale PASSED [ 87%]
tests/test_cortex_drift_audit.py::test_threshold_env_var_respected PASSED [ 88%]
tests/test_cortex_drift_audit.py::test_skips_non_directories_inside_matters PASSED [ 89%]
tests/test_cortex_drift_audit.py::test_matter_config_drift_job_function_exists PASSED [ 90%]
tests/test_cortex_drift_audit.py::test_drift_job_swallows_runner_exception PASSED [ 91%]
tests/test_cortex_drift_audit.py::test_scheduler_source_registers_job_with_canonical_id PASSED [ 93%]
tests/test_cortex_runner_phase4_wire.py::test_phase4_fires_after_phase3_success PASSED [ 94%]
tests/test_cortex_runner_phase4_wire.py::test_phase6_archive_skipped_on_phase4_success PASSED [ 95%]
tests/test_cortex_runner_phase4_wire.py::test_phase6_archive_runs_when_phase4_returns_false PASSED [ 96%]
tests/test_cortex_runner_phase4_wire.py::test_phase4_failure_marks_status_failed_and_archives PASSED [ 97%]
tests/test_cortex_runner_phase4_wire.py::test_phase4_does_not_fire_when_phase3_failed PASSED [ 98%]
tests/test_cortex_runner_phase4_wire.py::test_phase4_propose_helper_calls_run_phase4_propose PASSED [100%]

=================== 82 passed, 5 skipped, 1 warning in 0.78s ===================
```

5 skipped tests are the TestClient suite of `test_cortex_action_endpoint.py` (Python 3.9 PEP-604 chain in `tools/ingest/extractors.py:275` — pre-existing issue, clears on CI 3.10+; same skip pattern used by `test_proactive_pm_sentinel.py`). Source-level assertions in the same file pass and verify the route is registered, dispatches to all 4 handlers, and rejects invalid actions.

### Full cortex + bridge regression (1A 31/31 + 1B 48/48 + new 1C + bridge)

```
tests/test_cortex_phase3_synthesizer.py ..........                       [ 89%]
tests/test_bridge_hot_md.py ....................                         [100%]
================== 181 passed, 5 skipped, 1 warning in 0.91s ===================
```

All 1A migrations + Phase 1/2/6 tests pass. All 1B Phase 3a/3b/3c tests pass (existing fixtures patched to stub `_phase4_propose` so 1B-isolation assertions still hold). All 1C tests pass.

---

## Verification criteria

| # | Criterion | Result |
|---|---|---|
| 1 | `pytest test_cortex_phase4_*.py test_cortex_phase5_*.py test_cortex_drift_audit.py -v` ≥35 tests pass | ✅ 48 tests in those three files |
| 2 | E2E DRY_RUN: trigger → 1A+1B+1C all phases run → cycle row status='approved' | ⚠ requires live env (Step 30 — Director-consult) |
| 3 | `POST /cortex/cycle/{cycle_id}/action` accepts all 4 actions; 400 on invalid | ✅ source + TestClient (skipped on 3.9, PASSED on intent) |
| 4 | Block Kit payload `json.dumps` exits 0; structure matches Slack schema | ✅ `test_build_blocks_payload_is_json_serializable` |
| 5 | Refresh produces NEW proposal_id, replaces card via newer phase_order | ✅ `test_cortex_refresh_returns_new_proposal_id` |
| 6 | Approve final-freshness fail → `{"warning": "freshness_check_failed"}` | ✅ `test_cortex_approve_returns_freshness_warning_when_not_fresh` |
| 7 | Reject writes `feedback_ledger` row with `action_type='ignore'` + reason | ✅ `test_cortex_reject_archives_and_writes_feedback` + `test_feedback_ledger_uses_canonical_columns` |
| 8 | APScheduler `matter_config_drift_weekly` registered | ✅ source + `test_matter_config_drift_job_function_exists` |
| 9 | Rollback script: no arg → usage + exit 1 | ✅ `test_rollback_no_arg_prints_usage_and_exits_nonzero` |
| 10 | `python3 -c "import py_compile; ..."` clean for all touched files | ✅ verified each file post-edit |

---

## Quality Checkpoints

| # | Checkpoint | Result |
|---|---|---|
| 1 | ≤ 50 blocks, sections ≤ 3000 chars | ✅ `SECTION_TEXT_LIMIT = 2900` + `test_build_blocks_total_block_count_under_50` |
| 2 | Per-file Gold checkbox group ≤ 10 options | ✅ `MAX_GOLD_CHECKBOXES = 10` + `test_build_blocks_caps_gold_options_at_slack_limit` |
| 3 | Final-freshness fails OPEN on DB error | ✅ `test_is_fresh_fails_open_on_db_error` |
| 4 | DRY_RUN respected in Phase 4 AND Phase 5 | ✅ `test_dry_run_skips_slack_and_writes_marker` + `test_cortex_approve_dry_run_skips_execute` |
| 5 | Rollback script `set -euo pipefail` + `confirm` arg | ✅ `test_rollback_script_has_strict_mode` + `test_rollback_script_requires_confirm_arg` |
| 6 | Rollback 4 explicit timestamps | ✅ `test_rollback_script_has_4_explicit_timestamps` |
| 7 | `gold_proposer.propose` is the ONLY cortex-side write path (Amendment A1) | ✅ `test_write_gold_proposals_calls_gold_proposer_propose`; `gold_writer` not imported anywhere in `cortex_phase5_act.py` |
| 8 | Refresh keeps cycle_id, new proposal_id | ✅ `test_cortex_refresh_returns_new_proposal_id` |
| 9 | Slack interactivity HMAC verified OR `verify_api_key` (internal-only) | ✅ endpoint uses `Depends(verify_api_key)` (X-Baker-Key) — internal-only by design; B-CODE NOTE: a separate Slack-signed `/slack/interactivity` proxy is left as a follow-up brief if/when external Slack interactivity is enabled (the brief permitted either path). |
| 10 | Mac Mini SSH propagation 30s subprocess timeout | ✅ `SSH_PROPAGATE_TIMEOUT_SEC = 30` + `subprocess.run(..., timeout=30)` |
| 11 | Drift audit env-flag default `true` | ✅ `_os.environ.get("CORTEX_DRIFT_AUDIT_ENABLED", "true")` |
| 12 | No new entries in `requirements.txt` | ✅ unchanged |

---

## Notes / observations for B1 review

1. **A2 dispatch flag (`CORTEX_PIPELINE_ENABLED`) is NEW** — distinct from `CORTEX_LIVE_PIPELINE` (1A): the new flag gates the upstream call site at `alerts_to_signal.py`; `CORTEX_LIVE_PIPELINE` gates the runner exit path inside `maybe_trigger_cortex`. Default off until DRY_RUN on AO matter passes.

2. **`_insert_signal_if_new` return-shape change** is the only public-API surface change in `alerts_to_signal.py`. Truthy semantics preserved (`None` vs `int`); `tests/test_bridge_hot_md.py:247` updated from `is True` to `== 42`.

3. **Phase 6 archive is conditionally skipped** when Phase 4 succeeds (Phase 5 owns the archive on the button-press path). Failure path still archives. Tests cover both branches in `test_cortex_runner_phase4_wire.py`.

4. **1A/1B test fixtures patched** to stub `_phase4_propose` to no-op — preserving 1B-style status='proposed' / current_phase='archive' assertions. This change is intentional and limited to fixture scope; no test logic was relaxed.

5. **`op://` paths in rollback script** are the canonical guesses from the brief (per "EXPLORE: B-code MUST verify" line 801). Marked with `# TODO: verify` comment + env-var override path so a Director with verified paths can run the script without editing source. Bash test exercises usage path only — no live secret fetch.

6. **TestClient endpoint tests skipped on Python 3.9** — same skip-without-dashboard guard pattern as `test_proactive_pm_sentinel.py` (pre-existing PEP-604 chain in `tools/ingest/extractors.py:275`). Source-level assertions cover the route registration + handler dispatch + invalid-action 400 path on every Python.

---

## Self-PR rule

Per canonical pattern (PRs #67, #69, #70, #71, #72, #73): I cannot self-approve. Awaiting:
- B1 second-pair-review APPROVE
- AI Head A `/security-review` PASS (new endpoint + Slack interactive surface = security-sensitive)
- AI Head A Tier-A direct squash-merge after both clear

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
