# BRIEF: CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1 — Parallelize Phase 3b specialists + bump cycle cost incrementally

## Context

Step 30 first LIVE AO Cortex cycle (`70c5e634-134a-4e4d-a478-6c8da512f017`) archived `failed` on 2026-05-02 21:33Z because the wall-clock timeout (`CORTEX_CYCLE_TIMEOUT_SECONDS=900`) fired before Phase 4 propose could start. **All 4 selected specialists succeeded** — but they ran sequentially over 13 min, eating the entire cycle budget. Sunk: ~$11.93 / 776K tokens. The agenda content was salvaged by AI Head A from `cortex_phase_outputs` (canonical: `~/baker-vault/wiki/matters/oskolkov/curated/agenda-baden-baden-2026-05-04.md`, vault commit `2be272e`). Step 30 closed as PARTIAL-SUCCESS-VIA-SALVAGE in tracker (commit `308583c`).

Two bugs in `orchestrator/cortex_phase3_invoker.py` block clean Step 31 (first canonical Director GOLD):

**Bug #1 — Sequential specialist execution.** `run_phase3b_invocations` uses an explicit `for` loop with `await _invoke_one(...)` — specialists run one-after-another. With `SPECIALIST_TIMEOUT_S=180s` × 3 attempts × 5 cap = worst-case 45 min, far exceeding the 15-min cycle umbrella. Even success cases (cycle 70c5e634: 4 specialists × 150–330s) eat 13 min of a 15-min budget.

**Bug #2 — Cost roll-up at end of loop.** `_bump_cycle_cost` is called ONCE after the loop completes (line 127). When the outer `asyncio.wait_for(timeout=CYCLE_TIMEOUT_SECONDS)` cancels the task mid-loop, the bump never executes. `cortex_cycles.cost_dollars` stays at the meta-reason value (e.g., $0.07 for cycle 70c5e634, vs actual $11.93 across 4 specialists). Cost observability is broken on every wall-clock-failed cycle.

**Both bugs are surgical, isolated to one file.** This brief gates the canonical first Director GOLD (Stage 2 V1 Step 31) — without it, every AO LIVE cycle blows the budget.

## Estimated time: ~2-3h
## Complexity: Low-Medium
## Prerequisites: None — single-file change, no schema migration, no dependency bumps.

---

## Fix #1: Parallelize Phase 3b specialist invocations

### Problem
Lines 100–128 of `orchestrator/cortex_phase3_invoker.py`:

```python
async def run_phase3b_invocations(...) -> Phase3bResult:
    result = Phase3bResult()
    for slug in capabilities_to_invoke:
        out = await _invoke_one(...)              # ← sequential await
        result.outputs.append(out)
        result.total_cost_tokens += out.cost_tokens
        result.total_cost_dollars += out.cost_dollars
        await _persist_specialist_output(cycle_id, out)

    await _bump_cycle_cost(cycle_id, result.total_cost_tokens, result.total_cost_dollars)
    return result
```

Sequential execution kills cycles even when every specialist succeeds.

### Current State
- File: `orchestrator/cortex_phase3_invoker.py` (~313 lines)
- `run_phase3b_invocations` at lines 100–128 — sequential loop
- `_invoke_one` at lines 159–220 — single specialist with timeout + 2 retries (already concurrency-safe; calls `asyncio.to_thread(runner.run_single, cap, question)`)
- `_get_capability_runner()` at line 69 — returns a fresh `CapabilityRunner` per call (no shared mutable state) ✓ safe to parallelize
- `_persist_specialist_output` at line 228 — borrows PG conn from pool, INSERT, returns
- `_bump_cycle_cost` at line 287 — borrows PG conn, atomic `cost_X = cost_X + %s` UPDATE (race-safe at PG level)
- PG connection pool (`memory/store_back.py:227-228`): `minconn=1, maxconn=5`

### Implementation

Replace the sequential loop with `asyncio.gather`. Wrap each specialist + its persistence + its cost bump in a single async helper so completions are independent and out-of-order safe.

**Step 1 — Add a new helper above `run_phase3b_invocations` (insert at line ~99, before `# Public entry point`):**

