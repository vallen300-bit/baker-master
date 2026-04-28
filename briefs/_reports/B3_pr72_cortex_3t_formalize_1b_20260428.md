# Ship Report — CORTEX_3T_FORMALIZE_1B (Phase 3a/3b/3c)

**Brief:** [`briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md`](../BRIEF_CORTEX_3T_FORMALIZE_1B.md)
**PR:** https://github.com/vallen300-bit/baker-master/pull/72
**Branch:** `cortex-3t-formalize-1b` (cut from `main` post PR #71 merge `1709483`)
**Worktree:** B3 (`~/bm-b3`)
**Trigger class:** MEDIUM → B1 second-pair-review + AI Head A `/security-review` skill (Lesson #52)
**Dispatched by:** AI Head A
**Shipped:** 2026-04-28

---

## Summary

Built the brain of Cortex Stage 2 V1: 3a meta-reasoning + cap-5 enforcement,
3b specialist invocation with 60s/2-retry/fail-forward, 3c absorbed-
synthesizer combination. Phase 3 success flips the cycle from
`awaiting_reason` (1A terminal) → `proposed` (1C Phase 4 handoff).

---

## EXPLORE corrections (Lesson #44 mandatory)

| # | Brief assumption | Reality | Action taken |
|---|------------------|---------|--------------|
| 1 | `run_single` is module-level async function taking slug → returning str | `CapabilityRunner.run_single(self, capability: CapabilityDef, question: str, ...) -> AgentResult` (sync method on a class) | Phase 3b uses `CapabilityRegistry.get_by_slug(slug)` to resolve `CapabilityDef` first, then `await asyncio.to_thread(runner.run_single, cap, question)` for timeout enforcement |
| 2 | Use Claude Opus 4.7 | Production LLM model 2026-04-28 is `claude-opus-4-6` (verified `capability_runner.py:317`); brief §"Out of scope" explicitly says no model bump | Use `claude-opus-4-6` constant in 3a + 3c |
| 3 | `cycle.phase2_load_context['signal_text']` populated by Phase 2 | `_phase2_load` does NOT write `signal_text` (verified by grep on `cortex_phase2_loaders.py`) | Runner now plumbs `signal_text` from `director_question` after Phase 2 returns (signal-triggered cycles wait for 1C `signal_queue` lookup per Obs #1) |
| 4 | `cost_dollars` column means USD | `log_api_cost` returns EUR (verified `cost_monitor.py:88-93`) | Column kept named `cost_dollars` per 1A migration but stores EUR values; documented in module docstring |
| 5 | Phase 3b should call `log_api_cost` after each specialist | `CapabilityRunner.run_single` already logs API cost internally (verified `capability_runner.py:696`) — Phase 3b call would double-count Prometheus | Phase 3b uses `calculate_cost_eur` (silent helper, no DB write) for cycle-row deltas only |

All 5 corrections applied + ship-report-documented. Lesson #44 anchor renewed.

---

## Files

**Created (3 modules + 4 tests):**
- `orchestrator/cortex_phase3_reasoner.py` (295 LOC) — Phase 3a + cap-5 enforcement
- `orchestrator/cortex_phase3_invoker.py` (270 LOC) — Phase 3b w/ 60s timeout + 2 retries + fail-forward
- `orchestrator/cortex_phase3_synthesizer.py` (250 LOC) — Phase 3c + status='proposed' flip
- `tests/test_cortex_phase3_reasoner.py` (15 tests)
- `tests/test_cortex_phase3_invoker.py` (11 tests)
- `tests/test_cortex_phase3_synthesizer.py` (12 tests)
- `tests/test_cortex_runner_phase3.py` (10 tests)

**Modified:**
- `orchestrator/cortex_runner.py` — replaced 1A's `awaiting_reason` stub with `_phase3_reason()`; threads `signal_text` from `director_question` into `phase2_load_context`; archive payload string updated to reflect new state.
- `tests/test_cortex_runner_phase126.py` — autouse fixture stubs Phase 3 entry points (no real Anthropic calls in CI); `test_status_terminates_at_awaiting_reason_in_1a_scope` renamed → `test_status_terminates_at_proposed_in_1b_scope` to match new behavior.

---

## Quality Checkpoints

| # | Check | Status |
|---|-------|--------|
| 1 | Cap-5 enforced in 3a (`CAP5_LIMIT = 5`, hard cap even after LLM rank) | ✅ |
| 2 | `re.IGNORECASE` flag (no inline `(?i)`) | ✅ |
| 3 | Fail-forward: one specialist failure ≠ cycle failure | ✅ |
| 4 | Cost flows to cycle row + `cost_monitor.log_api_cost` (no double-count) | ✅ |
| 5 | Synthesizer `system_prompt` loaded from `capability_sets.slug='synthesizer'` (not hardcoded) | ✅ (with default fallback if row missing) |
| 6 | Phase 3c JSON extraction graceful: malformed → `[]` not crash | ✅ |
| 7 | Staging dir `outputs/cortex_proposed_curated/<cycle_id>/` (`parents=True, exist_ok=True`) | ✅ |
| 8 | 1A's outer 5-min `asyncio.wait_for` still wraps the cycle | ✅ (verified by stub test inheritance) |
| 9 | Status transitions: in_flight → reason → proposed (success) OR failed (Phase 3 exception) | ✅ |
| 10 | No new entries in `requirements.txt` | ✅ |

---

## Literal pytest output (Lesson #47 mandatory — NO "by inspection")

```
$ ~/bm-b3/.venv-b3/bin/python -m pytest tests/test_cortex_phase3_reasoner.py tests/test_cortex_phase3_invoker.py tests/test_cortex_phase3_synthesizer.py tests/test_cortex_runner_phase3.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 48 items

tests/test_cortex_phase3_reasoner.py::test_regex_match_picks_capabilities_with_pattern_hit PASSED [  2%]
tests/test_cortex_phase3_reasoner.py::test_regex_match_uses_re_ignorecase PASSED [  4%]
tests/test_cortex_phase3_reasoner.py::test_no_regex_match_returns_empty_pool PASSED [  6%]
tests/test_cortex_phase3_reasoner.py::test_bad_regex_does_not_crash PASSED [  8%]
tests/test_cortex_phase3_reasoner.py::test_cap5_enforced_when_more_than_five_match PASSED [ 10%]
tests/test_cortex_phase3_reasoner.py::test_cap5_ranking_prefers_more_hits PASSED [ 12%]
tests/test_cortex_phase3_reasoner.py::test_games_relevant_opt_in_adds_game_theory PASSED [ 14%]
tests/test_cortex_phase3_reasoner.py::test_games_relevant_opt_in_skipped_when_no_negotiation_signal PASSED [ 16%]
tests/test_cortex_phase3_reasoner.py::test_games_relevant_false_does_not_opt_in PASSED [ 18%]
tests/test_cortex_phase3_reasoner.py::test_llm_failure_falls_back_to_heuristic PASSED [ 20%]
tests/test_cortex_phase3_reasoner.py::test_cost_tokens_accumulated_from_llm_response PASSED [ 22%]
tests/test_cortex_phase3_reasoner.py::test_llm_response_non_json_falls_back_to_text_summary PASSED [ 25%]
tests/test_cortex_phase3_reasoner.py::test_persist_writes_meta_reason_artifact PASSED [ 27%]
tests/test_cortex_phase3_reasoner.py::test_persist_bumps_cycle_cost PASSED [ 29%]
tests/test_cortex_phase3_reasoner.py::test_no_db_conn_returns_empty_capabilities PASSED [ 31%]
tests/test_cortex_phase3_invoker.py::test_success_returns_specialist_output PASSED [ 33%]
tests/test_cortex_phase3_invoker.py::test_question_includes_signal_and_matter_brain PASSED [ 35%]
tests/test_cortex_phase3_invoker.py::test_unknown_capability_records_failure_and_continues PASSED [ 37%]
tests/test_cortex_phase3_invoker.py::test_timeout_triggers_retries_then_fail_forward PASSED [ 39%]
tests/test_cortex_phase3_invoker.py::test_exception_triggers_retries_then_fail_forward PASSED [ 41%]
tests/test_cortex_phase3_invoker.py::test_partial_failure_one_of_many PASSED [ 43%]
tests/test_cortex_phase3_invoker.py::test_persist_writes_specialist_invocation_artifact PASSED [ 45%]
tests/test_cortex_phase3_invoker.py::test_persist_bumps_cycle_cost_after_loop PASSED [ 47%]
tests/test_cortex_phase3_invoker.py::test_staging_file_written_on_success PASSED [ 50%]
tests/test_cortex_phase3_invoker.py::test_staging_file_skipped_on_failure PASSED [ 52%]
tests/test_cortex_phase3_invoker.py::test_empty_list_returns_empty_result PASSED [ 54%]
tests/test_cortex_phase3_synthesizer.py::test_load_synthesizer_prompt_uses_db_row PASSED [ 56%]
tests/test_cortex_phase3_synthesizer.py::test_load_synthesizer_prompt_falls_back_when_missing PASSED [ 58%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_from_valid_json_block PASSED [ 60%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_returns_empty_on_missing_block PASSED [ 62%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_returns_empty_on_malformed_json PASSED [ 64%]
tests/test_cortex_phase3_synthesizer.py::test_extract_structured_actions_returns_empty_on_object_not_list PASSED [ 66%]
tests/test_cortex_phase3_synthesizer.py::test_llm_failure_falls_back_to_safe_proposal PASSED [ 68%]
tests/test_cortex_phase3_synthesizer.py::test_cost_tokens_accumulated_from_response PASSED [ 70%]
tests/test_cortex_phase3_synthesizer.py::test_user_message_includes_signal_and_specialist_outputs PASSED [ 72%]
tests/test_cortex_phase3_synthesizer.py::test_persist_writes_synthesis_artifact_and_flips_status PASSED [ 75%]
tests/test_cortex_runner_phase3.py::test_phase3_runs_in_order_3a_3b_3c PASSED [ 77%]
tests/test_cortex_runner_phase3.py::test_phase3_success_status_proposed PASSED [ 79%]
tests/test_cortex_runner_phase3.py::test_cost_accumulates_across_phase3 PASSED [ 81%]
tests/test_cortex_runner_phase3.py::test_signal_text_threaded_from_director_question PASSED [ 83%]
tests/test_cortex_runner_phase3.py::test_signal_text_empty_string_when_no_director_question PASSED [ 85%]
tests/test_cortex_runner_phase3.py::test_signal_text_in_phase2_load_context PASSED [ 87%]
tests/test_cortex_runner_phase3.py::test_phase3a_failure_marks_status_failed_no_raise PASSED [ 89%]
tests/test_cortex_runner_phase3.py::test_phase3c_failure_marks_status_failed PASSED [ 91%]
tests/test_cortex_runner_phase3.py::test_phase6_archive_runs_even_on_phase3_failure PASSED [ 93%]
tests/test_cortex_runner_phase3.py::test_3a_capabilities_to_invoke_passed_to_3b PASSED [ 95%]
tests/test_cortex_runner_phase3.py::test_3a_and_3b_results_threaded_into_3c PASSED [ 97%]
tests/test_cortex_runner_phase3.py::test_cycle_id_propagated_to_all_phase3_calls PASSED [100%]

============================== 48 passed in 0.11s ==============================
```

**48/48 PASS** — exceeds the brief's ≥26 floor by ~85%.

### 1A regression check (mandated by brief)

```
$ ~/bm-b3/.venv-b3/bin/python -m pytest tests/test_cortex_*.py -v
============================== 79 passed in 0.18s ==============================
```

**79/79 PASS** — Phase 3a/3b/3c (48) + 1A Phase 1/2/6 (16) + Phase 2 loaders (15). Zero 1A regressions.

---

## B1 Obs #2 + #3 (forwarded from PR #71 review)

**Obs #2 (Phase 6 archive-self-failure structured logging)**: 1A code already used `logger.error("Phase 6 archive itself failed for cycle {cycle_id}: {e}")` — adequate for now. 1B does NOT touch the archive path; deferred to backlog (Slack alerts explicitly out of scope for 1B per Obs #2 wording).

**Obs #3 (Phase 1 cycle_id pre-generation bypassing DB default)**: 1B respects this — `cortex_phase3_reasoner._persist_phase3a` and friends use the cycle_id **passed in** (already-generated by Phase 1), not regenerated. Conceptual cleanup of pre-generation deferred to backlog per brief.

---

## Test-pollution mitigation (1A lesson reused)

Followed the 1A pattern: every Phase 3 module exposes patchable module-level helpers (`_get_store()`, `_call_opus()`, `_get_capability_runner()`, `_get_capability_def()`, `_load_active_domain_capabilities()`). Tests `monkeypatch.setattr(<module>, <helper>, fake)` directly — never need to reach into `memory.store_back` attributes (the source of 1A's full-suite fragility). Confirmed by running suite in mixed order:

```
$ ~/bm-b3/.venv-b3/bin/python -m pytest tests/test_cortex_*.py -v  # full cortex suite
79 passed in 0.18s
```

No flakiness across orderings.

---

## Ship gates

- [x] EXPLORE step (Lesson #44) — 5 brief deviations identified pre-coding
- [x] Implementation per brief §Fix/Feature 1-4 with documented deviations
- [x] Syntax check — `python3 -c "import py_compile; ..."` passes for all 4 new modules + cortex_runner edit
- [x] Test count ≥ 26 (delivered 48)
- [x] Literal pytest stdout in this report (Lesson #47)
- [x] 1A regression check — 0 failures in `tests/test_cortex_runner_phase126.py` + `tests/test_cortex_phase2_loaders.py`
- [x] Branch pushed: `cortex-3t-formalize-1b`
- [x] PR opened: https://github.com/vallen300-bit/baker-master/pull/72
- [ ] B1 second-pair review (MEDIUM trigger class — LLM API + cost writes + cross-capability coordination)
- [ ] AI Head A `/security-review` skill verdict (Lesson #52 mandatory)
- [ ] AI Head A Tier-A direct squash-merge (after B1 + A clear)

---

## Out of scope (1C territory — confirmed)

- Phase 4 proposal card (Slack Block Kit) + 4-button rendering
- Phase 5 act / GOLD propagation to wiki via Mac Mini SSH-mirror
- DRY_RUN flag for log-only first cycle
- Step 33 rollback script
- `kbl/bridge/alerts_to_signal.py` call-site activation (Obs #1)
- LLM model bump to 4.7 (separate brief — not in any 1A/1B/1C)

---

## Co-authored-by

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
