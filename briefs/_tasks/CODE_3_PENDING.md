# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** LAYER0-RULES-S1-S6 + C1-C2 shipped at `64d1712` (8 items). Step 1 amendment REDIRECT verdict from B2 with 2 should-fix.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: STEP1-AMEND-S1-S2 — Apply B2's 2 Should-Fix Items to Step 1 Triage Prompt

**Source:** `briefs/_reports/B2_chanda_compliance_fold_review_20260418.md` §2.2
**Target:** `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md`
**Part 2 (§10 fixtures):** APPROVED by B2 — no action on that file unless cross-link below triggers.

### Items to apply

**S1 — Cross-matter elevation (AI Head OQ3 resolution missed in original amend):**

1. **§1.2 rule update.** Replace:
   > *"If the signal's primary_matter appears in hot.md as actively pressing, ELEVATE triage_score by 0.15 (cap at 100)."*
   
   with:
   > *"If the signal's primary_matter OR any extracted entity (slug found in `related_matters`, or any matter slug appearing as a whole word in the signal text) matches a hot.md ACTIVE entry, ELEVATE triage_score by 0.15 (cap at 100). Apply the elevation once per signal even if multiple matches occur — don't double-stack."*
   
   Same shape change for FROZEN suppression rule.

2. **§6 OQ6 update.** Flip from DEFERRED → RESOLVED-by-AI-Head. Document over-elevation-noise mitigation: "single-shot elevation, no stacking" handles original concern.

3. **§10 fixture cross-link (coordinate with Part 2 APPROVE).** Add to `KBL_B_TEST_FIXTURES.md` EITHER:
   - Expand Fixture #11 with a "Phase 2: cross-matter case" sub-scenario, OR
   - Add Fixture #14: signal where primary is OUT of hot.md but a `related_matters` entry IS on ACTIVE list
   
   B2's recommendation: Fixture #14 is cleaner (adds a new named fixture rather than expanding existing). Your call — document the choice.

**S2 — `kbl/loop.py` API mismatch (coordination miss with B1's PR #6 ship):**

B1's shipped API (`kbl/loop.py` @ PR #6 `6c23d36`):
- `render_ledger(rows)` — no `_block` suffix
- `load_recent_feedback(conn, limit=None)` — takes `conn` arg, default None uses env var

Your §1.1 builder calls `render_ledger_block(ledger_rows)` and `load_recent_feedback(limit=20)`.

Fix in §1.1 + §1.4:
- Rename all `render_ledger_block` → `render_ledger`
- Update `load_recent_feedback` signature to match B1's: takes `conn` + optional `limit`
- Update builder to pass `conn` (get conn from existing Step 1 DB wiring — assume `signal_context.conn` or similar; spec exact accessor in §1.4)

### CHANDA pre-push

- Q1: cross-matter elevation is a content refinement within the already-ratified Leg 3 mechanism, not a new loop touch. Pass.
- Q2: serves wish (AI Head OQ3 ratified). Pass.

### Reviewer

B2. Third cycle on Step 1 file — consistent with iterative review.

### Timeline

~25-35 min (2 small-surface fixes + 1 fixture addition).

### Dispatch back

> B3 Step 1 S1+S2 applied + Fixture #14 added — `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` commit `<SHA>`, fixtures commit `<SHA>`. Ready for B2 re-review.

---

*Posted 2026-04-18 by AI Head. B1 idle post-PR-#6. B2 queue has PR #5 delta, Step 0 re-review, REDIRECT fold, CHANDA ack ahead. Director: hot.md debrief + Hagenauer labeling in separate sessions.*
