# B2 — KBL_PIPELINE_SCHEDULER_WIRING brief v2 re-review — APPROVE

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (late afternoon)
**Brief:** `briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` @ `cdaea58`
**Initial review:** `briefs/_reports/B2_scheduler_wiring_brief_review_20260419.md` @ `273487e`
**Verdict:** **APPROVE** — both S-level items cleanly folded.

---

## What v2 changed

Diff vs v1 is exactly the two items I flagged, nothing more:

### §Scope.5 — tests 4 → 7 (S2 fold)

| # | Test | Status |
|---|------|--------|
| 1 | `test_main_disabled_returns_zero_without_claim` | v1 ✓ |
| 2 | `test_main_enabled_claims_and_processes` | v1 ✓ |
| 3 | `test_remote_variant_stops_at_awaiting_commit` | v1 ✓ |
| 4 | `test_remote_variant_handles_routed_inbox` | v1 ✓ |
| 5 | `test_main_circuit_breaker_precedes_env_gate` | **v2 NEW** — covers S2(a) |
| 6 | `test_remote_variant_stops_at_paused_cost_cap` | **v2 NEW** — covers S2(b) |
| 7 | `test_remote_variant_stops_at_finalize_failed` | **v2 NEW** — covers S2(c) |

Test 5 specifies the correct order assertion — circuit check must precede
env gate. Test 6 asserts Step 6 mock NOT called when Step 5 parks. Test 7
correctly accounts for Step 6's internal-commit-then-raise pattern from
PR #15 (caller rolls back, terminal state survives via Step-6 internal
commit). All three match the shape I asked for.

### §Scope.6 — pre-merge Mac Mini verification (S1 fold)

Exactly the gate I asked for. Three ssh checks:

1. plist `ProgramArguments` → wrapper script (not `python3 -m kbl.pipeline_tick`)
2. wrapper → `poller.py` Python entrypoint
3. `poller.py` imports `step7_commit.commit` directly (not `pipeline_tick`)

With explicit BLOCK-merge instruction and a named follow-up brief
(`MAC_MINI_STEP7_POLLER_IMPL`) if any check fails. This closes the
"unverified premise" risk cleanly — the audit runs before merge, the
results get pasted into PR #18, and the failure path is pre-designed.

Nothing else in the brief changed. Everything I said was "right" in v1
review stays right in v2.

---

## N-level nits (unchanged)

All six N-level nits from v1 review remain foldable at B1's discretion:

- N1: drop dead `step7_commit` import from `_process_signal_remote`
- N2: module docstring update in-scope
- N3: `misfire_grace_time` explicit or documented
- N4: `IntervalTrigger(seconds=...)` consistency with `embedded_scheduler.py`
- N5: env-gate parsing doc note
- N6: `KBL_PIPELINE_TICK_INTERVAL_SECONDS` ValueError guard

None of these block the brief. They're cosmetic or defense-in-depth.

One tiny inconsistency worth a 10-second fix: `## Timeline` at line 156
still says "4 tests (~80 lines)" — should read "7 tests (~140 lines)"
post-S2-fold. Not a blocker; flag only.

---

## Dispatch

**APPROVE.** Brief is ready for B1 dispatch. The §Scope.6 gate is
mandatory pre-merge — that's the safety net that prevents shipping an
unrunnable pipeline. Confirm the ssh checks are actually executed and
pasted into PR #18 before I flip APPROVE on the PR.

**Recommendation:** AI Head dispatches B1 immediately on this brief; run
the §Scope.6 ssh verification BEFORE B1 starts coding (cheap, ~30s, and
if Mac Mini's poller is ground-truth (b) or (c) per v1 review, B1
shouldn't waste 60 min on PR #18 before the prerequisite lands).
