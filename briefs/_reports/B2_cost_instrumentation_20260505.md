# B2 Ship Report — BAKER-COST-INSTRUMENTATION-1

**TO:** AH1-App PL
**FROM:** B2 (Code Brisen build worker)
**DATE:** 2026-05-05
**BRIEF:** `briefs/BRIEF_BAKER_COST_INSTRUMENTATION_1.md` (Tier A, ~2 days, 10 ACs)
**PR:** https://github.com/vallen300-bit/baker-master/pull/158
**BRANCH:** `b2/baker-cost-instrumentation-1` (commit `801eb4bd`)
**BASE:** `main` @ `96cd7b86`

---

## Verdict

**SHIP READY** pending the 4-gate review chain (live pytest GREEN below + AH2 `/security-review` + architect spot-check + feature-dev:code-reviewer 2nd-pass).

## What changed

| Area | Change |
|---|---|
| Migrations | `20260505_api_cost_log_matter_slug.sql` (ADD COLUMN IF NOT EXISTS + partial index); `20260505b_cost_alert_state.sql` (new table for per-(date, tier_label) alarm idempotence) |
| `orchestrator/cost_monitor.py` | `COST_TIERS` list (info=€30 / warn=€60 / critical=€100); `COST_ALERT_EUR` kept as alias to `COST_TIERS[0][0]`; `log_api_cost(..., matter_slug=None)` (cache-token params decoupled to sibling caching brief); `check_circuit_breaker` walks tiers in ascending order; `_claim_tier_alert` DB-backed idempotence via `INSERT ... ON CONFLICT DO NOTHING`; `BAKER_COST_ALARMS_ENABLED` master kill (false suppresses tiers + daily summary; hard stop always on); `post_daily_cost_summary` with by-source / by-matter / by-model; `ensure_api_cost_log_table` bootstrap aligned with migration column shape (Lesson #50); `ensure_cost_alert_state_table` new bootstrap |
| `memory/store_back.py` | `_ensure_cost_and_metrics_tables` now also bootstraps `cost_alert_state` |
| `orchestrator/capability_runner.py` | `run_single`, `run_streaming`, `_maybe_store_insight` gain `matter_slug=None` kwarg; threaded through to all 3 `log_api_cost` calls |
| `orchestrator/cortex_phase3_invoker.py` | `runner.run_single(cap, question, matter_slug=matter_slug)` propagation (matter_slug already in scope) |
| `orchestrator/cortex_phase3_reasoner.py` | `_call_opus` + `run_phase3a_meta_reason` thread matter_slug → `log_api_cost` |
| `orchestrator/cortex_phase3_synthesizer.py` | Same pattern as reasoner — phase3c synthesis attribution |
| `triggers/embedded_scheduler.py` | New `daily_cost_summary` job registered with `CronTrigger(hour=23, minute=55, timezone='UTC')`, mirroring `gold_audit_sentinel` pattern at line 746; env-gated by `BAKER_COST_DAILY_SUMMARY_ENABLED` |
| `_ops/processes/cost-control-runbook.md` | NEW Director-facing runbook (5 sections — tiers, kill-switches, attribution queries, breaker bypass, alarm investigation) |
| `briefs/BRIEF_PIPELINE_MATTER_RESOLUTION_1.md` | NEW follow-up stub opening A7 honest-scope gap visibly |
| `tests/test_cost_alarms.py` | NEW 14-test file covering tier idempotence + hard-stop preservation + matter_slug INSERT + daily summary suppression |
| `tests/test_cortex_phase3_reasoner.py` + `test_cortex_phase3_synthesizer.py` | `_call_opus` test stub gains `matter_slug=None` kwarg |

## Architect post-WRITE review constraints honored

| Constraint | Status |
|---|---|
| Signature ownership decoupled (no shared cache-token signature with B1 caching brief) | ✅ Only `matter_slug` param added |
| `COST_ALERT_EUR` alias kept | ✅ Points at `COST_TIERS[0][0]` |
| A7 scope honest (capability_runner only + follow-up brief stub) | ✅ Stub committed at `briefs/BRIEF_PIPELINE_MATTER_RESOLUTION_1.md` |
| 23:55 UTC scheduler registration named explicitly | ✅ Job id=`daily_cost_summary` |
| New `cost_alert_state` table for DB-persisted tier idempotence | ✅ Migration + bootstrap aligned (Lesson #50 parity) |
| Migration sibling-coupling: distinct filenames; lock refresh after BOTH apply | ✅ `20260505_…sql` + `20260505b_…sql`; lock refresh deferred per mailbox dispatch |

## Pytest — literal GREEN (Python 3.12.12, local)

Per Lesson #52 — no by-inspection.

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_cost_alarms.py tests/test_cortex_phase3_invoker.py tests/test_cortex_phase3_reasoner.py tests/test_cortex_phase3_synthesizer.py tests/test_cortex_phase2_loaders.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.12/bin/python3.12
collecting ... collected 67 items

tests/test_cost_alarms.py::test_cost_tiers_ascending PASSED              [  1%]
tests/test_cost_alarms.py::test_cost_alert_eur_alias_points_at_info_tier PASSED [  2%]
tests/test_cost_alarms.py::test_log_api_cost_accepts_matter_slug_kwarg PASSED [  4%]
tests/test_cost_alarms.py::test_log_api_cost_matter_slug_defaults_to_none PASSED [  5%]
tests/test_cost_alarms.py::test_claim_tier_alert_returns_true_first_time PASSED [  7%]
tests/test_cost_alarms.py::test_claim_tier_alert_returns_false_on_conflict PASSED [  8%]
tests/test_cost_alarms.py::test_claim_tier_alert_degrades_open_on_db_failure PASSED [ 10%]
tests/test_cost_alarms.py::test_check_circuit_breaker_fires_each_tier_once_idempotent PASSED [ 11%]
tests/test_cost_alarms.py::test_check_circuit_breaker_walks_tiers_only_for_crossed_thresholds PASSED [ 13%]
tests/test_cost_alarms.py::test_alarms_disabled_suppresses_tiers_but_not_hard_stop PASSED [ 14%]
tests/test_cost_alarms.py::test_hard_stop_unchanged_below_threshold_allows PASSED [ 16%]
tests/test_cost_alarms.py::test_hard_stop_in_process_dedup_within_same_day PASSED [ 17%]
tests/test_cost_alarms.py::test_post_daily_cost_summary_returns_breakdown_when_disabled PASSED [ 19%]
tests/test_cost_alarms.py::test_post_daily_cost_summary_idempotent_per_day PASSED [ 20%]
tests/test_cortex_phase3_invoker.py::test_success_returns_specialist_output PASSED [ 22%]
tests/test_cortex_phase3_invoker.py::test_question_includes_signal_and_matter_brain PASSED [ 23%]
tests/test_cortex_phase3_invoker.py::test_unknown_capability_records_failure_and_continues PASSED [ 25%]
tests/test_cortex_phase3_invoker.py::test_timeout_triggers_retries_then_fail_forward PASSED [ 26%]
tests/test_cortex_phase3_invoker.py::test_exception_triggers_retries_then_fail_forward PASSED [ 28%]
tests/test_cortex_phase3_invoker.py::test_partial_failure_one_of_many PASSED [ 29%]
tests/test_cortex_phase3_invoker.py::test_persist_writes_specialist_invocation_artifact PASSED [ 31%]
tests/test_cortex_phase3_invoker.py::test_persist_bumps_cycle_cost_per_completion PASSED [ 32%]
tests/test_cortex_phase3_invoker.py::test_persist_skips_cost_bump_on_zero_cost_failure PASSED [ 34%]
tests/test_cortex_phase3_invoker.py::test_concurrent_execution_bounded_by_slowest PASSED [ 35%]
tests/test_cortex_phase3_invoker.py::test_staging_file_written_on_success PASSED [ 37%]
tests/test_cortex_phase3_invoker.py::test_staging_file_skipped_on_failure PASSED [ 38%]
tests/test_cortex_phase3_invoker.py::test_empty_list_returns_empty_result PASSED [ 40%]
tests/test_cortex_phase3_reasoner.py::test_regex_match_picks_capabilities_with_pattern_hit PASSED [ 41%]
tests/test_cortex_phase3_reasoner.py::test_regex_match_uses_re_ignorecase PASSED [ 43%]
tests/test_cortex_phase3_reasoner.py::test_no_regex_match_returns_empty_pool PASSED [ 44%]
tests/test_cortex_phase3_reasoner.py::test_bad_regex_does_not_crash PASSED [ 46%]
tests/test_cortex_phase3_reasoner.py::test_cap5_enforced_when_more_than_five_match PASSED [ 47%]
tests/test_cortex_phase3_reasoner.py::test_cap5_ranking_prefers_more_hits PASSED [ 49%]
tests/test_cortex_phase3_reasoner.py::test_games_relevant_opt_in_adds_game_theory PASSED [ 50%]
tests/test_cortex_phase3_reasoner.py::test_games_relevant_opt_in_skipped_when_no_negotiation_signal PASSED [ 52%]
tests/test_cortex_phase3_reasoner.py::test_games_relevant_false_does_not_opt_in PASSED [ 53%]
tests/test_cortex_phase3_reasoner.py::test_llm_failure_falls_back_to_heuristic PASSED [ 55%]
tests/test_cortex_phase3_reasoner.py::test_cost_tokens_accumulated_from_llm_response PASSED [ 56%]
tests/test_cortex_phase3_reasoner.py::test_llm_response_non_json_falls_back_to_text_summary PASSED [ 58%]
tests/test_cortex_phase3_reasoner.py::test_persist_writes_meta_reason_artifact PASSED [ 59%]
tests/test_cortex_phase3_reasoner.py::test_persist_bumps_cycle_cost PASSED [ 61%]
tests/test_cortex_phase3_reasoner.py::test_no_db_conn_returns_empty_capabilities PASSED [ 62%]
tests/test_cortex_phase3_synthesizer.py::test_load_synthesizer_prompt_uses_db_row PASSED [ 64%]
tests/test_cortex_phase3_synthesizer.py::test_load_synthesizer_prompt_falls_back_when_missing PASSED [ 65%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_from_valid_json_block PASSED [ 67%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_returns_empty_on_missing_block PASSED [ 68%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_returns_empty_on_malformed_json PASSED [ 70%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_returns_empty_on_object_not_list PASSED [ 71%]
tests/test_cortex_phase3_synthesizer.py::test_llm_failure_falls_back_to_safe_proposal PASSED [ 73%]
tests/test_cortex_phase3_synthesizer.py::test_cost_tokens_accumulated_from_response PASSED [ 74%]
tests/test_cortex_phase3_synthesizer.py::test_user_message_includes_signal_and_specialist_outputs PASSED [ 76%]
tests/test_cortex_phase3_synthesizer.py::test_persist_writes_synthesis_artifact_and_flips_status PASSED [ 77%]
tests/test_cortex_phase2_loaders.py::test_vault_unavailable_returns_warning_and_empty_vault_keys PASSED [ 79%]
tests/test_cortex_phase2_loaders.py::test_vault_present_but_matter_dir_missing PASSED [ 80%]
tests/test_cortex_phase2_loaders.py::test_load_phase2_context_happy_path PASSED [ 82%]
tests/test_cortex_phase2_loaders.py::test_read_or_empty_caps_at_max_bytes PASSED [ 83%]
tests/test_cortex_phase2_loaders.py::test_read_or_empty_returns_empty_for_missing PASSED [ 85%]
tests/test_cortex_phase2_loaders.py::test_load_curated_dir_alphabetical PASSED [ 86%]
tests/test_cortex_phase2_loaders.py::test_load_curated_dir_empty_when_missing PASSED [ 88%]
tests/test_cortex_phase2_loaders.py::test_load_cortex_meta_returns_three_keys PASSED [ 89%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_uses_body_preview_not_body PASSED [ 91%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_joins_signal_queue_for_email_messages PASSED [ 92%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_baker_actions_query_present PASSED [ 94%]
tests/test_cortex_phase2_loaders.py::test_all_recent_activity_queries_have_limit PASSED [ 95%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_no_db_returns_empty_lists PASSED [ 97%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_handles_db_exception_gracefully PASSED [ 98%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_serializes_datetimes_to_isoformat PASSED [100%]

============================== 67 passed in 0.73s ==============================
```

Other passing pre-existing test suites: `tests/test_phase6_*` (28 tests), `tests/test_pm_state_write.py`, `tests/test_pm_extraction_robustness.py`, `tests/test_prompt_cache_audit.py`, `tests/test_status_check_expand_migration.py` — all clean post-edit.

## Gate checks

| Gate | Result |
|---|---|
| Syntax check (every modified file) | ✅ `python3 -c "import py_compile; ..."` clean on 10 files |
| Singleton CI guard | ✅ `bash scripts/check_singletons.sh` — `OK: No singleton violations found.` |
| Migration immutability | ✅ `bash scripts/check_applied_migrations.sh` — additive only, no existing lock entries touched |
| Pytest GREEN (affected modules) | ✅ 67/67 PASSED (literal output above) |

## Acceptance criteria

| AC | Status | Evidence |
|---|---|---|
| **A1** Migration applies clean | ✅ | `20260505_api_cost_log_matter_slug.sql` ADD COLUMN IF NOT EXISTS; lock refresh deferred to post-prod-apply per mailbox |
| **A2** `COST_TIERS` list + `COST_ALERT_EUR` alias preserved | ✅ | Test `test_cost_alert_eur_alias_points_at_info_tier` |
| **A3** `log_api_cost` calls in `capability_runner.py` carry `matter_slug` | ✅ | 3 sites updated (run_single line 696, run_streaming line 910, _maybe_store_insight line 1433) + threading propagation through |
| **A4** Tiered alarms fire idempotently | ✅ | DB-backed via `cost_alert_state` PK (alert_date, tier_label); test `test_check_circuit_breaker_fires_each_tier_once_idempotent` covers re-fire suppression. **Manual shadow-env test required post-deploy** for live €30/€60/€100 transition. |
| **A5** `BAKER_COST_ALARMS_ENABLED=false` suppresses tiers but not hard stop | ✅ | Test `test_alarms_disabled_suppresses_tiers_but_not_hard_stop`. **Manual shadow-env test required post-deploy** to confirm Slack-side behavior. |
| **A6** Daily summary posts at 23:55 UTC | ✅ | `triggers/embedded_scheduler.py` registers `daily_cost_summary` CronTrigger; verification next-day after ship per brief §11. |
| **A7** Per-matter attribution works for `capability_runner` sources | ✅ | `matter_slug` threaded through capability_runner + phase3a + phase3c; ~95% `[unattributed]` on day-one expected; follow-up brief stub committed |
| **A8** Cost-control runbook landed | ✅ | `_ops/processes/cost-control-runbook.md` |
| **A9** Existing hard-stop unchanged | ✅ | Tests `test_hard_stop_unchanged_below_threshold_allows` + `test_hard_stop_in_process_dedup_within_same_day` |
| **A10** `feature-dev:code-reviewer` standard pass clean | ⏳ pending | Awaits 4-gate review chain |

## Post-merge verification checklist (for PL)

1. Render auto-deploy from main (typically 3-5 min).
2. Migration runner applies `20260505_api_cost_log_matter_slug.sql` + `20260505b_cost_alert_state.sql` on startup.
3. Refresh `applied_migrations.lock` from prod **after BOTH** this brief's migrations AND any sibling caching-brief migration apply: `DATABASE_URL=$PROD_URL python3 scripts/refresh_applied_migrations_lock.py`.
4. Smoke-test next AO Cortex cycle — verify `api_cost_log` rows for source `capability_runner`, `cortex_phase3a`, `cortex_phase3c` carry the matter slug.
5. A4 manual shadow-env test (push spend past €30 → confirm exactly one Slack ℹ️; push past €60 → exactly one ⚠️; push past €100 → exactly one 🚨; restart service → confirm none re-fire).
6. A5 manual shadow-env test (set `BAKER_COST_ALARMS_ENABLED=false` → push past €30 → no Slack; push past €150 → confirm hard stop still blocks).
7. A6 next-day verification — daily summary post at 23:55 UTC; check Slack post matches Feature 4 schema.

## Heartbeat

12h cadence binding. Next check-in ~2026-05-06T07:50Z (commit-msg-only on b-code branch acceptable).

## Out of scope (explicitly)

- Voyage embedding cost tracking (brief §10).
- Pipeline + agent_loop matter resolution — stubbed at `briefs/BRIEF_PIPELINE_MATTER_RESOLUTION_1.md`.
- Cache-token tracking — owned by sibling `BRIEF_BAKER_PROMPT_CACHING_1` (B1).

---

**Anchor:** Director ratification 2026-05-05 ("go" after compare-and-contrast of code-side vs app-side architect verdicts); brief commit `d086c8d`; mailbox dispatch `96cd7b86`.