```python
async def _invoke_one_with_persist_and_bump(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    capability_slug: str,
    phase2_context: dict,
    db_semaphore: asyncio.Semaphore,
) -> SpecialistOutput:
    """Invoke one capability, then immediately persist + bump cycle cost.

    Per-completion bump (vs end-of-loop) ensures partial cost survives
    mid-cycle cancellation (Bug #2 fix). DB writes are gated by a small
    semaphore to keep concurrent PG borrowers ≤ pool maxconn (5).
    """
    out = await _invoke_one(
        matter_slug=matter_slug,
        signal_text=signal_text,
        capability_slug=capability_slug,
        phase2_context=phase2_context,
    )
    async with db_semaphore:
        await _persist_specialist_output(cycle_id, out)
        if out.cost_tokens or out.cost_dollars:
            await _bump_cycle_cost(cycle_id, out.cost_tokens, out.cost_dollars)
    return out
```

**Step 2 — Replace the body of `run_phase3b_invocations` (lines 100–128):**

```python
async def run_phase3b_invocations(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    capabilities_to_invoke: list[str],
    phase2_context: dict,
) -> Phase3bResult:
    """Invoke each capability concurrently with bounded resilience.

    Per RA-23 Q5: 180s timeout per invocation, 2 retries, fail-forward.
    Concurrent execution keeps total Phase 3b wall-clock bounded by the
    SLOWEST specialist (~180s p99), not the SUM (~750s for cap=5).
    Worst-case Phase 3b wall = 180s timeout × 3 attempts = 540s, fitting
    inside the 900s cycle umbrella with room for Phase 4-6.

    Per-specialist completion immediately persists artifact + bumps
    cortex_cycles cost columns (Bug #2 fix — partial cost survives
    mid-cycle cancellation).
    """
    result = Phase3bResult()

    # PG pool maxconn=5 (memory/store_back.py:227-228). Cap concurrent
    # DB borrowers at 3 to leave headroom for the outer cycle runner
    # and Phase 3c synthesis writes that may overlap with late
    # specialist completions.
    db_semaphore = asyncio.Semaphore(3)

    invoke_tasks = [
        _invoke_one_with_persist_and_bump(
            cycle_id=cycle_id,
            matter_slug=matter_slug,
            signal_text=signal_text,
            capability_slug=slug,
            phase2_context=phase2_context,
            db_semaphore=db_semaphore,
        )
        for slug in capabilities_to_invoke
    ]

    # gather preserves input order in returned list. _invoke_one is
    # fail-forward (returns SpecialistOutput with success=False on
    # retry exhaustion) — exceptions here are unexpected and propagate
    # to Phase 3 outer try/except in cortex_runner.py.
    outputs = await asyncio.gather(*invoke_tasks)

    for out in outputs:
        result.outputs.append(out)
        result.total_cost_tokens += out.cost_tokens
        result.total_cost_dollars += out.cost_dollars

    return result
```

### Key Constraints
- **Do NOT remove** the existing `_invoke_one`, `_persist_specialist_output`, `_bump_cycle_cost` functions — they remain the canonical primitives. Only the ORCHESTRATION around them changes.
- **Do NOT raise** exceptions on individual specialist failure. `_invoke_one` already returns `SpecialistOutput(success=False, ...)` on retry exhaustion — fail-forward semantics are preserved by `gather` since `_invoke_one` never raises (its inner try/except catches both `asyncio.TimeoutError` and bare `Exception`).
- **Do NOT change** `SPECIALIST_TIMEOUT_S` (180s), `SPECIALIST_MAX_RETRIES` (2), or `STAGING_ROOT` constants.
- **Do NOT add** new env vars beyond what already exists.
- **Do NOT remove** the staging curated file write (line 271–284) — Phase 5/1C SSH-mirror depends on it.
- **Order preservation**: `asyncio.gather` returns results in input order. Existing test assertions on `result.outputs[i].capability_slug == expected_caps[i]` continue to hold.

### Verification
After deploy, fire a manual Cortex cycle on a 2-3 specialist matter (NOT oskolkov until Step 31 GOLD candidate identified — use a less-loaded matter or DRY_RUN on oskolkov):

```bash
# DRY_RUN flip on Render env, redeploy, then:
curl -sS -N -X POST https://baker-master.onrender.com/api/cortex/run \
  -H "X-Baker-Key: $BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{"matter_slug":"oskolkov","director_question":"DRY_RUN test of parallel Phase 3b","triggered_by":"director_manual","defer_notification":true}'
```

Expected behavior:
- SSE stream: `phase_output count: N` events arrive in ≤ ~200s (vs ~750s pre-fix)
- `cortex_phase_outputs` rows for `artifact_type='specialist_invocation'` should have `created_at` timestamps within ~30-60s of each other (concurrent), NOT sequentially spaced
- Cycle terminal at `tier_b_pending` (DRY_RUN) within budget

---

## Fix #2: Incremental cost roll-up

