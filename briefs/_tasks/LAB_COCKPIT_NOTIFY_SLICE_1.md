# LAB_COCKPIT_NOTIFY_SLICE_1 — macOS banner + sound when a bus lands on a non-self-awake seat

- status: QUEUED — dispatch AFTER LAB_COCKPIT_REDESIGN_1 PR 2 (D4-D6) merges
- ratified: Director GO 2026-07-17 (chat, AH1-lead session); requirement CORRECTED same day (see Context)
- seat: TBD at dispatch (b-pool)
- parent: LAB_COCKPIT_REDESIGN_1 @2836ae83 · scope SCOPE_LAB_TERMINAL_COCKPIT_1
- task class: production implementation (local-only cockpit controller + static page)
- done-state class: live-verified (Lesson #8 — real notification observed, not compile-clean)

## Context — Director's corrected requirement (2026-07-17)
NOT needed for work-completion: Cowork app and Codex app already fire their own
macOS notification when they finish, and self-awake seats answer by bus.
The REAL gap: when lead (or anyone) sends a bus dispatch TO an app-resident seat
that is NOT on the self-awake regime (e.g. codex-arch), the message sits unread
until Director happens to see the card flash. Director's example: he barely
caught codex-arch's card flashing from the corner of his eye; unnoticed, the
gate request would have sat for a long time.
Related live infra: Wake.app already carries BUS_AUTOWAKE_APP_RESIDENT_NOTIFY_1
(banner on fg=1 wake to live App-resident agents; repo forward-port =
WAKE_HANDLER_APP_RESIDENT_NOTIFY_FORWARD_PORT_1). That covers wake-registered
aliases only; seats outside the wake regime (codex-arch et al.) get nothing.
This slice closes the residue from the cockpit controller side.

## Problem
A bus dispatch to a non-self-awake seat produces no sound/banner. Director must
visually catch the cockpit card flash to know a seat needs a manual poke.

## Context Contract — read ONLY these
- scripts/cockpit_controller.py (poll loop + /api/agents fields: unacked_count, needs_go)
- scripts/cockpit_static/{cockpit.js,index.html} (header, poll consumer)
- Wake.app marker note above (dedupe boundary — do not re-notify what Wake.app already banners)
- This brief. NO vault libs, NO matter context, NO bus/dashboard.py.

## Files Modified (expected)
- scripts/cockpit_controller.py — transition detector: per-seat unacked_count
  0→N on NON-self-awake seats → macOS banner + sound (osascript /
  terminal-notifier if present), naming the seat ("codex-arch: unread bus — poke it")
- seat coverage list: derive non-self-awake set from the layout manifest /
  registry at generate time, no hand-kept list
- scripts/cockpit_static/index.html + cockpit.js — mute toggle in header
  (persisted localStorage, default ON)
- tests/test_cockpit_notify.py — new: transition matrix, debounce, mute, seat-set
- .claude/how-to/lab-cockpit.md — runbook section

## Constraints
- Controller-side firing (works with page closed). NO new model usage, NO bus
  changes, loopback-only unchanged. One notification per seat per 0→N
  transition; cooldown against storms; no double-banner where Wake.app already
  fired (dedupe by wake-registered alias set). Zero changes to PR #588 / PR 2
  gate chains.

## Verification
- Unit: pytest tests/test_cockpit_notify.py (transition matrix, debounce, mute,
  self-awake exclusion).
- Live (Lesson #8): post a real bus message to codex-arch → banner + sound
  top-right within one poll tick; second tick no duplicate; mute ON → silent;
  cockpit page closed → still fires; self-awake seat (e.g. b1) → NO banner.

## Quality Checkpoints / Acceptance criteria
- AC-1: bus lands on codex-arch (non-self-awake) → exactly one banner+sound
  within one poll tick, seat named.
- AC-2: N→N+1 within cooldown does not re-fire; ack-to-0 then new message re-fires.
- AC-3: self-awake / wake-registered seats excluded (no double-banner with Wake.app).
- AC-4: mute toggle suppresses all; persists across reload; controller with page
  closed still notifies.
- AC-5: existing cockpit suite green; live :7800 otherwise unchanged.

## Gate plan
codex delta gate (blocking, verdict ID cited) → lead line-read + merge →
deploy via install_cockpit_controller.sh → POST_DEPLOY_AC to lead →
Director eyeball (hear the sound on a real codex-arch dispatch).

## Estimate
~half-day build slice incl. gates.
