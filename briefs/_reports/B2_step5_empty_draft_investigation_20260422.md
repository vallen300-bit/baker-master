---
role: B2
kind: ship
brief: step5_empty_draft_investigation_1
pr: https://github.com/vallen300-bit/baker-master/pull/42
branch: step5-empty-draft-investigation-1
base: main
verdict: SHIPPED_READY_FOR_REVIEW
date: 2026-04-22
tags: [step5, opus, observability, empty-draft, cortex-t3, kbl-log]
---

# B2 — `STEP5_EMPTY_DRAFT_INVESTIGATION_1` ship report

**Scope:** Bundled observability fix + diagnostic per brief. Two code files (`kbl/steps/step5_opus.py` + test) plus this report. Headline: the 13 stuck rows the brief targets are **not** an empty-draft class; they are downstream of the PR #40 YAML-coercion bug. The emit_log instrumentation still ships because it closes the ghost-class-prevention gap.

---

## Part A — emit_log instrumentation (shipped)

### Before

```
$ grep -c "emit_log" kbl/steps/step5_opus.py
0
$ grep "from kbl.logging" kbl/steps/step5_opus.py
(no output)
```

### After — 8 log points (~10 call sites total)

All sites use the `step6_finalize.py` signature: `emit_log(level, component, signal_id, message)` with `component="step5_opus"`.

| # | Level | Location | file:line | Purpose |
|---|---|---|---|---|
| 1 | INFO | `synthesize()` entry | step5_opus.py:987 | Anchor every trace with `decision`, `primary_matter`, `raw_content_len`. First line for every signal. |
| 2 | INFO | Cost-gate denial | step5_opus.py:1065 | `paused_cost_cap` flip — joinable with `kbl_cost_ledger` for daily-cap analysis. Parallels existing `logger.warning` (kept for stdout). |
| 3 | ERROR | Invalid `step_5_decision` | step5_opus.py:1026 | Step 4 wrote something outside `{SKIP_INBOX, STUB_ONLY, FULL_SYNTHESIS}`. Pipeline-invariant violation; `opus_failed` flip. |
| 4 | WARN | R3 reflip | step5_opus.py:889 | Each `AnthropicUnavailableError` retry, numbered 1/3 → 3/3. Exception type + first 160 chars of message. |
| 5 | INFO | Opus call start | step5_opus.py:852 | Before each `call_opus`. Carries `attempt`, `max_tokens`, `user_len` for correlation with the R3 ladder's prompt shrinkage. |
| 6 | INFO / WARN | Opus call return | step5_opus.py:913-933 | Happy INFO includes `stop_reason`, `input_tokens`, `output_tokens`, `text_len`. **WARN variant fires if `response.text` is empty** — direct bisection signal for PR #40 Part B branch (2) "Opus 200 OK empty content". |
| 7 | ERROR | Opus 4xx | step5_opus.py:866 | `OpusRequestError` — no retry. Exception type + first 160 chars. |
| 8 | INFO / WARN / ERROR | Terminal / draft-written | step5_opus.py:1007, 1107, 1133, 1142 | Stub draft written (INFO, draft_len); R3 exhausted (ERROR, last_err summary); full-synthesis draft written (INFO with draft_len, or **WARN "wrote empty draft (draft_len=0): Step 6 will reject"** if len=0 — the explicit smoking-gun line the brief asked for). |

### Line map

| Section | Before | After |
|---|---|---|
| imports | `from kbl.loop import ...` | **+** `from kbl.logging import emit_log` |
| state constants | 4 `_STATE_*` constants | **+** `_LOG_COMPONENT = "step5_opus"` below `_STATE_PAUSED` |
| `_fire_opus_with_r3` (816-887) | No logging | **+5** emit_log calls: attempt start, 4xx, R3 retry, empty-response WARN, success-return INFO |
| `synthesize()` entry (893) | No logging | **+1** `INFO step5 entry` |
| Stub path (925-937) | No logging | **+1** `INFO stub draft written` |
| Invalid-decision path | No logging | **+1** `ERROR invalid step_5_decision` |
| Cost-gate branch (968-988) | `logger.warning` stdout-only | **+1** `INFO paused_cost_cap` to kbl_log (kept stdout too) |
| R3-exhausted branch | No logging | **+1** `ERROR r3 exhausted` |
| Happy-path draft write | No logging | **+1** `INFO draft written` OR **+1** `WARN wrote empty draft (draft_len=0)` on zero-length |

