# CODE_1_RETURN — Anthropic prompt cache TTL audit (diagnostic, no code change)

**B1 → AH1**
**Date:** 2026-05-03
**Dispatch:** AH1 plain-text dispatch in chat (no formal mailbox brief)
**Effort:** ~30 min

## Verdict

**Upgrade material on inter-cycle reuse, especially oskolkov. Hold the flip until post-Step-30 + 1 week observation.**

## Bottom line on the three asked questions

**Q1 — Current cache TTL on baker-master:** **default 5-minute ephemeral.**
- `cache_control={"type": "ephemeral"}` (no `ttl` field) at 4 hot sites:
  - `kbl/anthropic_client.py:238` (central wrapper)
  - `outputs/dashboard.py:67` (Scan stable-prefix)
  - `orchestrator/capability_runner.py:41` (capability blocks)
  - `baker_rag.py:214` (RAG path)
- Only beta header in flight is `context-1m-2025-08-07` (1M context). No `extended-cache-ttl-*` header anywhere.

**Q2 — Cycle gap measurements (last 15 completed cycles, 134 phase gaps):**

| Metric | Value |
|---|---|
| Intra-cycle phase-to-phase **median** gap | **13.6 s** (5-min cache fits) |
| Intra-cycle phase-to-phase **p90** gap | **181.6 s** (~3 min — still fits) |
| Intra-cycle gaps over 5 min | 13/134 (9.7%) |
| Intra-cycle gaps over 1 hr | 11/134 (8.2%) |

Inter-cycle (per matter, oskolkov dominates traffic with 17 cycles / 16 gaps):

| matter | median inter-cycle | within 5min | 5min–1hr | over 1hr |
|---|---|---|---|---|
| **oskolkov** | **1295 s (~21.6 min)** | 4 | **9** | 3 |
| hagenauer-rg7 | ~16.9 h | 0 | 1 | 1 |

Phase-span "median = 300 s" claim from the cycle-level join was the cycle umbrella firing on the 2026-04-28 oskolkov bug-bash batch — **not representative of cache-relevant call gaps**. The 13.6 s intra-phase median is the right number for intra-cycle cache hits.

**Q3 — Action recommendation:**
- **Median intra-cycle gap (13.6 s) sits well inside 5-min default → no urgent action for intra-cycle work.**
- **Median oskolkov inter-cycle gap (~21.6 min) sits in the 5-min-to-1-hr window → 1-hr cache would convert ~9 misses to hits per debug batch, saving ~$4-5 of input tax on the AO PM capability prefix per batch.**
- Steady state is unknown — current data is dominated by the 2026-04-28 evening AO bug-bash. Recommend re-audit after Step 30 LIVE first cycle + 1 week observation, then queue follow-up brief.
- Upgrade path (for the eventual brief): flip `_get_client()` / `call_opus()` in `kbl/anthropic_client.py` to centralize — add `extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"}` (verify exact header string at brief-write time) + `cache_control={"type": "ephemeral", "ttl": "1h"}` on the system block. Cost delta: +0.75× base on first call per matter; reads stay 0.1×; break-even at ≥1 second cycle within 1 hr.

## Full report

`briefs/_reports/B1_anthropic_cache_ttl_audit_20260503.md` — includes per-cycle data tables, cost analysis, data hygiene flags, full upgrade path.

## Non-blockers flagged for AH1

1. `cortex_phase_outputs` shows occasional negative inter-row deltas when sorted by `(phase_order, created_at)` — minor data race, doesn't affect cache verdict.
2. Several cycles closed in a `2026-04-30 23:55:xx` batch sweep — inflates cycle-level `completed_at - started_at`. Phase-span gap analysis is the cleaner signal.
3. Failed-cycle cluster around 250-300s = the 5-min cycle umbrella from `orchestrator/cortex_phase3_invoker.py:111` firing — unrelated to cache TTL.

## No code change in this dispatch.

Per AH1 instructions: surface findings only. AH1 to queue follow-up brief if upgrade warranted.
