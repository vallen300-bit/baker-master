# B1 report — CLERK_SEAT_COLLISION_FIX_1

- **Brief:** `briefs/_tasks/CLERK_SEAT_COLLISION_FIX_1.md` @aab6e687 (Director-dispatched, lead #13130)
- **Date:** 2026-07-19
- **Class:** PROBE-VERIFIED local seat/launcher repair (no repo code → no codex gate; lead reviews)
- **Report topic:** `clerk-seat-collision-fix-1`

## Hypothesis verdict

**Hyp 2 (fleet launcher / manifest maps both slugs to one launch) — RULED OUT.**
`~/Library/Application Support/baker/cockpit/launch_manifest.json` has two distinct
entries: `clerk → alias clerkqwenterm, launch "/bin/zsh -lic 'clerkqwenterm'", port 7614`
and `clerk-haiku → alias clerkhaiku, launch "/bin/zsh -lic 'clerkhaiku'", port 7615`.
`fleet_terminals.sh` launches each seat **verbatim from the manifest** and explicitly
never double-seats an already-running/already-migrated slug. `~/.zshrc` aliases are
distinct. No structural mapping bug.

**Hyp 1 (clerkqwen fails at launch + fragile launcher) — HOLDS; this is the durable defect.**
`clerkqwenterm()` ends in `exec zsh -ic 'clerkqwen chat'` with **zero failure handling**.
`clerk_qwen.py cmd_chat` (line 533) resolves the Baker API key **eagerly** at start via
`resolve_api_key()`; an empty `op read` (op not authenticated in the launchd/cutover
context) or a network/crash raises `ClerkQwenError` → `main()` returns 2 → `clerkqwen chat`
exits 2. Because the launcher `exec`s a `zsh -ic '<one command>'`, when that command exits
the shell exits and **the entire `clerk` tmux session vanishes silently**. Empirically
reproduced in a scratch session: `exec zsh -ic false` → session gone, no trace. This is
exactly the "clerk seat effectively dead as an independent agent" the smoke observed.

**Hyp 3 (clerkhaiku launched into a clerk-named session) — the masquerade cause, unreconstructable.**
The smoke saw the `clerk` session running `claude.exe` titled "Clerk Chat" (that title +
binary come only from `clerkhaiku()` / `claude --name "Clerk Chat"`, never from
`clerkqwenterm`). That required a separate wrong-launcher event into a clerk-named session.
The original session was already killed and relaunched correctly at **03:19:15 Jul 19**
(before this dispatch), so no forensic artifact remains. Not a structural bug — a one-off.

## Captured failure output (Diagnose gate)

```
# current launcher form, command exits → session disappears
$ tmux new-session -d -s probe "zsh -ic 'exec zsh -ic false'"
$ tmux has-session -t probe  →  SESSION GONE — pane closed silently on command exit
```

```
# clerk_qwen.py cmd_chat, bad/empty key
resolve_api_key() → raise ClerkQwenError("Baker API key missing…")
main() → print "ERROR: Baker API key missing…" (stderr) → return 2
```

## Live state (rubric b — already correct, no active collision)

- `clerk` pane: `Python` → child `clerk_qwen.py chat` (pid 40623), cwd `~/bm-clerk`. Correct.
- `clerk-haiku` pane: `claude.exe`, title "✳ Clerk Chat". Untouched.
- Both tmux sessions `session_up=true`. (`/api/agents` on 127.0.0.1:7800 returns 401 without
  the cockpit key; underlying tmux truth verified directly.)

No kill/relaunch of the clerk seat was needed — it was already running the right launcher.
`clerk-haiku` never touched.

## Proposed fix (rubric c — GATED on lead: shared `~/.zshrc`, not yet landed)

Harden `clerkqwenterm()` to fail loud and idle instead of vanishing. Exact diff:

```diff
 clerkqwenterm() {
   export BAKER_ROLE=clerk FORGE_TERMINAL=clerk
   cd "$HOME/bm-clerk" || cd "$HOME"
   clear
   print -P "%F{green}Clerk Qwen3 terminal%f - plain-English chat mode"
-  exec zsh -ic 'clerkqwen chat'
+  # CLERK_SEAT_COLLISION_FIX_1: run in the FOREGROUND (not exec) so the seat keeps
+  # control when the CLI exits. The old `exec zsh -ic 'clerkqwen chat'` silently
+  # vanished the whole clerk tmux session whenever clerkqwen chat exited (empty
+  # op-read key at launch, network, crash, or clean exit) — the seat died as an
+  # independent agent.
+  clerkqwen chat
+  local rc=$?
+  # Fail loud + idle: never close silently, never fall through to an interactive
+  # shell that could relaunch another agent (e.g. clerkhaiku) into this seat.
+  print -P "%F{red}%BCLERK SEAT DOWN%b%f: clerkqwen chat exited (rc=${rc}). Seat idle — NOT running any agent. Fix key/network, then relaunch 'clerkqwenterm'."
+  while true; do sleep 3600; done
 }
```

Scratch-tested (simulated bad-key crash): pane **stays alive** showing
`CLERK SEAT DOWN: clerkqwen chat exited (rc=2). Seat idle — NOT running any agent…`,
foreground process = `sleep`, `pane_dead=0`. Passes Verification probe 3 (kill/crash →
CLERK SEAT DOWN, does NOT morph into claude).

## Open items for lead

1. Go to land the `~/.zshrc` `clerkqwenterm()` diff above (gate: "escalate to lead before
   any `~/.zshrc` edit lands"). On go: land it, re-source, re-run probes 1/3/4 live on the
   real clerk seat, post final verdict.
2. Verification probe 2 raised a real question the brief says NOT to improvise: the Qwen CLI
   does **not** drain the bus, so the `clerk` slug's bus mailbox only clears via lead
   bookkeeping. Whether the clerk seat *should* ack its own bus is a design decision — flagged
   here, not changed.
