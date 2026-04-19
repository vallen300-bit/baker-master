# B2 PR #18 KBL_PIPELINE_SCHEDULER_WIRING re-review post-amend — APPROVE

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (late afternoon)
**PR:** https://github.com/vallen300-bit/baker-master/pull/18
**Branch head:** `27c3db4` (amend from `d7312e8`)
**Prior review:** `briefs/_reports/B2_pr18_scheduler_wiring_review_20260419.md` @ `5eead3f` (REDIRECT S1+S2)
**Brief:** `briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` @ `60d653b` (v3 — Option B ratified)
**Verdict:** **APPROVE** — both redirects landed exactly as prescribed; independently verified 22/22 green locally.

---

## Amend diff — surgical and tight

`git diff d7312e8..27c3db4 --stat`:

```
 tests/test_pipeline_tick.py | 87 +++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 87 insertions(+)
```

**One file, +87/-0, zero drive-by.** No production-code delta (`kbl/pipeline_tick.py` and `triggers/embedded_scheduler.py` both untouched in this amend — confirmed via `git diff d7312e8..27c3db4 -- kbl/pipeline_tick.py triggers/embedded_scheduler.py` → empty). Brief `KBL_B_PIPELINE_CODE_BRIEF.md` also untouched. Correct surface for a test-only fix.

---

## S1 — `test_remote_variant_stops_at_finalize_failed` ✓

Landed at `tests/test_pipeline_tick.py:634-671`. Cleanly mirrors the
existing precedent `test_process_signal_step6_terminal_flip_internal_commit_then_rollback`
(line 376) — same step-internal-commit-then-raise pattern — but
targets `_process_signal_remote` instead of `_process_signal`, which
is exactly the coverage gap I flagged in the initial review.

Assertion shape (verified):

| Assertion | Value | Correct? |
|-----------|-------|----------|
| `conn.commit.call_count` | `6` | ✓ 5 orchestrator (steps 1-5) + 1 step-internal finalize_failed flip |
| `conn.rollback.call_count` | `1` | ✓ caller rolls back Step-6 fragment on FinalizationError |
| `mocks["step6"].assert_called_once_with(201, conn)` | called | ✓ |
| `mocks["step7"].call_count == 0` | 0 | ✓ proves remote variant never touches Step 7 — §Scope.5 #7 explicit assertion |
| `pytest.raises(FinalizationError, match="terminal")` | caught | ✓ raise propagates out of `_process_signal_remote` correctly |

The docstring explains the semantic: "the step-internal commit has
already sealed the terminal-state flip" — correct PG-level behavior.
This is the exact test I prescribed, written slightly cleaner than my
proposed version (uses the raise-variant rather than return-None
variant, which actually matches Step 6's real production path more
faithfully per the existing precedent at line 376).

---

## S2 — `test_main_disabled_silent_when_circuit_open` ✓

Landed at `tests/test_pipeline_tick.py:673-718`. Brief v3 at `60d653b`
already ratified Option B (env-first order) + renamed the test per
that ratification; B1's test matches the v3 spec exactly.

Assertion shape (verified):

| Assertion | Value | Why it's the cleanest order-proof |
|-----------|-------|-----------------------------------|
| `mock_state.call_count == 0` | 0 | **This is the order assertion.** If env gate ran AFTER circuits, `get_state` would have been called twice (one per circuit). Zero calls proves env gate short-circuits first. |
| `mock_dedupe.call_count == 0` | 0 | silence |
| `mock_emit.call_count == 0` | 0 | silence |
| `mock_claim.call_count == 0` | 0 | gate blocked |
| `mock_conn_ctx.call_count == 0` | 0 | bonus — no DB connection opened |
| `rc == 0` | 0 | clean return |

Double-test bonus: the test runs the assertion block twice — once
with `delenv` (default "false") and once with explicit
`setenv("KBL_FLAGS_PIPELINE_ENABLED", "false")` — proving the two
paths are identically silent. Nice defensive equivalence proof for
the env-default semantics.

This is a stronger test than the v1 brief's
`test_main_circuit_breaker_precedes_env_gate` would have been — the
`mock_state.call_count == 0` line directly proves the order without
any indirect side-effect chain. Excellent implementation.

---

## Independent test verification — 22/22 PASSED locally

`py3.9` extractors.py blocker from my prior review applies to the
full suite collection. I bypassed it by scoping pytest to just
`tests/test_pipeline_tick.py` — which has its own imports and does
not touch the broken module.

```
$ python3 -m pytest tests/test_pipeline_tick.py -v --tb=short
...
tests/test_pipeline_tick.py::test_remote_variant_stops_at_finalize_failed PASSED [ 95%]
tests/test_pipeline_tick.py::test_main_disabled_silent_when_circuit_open PASSED [100%]
============================== 22 passed in 0.24s ==============================
```

Full file green, including both new tests. This is independent
verification — not trust-based on B1's 22/22 claim. The 88/88 full
KBL-suite number I'm still trusting (B1 reports it; collection
blocked here for the suite-level run) but the two amend-specific
tests are confirmed green on my machine.

