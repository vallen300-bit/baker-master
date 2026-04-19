# B2 PR #18 KBL_PIPELINE_SCHEDULER_WIRING review — REDIRECT

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (late afternoon)
**PR:** https://github.com/vallen300-bit/baker-master/pull/18
**Branch head:** `d7312e8` (base `main` @ `29294ab`)
**Brief:** `briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` @ `cdaea58` (v2)
**Verdict:** **REDIRECT** — one missing required test (S1) and one quiet spec deviation on gate ordering (S2). Everything else is clean.

---

## Bottom line

B1 shipped a solid implementation of the architectural split: new
`_process_signal_remote` mirrors Steps 1-6 exactly, Step 7 is
deliberately NOT imported, `main()` is env-gated + circuit-gated,
APScheduler registration matches the existing pattern. The brief's §Scope.6
ssh verification gate has not been executed yet — that's still required
before merge.

But two items from the spec are not fully landed:

- **S1 (must-fix):** `test_remote_variant_stops_at_finalize_failed`
  (§Scope.5 item 7) is missing.
- **S2 (should-fix — pick one):** `main()` runs env gate BEFORE circuit
  checks; brief §Scope.2 explicitly says "after the two circuit checks"
  and §Scope.5 test 5 (`test_main_circuit_breaker_precedes_env_gate`)
  was meant to enforce that order. The order is silently inverted and
  the order-assertion test is also absent.

Both fixes are small-surface amends on the same branch.

---

## S1 — Missing `test_remote_variant_stops_at_finalize_failed`

Brief §Scope.5 item 7 specified:

> `test_remote_variant_stops_at_finalize_failed` — fixture signal routed
> through Step 6 with 3 retries exhausted (terminal `finalize_failed`
> flip committed by Step 6 internally per its docstring);
> `_process_signal_remote` returns cleanly (Step 6 re-raise propagates,
> but caller-owned rollback leaves the Step-6-internal commit intact);
> final status stays `finalize_failed`; Step 7 driver (not-in-this-variant)
> never invoked.

