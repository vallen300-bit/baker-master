# `briefs/_runbooks/` — Operator Procedures

**Purpose:** straight-line, copy-paste-ready procedures for operators (usually Director). Complement to `briefs/` (design docs) and `briefs/_reports/` (agent reports).

## When to write a runbook

- A non-trivial merge or deploy that needs to execute cleanly on the first try
- A recovery procedure that would be time-critical to find later
- A manual verification or sanity-check sequence that's run more than once

## When NOT to write a runbook

- A one-off task that won't repeat
- Something fully automated — commit the automation instead
- Decision-heavy flow with multiple branches — that's a brief or a decision doc, not a runbook

## Shape

Each runbook:

- Opens with a **Scope + outcome + est. time** block
- One **section per step** with: precondition, exact commands, expected output, failure triage, rollback
- **No decisions mid-procedure** — if a step has branching logic, the runbook should escalate rather than offer a choice
- Cross-links to source-of-truth briefs so operators can drill down if needed

## Naming

`<TOPIC>_RUNBOOK.md` in `SCREAMING_SNAKE`. Examples:

- `KBL_A_MERGE_RUNBOOK.md`
- `MAC_MINI_RECOVERY_RUNBOOK.md`

## Directory hygiene

Runbooks are versioned alongside briefs — git history is the audit trail. If a runbook becomes obsolete (procedure replaced by automation, subsystem retired), add a `DEPRECATED:` line at the top pointing to the replacement. Don't delete.
