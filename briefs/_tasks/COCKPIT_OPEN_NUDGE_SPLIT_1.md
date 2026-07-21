# BRIEF: COCKPIT_OPEN_NUDGE_SPLIT_1 — opening a seat's terminal must not auto-wake it

```yaml
brief_id: COCKPIT_OPEN_NUDGE_SPLIT_1
dispatched_by: lead
assigned_to: deputy-codex
repo: baker-master (local checkout; branch deputy/cockpit-open-nudge-split-1 from origin/main)
status: PENDING
```

## Context

codex-arch Lab-V2 functional audit (bus #14272) P0, lead-verified real,
**Director-approved 2026-07-21** ("both accepted"): `openTerm()` in
`scripts/cockpit_static/cockpit.js` calls `nudgeSeat(slug, name)` (line ~335)
— so opening a seat's detail pane to LOOK at it fires a force-wake
(`/api/sessions/<slug>/wake?force=1&origin=cockpit_click`) whenever that seat
has unacked mail. Inspection must never be an action. The explicit Nudge
button (`termNudge` listener, line ~970) already provides the intentional
path and STAYS.

## Estimated time: ~45m
## Complexity: Low
## Prerequisites: none

## Harness V2

- **Context Contract:** this brief; `scripts/cockpit_static/cockpit.js` (nudgeSeat block ~300-345, termNudge wiring ~965-975); any tests referencing nudge/openTerm (`grep -rn nudge tests/`).
- **Task class:** small-fix-production.
- **Done rubric:** Merged + resynced to `~/Library/Application Support/baker/cockpit/` + controller kickstarted + live AC (open a seat with unacked mail → NO wake fires, no toast; press Nudge → wake fires, toast shows) + POST_DEPLOY_AC_VERDICT. Writeback: lead registry note.
- **Gate plan:** self-test → push branch → blocking codex gate on pushed SHA → lead merge → resync + kickstart → live AC → verdict.

## Implementation

1. Delete the `nudgeSeat(slug, name);` call (and its `// explicit-click wake` comment) from `openTerm()`. Nothing else in `openTerm()` changes.
2. Keep `nudgeSeat()` itself, its debounce, guards, and the `termNudge` button listener untouched — that is now the ONLY caller.
3. Update the comment block above `nudgeSeat()` (it currently describes click-to-open as the trigger) to reflect button-only invocation.
4. Adjust/extend any test that asserted the auto-nudge; add one asserting `openTerm` does NOT call the wake endpoint (fetch spy or DOM harness per existing test idiom).

## Key Constraints
- Do NOT touch the controller's wake endpoint, dedupe/force semantics, or the WAKE_INJECT arc — client-side caller removal only.
- The audit's other findings (embed 503 retry, stale quarantine, IA) are OTHER briefs — zero scope creep.

## Verification
1. Tests green.
2. Local cockpit: seat with unacked mail — open detail → wake_audit.log shows NO cockpit_click wake; press Nudge → wake fires + toast.
3. `git diff --stat`: cockpit.js + tests only.

## Quality Checkpoints
1. Nudge button provably still works after the split.
2. Ship report + SHA on bus topic `cockpit/open-nudge-split`; codex gate on pushed SHA.