### Diff summary

```
 kbl/steps/step5_opus.py     | 113 ++++++++++++++++++++++++++++++++-
 tests/test_step5_opus.py    | 167 ++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 280 insertions(+)
```

### Tests — 3 new (pass)

All three mock `emit_log` and assert `call_args_list` contains the right `(level, component, signal_id, message-prefix)` tuples.

| Test | What it locks | Why |
|---|---|---|
| `test_emit_log_skip_inbox_logs_entry_and_stub_written` | SKIP_INBOX path emits `INFO step5 entry` + `INFO stub draft written` with correct component + signal_id. Zero WARN/ERROR. | Stub paths should be log-clean. |
| `test_emit_log_full_synthesis_happy_path_logs_trace_points` | FULL_SYNTHESIS happy path emits 4 INFO anchors (entry, opus call start, opus call return, draft written). `opus call return` carries `stop_reason='end_turn'` + `output_tokens=42`. Zero WARN. | Every live signal trace has at least these 4 lines — enough to bisect cost + capture + retry behavior. |
| `test_emit_log_full_synthesis_empty_response_warns_with_bisection_signal` | Empty `response.text` emits BOTH WARN "empty draft from Opus 200" **and** WARN "wrote empty draft (draft_len=0)" with `stop_reason` + `output_tokens=0`. | Critical: locks in the smoking-gun logs so a future follow-up brief can diagnose from kbl_log alone, no re-run. |

### Focused run

```
$ python -m pytest tests/test_step5_opus.py
============================== 39 passed in 0.41s ==============================
```

---

## Full pytest (no "by inspection")

### Head

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b2
plugins: langsmith-0.7.33, anyio-4.13.0
collected 845 items

