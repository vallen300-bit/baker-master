# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-19 (late afternoon, post-B2-redirect)
**Status:** OPEN — PR #18 same-branch amend per B2 REDIRECT

---

## Task: PR #18 amend — one missing test + one order-assertion test swap

B2 REDIRECT at `briefs/_reports/B2_pr18_scheduler_wiring_review_20260419.md`. Two items. Everything else in the PR is clean. ~40 lines total across one test file.

Branch: `kbl-pipeline-scheduler-wiring` (same — no new PR). Head: `d7312e8`.

---

### Item 1 (S1 must-fix): add `test_remote_variant_stops_at_finalize_failed`

Brief §Scope.5 item 7 explicitly required this test. It was missing in your shipped 8 tests. Model it on the existing `test_process_signal_step6_finalize_failed_gates_out_step7` in the same test module.

**What the test asserts:**

- Fixture signal routed into Step 6 where `finalize` exhausts its 3 retries and commits terminal state `finalize_failed` internally (per Step 6's docstring: internal-commit-then-raise).
- Call `_process_signal_remote(signal_id, conn)`.
- Step 6's internal commit of `finalize_failed` survives the caller's rollback (intentional per Step 6 design — R3 retry exhaustion must be durable).
- Final signal status: `finalize_failed`.
- Step 7 mock (if imported anywhere in the test module for the full-path variant) NOT called from the remote variant's code path — but since `_process_signal_remote` has no Step 7 call at all, the assertion is simply that the remote variant propagates the Step-6 raise without attempting any further steps.

**Spec:**

```python
def test_remote_variant_stops_at_finalize_failed(...):
    # Set up signal at awaiting_finalize, Step 6 mock raises after internal
    # terminal commit flip.
    # Call _process_signal_remote(signal_id, conn).
    # Expect Step-6-raised exception to propagate; caller rolls back.
    # Assert final DB status is 'finalize_failed' (Step-6 internal commit survived).
    # Assert no post-Step-6 logic ran (Step 7 is not in this variant; assertion
    # is on call sequence of steps 5→6, with nothing past 6).
```

~25 lines modeled on `test_process_signal_step6_finalize_failed_gates_out_step7`.

---

### Item 2 (S2 should-fix): swap `test_main_circuit_breaker_precedes_env_gate` for `test_main_disabled_silent_when_circuit_open`

Brief v3 at commit `60d653b` ratified your env→circuit order (it is better production hygiene than the original circuit→env). The old test (which would have asserted the v1 order) becomes stale. Replace with the new test from updated brief §Scope.5:

- Set `KBL_FLAGS_PIPELINE_ENABLED` unset OR `"false"`.
- Force both circuits open: `get_state("anthropic_circuit_open") == "true"` OR `get_state("cost_circuit_open") == "true"` (one test per circuit or one parametrized test — your call).
- Call `main()`.
- Mock `check_alert_dedupe` and `emit_log` and assert `call_count == 0` on both (silent).
- Mock `claim_one_signal` and assert `call_count == 0` (gate blocked).
- Assert `main()` returned `0`.

**The key assertion is SILENCE.** Brief's point: when the pipeline is disabled, it should not produce log output for upstream state it is not acting on.

~15 lines. Replace the two existing `test_main_respects_anthropic_circuit` + `test_main_respects_cost_circuit` substitute tests IF you want one parametrized test — else keep the two, and just add the silent-when-disabled variant as a third. Your judgment on test-file cleanliness.

---

### Delivery

- Amend commit on `kbl-pipeline-scheduler-wiring` branch. No new PR.
- Push.
- All tests green (9 new scheduler-wiring tests minimum; full regression still passes).
- Dispatch back: `B1 PR #18 amend shipped — head <SHA>, <N>/<N> tests green including new finalize_failed + disabled-silent-on-circuit. Ready for B2 re-review.`
- ~20-30 min.

### Reviewer

B2 — re-review ~10 min per B2's own estimate.

### After this task

- On B2 APPROVE: AI Head auto-merges PR #18 (Tier A). §Scope.6 Mac Mini verification already posted as PR comment at https://github.com/vallen300-bit/baker-master/pull/18#issuecomment-4276033003 — no blocker.
- After merge: shadow-mode flip unlocks. AI Head asks Director for authorization to set `KBL_FLAGS_PIPELINE_ENABLED=true` on Render (Tier B under new bank-model rule).

---

## Working-tree reminder

Work in `~/bm-b1`. Quit Terminal tab after amend lands — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Brief v3 at 60d653b reflects ratified env→circuit order; amend aligns tests to the new spec + fills the §Scope.5 #7 gap.*
