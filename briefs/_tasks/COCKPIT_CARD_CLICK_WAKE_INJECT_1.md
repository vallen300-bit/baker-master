# BRIEF: COCKPIT_CARD_CLICK_WAKE_INJECT_1 — card click auto-pushes "check bus #id" into the seat's terminal

## Context
Director directive 2026-07-19 afternoon: he still manually wakes almost every seat —
today only ARM auto-woke on a bus post; nothing else moved until manual nudges.
Loops cannot work like that. Interim relief while codex-arch runs the full bus-comm
audit (separate dispatch, same day): clicking an agent's card in the cockpit must
automatically push the wake nudge — "check your bus: #id / topic / from" — into that
seat's terminal composer, saving the Director all copy-pasting.

## Estimated time: ~2h
## Complexity: Medium (mostly diagnosis + wiring existing parts)
## Prerequisites: COCKPIT_REVAMP_COLORS_HEADER_COPY_1 merged (same files). Takes
priority OVER COCKPIT_REVAMP_SPLIT_VIEW_SIDEBAR_1 — build this first.

## Baker Agent Vault Rails
Relevant: build-command-center, verification-surfaces, bus-and-lanes (consumes wake path, no schema change).
Ignore: memory-and-lessons, loop-runner.

## Harness V2
- **Context Contract:** inputs = this brief + cockpit.js openTerm region +
  cockpit_controller.py wake path (`send_wake`, `/api/sessions/{slug}/wake`,
  `_verify_wake_submit`) + wake_audit.log; no Lab code, no vault reads.
- **Task class:** production implementation with a mandatory Diagnose gate first.
- **Done rubric / done-state class:** done = live proof on ≥2 real seats (click →
  nudge text visibly lands + submits in the seat's tmux composer, receipt in
  wake_audit.log) + report with exact HEAD. Gate-verified merge. Compile-clean or
  unit-only is NOT done (Lesson #8).
- **Gate plan:** codex gate on `gates/cockpit-card-click-wake-inject-1`; lead merges
  on PASS + App Support re-sync + controller kickstart + Director live click-test.

## UI-surface prebrief (6 checks)
Surface = existing cockpit cards + terminal drawer, local http://127.0.0.1:7800/.
No new route; reuses POST `/api/sessions/{slug}/wake` (exists, exercised in tests).
Keep the live cockpit visual structure (Director ruling #13307) — a small affordance
on the existing card/drawer, no structural redesign.

---

## Fix 1: Diagnose the wake-on-open path FIRST (mandatory gate)

### Problem
A wake-on-open verb shipped in the redesign (E6), yet the Director still manually
nudges seats. Either card-open never calls the wake endpoint, the wake returns
`skipped: no unacked` on stale glance data, injection lands without submit, or the
nudge text lacks the message details he needs pushed.

### Engineering Craft Gates
- Diagnose: applies — feedback loop = click a card for a seat with a KNOWN unacked
  message, then read `wake_audit.log` + tmux pane. Hypotheses, ranked: (1) frontend
  never calls wake on open; (2) controller skips on stale/empty unacked glance;
  (3) inject-no-submit; (4) nudge text too bare. Probe each in that order; record
  findings in the report BEFORE coding.
- Prototype: N/A — existing plumbing. TDD: applies (Fix 2).

## Fix 2: Click → composed nudge + submit

### Implementation
1. On card click / terminal open for a driveable seat with `unacked_count > 0`:
   frontend calls POST `/api/sessions/{slug}/wake?force=1` (force bypasses dedupe
   floors for an explicit Director click — human intent wins).
2. Controller nudge text for click-origin wakes must carry the payload the Director
   copy-pastes today: `Check your bus: N unacked — #id topic (from sender), ...`
   (top 3 messages max, then "+K more"). Extend the existing nudge composer; add
   `origin=cockpit_click` to the wake audit entry.
3. Ensure the existing verified-submit path (`_verify_wake_submit`, C-l settle) runs
   so the nudge SUBMITS — not parked in the composer. Codex-family C-l skip rule
   applies unchanged.
4. Idempotence: clicking twice must not double-spam — force wake still records
   per-message dedupe so an identical repeat within the floor is coalesced (existing
   guards; verify, don't rebuild).
5. Add a small "nudge" affordance on the drawer bar too (same call) for seats
   already open. No other UI change; structure ruling #13307 holds.

### Key Constraints
- No Lab/bus schema changes; consume existing endpoints only.
- Do NOT auto-wake on mere hover or grid render — explicit click only.
- Fault-tolerant: wake failure surfaces as a visible toast/notice on the card, never
  silent (fail loud).

## Files Modified
- `scripts/cockpit_static/cockpit.js` — click wiring + drawer nudge affordance + failure notice
- `scripts/cockpit_controller.py` — click-origin nudge text + audit origin tag
- `tests/test_cockpit_controller.py` / `tests/test_cockpit_wake.py` — nudge-compose + origin tests
- `scripts/cockpit_static/index.html` — cache-bust bump only

## Do NOT Touch
- Wake dedupe windows / typed repeat logic (merged arcs) — consume, don't modify.
- brisen-lab — nothing server-side.

## Quality Checkpoints
1. Diagnosis findings reported before code (which hypothesis was true).
2. Live: click on 2 real seats with unacked → composed nudge lands AND submits;
   wake_audit.log shows origin=cockpit_click.
3. Double-click does not double-post.
4. Wake failure shows visible notice on the card.
5. Suites green; node --check clean; `?v` bumped.

## Verification SQL
N/A — no DB surface.
