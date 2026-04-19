# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #14 STEP5-OPUS-IMPL shipped at `8225d0f`. B2 review filed (REDIRECT @ `6c3e833`).
**Task posted:** 2026-04-19 (afternoon)
**Status:** OPEN — one S1 test-gap fix on PR #14

---

## Task: PR14-S1-FIX — Add `tests/test_pipeline_tick.py` for tx-boundary contract

**Source:** B2's PR #14 review @ `6c3e833` — S1.

### Why

`_process_signal` orchestrator (77 lines in `kbl/pipeline_tick.py`) is the Task K YELLOW remediation — the caller-owns-commit tx-boundary contract made concrete. B2's critical spine verifications all passed (prompt cache, cost derivation, error split, R3 ladder, circuit breaker, etc.) EXCEPT the orchestrator itself has zero test coverage. Dispatch brief point 19 explicitly required MagicMock-conn tests on commit/rollback call counts + order + INSERT/UPDATE sequences. Missing = REDIRECT.

### Scope

**IN**

1. **`tests/test_pipeline_tick.py`** — new file, ~100-150 lines per B2's inline estimate.

2. **Mirror the `_mock_conn` pattern you already use** in `tests/test_step5_opus.py`. Don't invent a new helper — lift or share what's there.

3. **Test coverage (~5-8 tests):**

   - **Happy path — all 5 steps succeed:** `_process_signal` calls Step 1 → 2 → 3 → 4 → 5 in order; each step's writes land; final `conn.commit()` fires exactly once at end; `conn.rollback()` NOT called. Assert call order via `mock.call_args_list` or `MagicMock.mock_calls`.

   - **Failure at Step 1 (pre-commit):** Step 1 raises `TriageParseError` in the middle; orchestrator catches; `conn.rollback()` fires; no subsequent steps called; no `conn.commit()`. Exception propagates or is swallowed per orchestrator design — verify whichever B1 chose.

   - **Failure at Step 2:** Step 2 raises `ResolverError`; all-or-nothing — Steps 1's writes must roll back too (single transaction). Assert `rollback()` fires; no commit. Steps 3-5 not called.

   - **Failure at Step 5 with R3 exhaustion:** Step 5 raises `AnthropicUnavailableError` 3 times (R3 exhausted), final state `opus_failed` lands via internal-commit pattern. Orchestrator-level `commit()` should still fire to seal the failure state. Verify this matches the contract's point 5 (step MAY internally commit to preserve failure-state writes).

   - **Cost-cap paused path (Step 5 CostDecision.DAILY_CAP_EXCEEDED):** Step 5 writes `state='paused_cost_cap'` and returns without raising. Orchestrator commits normally. No R3. Signal re-entered next day.

   - **Tx-boundary contract — commit-count invariant:** across all above paths, exactly one `conn.commit()` per `_process_signal` call (modulo the documented step-internal failure-state commits). No orphan commits. Use `_mock_conn.commit.call_count`.

   - **Tx-boundary contract — rollback-count invariant:** on any unhandled exception path, exactly one `conn.rollback()`. No double-rollback, no rollback-after-commit.

   - **Stop at `awaiting_finalize`:** after successful Step 5, orchestrator returns; Step 6/7 not called (they don't exist yet); assert no attempt.

4. **No production code changes.** Only the test file. If you find a tx-boundary bug while writing the test, stop and flag — do NOT quietly fix it in this amend. Integrity of the audit chain.

### Nice-to-haves (DEFER — do NOT apply now)

B2's N1-N5 all deferrable:
- N1 UTC-symmetric SQL
- N2 dead CB probe machinery
- N3 Inv 3 docstring overclaim on stub paths
- N4 commit-before-raise silent-swallow
- N5 3 ledger rows on R3 exhaust (B1 deliberate — keep)

Track for a later polish PR. Skip for this amend.

### CHANDA pre-push

- **Q1 Loop Test:** adding tests only, no Leg touched. Pass.
- **Q2 Wish Test:** serves wish — tx-boundary contract under explicit test = CI catches orchestrator drift. Pass.

### Branch + PR

- **Branch:** `step5-opus-impl` (same PR #14).
- **Amend as additional commit** on top of `8225d0f`. Do NOT open new PR.
- **PR #14 head advances** — B2 S1 delta re-review as fast APPROVE.

### Timeline

~30-45 min (test file + MagicMock wiring + run suite + commit + push).

### Dispatch back

> B1 PR14-S1-FIX shipped — PR #14 head advanced to `<SHA>`, tests/test_pipeline_tick.py added with <N> tests covering tx-boundary contract, `<N>`/`<N>` total tests green. Ready for B2 S1 delta APPROVE.

---

## After this task

On B2 APPROVE: I auto-merge PR #14.

Next dispatch to you: **STEP6-FINALIZE-IMPL** per B3's spec at `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` (AI Head resolves 8 OQs first, then dispatches). ~60 min.

---

*Posted 2026-04-19 by AI Head. Tight S1 test-gap fix. N1-N5 nice-to-haves parked for Phase 2 polish.*
