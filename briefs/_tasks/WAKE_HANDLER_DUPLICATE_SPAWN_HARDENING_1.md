# WAKE_HANDLER_DUPLICATE_SPAWN_HARDENING_1

**dispatched_by:** lead · reply-target: bus → lead · effort: high
**Task class:** bug-fix / hardening (Diagnose gate first — reproduce each failure mode before fixing)
**Harness-V2:** Context Contract below; done rubric AC1-AC5; gate plan G1 self-test → codex G3 → lead merge.

## Problem (live incident 2026-07-04, step-2 pilot)

Every bus message addressed to `baden-baden-desk` spawned a FRESH Terminal window on the Mac Mini
(3+ duplicates twice in one hour). Two compounding bugs plus one design gap:

1. **Launcher stalls at interactive prompt.** `/tmp/brisen-lab-wake-badenbadendesk.command` inherits
   `ANTHROPIC_API_KEY` from the wake-handler environment; Claude Code then blocks on the interactive
   "Detected a custom API key — use it?" dialog. The session never becomes live, so every subsequent
   wake sees "not running" and spawns another window.
2. **isAliasLive is host-local.** The desk had a LIVE session on the Director's laptop; the Mini's
   guard cannot see cross-host sessions, so it spawned anyway.
3. **No wake debounce.** N messages in a burst = N wake attempts. A claim/receipt storm (20 msgs)
   would have opened 20 windows.

## Scope / where

- Wake handler + wake-command template on the Mac Mini (launchd/wake-listener stack; see
  `~/.claude/...memory` wake-delivery notes and brisen-lab wake_events flow).
- brisen-lab daemon side ONLY if the debounce belongs server-side (prefer server-side dedup:
  one wake attempt per slug per cooldown window, e.g. 120s, tracked on wake_events).

## Fix requirements

- **F1:** Strip `ANTHROPIC_API_KEY` (and any `*_API_KEY` not needed by the launcher) from the spawned
  command environment, OR pre-seed the CC config so no interactive prompt can appear. Wake spawn must
  reach the CC prompt unattended, zero keypresses.
- **F2:** Replace/augment `isAliasLive` with a robust liveness check on the wake host: lock/pidfile
  per slug (`~/.brisen-lab/live/<slug>.pid`, stale-safe) written by the spawned session itself at boot;
  handler refuses to spawn while a fresh pid/heartbeat exists. Cross-host: if the daemon carries a
  recent heartbeat for the slug from ANY host (forge telemetry `daemon_last_seen` / terminal heartbeat),
  skip the spawn and log `wake_skipped_live_elsewhere`.
- **F3:** Debounce: max 1 spawn attempt per slug per cooldown window regardless of message volume;
  further wakes within the window are recorded, not spawned.
- **F4:** Fail loud: every skipped/deduped/stalled wake logged with reason (wake-listener log + bus
  audit where applicable). No silent drops.

## Acceptance criteria

- AC1: Simulated burst of 5 dispatches to a test slug → exactly 1 Terminal spawn, 4 logged dedups.
- AC2: Spawn reaches interactive CC prompt with NO api-key dialog (prove with a scripted spawn).
- AC3: With a live session (pidfile fresh), new dispatch → 0 spawns, `wake_skipped` logged.
- AC4: With daemon heartbeat showing slug live elsewhere → 0 spawns, `wake_skipped_live_elsewhere`.
- AC5: Stale pidfile (dead pid) does NOT block a legitimate wake.

## Constraints

- Desk auto-wakes are currently SUSPENDED fleet-wide (Director directive; 6 slugs in
  `BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS`). Test against a NON-desk test slug or a scratch slug —
  do NOT re-enable any desk slug.
- macOS TCC: deploy launchd artifacts under `~/Library/Application Support/...`, never `~/Desktop`.
- Coordinate any brisen-lab (server) change as its own PR in the brisen-lab repo with codex G3.

## Anchors

- Incident: AH1 session 2026-07-04 ~17:40-18:35Z; memory `project_desk_wake_suspension_live_restore_owed.md`.
- Related prior arc: wake-delivery two-layer failure 2026-06-18 (`-609/-600` launch-context).
