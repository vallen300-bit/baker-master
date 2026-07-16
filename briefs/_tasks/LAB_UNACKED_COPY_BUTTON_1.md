# LAB_UNACKED_COPY_BUTTON_1 — copy control on the unread-badge popup (Director-ratified 2026-07-16)

- **Status:** READY — Director-ratified in chat 2026-07-16 evening; independent of the cockpit arc.
- **Repo:** brisen-lab. **Dispatcher:** lead. **Builder:** deputy-codex (mechanical UI slice). **Gate:** deputy (Claude side) cross-vendor review → lead merge.

## Context

Director ruling 2026-07-16 evening (cockpit conversation, but Lab-side and independent). Existing surface works well; this adds one control.

**Context Contract (Harness V2):** builder reads ONLY brisen-lab `static/app.js` (renderUnreadBadge / state.busBadge / dot-popup code path) + `static/glance_state.js` + the Lab CSS tokens. Nothing else.
**Task class:** small production UI slice (Render-deployed Lab).
**Done rubric / done-state:** ACs live on staging/local, existing JS tests green + 1 new payload test; done-state = merged + deployed + Director can copy-paste from a live card.
**Gate plan:** G1 self-test → deputy (Claude side) cross-vendor review → lead merge → live check on one flashing card.

## Problem

The fleet-card white-circle unread indicator opens an info box listing unacked bus messages (count + topics; age colors amber >10 min / red >30 min — see `static/app.js` renderUnreadBadge/renderStateDot lineage and `static/glance_state.js`). Director wants a one-click **copy** control on that box: copy the full unacked summary (alias, count, topics, ages) to the clipboard, so he can paste it into an idle terminal that is sitting on unacked buses and tell it to act.

## Files Modified (expected)

- brisen-lab `static/app.js` (+ CSS file if tokens live separately); 1 new test file. Nothing else.

## Deliverables

1. Copy control (button or checkbox per current Lab design tokens) on the unread info box/tooltip surface.
2. Copied payload (plain text): `TO: <alias> — <N> unacked bus message(s), oldest <age>` + one line per topic. Ends with `Read /msg/<alias> with the full unacked filter and act.` — paste-ready as a terminal instruction.
3. `navigator.clipboard.writeText` with fallback; visible "copied ✓" feedback.
4. No schema/API changes — data already in `state.busBadge`.

## Verification

Live click-and-paste proof on a card with real unacked messages; paste result shown in ship report.

## Quality Checkpoints / Acceptance criteria (live)

1. Click copy on a card with unacked ≥1 → clipboard holds the exact payload (verified paste).
2. Zero-unacked cards show no copy control.
3. No regression to badge/dot rendering (existing tests pass; add one covering payload format).

## Out of scope

Cockpit page (separate arc). Bus ack semantics. Any auto-dispatch of the pasted text.
