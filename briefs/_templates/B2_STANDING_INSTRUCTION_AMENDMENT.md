<!--
Proposed standing-instruction amendment for Code Brisen #2.
Canonical location TBD — flagged in PR body for AI Head to decide.

Candidate locations B2 considered:
  1. ~/.claude/agent-memory/code-brisen-2/ — doesn't exist on Director's Mac
     (checked 2026-04-20; agent-memory/ dir itself is absent)
  2. ~/.claude/agents/code-brisen-2.md — doesn't exist either; ~/.claude/agents/
     holds persona briefs (ai-head, baker-*), not B-codes
  3. Cowork session prompt / harness-level config — B2 can't reach from inside
     a session
  4. Inline in dispatch briefs (briefs/_tasks/CODE_2_PENDING.md) — works per
     dispatch but doesn't survive cycle hand-offs

AI Head call: paste the block below into the canonical source OR decide
location is in the standing-instruction setup script (plist, shell init,
etc.) that the Director runs when spawning B-code terminals.
-->

# Proposed amendment — Code Brisen #2 standing instructions

Append the following bullet to B2's standing-instructions block (between the existing items #5 "Review output = APPROVE or REDIRECT..." and #6 "Verdict file..."):

```
5a. Before writing the verdict paragraph:
    (a) Start from briefs/_templates/B2_verdict_template.md (copy to the
        report path; fill cells; never re-draft the structure).
    (b) Run `bash briefs/_templates/lessons-grep-helper.sh <pr_number>` and
        paste output into §Automated lessons sweep. For each flagged
        lesson with score ≥4, either cite how the diff handles it OR
        state why it is N/A in that section — do not silently skip.
    (c) Apply CHANDA Q1 (Loop Test) + Q2 (Wish Test) block literally —
        answer each leg of Section 2 even if the answer is "untouched".
    Skipping any of (a)/(b)/(c) is disallowed on an APPROVE verdict.
```

**Rationale:** captures the three actions that took B2 the most time or were most prone to drift across PR #21/#22/#23/#24 reviews. Template codifies structure so cycle = fill cells; helper removes reliance on B2's memory of 42 numbered lessons; CHANDA block is forced-recall vs. recall-when-relevant.

**Cost:** adds ~2 min per review (helper run + reading its output). Offset by ~3 min saved on structure re-drafting. Net: similar time, higher consistency, systematic lesson coverage.

**Reviewer-separation matrix unchanged.** B2 still reviews AI Head briefs, B1 PRs, B3 drafts; still never reviews own implementations.
