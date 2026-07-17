# LAB_COCKPIT_NOTIFY_SLICE_1 — macOS notification + sound on card attention

- status: QUEUED — dispatch AFTER LAB_COCKPIT_REDESIGN_1 PR 2 (D4-D6) merges
- ratified: Director GO 2026-07-17 (chat, AH1-lead session) — "go queue notifications after launch"
- seat: TBD at dispatch (b-pool)
- parent: LAB_COCKPIT_REDESIGN_1 @2836ae83 · scope SCOPE_LAB_TERMINAL_COCKPIT_1
- task class: production implementation (local-only cockpit controller + static page)
- done-state class: live-verified (Lesson #8 — real notification observed, not compile-clean)

## Context
Cowork pops a sound + top-right macOS banner when Claude finishes. The cockpit
cards only flash on-screen; Director misses them when not looking at the control
room. Wants the same sound + banner from cockpit seats. Ratified as a small
slice riding AFTER PR 2 so the cockpit launch is not delayed.

## Problem
No out-of-app signal when a cockpit seat enters an attention state (needs_go
newly true, unacked 0→N). Director must be watching the grid to notice.

## Context Contract — read ONLY these
- scripts/cockpit_controller.py (poll loop + /api/agents fields)
- scripts/cockpit_static/{cockpit.js,index.html} (header, poll consumer)
- This brief. NO vault libs, NO matter context, NO bus/dashboard.py.

## Files Modified (expected)
- scripts/cockpit_controller.py — transition detector + notifier (osascript /
  terminal-notifier if present; system sound; per-seat debounce + cooldown)
- scripts/cockpit_static/index.html + cockpit.js — mute toggle in header
  (persisted localStorage, default ON = notifications enabled)
- tests/test_cockpit_notify.py — new: transition detection, debounce, mute flag
- .claude/how-to/lab-cockpit.md — runbook section

## Constraints
- Controller-side firing (works with page closed). NO new model usage, NO bus
  changes, loopback-only unchanged. One notification per seat per transition;
  cooldown against storms. Zero changes to PR #588 / PR 2 gate chains.

## Verification
- Unit: pytest tests/test_cockpit_notify.py (transition matrix, debounce, mute).
- Live (Lesson #8): flip a pilot seat into needs_go → banner + sound appear
  top-right on the Mac; second identical poll tick → NO duplicate; mute ON →
  silent; page closed → still fires.

## Quality Checkpoints / Acceptance criteria
- AC-1: needs_go false→true fires exactly one banner+sound within one poll tick.
- AC-2: unacked 0→N fires once; N→N+1 within cooldown does not.
- AC-3: mute toggle suppresses all notifications; persists across reload.
- AC-4: controller with cockpit page closed still notifies.
- AC-5: existing cockpit test suite green; live :7800 behavior unchanged otherwise.

## Gate plan
codex delta gate (blocking, verdict ID cited) → lead line-read + merge →
deploy via install_cockpit_controller.sh → POST_DEPLOY_AC to lead →
Director eyeball (hear the sound once).

## Estimate
~half-day build slice incl. gates.
