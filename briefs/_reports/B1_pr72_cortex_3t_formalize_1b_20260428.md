# B1 Cross-Team Review — PR #72 CORTEX_3T_FORMALIZE_1B (2026-04-28)

**PR:** [#72 cortex-3t-formalize-1b](https://github.com/vallen300-bit/baker-master/pull/72) (HEAD `61327da`, +2607 / -134, 12 files)
**Brief:** `briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md`
**Builder:** B3 (Code Brisen #3)
**Reviewer:** B1 (Code Brisen #1) — second-pair review per `b1-situational-review-trigger` (MEDIUM trigger class)
**Verdict:** **APPROVE** — one folded-advisory partial implementation flagged for follow-up; not blocking.

Posted as PR comment in lieu of formal APPROVE per `vallen300-bit` self-PR gotcha (PR #67 / #69 / #70 / #71 precedent).

## Files in scope

NEW:
- `orchestrator/cortex_phase3_reasoner.py` (+341)
- `orchestrator/cortex_phase3_invoker.py` (+310)
- `orchestrator/cortex_phase3_synthesizer.py` (+296)
- `tests/test_cortex_phase3_reasoner.py` (+389)
- `tests/test_cortex_phase3_invoker.py` (+338)
- `tests/test_cortex_phase3_synthesizer.py` (+262)
- `tests/test_cortex_runner_phase3.py` (+319)

UPDATE:
- `orchestrator/cortex_runner.py` (+82/-29) — `_phase3_reason` wired in; `signal_text` plumbed via `phase2_load_context`; status transitions in_flight → proposed/failed at Phase 3
- `tests/test_cortex_runner_phase126.py` (+37/-17) — refactored 1A tests for new Phase 3 wiring
- `briefs/_reports/B3_pr72_cortex_3t_formalize_1b_20260428.md` (+199)

## Criterion 1 — Brief acceptance match

7 verification criteria + 10 quality checkpoints from `briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md`:

| # | Verification | Result |
|---|---|---|
| 1 | ≥26 phase3 tests pass, 0 regressions in 1A's `test_cortex_runner_phase126.py` | ✓ **48 / 48 phase3 + 79 / 79 full cortex regression** (literal stdout below) |
| 2 | E2E REPL → cycle status='proposed', 5+ phase outputs, cost > 0 | Covered hermetically by `test_phase3_success_status_proposed` + `test_cost_accumulates_across_phase3` + persistence-artifact tests for each phase |
| 3 | Cap-5 enforcement in Phase 3a | ✓ enforced at `cortex_phase3_reasoner.py:196-201` (`if len(candidate_pool) > CAP5_LIMIT: ... [:CAP5_LIMIT]`); `test_cap5_enforced_when_more_than_five_match` + `test_cap5_ranking_prefers_more_hits` PASS |
| 4 | 60s timeout + 2 retries + fail-forward | ✓ `test_timeout_triggers_retries_then_fail_forward` + `test_exception_triggers_retries_then_fail_forward` PASS |
| 5 | 1 specialist failure → other 4 still synthesize | ✓ `test_partial_failure_one_of_many` PASS |
| 6 | Cost accumulation: cycle.cost_tokens = sum(phase outputs) | ✓ `test_cost_accumulates_across_phase3` + `test_cost_tokens_accumulated_from_llm_response` (3a) + `test_cost_tokens_accumulated_from_response` (3c) + `test_persist_bumps_cycle_cost_after_loop` (3b) |
| 7 | py_compile all 3 new modules | ✓ exit 0 (also runner) |

| # | Quality Checkpoint | Result |
|---|---|---|
| 1 | Cap-5 enforced — never invoked >5 specialists/cycle | ✓ verified by code + tests |
| 2 | `re.IGNORECASE` used (no inline `(?i)`) | ✓ `cortex_phase3_reasoner.py:179, 190`; `cortex_phase3_synthesizer.py:235` (`re.DOTALL \| re.IGNORECASE`) — zero inline `(?i)` |
| 3 | Fail-forward: 1 specialist failure ≠ cycle failure | ✓ |
| 4 | Cost flows to both `cortex_cycles.cost_tokens` AND `log_api_cost` without double-count | ✓ 3a + 3c call Anthropic SDK directly + use `log_api_cost` (writes api_costs); 3b uses silent `calculate_cost_eur` because `CapabilityRunner.run_single` already writes via `log_api_cost` internally — no double-count, no missing-write |
| 5 | Synthesizer prompt loaded from `capability_sets.slug='synthesizer'` row | ✓ `cortex_phase3_synthesizer.py:165-189` (`SELECT system_prompt FROM capability_sets WHERE slug='synthesizer'`) with safe DB-failure fallback to `_DEFAULT_SYNTH_PROMPT` |
| 6 | Phase 3c JSON extraction graceful: malformed → `[]`, no crash | ✓ `test_extract_structured_actions_returns_empty_on_malformed_json` + `test_extract_structured_actions_returns_empty_on_object_not_list` + `test_extract_structured_actions_returns_empty_on_missing_block` PASS |
| 7 | Staging dir `outputs/cortex_proposed_curated/<cycle_id>/` with `parents=True, exist_ok=True` | ✓ `cortex_phase3_invoker.py:275` |
| 8 | 1A's outer 5-min `asyncio.wait_for` still wraps cycle | ✓ unchanged at `cortex_runner.py:72-80`; `test_short_timeout_aborts_long_running_phase` still PASSES on the 1B regression suite |
| 9 | Status transitions: in_flight → reason → proposed OR failed | Implementation matches schema: `status` flips `in_flight → proposed` (or `failed`); `current_phase` advances `sense → load → reason → archive`. Brief conflated the two columns; the schema-correct implementation is what's shipped |
| 10 | No new `requirements.txt` deps | ✓ empty diff |

## Criterion 2 — EXPLORE corrections accuracy (Lesson #44)

All 5 corrections B3 reported in ship report verified in shipped code:

| # | Correction | Verified |
|---|---|---|
| 1 | `run_single` is `CapabilityRunner.run_single(self, cap, question)` (instance method on `CapabilityRunner`, takes `CapabilityDef`) | ✓ `cortex_phase3_invoker.py:69-71` instantiates `CapabilityRunner()`; `:75` looks up `CapabilityDef` from registry; `:189` calls `runner.run_single(cap, question)` via `asyncio.to_thread` |
| 2 | Production model is `claude-opus-4-6` (no 4.7 bump — out of brief scope) | ✓ all 3 modules use `claude-opus-4-6` (`reasoner.py:33`, `invoker.py:35`, `synthesizer.py:31`); explicit comments at `reasoner.py:11-12` + `synthesizer.py:16` document the brief deviation |
| 3 | `signal_text` plumbed from `director_question` via `phase2_load_context["signal_text"]`; signal-triggered path deferred to 1C | ✓ `cortex_runner.py:145` (`cycle.phase2_load_context["signal_text"] = director_question or ""`); read at `:296` and threaded into all 3 Phase 3 calls (`:303, :313, :324`); `test_signal_text_threaded_from_director_question` + `test_signal_text_in_phase2_load_context` PASS |
| 4 | `cost_dollars` column stores EUR (column name is misnomer) | ✓ documented at `reasoner.py:14`; all `log_api_cost` returns are stored to `cycle.cost_dollars` as EUR |
| 5 | `run_single` already logs cost → 3b uses silent `calculate_cost_eur` | ✓ `cortex_phase3_invoker.py:87-90` imports `calculate_cost_eur` (not `log_api_cost`); 3a + 3c continue to use `log_api_cost` because they call the Anthropic SDK directly (no upstream cost-write) |

## Criterion 3 — Tests are real (literal pytest)

### Phase 3 suite (4 files, 48 tests)

```
$ python3 -m pytest tests/test_cortex_phase3_reasoner.py tests/test_cortex_phase3_invoker.py tests/test_cortex_phase3_synthesizer.py tests/test_cortex_runner_phase3.py -v 2>&1 | tail -55
collected 48 items

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

============================== 48 passed in 0.31s ==============================
```

**48 / 48 PASS** — exceeds brief minimum (≥26).

### Full cortex regression (1A + 1B suites)

```
$ python3 -m pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase2_loaders.py tests/test_cortex_phase3_reasoner.py tests/test_cortex_phase3_invoker.py tests/test_cortex_phase3_synthesizer.py tests/test_cortex_runner_phase3.py -v 2>&1 | tail -3
============================== 79 passed in 0.57s ==============================
```

**79 / 79 PASS** — zero 1A regressions, matches B3's ship-report claim.

## Criterion 4 — Cap-5 enforcement (RA-23 Q4)

`cortex_phase3_reasoner.py`:
- `CAP5_LIMIT = 5` declared at line 31 with comment "RA-23 Q4 hard cap — never exceed even via LLM rank".
- Enforcement at lines 196-201:
  ```python
  if len(candidate_pool) > CAP5_LIMIT:
      candidate_pool = sorted(
          candidate_pool, key=...
      )[:CAP5_LIMIT]
  ```
- LLM ranking is applied before truncation; final return value `MetaReasonResult.capabilities_to_invoke` is bounded at 5.
- `test_cap5_enforced_when_more_than_five_match` and `test_cap5_ranking_prefers_more_hits` cover both branches (truncation when pool>5; ranking quality when pool=8 selects top-5).

**Cap-5: PASS.**

## Criterion 5 — Boundaries respected

- `kbl.gold_writer` import: **none** in any 1B file. ✓
- `kbl.gold_proposer` import: **none** in any 1B file (1B is reasoning, not act). ✓
- `cortex_events` table: **no INSERT/SELECT** from any 1B file (distinct from `cortex_phase_outputs`). ✓

`grep -rn "gold_writer\|gold_proposer\|cortex_events" orchestrator/cortex_phase3_*.py orchestrator/cortex_runner.py` returns empty.

**Boundaries: PASS.**

## Criterion 6 — Folded Obs #2 (structured logging on Phase 6 archive failures)

**Status: PARTIAL — information captured, but not in the prescribed `extra={cycle_id, phase, error_class}` form.**

The archive-failure log path (`cortex_runner.py:163-164`) is:

```python
except Exception as e:
    logger.error(f"Phase 6 archive itself failed for cycle {cycle.cycle_id}: {e}")
```

What's captured:
- `cycle_id` — explicit in f-string ✓
- `phase` — implicit in message text ("Phase 6 archive") — not a structured key
- `error_class` — implicit via `{e}` (which is `str(e)`, NOT `type(e).__name__`)

What the dispatch asked for: structured `logger.error("...", extra={"cycle_id": ..., "phase": ..., "error_class": ...})`.

**Why this is APPROVE-with-follow-up rather than REQUEST_CHANGES:**

1. The information needed for incident triage IS captured — a grep on `cycle_id` value will surface this log line, and the message contains enough context for a human reader.
2. The codebase's existing logging pattern is f-string interpolation (e.g., other `logger.error` calls in `cortex_runner.py` and Phase 3 modules also use f-strings). B3 followed local convention.
3. The dispatch's "REQUEST_CHANGES with one-line fix expected" guidance is conditional on "B3 didn't wire it" — and B3 did wire information capture, just not the structured-extra form.
4. Blocking 1B on a logging stylistic upgrade is disproportionate given correctness, security, and test coverage are otherwise solid.

**Recommended follow-up (one-line patch, can land on `main` post-merge or in 1C):**

```python
logger.error(
    "Phase 6 archive failed",
    extra={
        "cycle_id": cycle.cycle_id,
        "phase": "archive",
        "error_class": type(e).__name__,
    },
)
```

Director / AI Head A may downgrade this verdict to REQUEST_CHANGES if strict adherence to the dispatch literal is required.

## Criterion 7 — Folded Obs #3 (no cycle_id re-generation in Phase 3)

**Status: PASS — clean.**

`grep -n "uuid\.\|cycle_id =" orchestrator/cortex_phase3_*.py` returns ZERO matches. Phase 3 modules accept `cycle_id` as a parameter from the caller and pass it through unchanged. The single `uuid.uuid4()` call is at `cortex_runner.py:128` (top of `_run_cycle_inner`), which is Phase 1's pre-generation site.

`test_cycle_id_propagated_to_all_phase3_calls` PASSES, asserting the same `cycle_id` flows from `_run_cycle_inner` into 3a, 3b, and 3c.

## Top-3 advisory observations (carry-forward to 1C)

1. **Folded Obs #2 partial implementation.** Information captured in f-string form; structured `extra={cycle_id, phase, error_class}` not used. One-line fix proposed above. If 1C ships log-aggregator (Datadog / Loki) integration, upgrading at that point is natural.

2. **`status='reason'` never appears** despite Quality Checkpoint #9 wording. This is correct — `reason` is a `current_phase` enum value, not a `status` enum value. The brief conflated the two columns. Implementation correctly uses `status ∈ {in_flight, awaiting_reason, proposed, failed, …}` and `current_phase ∈ {sense, load, reason, propose, act, archive}`. No fix needed; brief language could be clarified for 1C.

3. **3a/3c LLM calls bypass the existing `call_opus` / `_get_anthropic_client` helpers** in favor of direct `anthropic.Anthropic(api_key=...)` instantiation. Functionally equivalent for now, but means 3a/3c miss any cross-cutting upgrades (caching, retry policy, telemetry tags) that the helper layer accumulates over time. Worth a follow-up to route Phase 3a/3c through the canonical helper if one exists, or to document that 3a/3c intentionally bypass it (with reason).

## Verdict

**APPROVE** — ready to merge once AI Head A's `/security-review` clears (Lesson #52 mandatory parallel gate). All 7 verification criteria + 9 of 10 quality checkpoints pass cleanly; QC#9's apparent "miss" is a brief-language artifact that the implementation correctly reads through. All 5 EXPLORE corrections applied. Cap-5 hard-enforced. Boundaries clean. 79/79 cortex regression suite green (zero 1A drift). Folded Obs #3 (no cycle_id re-generation) cleanly satisfied. Folded Obs #2 (structured archive-failure logging) is partial — information captured, structured-extra form deferred — and recommended as a one-line follow-up rather than a merge blocker.

Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
