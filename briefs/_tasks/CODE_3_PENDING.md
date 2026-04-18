# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** STEP5-OPUS-PROMPT shipped at `7ea63c6`. B2 verdict REDIRECT with 1 should-fix.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: STEP5-S1-AUTHOR-RENAME — 9-site `author: tier2 → author: pipeline`

**Source:** `briefs/_reports/B2_step5_opus_prompt_review_20260418.md` S1

### Why

Step 5 produces machine-generated wiki entries. Lifecycle:
- Pipeline writes → `author: pipeline` + `voice: silver`
- Director promotes → `author: director` + `voice: gold` (CHANDA Inv 4 protection engages)

Two distinct `author` values mark lifecycle cleanly. `tier2` was a draft-session convention; pipeline output should NOT inherit it. Locking the semantics now, before any impl consumes the spec.

### Fix

In `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md`, replace `author: tier2` → `author: pipeline` at all 9 occurrences per B2's list:
1. Rule F2 (frontmatter rule)
2. Frontmatter spec
3. Invariants summary
4. Worked example #1 frontmatter
5. Worked example #2 frontmatter
6. Worked example #3 frontmatter
7. §2 reconciliation
8. §4 Inv 4 row
9. §5 OQ1 status flip

B2 noted: "system-block prompt-cache invalidates one-time on fold" — expected, no action required from you.

### CHANDA pre-push

- Q1: no loop-mechanism change; template spec convention. Pass.
- Q2: serves wish (clean lifecycle semantics). Pass.

### Timeline

~10 min (mechanical rename; re-scan to confirm all 9 landed).

### Dispatch back

> B3 STEP5-OPUS S1 applied — 9 sites renamed `tier2 → pipeline`, `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` commit `<SHA>`. Ready for B2 APPROVE.

---

*Posted 2026-04-18 by AI Head. Small mechanical fix.*
