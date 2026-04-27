# B-Code Autopoll — Start of Overnight Window

Paste each block into the named tab once at start of overnight. After
that, B-codes self-wake until `OVERNIGHT_AUTONOMY_UNTIL` deadline
(default `07:00 UTC`) or 3 consecutive idle wakes, whichever fires
first. Authority: `briefs/BRIEF_B_CODE_AUTOPOLL_1.md` (Director ratified
2026-04-27, Q7 = B2 + B3 only first overnight).

## Pre-flight (do this once)

- Set `BAKER_OVERNIGHT_CHANNEL_ID=<channel_id>` in the shell env if a
  dedicated `#baker-overnight` channel was created. Otherwise the
  default `#cockpit` (`C0AF4FVN3FB`) is used.
- Verify `SLACK_BOT_TOKEN` is set in each B-code shell (autopoll Slack
  pushes read it via `outputs.slack_notifier._get_webclient`):
  ```
  cd ~/bm-bN && python3 -c "import os; \
    print('OK' if os.getenv('SLACK_BOT_TOKEN') else 'MISSING')"
  ```
  If MISSING — autopoll silently skips Slack pushes (non-fatal per
  `outputs/slack_notifier.py:142-144`) but the morning Director will
  lack the state-transition log. Source from 1Password CLI
  (`op read op://baker/SLACK_BOT_TOKEN`) or `~/.zshrc` export.
- Verify B-code worktrees clean: `cd ~/bm-bN && git status` returns
  clean tree on `main`.
- Confirm `_ops/processes/b-code-autopoll-protocol.md` is on `main` in
  every B-code worktree.

## Paste to: b2

```
You are entering autopoll mode per
_ops/processes/b-code-autopoll-protocol.md. Read that file first; it is
your protocol for every wake. Cap loop at OVERNIGHT_AUTONOMY_UNTIL=07:00
UTC or 3 consecutive idle wakes, whichever fires first. Wake interval
900s.

cd ~/bm-b2 && git checkout main && git pull -q && \
  cat _ops/processes/b-code-autopoll-protocol.md && \
  cat briefs/_tasks/CODE_2_PENDING.md

Begin Phase 1 of the protocol.
```

## Paste to: b3

```
You are entering autopoll mode per
_ops/processes/b-code-autopoll-protocol.md. Read that file first; it is
your protocol for every wake. Cap loop at OVERNIGHT_AUTONOMY_UNTIL=07:00
UTC or 3 consecutive idle wakes, whichever fires first. Wake interval
900s.

cd ~/bm-b3 && git checkout main && git pull -q && \
  cat _ops/processes/b-code-autopoll-protocol.md && \
  cat briefs/_tasks/CODE_3_PENDING.md

Begin Phase 1 of the protocol.
```

## Paste to: aihead1 (Build-lead's own loop — stale-claim watchdog)

```
You are AI Head A entering autopoll mode for the night. Every 600s:

1. cd ~/bm-b1 && git pull -q
2. python3 -c "from scripts.autopoll_state import find_stale_claims; \
   [print(f'STALE: {p}') for p in find_stale_claims('briefs/_tasks/')]"
3. For each stale claim:
   - transition the mailbox back to OPEN (clear claimed_by / claimed_at)
   - push_state_transition(path, to='OPEN', extra='stale-recover')
   - git commit + push
4. Scan for status=BLOCKED-AI-HEAD-Q in any mailbox; answer if Tier A
   scope, else escalate by transitioning to BLOCKED-DIRECTOR-Q with the
   question preserved.
5. On any PR opened by a B-code in autopoll: run /security-review. If
   clean AND the PR has APPROVE from AI Head B → merge (Tier A
   standing). Slack-push the merge.
6. ScheduleWakeup(delaySeconds=600, reason='aihead-a watchdog wake',
   prompt=<verbatim /loop prompt>).

Stop conditions: OVERNIGHT_AUTONOMY_UNTIL=07:00 UTC OR Director paste of
"STOP AUTOPOLL".
```

## Manual stop

Paste `STOP AUTOPOLL` into any tab to exit that loop immediately. The
B-code (or AI Head A watchdog) detects the literal in its next wake's
context and skips the `ScheduleWakeup` call.

## Cohort note (first overnight)

Per Q7 ratification, only B2 + B3 + AI Head A run autopoll for the
first overnight window. B1 / B4 / B5 stay in cold-start (paste-block)
mode. AI Head B (`aihead2`) stays cold-start for the first overnight
and joins on the second window after the first overnight retro.