tests/test_1m_storeback_verify.py FFFF                                   [  0%]
tests/test_anthropic_client.py .....................s                    [  3%]
tests/test_bridge_alerts_to_signal.py ..................................[  7%]
...
```

### Tail

```
=========================== short test summary info ============================
FAILED tests/test_1m_storeback_verify.py::test_1_dry_run - FileNotFoundError:...
FAILED tests/test_1m_storeback_verify.py::test_2_mock_analysis - ModuleNotFou...
FAILED tests/test_1m_storeback_verify.py::test_3_chunking - ModuleNotFoundErr...
FAILED tests/test_1m_storeback_verify.py::test_4_failure_resilience - ModuleN...
FAILED tests/test_clickup_client.py::TestWriteSafety::test_add_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_create_task_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_post_comment_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_remove_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_update_task_wrong_space_raises
FAILED tests/test_clickup_integration.py::test_tasks_in_database - voyageai.e...
FAILED tests/test_clickup_integration.py::test_qdrant_clickup_collection - vo...
FAILED tests/test_clickup_integration.py::test_watermark_persistence - voyage...
FAILED tests/test_scan_endpoint.py::test_scan_returns_sse_stream - assert 401...
FAILED tests/test_scan_endpoint.py::test_scan_rejects_empty_question - assert...
FAILED tests/test_scan_endpoint.py::test_scan_accepts_history - assert 401 ==...
FAILED tests/test_scan_prompt.py::test_prompt_is_conversational_no_json_requirement
=========== 16 failed, 808 passed, 21 skipped, 19 warnings in 11.50s ===========
```

**Counts:** `16 failed, 808 passed, 21 skipped`. Baseline per brief was `805 passed` → this PR adds 3 tests → expected 808. Exact match. **Zero new failures.** The 16 failures are byte-identical to the main-baseline (voyageai key / scan 401 / `test_1m_storeback_verify` env) and touch none of `kbl/steps/step5_opus.py`, `kbl/logging.py`, or the schema.

---

## Part B — Diagnostic on "13 stuck rows"

### Headline finding (contradicts brief's premise)

**The 13 `finalize_failed` rows are NOT an empty-draft class.** They have real `opus_draft_markdown` content (1524-2570 chars each), full `kbl_cost_ledger` coverage showing Opus answered with content across all 3 R3 attempts, and failed Step 6 on the `deadline` field (PR #40 target) — not on the body-too-short / empty-draft path.

The empty-draft snapshot PR #40 Part B captured (13 rows with `draft_len=0`) has **self-healed** — almost certainly because the Step 5 opus-failed reclaim path (`_process_signal_reclaim_remote`, pipeline_tick.py:522-575) re-runs Step 5, which unconditionally overwrites `opus_draft_markdown`. The re-runs produced content (output_tokens 1854-2838 per attempt, 3 attempts each = 9x non-empty responses per row).

### Q1: Was Opus actually called for the 13 rows?

**Yes, with real output.** `kbl_cost_ledger` with the correct step key `'opus_step5'` (the brief's hypothesized `'step5'` was wrong — actual key verified via `SELECT DISTINCT step FROM kbl_cost_ledger`):

| signal_id | attempts | successes | sum(input_tokens) | sum(output_tokens) |
|---|---|---|---|---|
| 73 | 3 | 3 | 7260 | 2838 |
| 61 | 3 | 3 | 5304 | 1886 |
| 59 | 3 | 3 | 5643 | 2803 |
| 54 | 3 | 3 | 5166 | 2325 |
| 53 | 3 | 3 | 5181 | 2334 |
| 52 | 3 | 3 | 5418 | 1854 |
| 51 | 3 | 3 | 5319 | 2321 |
| 50 | 3 | 3 | 5421 | 2521 |
| 25 | 3 | 3 | 5226 | 2425 |
| 24 | 3 | 3 | 5166 | 2283 |
| 22 | 3 | 3 | 5418 | 2114 |
| 17 | 3 | 3 | ~5000 | ~2400 |
| 10 | 3 | 3 | ~5000 | ~2500 |

All 13 rows: 3 successful Opus attempts with 1500-2900 output tokens total. No zero-output-token rows, no API errors. **Conclusion: branches (1) transient error + (2) Opus empty-content are BOTH ruled out for the current state. Branch (3) capture bug is also ruled out because the drafts are in the column.**

### Q2: Cost anomalies?

No anomalies. Each row is a standard R3-attempted-all-3 profile at roughly:
- triage: 1-6 attempts (earliest rows cycled through Step 1 triage more, consistent with matter reassignment)
- extract: 1-6 attempts
- opus_step5: exactly 3 attempts, all successful, ~$0.10-0.20 total across the 3

The earliest rows (10, 17, 22, 24, 25 — created 2026-04-20 to 2026-04-21) show 6 triage + 6 extract attempts each. Those rows have been cycling through the opus_failed reclaim loop for >12 hours; each cycle re-runs Steps 1-6 with full cost. Cumulative cost for the 13 rows across all attempts ≈ $4-6 (rough estimate from the ledger sums — exact figure requires summing the cost_usd column).

### Q3: Matter-routing correlation

AI Head suspected hagenauer-rg7 over-routing. Confirmed:

| primary_matter | count |
|---|---|
| hagenauer-rg7 | 9 |
| lilienmatt | 2 |
| annaberg | 1 |
| (others) | 1 |

**9 of 13 = 69% routed to hagenauer-rg7.** This is consistent with the brief's note that Step 1 matter-routing may have a hagenauer-rg7 bias. **Noted for Cortex Design §4 (Director territory); no action taken this brief.**

### Finalize field-failure breakdown — the real root cause

```sql
SELECT signal_id, STRING_AGG(DISTINCT SUBSTRING(message FROM '^[^:]+'), ', ') AS fields
  FROM kbl_log WHERE component='finalize' AND level='WARN'
   AND signal_id IN (<13 IDs>) GROUP BY signal_id;
