<!--
B2 verdict-report template v1 — 2026-04-20.

How to use:
  1. Copy this file to briefs/_reports/B2_<topic>_<YYYYMMDD>.md (or wherever the
     dispatch brief specifies).
  2. Fill the {{PLACEHOLDER}} cells. Delete unused rows from tables if truly N/A,
     but prefer leaving them with `N/A — <reason>` to prove you considered them.
  3. Run `bash briefs/_templates/lessons-grep-helper.sh <pr_number>` and paste
     its output into §Automated lessons sweep before writing §Manual landmine checks.
  4. Do NOT delete section headers — structure consistency across reports is
     what makes drift spottable. If a section is truly N/A for this PR, keep
     the header and write "N/A — <reason>" as its body.

Reference: tasks/lessons.md (42 lessons as of 2026-04-20). Reviewer-separation
matrix: AI Head briefs, B1 PRs, B3 prompt/rule/spec drafts → B2 reviews.
Never review what you implement.

This template lands in briefs/_templates/ today. Per
SOT_OBSIDIAN_UNIFICATION_1 Phase B, migrates to
~/baker-vault/_ops/processes/baker-review/ when that phase merges.
-->
---
title: B2 {{TOPIC_SHORT}} — {{VERDICT}}
voice: report
author: code-brisen-2
created: {{YYYY-MM-DD}}
---

# {{TOPIC_FULL_TITLE}} Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) {{TASK_REF}}
**PR:** {{PR_URL}}
**Branch:** `{{BRANCH_NAME}}`
**Head commit:** `{{HEAD_SHA}}`
**Base:** `main` at `{{BASE_SHA}}`
**Date:** {{YYYY-MM-DD}}
**Time:** ~{{MINUTES}} min

---

## Verdict

**{{VERDICT}}.** {{ONE_PARAGRAPH_RATIONALE}}

*(Verdict values: `APPROVE` / `REQUEST_CHANGES` / `REDIRECT`. Rationale = one
paragraph stating WHY in terms of scope-fidelity + CHANDA Q1/Q2 + landmine
absence. No prose flourishes. If REDIRECT/REQUEST_CHANGES, list the S1 blockers
here and itemize below.)*

---

## Scope verification (brief §VerdictFocus, 1-for-1)

| Check (quote from brief) | Result |
|---|---|
| {{BRIEF_CHECK_1}} | {{✅/⚠️/❌ + one-sentence evidence, with exact file:line or command output}} |
| {{BRIEF_CHECK_2}} | {{...}} |
| {{BRIEF_CHECK_N}} | {{...}} |

*(Use ✅ PASS, ⚠️ PASS-with-caveat, ❌ FAIL. One row per verdict-focus bullet in
the dispatch brief. Do not reorder or collapse — reviewer-brief parity is what
makes the verdict auditable.)*

---

## Per-file diff inspection

**`{{FILE_1}}` (±{{N}} lines, {{one-sentence characterization}}):**

- {{Bullet per meaningful edit: line range + what changed + why it matches/deviates from brief}}
- {{...}}

**`{{FILE_2}}` (...)**:

- ...

*(One subsection per file in `git diff main..HEAD --stat`. For pure renames or
trivial bumps, a single line is enough. For SQL / LLM / schema / auth edits, walk
the diff hunk-by-hunk.)*

---

## Automated lessons sweep

*Output from `bash briefs/_templates/lessons-grep-helper.sh {{PR_NUMBER}}`:*

```
{{HELPER_OUTPUT}}
```

**Director's call on flagged lessons:**

- {{Lesson #N}} — {{addressed? Explain how the diff handles it, or why N/A}}
- {{...}}

*(The helper ranks by keyword overlap, not semantics — false positives are
expected. Addressing them is your judgment call, not auto-pass/fail.)*

---

## Manual landmine checks (every review, no exceptions)

| Pattern | Lesson | Result |
|---|---|---|
| Column-name drift | #34, #42 | {{N/A — no SQL / OR: ✅ verified columns exist with `SELECT column_name FROM information_schema.columns WHERE table_name = 'X'` OR: ❌ <evidence>}} |
| Unbounded queries | — | {{N/A — deletions only / OR: ✅ WHERE clauses bound / OR: ❌ <evidence>}} |
| Missing `conn.rollback()` in except | — | {{N/A / ✅ / ❌ <evidence>}} |
| Fixture-only tests missing real schema | #42 | {{N/A / ✅ / ❌ <evidence>}} |
| LLM call signature + response access three-way match | #17 | {{N/A / ✅ / ❌ <evidence>}} |
| Wrong env var name assumption | #36 | {{N/A / ✅ / ❌ <evidence>}} |
| py3.9 PEP-604 `X \| None` landmine | — | {{✅ `python3 -c "import ast; ast.parse(open('<file>').read())"` passes on py3.9 / OR: ❌ <evidence>}} |
| Dangling callers of deleted code | — | {{✅ `grep -rn "<deleted_symbol>" . --include="*.py"` → zero / OR: ❌ <evidence>}} |

*(Add rows for PR-specific patterns — e.g., "Regex compiles after token drop",
"Phantom file references". Do not remove existing rows; mark N/A.)*

---

## CHANDA pre-push test

- **Q1 (Loop Test):** Does this change preserve all three legs of CHANDA §2?
  - Leg 1 (Gold read before Silver compile): {{unchanged / touched — explain}}
  - Leg 2 (Director action → feedback ledger atomic write): {{unchanged / touched — explain}}
  - Leg 3 (Step 1 reads `hot.md` AND ledger every run): {{unchanged / touched — explain}}
  - **{{PASS / FLAG}}**

- **Q2 (Wish Test):** Serves the wish or engineering convenience?
  - {{One sentence on WHY this change exists in wish-terms. If convenience, state the tradeoff.}}
  - **{{PASS / FLAG}}**

**Structural invariants §3.4-10 audit (confirm via `git diff --stat`):**

- Inv 4 (`author: director` files untouched by agents): {{✅ / ❌ — check with `git diff main..HEAD -- <author:director files>`}}
- Inv 5 (every wiki file has frontmatter): {{N/A — no wiki touch / ✅ / ❌}}
- Inv 6 (pipeline never skips Step 6): {{N/A / ✅}}
- Inv 7 (ayoniso alerts are prompts): {{N/A / ✅}}
- Inv 8 (Silver→Gold only by Director frontmatter edit): {{N/A / ✅}}
- Inv 9 (Mac Mini = single agent writer to `~/baker-vault`): {{N/A — no vault writes / ✅ — change lives in `_ops/` carve-out}}
- Inv 10 (pipeline prompts do not self-modify): {{N/A / ✅}}

---

## Nits

**N1 ({{severity — informational / follow-up scope / S2}}):** {{One short paragraph. Keep nits numbered. Don't promote an N-level nit to a blocker in the verdict unless it truly merits REQUEST_CHANGES — put S1 blockers in the verdict paragraph.}}

**N2 (...):** {{...}}

*(Zero nits is a valid state. Say "None." if so — don't pad.)*

---

## Dispatch-back

B2 verdict: **{{VERDICT}}** {{PR_REF}} at head `{{HEAD_SHA}}`. Report at `{{REPORT_PATH}}`. {{One line on next action: "AI Head may auto-merge per Tier A." / "REDIRECT with <N> S1 blockers — see §Verdict." / "REQUEST_CHANGES — B<N> to address N1-N<M> + push revised commit."}}

*— Code Brisen #2*
