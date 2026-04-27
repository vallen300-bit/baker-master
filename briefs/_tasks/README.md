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

## State-machine frontmatter (BRIEF_B_CODE_AUTOPOLL_1, 2026-04-27)

`CODE_*_PENDING.md` files carry YAML frontmatter so a B-code (or AI Head
watchdog) can parse mailbox state without reading prose. Schema:

```yaml
---
status: OPEN | IN_PROGRESS | BLOCKED-AI-HEAD-Q | BLOCKED-DIRECTOR-Q | COMPLETE | RETIRED
brief: briefs/BRIEF_<NAME>.md          # required if status != RETIRED
trigger_class: LOW | MEDIUM | HIGH     # per b1-situational-review-trigger
dispatched_at: 2026-04-27T18:30:00Z    # ISO8601 UTC
dispatched_by: ai-head-a | ai-head-b
claimed_at: null | <ISO8601>           # set by B-code on IN_PROGRESS transition
claimed_by: null | b1 | b2 | b3 | b4 | b5
last_heartbeat: null | <ISO8601>       # B-code writes ~10–15 min cadence
blocker_question: null | <text>        # set when status = BLOCKED-*-Q
ship_report: null | briefs/_reports/B<N>_<name>_<date>.md  # set on COMPLETE
autopoll_eligible: true | false        # if false, requires paste-block (cold-start)
---
```

Legal transitions (every other transition raises):

```
OPEN → IN_PROGRESS               (B-code claims)
IN_PROGRESS → BLOCKED-AI-HEAD-Q  (B-code surfaces Tier-A-scope ambiguity)
IN_PROGRESS → BLOCKED-DIRECTOR-Q (B-code surfaces true Director Q)
IN_PROGRESS → COMPLETE           (PR shipped + ship-report written)
BLOCKED-AI-HEAD-Q → IN_PROGRESS  (AI Head answered, B-code resumes)
BLOCKED-DIRECTOR-Q → IN_PROGRESS (Director answered, B-code resumes)
IN_PROGRESS → OPEN               (stale-claim recovery — AI Head loop after >60 min)
COMPLETE → RETIRED               (post-merge §3 hygiene, optional)
```

Helper API: `scripts/autopoll_state.py`
(`read_state` / `transition_state` / `heartbeat` / `find_stale_claims` /
`push_state_transition`). All transitions go through `transition_state`
— no direct frontmatter writes. Concurrency: `git pull --rebase` before
write, last-writer-wins on push race (Q6 ratification).

Cold-start dispatches (`autopoll_eligible: false`) still require the
paste-block per Lesson #48 — autopoll is a window-scoped exception, not
a replacement (see Lesson #50 + `_ops/processes/b-code-autopoll-protocol.md`).

## Paired with `briefs/_reports/`

See `briefs/_reports/README.md` — the symmetric pattern for Code Brisen reports back to AI Head / Director. Substantive reports go in files; short status confirmations stay inline in chat.
