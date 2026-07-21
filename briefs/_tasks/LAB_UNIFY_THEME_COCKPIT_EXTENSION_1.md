# BRIEF: LAB_UNIFY_THEME_COCKPIT_EXTENSION_1 — light mode reaches the cockpit pane + drop dup status line

```yaml
brief_id: LAB_UNIFY_THEME_COCKPIT_EXTENSION_1
dispatched_by: lead
assigned_to: b2
repo: baker-master (worktree ~/bm-b2; branch b2/theme-cockpit-extension-1 from origin/main) — cockpit static lives here, NOT brisen-lab
status: PENDING
```

## Context

Director feedback 2026-07-21 morning on the live /v2 toggle (verbatim): "light
mode button... switches to the lead mode only in the left side panel. Not the
whole site." + "the dark button sits on top of Live28 with terminal... remove
Live28 with terminal, which is in green from this right-hand corner. We have
the same sitting next to the fleet cockpit. That will be enough."

Prior brief LAB_UNIFY_UI_THEME_TOGGLE_1 scoped the cockpit OUT; Director has now
scoped it IN. Two changes, both in `scripts/cockpit_static/` (baker-master):

1. **Cockpit follows `labTheme`** — light palette + bootstrap + storage-event
   live-follow, same mechanism as the v2 sub-pages (see merged brisen-lab
   @1cf9245 `static/v2/skills.html` for the reference pattern).
2. **Remove the top-right `#conn` status line** (`index.html:17`, populated
   `cockpit.js:242` "live · N with terminal / M seats"). CAREFUL: `#conn` is
   also the red feed-offline surface (`connEl.textContent = "feed offline …"`,
   `.feed-dead`). That signal must NOT be lost — migrate live/offline state
   into the existing header status next to FLEET COCKPIT (the `cockpit.js:202`
   surface) so ONE health line remains, where Director expects it.

### Surface contract (ui-surface-prebrief, V1)

1. **User action:** Director clicks the /v2 theme button; the embedded cockpit pane re-themes with everything else. No new control on the cockpit itself.
2. **Backend route:** NONE new. Cockpit static served via controller/bridge; same-origin under the Lab domain when embedded.
3. **Endpoint contract:** no fetches added. Theme = `localStorage` key `labTheme` (shared origin with the /v2 shell when embedded; standalone local cockpit with no key stays dark).
4. **State location:** browser localStorage only.
5. **UI repo:** baker-master `scripts/cockpit_static/*` + laptop resync.
6. **Director surface preference:** Director specified both changes himself.
7. **Reviewer instruction:** load /v2 in a browser via the Lab, toggle both ways, confirm the cockpit pane re-themes live AND the top-right status line is gone AND the header line next to FLEET COCKPIT still shows live/offline state (kill the controller to prove offline still surfaces). Code-shape review is NOT sufficient.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: none

## Harness V2

- **Context Contract:** this brief (whole); `scripts/cockpit_static/cockpit.css` (token block); `scripts/cockpit_static/index.html`; `scripts/cockpit_static/cockpit.js` (lines ~195-260 status surfaces); merged brisen-lab theme pattern (`static/v2/skills.html` bootstrap + storage listener) as reference; `.claude/how-to/lab-cockpit.md` (resync/kickstart steps).
- **Task class:** small-fix-production (Director-facing cockpit).
- **Done rubric:** Merged + resynced to `~/Library/Application Support/baker/cockpit/` + controller kickstarted + live AC in the Lab embed + POST_DEPLOY_AC_VERDICT. Writeback: lead registry note.
- **Gate plan:** b2 self-test (local browser both themes + offline sim) → push branch → blocking codex gate on pushed SHA → lead merge → resync + kickstart → lead live AC via Lab → verdict on bus.

## Feature 1: cockpit light palette + labTheme follow

### Problem
The /v2 light mode stops at the shell edge — the cockpit pane (most of the
screen on AGENTS) stays dark, and a duplicate green status line clutters the
top-right corner under the theme button.

- Add `html[data-theme="light"]` override block to cockpit.css redefining the cockpit's own token names 1:1 (map from the dark values; keep status semantics — green stays green, red stays red, amber darkens for white contrast). Grep for hardcoded hex outside the token block; migrate leftovers; report count.
- Inline pre-paint bootstrap snippet in index.html `<head>` (identical try/catch pattern to v2 pages).
- `storage` event listener applies theme changes live while embedded (shell writes labTheme; same-origin iframe receives the event).
- Standalone cockpit (127.0.0.1:7800, different origin, no labTheme key) = dark default, zero visual change.

## Feature 2: single health line

- Remove the `#conn` element render path from the top-right corner.
- Fold its two states into the FLEET COCKPIT header status surface: live (green, keep the driveable/seat count there if it fits naturally) and feed-offline (red, keeps `.feed-dead` semantics).
- No other header/layout changes.

## Files Modified
- `scripts/cockpit_static/cockpit.css` (light token override) · `scripts/cockpit_static/index.html` (bootstrap snippet, #conn removal) · `scripts/cockpit_static/cockpit.js` (storage listener, status-line fold-in) · related tests.

## Verification
1. Existing cockpit tests green; extend/adjust any test asserting `#conn`.
2. Local browser: both themes; kill controller feed → offline shows red in the header line; restart → green returns.
3. Embedded via Lab: toggle both ways, cockpit follows live, no reload needed.
4. `git diff --stat`: `scripts/cockpit_static/*` + tests only.

## Do NOT Touch
- Wake/nudge logic (separate brief COCKPIT_OPEN_NUDGE_SPLIT_1 owns openTerm) · controller python beyond what resync requires · brisen-lab repo · loop boards.

## Quality Checkpoints
1. No flash-of-wrong-theme; first-time visitor byte-identical dark.
2. Feed-offline signal provably survives the #conn removal.
3. Ship report + SHA on bus topic `lab-unify/theme-cockpit`; codex gate on pushed SHA.
