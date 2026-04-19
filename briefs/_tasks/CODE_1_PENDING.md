# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** STEP4-CLASSIFY-IMPL shipped as PR #13 @ `4d38a44`. B2 review filed: REDIRECT (1 should-fix + 3 nice-to-have deferrable).
**Task posted:** 2026-04-19 (morning)
**Status:** OPEN — tiny test amend on PR #13

---

## Task: PR13-S1-FIX — Add CROSS_LINK_ONLY runtime-guard test

**Source:** B2's PR #13 review @ `dedab68` — S1.

### Why

Your `classify()` has a runtime guard: if `_evaluate_rules()` ever returns `CROSS_LINK_ONLY`, fail loud (not silent fallback). Code is correct. Problem: **no test actually exercises the guard** — so it's unreachable code that CI can't validate. Without this test the guard becomes rotting dead code the moment a future Phase-2 edit hits the classify path.

Brief §Specific-Scrutiny item 2 explicitly required this test. Missing it = REDIRECT.

### Scope

**IN**

1. **`tests/test_step4_classify.py`** — add single test (~12 lines per B2's inline suggestion):
   - Force `_evaluate_rules()` to return `ClassifyDecision.CROSS_LINK_ONLY` — monkeypatch or `unittest.mock.patch` is fine (not a structural refactor).
   - Call `classify(signal_id, conn)` — must raise `ClassifyError` (whatever exception you chose for the guard).
   - After the raise, the signal row's `status` must be `classify_failed` (guard fires the same state-flip-before-raise pattern as other failure paths).
   - Assert both: exception type AND post-raise state column.

2. **No production code changes.** The guard already exists; only the test is missing.

### CHANDA pre-push

- **Q1 Loop Test:** adding a test, no Leg touched. Pass.
- **Q2 Wish Test:** serves wish — CI can catch Phase 2 regressions against the Phase 1 invariant. Pass.

### B2's 3 nice-to-have (**DEFER** — do NOT apply now)

N1 (docstring on env unknown-slug pass-through), N2 (Watch-list-exclusion test by name), N3 (reverse-pointer to Step 6 consumer in docstring) — all optional polish. Track for a later consolidation commit; skip for this amend.

### Branch + PR

- Branch: `step4-classify-impl` (same PR #13).
- Amend as additional commit on top of `4d38a44`. Do NOT open new PR.
- Head will advance; B2 re-reviews S1 delta as a fast APPROVE.

### Timeline

~10-15 min (write test + run suite + commit + push).

### Dispatch back

> B1 PR13-S1-FIX shipped — PR #13 head advanced to `<SHA>`, CROSS_LINK_ONLY guard test added, `<N>`/`<N>` tests green. Ready for B2 S1 delta APPROVE.

---

## After this task

On B2 APPROVE: I auto-merge PR #13. Step 4 complete.

Next dispatch to you: **STEP5-OPUS-IMPL** — the big one. Spec in KBL-B §4.6 + `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` (now 7 worked examples post-B3 expansion at `fceb22f`). ~2-3 hours. Depends on PR #13 merge + `load_gold_context_by_matter` (PR #9, already merged).

---

*Posted 2026-04-19 by AI Head. Tiny test amend. B2's S1 was the only should-fix; 3 N-items deferred.*