---

## Brief v3 consistency check ✓

`briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` @ `60d653b`:

- §Scope.2 line 56: "Add env gate at top of `main()` **BEFORE** the
  two circuit checks (env → circuit → claim)." ✓ ratified per Option
  B recommendation.
- §Scope.5 test #5 line 91: renamed to
  `test_main_disabled_silent_when_circuit_open` with explicit
  `check_alert_dedupe` + `emit_log` + `claim_one_signal` zero-count
  assertions. ✓ matches B1's test verbatim.
- §Scope.5 test #7 line 93: `test_remote_variant_stops_at_finalize_failed`
  remains in the test list. ✓ matches B1's new test.

Brief and code are now consistent. The v1 order-inversion landmine is
retired.

---

## §Scope.6 Mac Mini verification — PASS (per PR comment)

AI Head posted the 3-check audit result to PR #18 comment thread
(<https://github.com/vallen300-bit/baker-master/pull/18#issuecomment-4276033003>).
Output verified via `gh api`:

- **Check 1 — poller plist `ProgramArguments`:** invokes
  `/Users/dimitry/baker-pipeline/poller-wrapper.sh`. ✓
- **Check 2 — `poller-wrapper.sh` tail:** sources `~/.kbl.env`, exports
  `BAKER_VAULT_PATH` + `MAC_MINI_POLLER_BATCH`, execs
  `/usr/bin/python3 ~/baker-pipeline/poller.py`. ✓
- **Check 3 — `poller.py` imports line 17:** `from kbl.steps.step7_commit
  import commit as step7_commit`. ✓ Step 7 still lives on Mac Mini and
  owns its invocation.

**Interpretation:** Mac Mini poller is Step-7-only; PR #18 will not
orphan Step 7. Inv 9 holds — Render handles Steps 1-6, Mac Mini
handles Step 7 exclusively.

---

## CI / mergeable note

`gh pr view 18 --json mergeable,state,statusCheckRollup` at the time
of review:

```
{"headRefOid":"27c3db4...","mergeable":"UNKNOWN","state":"OPEN","statusCheckRollup":[]}
```

Empty rollup = no CI configured. `UNKNOWN` mergeable = GitHub
not-yet-computed (same as PR #17 pre-merge). AI Head should re-poll
once before auto-merging; if it stays `UNKNOWN`, a fresh PR-page load
usually nudges it to `MERGEABLE` within ~30 s.

---

## What's right (rolled forward from initial review)

All the positive items I flagged in the initial review remain intact
(no amend changes to production code):

- `_process_signal_remote` Steps 1-6-only, no `step7_commit` import. ✓
- Tx-boundary contract preserved — per-step commit/rollback. ✓
- KBL-A stub fully removed. ✓
- Env gate default-closed, case-insensitive parse. ✓
- APScheduler params: `id`, `max_instances=1`, `coalesce=True`,
  `replace_existing=True`, `misfire_grace_time=60`. ✓
- `IntervalTrigger(seconds=...)` positional — matches `embedded_scheduler.py`
  convention. ✓
- `_kbl_pipeline_tick_job` wrapper good shape. ✓
- Module docstring documents both variants + Inv 9 boundary. ✓
- Env docs at §9.4 of `KBL_B_PIPELINE_CODE_BRIEF.md`. ✓
- 30 s floor clamp on `KBL_PIPELINE_TICK_INTERVAL_SECONDS` with WARN. ✓
- `claim_one_signal is None` → return 0 early-exit. ✓
- Exception propagation — raises re-raised for APScheduler listener. ✓
- Two existing circuit-breaker tests (`test_main_respects_anthropic_circuit`,
  `test_main_respects_cost_circuit`) — still pass under the new env-first
  order because both set `KBL_FLAGS_PIPELINE_ENABLED=true` AND circuit
  open, which exercises the post-env-gate circuit paths. ✓

And the two amend-specific additions now close the S1 + S2 gaps.

---

## Dispatch

**APPROVE.** Single-file test-only amend. Both new tests present with
correct shape. 22/22 local pass confirmed independently. Brief v3
ratified. §Scope.6 Mac Mini verification already passed. Zero drive-by
changes. Ready for AI Head auto-merge on `MERGEABLE`.

**Post-merge path (per AI Head's dispatch):**
1. AI Head re-polls `gh pr view 18 --json mergeable` → `MERGEABLE`.
2. AI Head auto-merges PR #18 (Tier A authority — PR merge on B2 APPROVE).
3. AI Head asks Director: "Shall I set `KBL_FLAGS_PIPELINE_ENABLED=true`
   on Render?" (Tier B — env-var flip on production).
4. Director authorizes → AI Head executes via 1Password + Render API.
5. First signals flow through Render Steps 1-6 → Mac Mini Step 7 → vault.

Shadow-mode go-live unlocked. Tab closing per directive.