### Problem
`_bump_cycle_cost(cycle_id, total_tokens, total_dollars)` is called ONCE at the end of the `for` loop (line 127). If the outer `asyncio.wait_for` cancels mid-loop, this never runs → `cortex_cycles.cost_dollars` stuck at the pre-Phase-3b value.

### Current State
After Fix #1, `_invoke_one_with_persist_and_bump` already calls `_bump_cycle_cost` per-completion (inside the `db_semaphore` block). So Fix #2 is **fully addressed by Fix #1's restructure** — no additional code change needed.

### Implementation
Already covered by Fix #1's `_invoke_one_with_persist_and_bump`. The end-of-loop bump (former line 127) is REMOVED in Fix #1's replacement block.

### Verification
After deploy, query a completed (or even cancelled) cycle:

```sql
-- Per-specialist costs in phase_outputs:
SELECT
    cycle_id,
    payload->>'capability_slug' AS capability,
    payload->>'success' AS success,
    (payload->>'cost_tokens')::int AS spec_tokens,
    (payload->>'cost_dollars')::float AS spec_dollars
FROM cortex_phase_outputs
WHERE cycle_id = '<test_cycle_id>'
  AND artifact_type = 'specialist_invocation'
ORDER BY created_at;

-- Cycle row should reflect SUM of all specialist costs + meta-reason cost:
SELECT cycle_id, current_phase, status, cost_tokens, cost_dollars
FROM cortex_cycles
WHERE cycle_id = '<test_cycle_id>';
```

Expected: `cortex_cycles.cost_dollars` ≈ SUM of `specialist_invocation` costs + meta-reason cost (~$0.07). Even if the cycle was cancelled mid-Phase-3b, `cost_dollars` reflects whatever specialists DID complete.

---

## Files Modified
- `orchestrator/cortex_phase3_invoker.py` — replace sequential loop with concurrent `asyncio.gather` + per-completion persist + per-completion cost bump (~50 lines changed)
- `tests/test_cortex_phase3_invoker.py` — update tests that assert sequential ordering of side effects; add concurrent-execution assertion (~20-40 lines changed)

## Do NOT Touch
- `orchestrator/cortex_runner.py` — outer cycle wrapper unchanged. The 900s `CORTEX_CYCLE_TIMEOUT_SECONDS` umbrella stays.
- `orchestrator/cortex_phase3_reasoner.py` — Phase 3a meta-reason cost bump (lines 320-329) is independent and already works correctly.
- `orchestrator/cortex_phase3_synthesizer.py` — Phase 3c synthesis is downstream of Phase 3b; no changes needed.
- `orchestrator/capability_runner.py` — already concurrency-safe; fresh runner per `_invoke_one` call.
- `orchestrator/cortex_phase4_proposal.py`, `cortex_phase5_act.py`, `cortex_phase6_*.py` — unrelated to bug surface.
- `memory/store_back.py` PG pool — `maxconn=5` stays. Bug #1 fix's `asyncio.Semaphore(3)` keeps concurrent borrowers ≤ pool size.
- `cortex_cycles` / `cortex_phase_outputs` schema — no migration. UPDATE on `cost_X = cost_X + %s` is already atomic at PG level.
- `SPECIALIST_TIMEOUT_S` / `SPECIALIST_MAX_RETRIES` constants — RA-23-ratified values.

## Quality Checkpoints

1. **`python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase3_invoker.py', doraise=True)"`** — syntax clean.
2. **`pytest tests/test_cortex_phase3_invoker.py -v`** — all tests pass. Updated tests should include at least one concurrent-execution assertion (e.g., elapsed time < 1.5x the single-specialist timeout when running 3 specialists concurrently with patched fast `_invoke_one`).
3. **`pytest tests/test_cortex_runner_phase126.py -v`** — runner-level tests still pass (cycle wrapper unchanged but Phase 3b interface untouched, so these should be unaffected).
4. **Singleton CI guard:** `bash scripts/check_singletons.sh` — no new direct constructor calls of `SentinelStoreBack()` or `SentinelRetriever()`.
5. **Manual SSE test in DRY_RUN** (after Render deploy): fire `/api/cortex/run` on a multi-specialist matter, observe `phase_output count: N` SSE events arriving in ≤ ~200s vs. the prior sequential ~750s.
6. **Verify per-completion cost bump**: while a DRY_RUN cycle is mid-Phase-3b, query `cortex_cycles.cost_dollars` — it should be growing as each specialist completes (not flat until the loop ends).
7. **PG pool sanity**: under load, `SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE 'baker%'` should not exceed pool's `maxconn=5`. The `asyncio.Semaphore(3)` enforces this.
8. **Cycle 70c5e634 regression check**: re-fire the AO meeting-agenda question with the same anchor context (DRY_RUN). Expected: cycle terminates at `tier_b_pending` within ~3-5 min total (vs prior 15-min wall-clock kill), cost roll-up matches sum of phase_outputs specialist costs.

