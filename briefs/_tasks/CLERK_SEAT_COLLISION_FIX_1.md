# BRIEF: CLERK_SEAT_COLLISION_FIX_1 — clerk + clerk-haiku tmux seats are one shared claude instance

- **Priority:** P1 (Director-dispatched 2026-07-19 morning, overnight smoke finding)
- **Executor:** b1
- **Complexity:** Low-Medium
- **Estimated time:** ~2h
- **Evidence base:** `briefs/_reports/FLEET_WAKE_SMOKE_2026-07-19.md` row 5

## Harness V2

- **Context Contract:** inputs = this brief + `~/.zshrc` (clerkqwenterm/clerkqwen only) + `~/Library/Application Support/baker/cockpit/{fleet_terminals.sh,launch_manifest.json}` + `/Users/dimitry/bm-clerk/clerk_qwen.py`; nothing else. Worker refresh at 50% context.
- **Task class:** local seat/launcher repair (non-repo production surface), P1.
- **Done rubric / done-state class:** class PROBE-VERIFIED — done only when (a) hypothesis verdict with captured failure output, (b) clerk pane runs clerk_qwen (not claude.exe) and clerk-haiku untouched, (c) fail-loud probe 3 passes, (d) report to lead with exact diffs of any shared-file edits. No codex gate (no repo code); lead reviews the report.
- **Gate plan:** lead review of report on topic `clerk-seat-collision-fix-1`; escalate to lead before any `~/.zshrc` edit lands.

## Context

Overnight smoke: tmux sessions `clerk` and `clerk-haiku` both show pane command
`claude.exe`, cwd `/Users/dimitry/bm-clerk`, title "Clerk Chat", identical
context/cost readouts at every capture — one underlying Claude(Haiku) instance
serving both seats. When lead injected clerk's ack instruction (msg #13067) into
the `clerk` session, the session acked #13070 (clerk-haiku's message) instead.
The clerk seat is effectively dead as an independent agent; its bus mailbox
drains only via lead bookkeeping.

Intended wiring (verified in `~/.zshrc` + launch manifest
`~/Library/Application Support/baker/cockpit/launch_manifest.json` entries
~97-107):
- `clerk` seat → `/bin/zsh -lic 'clerkqwenterm'` → `exec zsh -ic 'clerkqwen chat'`
  → `clerk_qwen.py chat` (Qwen3 workbench CLI — NOT a Claude session;
  CLERK_QWEN3_TERMINAL_LAUNCHER_INSTALL_1, 2026-06-06). `clerkqwen()` reads
  `BAKER_API_KEY` via `op read` at launch.
- `clerk-haiku` seat → `clerkhaiku()` → `claude --model claude-haiku-4-5-...`,
  `BAKER_ROLE=clerk-haiku`, title "Clerk Chat".

So the `clerk` session is NOT running what its launcher specifies.

## Engineering Craft Gates

- **Diagnose (applies, MANDATORY FIRST):** establish how the clerk session ended
  up running claude. Fastest loop: `tmux respawn-pane`-style relaunch of the
  clerk seat launch command in a scratch tmux session and watch it. Ranked
  hypotheses: (1) `clerkqwen chat` fails at launch (op read empty in launchd
  context / clerk_qwen.py crash) and the surviving interactive zsh then runs
  something else or a fleet-restore path relaunched the wrong alias; (2) fleet
  launcher (`fleet_terminals.sh` / cutover restore) mapped both slugs to one
  launch; (3) someone manually started clerkhaiku inside the clerk session
  post-cutover (2026-07-18 00:30Z fleet bring-up). Capture the actual failure
  output before fixing.
- **Prototype:** N/A — restore-to-spec work.
- **TDD (applies, probe form):** no unit seam; verification is live probes below.

## Implementation

1. Per Diagnose result, restore the `clerk` tmux session to its specified
   launcher (`clerkqwenterm` → `clerk_qwen.py chat`) — kill the stray claude in
   that session first (it is a duplicate of clerk-haiku, no unique state; leave
   the real `clerk-haiku` session untouched).
2. Harden `clerkqwenterm` failure mode: if `clerk_qwen.py` exits/crashes (bad
   key, network), the pane must show a loud `CLERK SEAT DOWN: <reason>` line and
   idle — never silently fall back into another agent's launcher. (Fail loud;
   Mnilax rule.)
3. If hypothesis (2) proves a launcher/manifest bug, fix `fleet_terminals.sh` /
   manifest so each slug launches its own command; re-run only the clerk seat.
4. Report which hypothesis held.

## Key Constraints

- Do NOT touch the `clerk-haiku` session/alias (Director-ratified 2026-06-05 Haiku clerk lane).
- Do NOT edit `~/.zshrc` clerkhaiku/other functions beyond the `clerkqwenterm` hardening.
- No secrets in files; `op read` stays the key source.
- Wake mapping / bus keys for both slugs unchanged.

## Verification

1. `tmux display-message -t clerk -p '#{pane_current_command}'` → python3/clerk_qwen (not claude.exe); clerk-haiku still claude.exe.
2. Bus probe: post a test message to `clerk`; confirm the clerk seat's own lane handles or the ttyd view shows the Qwen terminal alive (Qwen CLI does not drain bus — state expected behavior in the report; if clerk seat should ack bus, flag as follow-up decision for lead, do not improvise).
3. Kill `clerk_qwen.py` manually → pane shows `CLERK SEAT DOWN`, does NOT morph into claude.
4. Cockpit `/api/agents` shows both seats `session_up`.

## Files Modified
- `~/.zshrc` `clerkqwenterm()` only (hardening) — coordinate with lead before editing (shared file)
- `fleet_terminals.sh` / `launch_manifest.json` only if hypothesis (2)

## Do NOT Touch
- `clerkhaiku()` alias, clerk-haiku session, `~/bm-clerk/CLAUDE.md`
- Controller code (separate brief WAKE_RESPAWN_BACKLOG_DRAIN_1 owns it)

## Done

Report to lead on topic `clerk-seat-collision-fix-1` with hypothesis verdict + probe outputs. No commits to shared dotfiles without noting exact diff in the report.