No such test in `tests/test_pipeline_tick.py` for the REMOTE variant.
There is a pre-existing `test_process_signal_step6_finalize_failed_gates_out_step7`
(line 323) but that covers the full `_process_signal` 1-7 path, not
`_process_signal_remote`. The coverage gap is real — if a future refactor
reintroduces a post-Step-6 `awaiting_commit` status assertion to
`_process_signal_remote` (mirroring `_process_signal`'s line 183 gate),
it would silently break the remote variant's finalize_failed path and no
existing test would catch it.

### Concrete fix

Add this test (~25 lines), modeled on the existing `test_process_signal_step6_finalize_failed_gates_out_step7`
but targeting `_process_signal_remote`:

```python
def test_process_signal_remote_stops_at_finalize_failed() -> None:
    """Step 6 internally commits ``finalize_failed`` (3 Opus retries
    exhausted) and returns normally. Remote variant has no post-Step-6
    gate, so it falls through and returns cleanly. Step 7 never
    imported or invoked."""
    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
        post_step6_status="finalize_failed",
    )

    def _step6_terminal_returns(signal_id: int, c: Any) -> None:
        c.commit()  # step-internal finalize_failed flip
        return None

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step6"].side_effect = _step6_terminal_returns
        _process_signal_remote(signal_id=104, conn=conn)

    # 5 orchestrator (Steps 1-5) + 1 step6-internal + 1 orchestrator-post-step6.
    assert conn.commit.call_count == 7
    assert conn.rollback.call_count == 0
    # Step 7 never imported/invoked.
    assert mocks["step7"].call_count == 0
```

---

## S2 — Env gate / circuit check ORDER silently inverted

### What the brief said

§Scope.2 (brief v2):

> Add env gate at top of `main()` (after the two circuit checks):

§Scope.5 test 5:

> `test_main_circuit_breaker_precedes_env_gate` — when
> `anthropic_circuit_open == "true"` OR `cost_circuit_open == "true"`,
> `main()` returns 0 even with `KBL_FLAGS_PIPELINE_ENABLED="true"`, AND
> does NOT call `claim_one_signal`. **Asserts circuit checks run before
> the env-gate (existing order in `main()` lines 197-206) is preserved.**

The brief's intended order: **circuit checks → env gate → claim**.

### What B1 shipped

`kbl/pipeline_tick.py:313-348` order: **env gate → circuit checks → claim**.

No `test_main_circuit_breaker_precedes_env_gate` test exists. Instead
B1 wrote two separate tests — `test_main_respects_anthropic_circuit`
and `test_main_respects_cost_circuit` — that both set
`KBL_FLAGS_PIPELINE_ENABLED=true` + one circuit-open and assert
`mock_claim.call_count == 0`. These pass trivially with either order.
Neither asserts ORDER.

### Why it matters

Functionally both orders are near-identical (both return 0 without
claiming when they should). The only observable difference is in the
disabled-pipeline-with-circuit-open scenario:

| State | Brief order | B1 order |
|-------|-------------|----------|
| `PIPELINE_ENABLED=false`, `anthropic_circuit_open=true` | Emits WARN "Anthropic circuit open", then returns 0 | Returns 0 silently (no circuit WARN) |
| `PIPELINE_ENABLED=false`, circuits clear | "pipeline disabled" INFO log | Same |
| `PIPELINE_ENABLED=true`, circuit open | Emits WARN, returns 0 | Same |
| `PIPELINE_ENABLED=true`, circuits clear | Claims + processes | Same |

B1's order is arguably cleaner — less log noise when the pipeline is
deliberately disabled. The brief's order is arguably more observable
— circuit-open messages still fire as a health signal even when the
pipeline is off.

Either choice is defensible. The problem is that B1 silently picked
the inverse of what was spec'd without documenting the reasoning and
without adjusting the brief or the tests. If AI Head or I hadn't
caught this, the brief and the code would be contradictory on main.

### Concrete fix — pick one

**Option A: restore brief order.** Move the env gate to line 335
(after the cost_circuit check), matching the brief verbatim. Tests
stay green. Write the missing
`test_main_circuit_breaker_precedes_env_gate` with a side-effect
assertion (e.g., `check_alert_dedupe` call count on the anthropic
circuit branch) that fails if the gate hoists back above the circuit
checks.

**Option B: keep B1's order, update brief + tests.** Amend brief
§Scope.2 to say "at top of `main()`, BEFORE the two circuit checks"
and note the log-noise rationale. Rename the missing test to
`test_main_env_gate_precedes_circuit_breaker` with a side-effect
assertion that fires if circuits run before the gate (e.g., assert
`check_alert_dedupe.call_count == 0` when disabled + circuit-open).

**Recommendation: Option B.** B1's order is the better choice for
production — disabled pipelines shouldn't spam circuit-open WARN
messages every 120 s. Update the brief + add the test to lock it in
as a deliberate decision. ~10 lines total across brief + test.

If B1 prefers Option A, also fine — but must add the
order-assertion test (not just the current two outcome-only tests).

---

## N-level notes (non-blocking, record for polish PR)

- **N1. `KBL_PIPELINE_TICK_INTERVAL_SECONDS < 30 s clamp** — B1 added a
  30-second floor at `triggers/embedded_scheduler.py` with WARN on
  clamp. Not spec'd but reasonable defense (prevents accidental
  thundering-herd). Clean implementation.

- **N2. `misfire_grace_time=60`** — exactly what I recommended in the
  brief review. ✓

- **N3. `_kbl_pipeline_tick_job` wrapper** is 9 lines, lazy-imports,
  logs non-zero return at WARN, re-raises exceptions. Good shape.

- **N4. `IntervalTrigger(seconds=...)` positional** — matches the 20+
  existing jobs in `embedded_scheduler.py`. ✓

- **N5. Module docstring rewrite** — N2 from my v1 brief review cleanly
  addressed. Docstring now documents both variants + explicit Inv 9
  callout + "do not call remote from Mac Mini" boundary. Good.

- **N6. §Pre-merge Mac Mini verification (§Scope.6 of brief)** — still
  pending. This PR cannot merge until AI Head OR B1 runs the three
  `ssh macmini` checks and pastes output into the PR. Flag for AI Head
  to execute before auto-merging.

---

## What's right (for the record)

- **Tx-boundary contract preserved** in `_process_signal_remote` —
  identical per-step `try/commit/except/rollback` pattern to
  `_process_signal`. No collapsed commits. ✓
- **Dead `step7_commit` import** NOT added to `_process_signal_remote`
  (my v1 N1 addressed) — explicitly comments the reason. ✓
- **CHANDA Inv 9** — `_process_signal_remote` imports Steps 1-6 only.
  `main()` routes to the remote variant. No path from Render to Step 7.
  Mac Mini poller unchanged. ✓
- **KBL-A stub fully removed** — no `classified-deferred` UPDATE, no
  stub WARN emit_log anywhere. ✓
- **Env gate parsing** — `os.environ.get("KBL_FLAGS_PIPELINE_ENABLED",
  "false").lower() != "true"` → default-closed, case-insensitive, typo-
  resistant. ✓
- **Env docs landed** at §9.4 of `KBL_B_PIPELINE_CODE_BRIEF.md` — table
  with both env vars, defaults, purpose, and "below 30 s clamped"
  notation. Clear. ✓
- **APScheduler params** — `IntervalTrigger(seconds=_kbl_tick_seconds)`
  + `id="kbl_pipeline_tick"` + `max_instances=1` + `coalesce=True` +
  `replace_existing=True` + `misfire_grace_time=60`. All correct and
  consistent with existing jobs. ✓
- **Claim-empty path** — `if signal_id is None: return 0` ✓
- **Exception propagation** — `_process_signal_remote` raises are caught
  at `main()`, emit_log ERROR, then re-raised for APScheduler's listener
  to log. Brief spec'd "propagate" — confirmed. ✓
- **Circuit breaker tests** — two separate tests for anthropic + cost
  circuits, each sets pipeline=enabled + that circuit=open + asserts no
  claim. Passes. (Just doesn't assert ORDER — see S2.)
- **86/86 green claim** — can't independently run tests locally (py3.9
  env, `tools/ingest/extractors.py:275` blocks collection via 3.10+
  union syntax). Code review clean; trusting B1's 86/86 report. CI
  rollup is empty (`gh pr view 18 --json statusCheckRollup` = []); no
  CI configured on this repo.

---

## Dispatch

**REDIRECT.** Two small amends on the same branch:

1. Add `test_remote_variant_stops_at_finalize_failed` (~25 lines).
2. Pick ONE of S2's options: restore brief order + add order-assertion
   test, OR keep current order + update brief §Scope.2 + rename test
   to reflect the new deliberate order.

Plus: AI Head still needs to run the §Scope.6 ssh verification before
auto-merge. That's a brief-level prerequisite, not a code-level fix.

**Recommendation:** B1 ships S2 as Option B (keep env-first, document
the deliberate choice + test). Better production semantics, minimal
diff. Combined with S1 fix: one amend, ~40 lines, I flip to APPROVE in
~10 min.