## Verification SQL

```sql
-- After test cycle: confirm parallel execution by checking timestamp clustering
SELECT
    cycle_id,
    artifact_type,
    payload->>'capability_slug' AS capability,
    created_at,
    LAG(created_at) OVER (PARTITION BY cycle_id ORDER BY created_at) AS prev_created_at,
    EXTRACT(EPOCH FROM (created_at - LAG(created_at) OVER (PARTITION BY cycle_id ORDER BY created_at))) AS gap_seconds
FROM cortex_phase_outputs
WHERE cycle_id = '<test_cycle_id>'
  AND artifact_type = 'specialist_invocation'
ORDER BY created_at
LIMIT 10;
-- Expected post-fix: gap_seconds between specialists is small (sub-second to few-second),
-- not the 100-300s gaps observed in cycle 70c5e634.

-- Cycle cost roll-up consistency check:
SELECT
    c.cycle_id,
    c.status,
    c.cost_dollars AS cycle_cost,
    COALESCE(SUM((p.payload->>'cost_dollars')::float), 0) +
        COALESCE((SELECT (payload->>'cost_dollars')::float
                  FROM cortex_phase_outputs
                  WHERE cycle_id = c.cycle_id
                    AND artifact_type = 'meta_reason'
                  LIMIT 1), 0) AS sum_phase_outputs_cost,
    c.cost_dollars - (
        COALESCE(SUM((p.payload->>'cost_dollars')::float), 0) +
        COALESCE((SELECT (payload->>'cost_dollars')::float
                  FROM cortex_phase_outputs
                  WHERE cycle_id = c.cycle_id
                    AND artifact_type = 'meta_reason'
                  LIMIT 1), 0)
    ) AS delta
FROM cortex_cycles c
LEFT JOIN cortex_phase_outputs p
    ON p.cycle_id = c.cycle_id
    AND p.artifact_type = 'specialist_invocation'
WHERE c.cycle_id = '<test_cycle_id>'
GROUP BY c.cycle_id, c.status, c.cost_dollars
LIMIT 1;
-- Expected: delta ≈ 0 (cycle row matches sum of phase outputs within float-rounding).
-- Pre-fix: delta would be large negative (~ -$11 for cycle 70c5e634).
```

## Lessons applied (from `tasks/lessons.md`)

- **Lesson #44 cousin** (verify function signatures): All function calls in this brief verified against actual `cortex_phase3_invoker.py` source — `_invoke_one`, `_persist_specialist_output`, `_bump_cycle_cost` signatures match.
- **Lesson on unbounded queries**: All SQL in Quality Checkpoints + Verification has `LIMIT`.
- **Lesson on `conn.rollback()`**: Existing `_persist_specialist_output` (lines 261-265) and `_bump_cycle_cost` (lines 304-308) already have rollback in except blocks. New code reuses them, no new except blocks added.
- **Lesson on don't batch-migrate**: Single file scope. Both bugs share the same surface, so addressing them together is correct (not batching unrelated work).
- **Lesson on Render restart survival**: `asyncio.Semaphore` is process-local — on restart, fresh process gets fresh semaphore. No persistent state. ✓ safe.
- **Lesson on rate limits**: 5 concurrent Anthropic Opus calls may approach per-org TPM limits on lower tiers. Existing 2-retry pattern in `_invoke_one` handles transient 429s. If observed in production: P2 follow-up adds `asyncio.Semaphore(N<5)` around `_invoke_one` itself.

## Source

- Failing cycle: `cortex_cycles.cycle_id = '70c5e634-134a-4e4d-a478-6c8da512f017'` (oskolkov, 2026-05-02 21:18-21:33Z)
- Tracker row: `~/baker-vault/_ops/processes/cortex-stage2-v1-tracker.md` Step 30 (commit `308583c`)
- Salvaged content: `~/baker-vault/wiki/matters/oskolkov/curated/agenda-baden-baden-2026-05-04.md` (commit `2be272e`)
- Live agenda URL: `brisen-docs.onrender.com/ao/agenda-baden-baden-2026-05-04.html`
- Director-curated via two-step HTML Triaga 2026-05-03
