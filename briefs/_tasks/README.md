# `briefs/_tasks/` — Task Mailboxes

**Purpose:** persistent per-Code task files. Director points a Code instance at their pending file; Code reads, executes, reports. No more copy-paste of long task blocks in chat.

## Files

- `CODE_1_PENDING.md` — current task for Code Brisen #1 (terminal instance)
- `CODE_2_PENDING.md` — current task for Code Brisen #2 (app instance)
- `README.md` — this file

## Director's usage pattern

```
"Code 1 — read briefs/_tasks/CODE_1_PENDING.md and execute"
"Code 2 — read briefs/_tasks/CODE_2_PENDING.md and execute"
```

Single path per Code instance. No remembering "which task file" — always the same name.

## AI Head's usage pattern

When dispatching a new task:
1. Overwrite the target `CODE_<n>_PENDING.md` with new content
2. Commit + push
3. Notify Director the file is updated

The previous task's content is preserved in git history. If you want permanent record, `git log briefs/_tasks/CODE_1_PENDING.md` shows every task dispatched.

## When a task completes

- Code reports completion in-chat
- AI Head updates the file with next task, OR writes a "STANDBY — no pending task" state
- No `briefs/_tasks/done/` folder needed — git history is the archive

## Invariants

- One open task per Code at any time (don't stack — Code's 1M context is precious)
- Tasks self-contained — assume Code has zero session memory of prior exchanges
- Include: target file, scope, output format, time budget, pass criteria, parallel context
- Commit atomically — one task update = one commit

## Paired with `briefs/_reports/`

See `briefs/_reports/README.md` — the symmetric pattern for Code Brisen reports back to AI Head / Director. Substantive reports go in files; short status confirmations stay inline in chat.
