# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** Step 1 S1+S2 + Fixture #14 shipped at `6c255d1`. B2 re-review: REDIRECT with 1 tiny should-fix.
**Task posted:** 2026-04-18
**Status:** OPEN — micro-fix

---

## Task: STEP1-ENV-VAR-TYPO — 3-line env-var name correction

**Source:** `briefs/_reports/B2_step1_fixture14_rereview_20260418.md` (verdict REDIRECT, 1 should-fix)

### Fix

In `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` §1.4, the `load_recent_feedback` docstring cites env var `KBL_LEDGER_DEFAULT_LIMIT`. PR #6's shipped `kbl/loop.py` uses `KBL_STEP1_LEDGER_LIMIT`.

Change every occurrence in the draft: `KBL_LEDGER_DEFAULT_LIMIT` → `KBL_STEP1_LEDGER_LIMIT`.

### CHANDA pre-push

- Q1: documentation typo, not a loop-mechanism change. Pass.
- Q2: serves wish (canonical env-var naming). Pass.

### Timeline

~5 min.

### Dispatch back

> B3 env-var typo fixed — `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` commit `<SHA>`. Ready for B2 final-pass APPROVE.

---

*Posted 2026-04-18 by AI Head.*
