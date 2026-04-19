# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-19 (morning)
**Status:** OPEN — 2 tasks in sequence

---

## Completed since last dispatch

- Task I — PR #13 STEP4-CLASSIFY-IMPL initial review (REDIRECT @ `dedab68`) ✓

---

## Task J (NOW, fast): PR #13 S1 delta APPROVE

**PR:** https://github.com/vallen300-bit/baker-master/pull/13
**Branch:** `step4-classify-impl`
**New head:** `315695f` (advanced from `4d38a44` with S1 fix)
**Change:** B1 added `test_classify_cross_link_only_guard_raises_and_marks_failed` — patches `_evaluate_rules` to return `CROSS_LINK_ONLY`, calls `classify()`, asserts `ClassifyError` raises AND status flips to `classify_failed` BEFORE the raise. Mirror shape of existing below-threshold guard test. No production code change. 41/41 tests green (was 40).

### Scope

- Verify the new test exercises the runtime guard (not a trivially-passing assertion that bypasses the guard code path)
- Verify the exception type + state-flip assertions are both present
- Verify test naming + location consistency with existing test file
- Verify your 3 nice-to-haves (N1 docstring, N2 Watch-list exclusion, N3 cross_link_hint consumer pointer) were **deferred** per dispatch — no scope creep

### Format

Short one-paragraph APPROVE report: `briefs/_reports/B2_pr13_s1_delta_20260419.md`
Or append to existing `B2_pr13_review_20260419.md` — your preference.

### Timeline

~5-10 min.

### Dispatch back

> B2 PR #13 S1 delta APPROVE — head `315695f`, report at `<path>`, commit `<SHA>`.

On APPROVE I auto-merge PR #13.

---

## Task K (after Task J): Burn-in audit of 5 merged Phase 1 PRs

**Scope:** independent audit of `#7 / #8 / #10 / #11 / #12` against CHANDA.md §3 invariants + §2 three legs. De-risk before Opus starts pumping real signals through the pipeline.

### Why

All 5 Phase 1 PRs landed via cascade merge in one session (~2 hrs). Each got focused review, but cross-PR integration paths weren't audited end-to-end post-merge. Real signal traffic starts once Step 5 ships. Catching invariant drift NOW is cheaper than catching it via a production bug once Opus is charging cost-ledger rows.

### Scope

**IN — per-invariant sweep against current `main` state:**

1. **Inv 1 (zero-Gold safe):** trace a hypothetical signal through Steps 1-4 when `load_gold_context_by_matter` returns `""`. Each step must handle empty-string / empty-list Gold inputs without error. Flag any step that crashes or silently drops the signal.

2. **Inv 2 (atomic ledger writes):** `kbl_cost_ledger` writes across Steps 1-3 — are they inside or outside the same transaction as the step's main state UPDATE? If a step's main UPDATE commits but the ledger INSERT fails (e.g., PG connection drop), does the signal advance without the cost row? Compare to Leg 2 (feedback_ledger): is its atomicity intact? Note: ledger atomicity per B2's PR #10 Inv 2 sub-observation was flagged as documentation-level, not violation — re-confirm or escalate.

3. **Inv 3 (hot.md + ledger every run):** verify Steps 1 AND 4 both read hot.md + feedback_ledger on every invocation (no caching). You already certified this for each step individually in PR review — re-verify across the combined main state (no post-merge regression).

4. **Inv 4 (`author: director` files never modified):** grep for any write surface that touches `/Users/dimitry/baker-vault/wiki/*.md` where the target file's frontmatter has `author: director`. CHANDA.md is the canonical example. Should be zero writes from agents.

5. **Inv 6 (never skip Step 6):** Steps 1-4 all advance to `awaiting_<next>` states — none short-circuit to `done` or `completed` before Step 6. Step 6 itself not yet implemented; skip that sub-check.

6. **Inv 7 (ayoniso alerts are prompts, not overrides):** KBL-C surface; Phase 1 doesn't touch. Note as N/A.

7. **Inv 9 (Mac Mini single writer):** baker-vault write surfaces across merged code. Any step that writes to `/Users/dimitry/baker-vault/wiki/` from Render? Should be zero. Inv 9 vault-write path lives in Step 7 (not yet shipped). Flag any drift.

8. **Inv 10 (pipeline prompts don't self-modify):** grep for any code that writes `kbl/prompts/*.txt`. Should be zero. All template loads should be read-only.

**IN — per-leg sweep:**

9. **Leg 1 (Compounding):** `load_gold_context_by_matter` (PR #9) is the Leg 1 read. Is it called by any Phase 1 code? It should be called by Step 5 (not shipped yet), so Phase 1 has zero Leg 1 reads — which is correct. Confirm.

10. **Leg 2 (Capture):** feedback_ledger write path from Director actions. Phase 1 has no Director-action-capture surface (KBL-C ayoniso/WA handlers ship the writes). Confirm zero Leg 2 writes from Phase 1; flag any accidental write.

11. **Leg 3 (Flow-forward):** Step 1 + Step 4 both read hot.md + feedback_ledger on every call. Verified in individual reviews — re-verify the combined main state.

### Format

`briefs/_reports/B2_phase1_burn_in_audit_20260419.md`
- Top-line verdict: **GREEN** (no issues) / **YELLOW** (minor drift, documentation-level) / **RED** (should-fix blocker)
- Per-invariant 1-line status
- Per-leg 1-line status
- Drift findings with file:line citations
- If RED: actionable remediation path

### Timeline

~45-60 min. Read-only audit; no code changes.

### Dispatch back

> B2 Phase 1 burn-in audit done — `briefs/_reports/B2_phase1_burn_in_audit_20260419.md`, commit `<SHA>`. Verdict: <GREEN/YELLOW/RED>. <0-5 line summary>.

---

## Working-tree reminder

Work only in `/tmp/bm-b2`. Never Dropbox paths.

---

*Posted 2026-04-19 by AI Head. Task J fast; Task K is defensive spadework while B1 builds Step 5.*
