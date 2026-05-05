# BRIEF: PIPELINE-MATTER-RESOLUTION-1 — extend per-matter spend attribution to pipeline + agent_loop

## Status

**STUB** — opens visibly the AC A7 honest-scope gap left by
`BRIEF_BAKER_COST_INSTRUMENTATION_1`. Not yet ratified, not yet sized.

## Context

`BAKER-COST-INSTRUMENTATION-1` (shipped 2026-05-05) added a `matter_slug`
column to `api_cost_log` and tagged every Cortex path that already had the
slug in scope (`capability_runner`, `capability_runner_streaming`,
`cortex_phase3a`, `cortex_phase3c`, `auto_insight`). Result: per-matter
spend is queryable cleanly for **Cortex sources**.

Two large-volume sources still write `matter_slug=NULL` because the pipeline
does not resolve a matter before invoking Gemini, and the agent loop chat
endpoint doesn't carry a matter context:

- `orchestrator/pipeline.py:531,633` — pipeline tick (Gemini classification +
  draft) — no upstream matter resolution
- `orchestrator/agent.py:2262,2511` — dashboard chat agent loop — no
  detection of matter from question text

On day-one of the ship, expected `[unattributed]` share of the daily
summary is ~95%. The runbook (`_ops/processes/cost-control-runbook.md`)
explicitly mentions this gap so the Director sees it surfaced rather than
hidden.

## Goal

Drive the unattributed share down to <10% by adding matter resolution to the
two missing paths.

## Proposed approach (sketch — needs ratification)

1. **Pipeline:** when `signal_queue.matter_slug` is set on the row being
   processed, propagate it through `_process_signal` → `log_api_cost(...,
   matter_slug=row.matter_slug)`. Where the column is NULL, leave attribution
   as NULL — do **not** introduce a matter classifier here.
2. **Agent loop (dashboard chat):** detect matter via a thin wrapper around
   `kbl/slug_registry.py` keyword scan. Best-effort — pass `None` if no slug
   is mentioned in the question. Avoid an LLM-based classifier.
3. **Tests:** extend `tests/test_cost_alarms.py` with attribution coverage
   for both sources.
4. **Runbook:** update §3 query examples to drop the `source IN (...)`
   constraint once attribution is broadly populated.

## Open questions

- Should pipeline matter resolution happen at `signal_queue` insertion (one
  upstream tag) or at `pipeline.py:531,633` read time?
- Is keyword-based detection on the agent loop good enough, or do we need
  Phase-2 entity resolution (which currently lives only inside Cortex)?
- Acceptable false-positive rate on agent-loop detection — better to leave
  ambiguous calls as `[unattributed]` than to mis-tag.

## Sequencing

After `BAKER-COST-INSTRUMENTATION-1` ships and at least 7 days of
`[unattributed]` share data is available — that observation reframes the
priority (if Cortex spend dominates, this brief is low priority; if pipeline
dominates, it is high priority).

## Reference

- Parent brief: `briefs/BRIEF_BAKER_COST_INSTRUMENTATION_1.md` (AC A7 honest
  scope clause).
- Runbook: `_ops/processes/cost-control-runbook.md` §3.
- Architect post-WRITE review (2026-05-05): "follow-up brief stub
  `BRIEF_PIPELINE_MATTER_RESOLUTION_1.md` opens the gap visibly."