```

| sid | warns | failed fields |
|---|---|---|
| 73 | 3 | **deadline** |
| 61 | 3 | **deadline** |
| 59 | 3 | **deadline** |
| 54 | 3 | **deadline** |
| 53 | 4 | body, **deadline** |
| 52 | 4 | body, **deadline** |
| 51 | 4 | body, **deadline** |
| 50 | 4 | body, **deadline** |
| 25 | 5 | body, **deadline**, source_id |
| 24 | 4 | body, **deadline** |
| 22 | 5 | body, **deadline**, source_id |
| 17 | 5 | body, **deadline**, source_id |
| 10 | 4 | body, **deadline** |

**`deadline` appears on 13 of 13 rows (100%). `source_id` appears on 3 of 13.** Both are covered by PR #40. `body` appears on 9 of 13 — some attempts produce under-300-char body (genuine body-floor failures, tail of the distribution).

---

## Part C — Recovery-path recommendation

### Evaluation of brief's three options

| Option | Recommendation | Reasoning |
|---|---|---|
| **A.** UPDATE to `status='pending'` + re-enter from Step 1 | **Don't.** | Costs another full Step 1→5 pass (~$0.30-0.60/row × 13 = ~$5-8), and Step 5 will produce the same drafts, which will still fail Step 6 deadline validation. **No reason to expect a different outcome.** |
| **B.** Leave terminal. | **Only for rows the Director de-prioritizes.** | Cortex won't see these — but 9 of 13 are hagenauer-rg7 (currently the hottest matter in hot.md) and the drafts are real (1500-2500 chars of actual Opus analysis). Losing them has content cost. |
| **C.** Wait — merge PR #40, deploy, then follow-up replay. | **RECOMMENDED.** | PR #40 fixes `deadline` + `source_id` YAML coercion at the schema layer. Once deployed, a follow-up brief can reset `finalize_retry_count` on these 13 rows (simple UPDATE) and they'll re-enter Step 6, which will NOW validate the existing `opus_draft_markdown` successfully. **No re-run of Step 5 needed** — the drafts are already there and correct; only the Pydantic coercion was broken. |

### Recommended action sequence (for AI Head / Director)

1. Merge PR #40 (STEP6_VALIDATION_HOTFIX_1) — blocked on B3 review.
2. Confirm Render auto-deploy.
3. Merge PR #42 (this PR) — observability for catching a REAL empty-draft event if one happens again.
4. New brief: reset `finalize_retry_count=0` on the 13 rows + UPDATE `status='awaiting_finalize'`. Pipeline picks up on next tick; Step 6 validates the existing drafts; completion should succeed.
5. For the 9-of-13 body-too-short subset, a further follow-up may be needed to investigate whether these specific drafts are legitimately under-300 chars of body (check frontmatter-vs-body split in the raw `opus_draft_markdown`).

### Option B footnote

If the Director decides some of the 13 rows are not worth retrying (e.g. low-value email alerts rather than strategic content), Option B on a subset + Option C on the rest is also clean. The observability from this PR means future decisions of this shape will have full kbl_log evidence.

---

## Out-of-scope findings (flagged only, no action)

1. **hagenauer-rg7 over-routing bias (Step 1 matter-routing):** 9 of 13 stuck rows routed here. Per brief: "Cortex Design §4, Director territory." Not acted on.
2. **step_5_decision routing from Step 4:** no current invalid decisions seen; the log line (#3) is prophylactic.
3. **Body-too-short tail (9 of 13 rows):** this is distinct from the deadline class. Real drafts with short bodies. Likely a Step 5 prompt-tuning issue for certain signal shapes. Out of scope per brief "No Step 5 prompt changes."

## Rule alignment

- **`feedback_no_ship_by_inspection.md`:** full pytest counts quoted literally above (808 / 16 / 21). Head + tail both shown.
- **`feedback_migration_bootstrap_drift.md`:** N/A — no DB columns touched. Only `emit_log` into existing `kbl_log` table, which exists and is already the write target for step6_finalize.
- **`feedback_code_working_dirs.md`:** `~/bm-b2` throughout.
- **Timebox:** ~75 min of the 180 budget. Part A 35 min, Part B 25 min (one-off SQL + analysis), Part C + report 15 min.

## PR

[#42](https://github.com/vallen300-bit/baker-master/pull/42) — reviewer B3. Tier A auto-merge on APPROVE.

— B2
