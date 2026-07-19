# BRIEF: COCKPIT_REVAMP_COLORS_HEADER_COPY_1 — Final state palette + header rework + drawer copy button

## Context
Director live walkthrough 2026-07-19 produced a ratified 9-item cockpit revamp spec
(`briefs/_plans/COCKPIT_REVAMP_SPEC_20260719.md` @d5e25efa). This brief carries spec
items **3 (FINAL color palette)**, **6 (header rework)**, **2 (drawer copy button)**,
and encodes item **7 (quiet-when-healthy standing rule)**. Frontend-only + trivial
controller-free changes. First brief of the b2 revamp lane; ship before
COCKPIT_REVAMP_SPLIT_VIEW_SIDEBAR_1.

## Estimated time: ~2-3h
## Complexity: Medium
## Prerequisites: none (independent of split view). NOTE: deputy-codex has a parallel
fix round on `deputy-codex/cockpit-msg-panel-body-preview-1` (msg panel hydration) —
different cockpit.js regions, but REBASE on main before opening your PR.

## Baker Agent Vault Rails
Relevant: build-command-center (dispatch/gate flow), verification-surfaces (live curls + eyeball).
Ignore: bus-and-lanes, memory-and-lessons, loop-runner — no bus or memory surface changes.

## Harness V2
- **Context Contract:** inputs = this brief + `briefs/_plans/COCKPIT_REVAMP_SPEC_20260719.md`
  (items 2/3/6/7) + the three static files named below; no vault reads, no bus reads
  beyond dispatch/report; do NOT load dashboard.py or Lab code.
- **Task class:** production implementation — frontend-only, local surface (cockpit),
  no DB, no external API.
- **Done rubric / done-state class:** done = branch pushed + Quality Checkpoints 1-6
  all literally exercised (screenshots for 1-3) + report on bus with exact HEAD.
  Done-state class: gate-verified merge (lead merges on codex PASS); compile-clean or
  eyeball-only claims are NOT done.
- **Gate plan:** independent codex gate on `gates/cockpit-revamp-colors-header-copy-1`
  after b2 report; lead merges on PASS, re-syncs App Support, kickstarts controller,
  then live eyeball as post-deploy AC.

## UI-surface prebrief (6 checks)
Surface = local cockpit at http://127.0.0.1:7800/ (token-gated), served from
`scripts/cockpit_static/` via `scripts/cockpit_controller.py`. Surface exists and was
walked through live by Director 2026-07-19 — every change below is a ratified verbatim
ruling on that exact surface. No new routes, no cross-repo URLs. Remote path (Lab
bridge /cockpit/) serves the same static dir — changes propagate automatically.

---

## Feature 1: FINAL state color palette (spec item 3)

### Problem
Current glance colors (green tint NEEDS_GO, amber NEW, grey unknown) predate the
Director's final palette ruling. Ratified FINAL palette supersedes ALL earlier
proposals.

### Current State
- `scripts/cockpit_static/glance_state.js` — `resolveGlanceState()` precedence NEEDS_GO > WORKING > NEW.
- `scripts/cockpit_static/cockpit.js` `glanceClass(row)` lines ~88-105 maps state → CSS class
  (`glance-needs-go`, `glance-amber`, `glance-unknown`, "" for WORKING/IDLE).
- `card(meta)` lines ~430-505 assigns `row/app/up/down/error` classes.
- `/api/agents` rows already carry `oldest_unacked_age_sec`, `unacked_count`,
  `is_working`, `needs_go`, `session_up`, `has_telemetry` — all inputs exist; NO
  controller change needed.

### Engineering Craft Gates
- Diagnose: N/A — not a bug; ratified visual change.
- Prototype: N/A — palette is ratified verbatim; no design uncertainty.
- TDD/verification: applies — extend the state-resolution logic in `glance_state.js`
  (pure function) and add/extend its unit vectors if a test harness exists for it;
  otherwise verify via the live-state checklist below.

### Implementation
1. Extend state resolution (keep precedence order, add age split):
   - running (`is_working`) → class `st-running` — **bright green**.
   - `needs_go` → class `st-go` — **bright blue, PULSATING** (CSS `@keyframes` pulse on
     border/chip; reuse existing pulse pattern if present, else add one).
   - unread (`unacked_count > 0`) AND `oldest_unacked_age_sec <= 600` → class
     `st-unread` — **muted amber**. Applies from second zero (Director explicitly
     rejected a neutral sub-2-min window).
   - unread AND `oldest_unacked_age_sec > 600` → class `st-unread-old` — **bright red**.
   - no-signal + offline (`!session_up` OR no telemetry AND seat expected up) → class
     `st-offline` — **muted red, PULSATING**.
   - idle / plain no-signal / not-started / everything else → class `st-idle` — **muted grey**.
2. Agent NAME text takes the same color as its chip, slightly softer intensity OK —
   apply via the same `st-*` class on the card, name styled with a reduced-opacity
   variant of the chip color.
3. Update `cockpit.css` with the 6 `st-*` classes; delete/alias the superseded
   `glance-needs-go`/`glance-amber` colors (keep class names only if removal breaks
   other selectors — then re-point their colors to the new palette).
4. **Quiet-when-healthy standing rule (spec item 7):** add a top-of-file CSS comment
   block: color is an attention budget; healthy = colorless/muted; color only for
   states needing Director's eyes; single exception = the green header health line.
   Apply this rule to every choice in this brief.
5. Cockpit deliberately diverges from Lab colors. Touch NOTHING in brisen-lab.

### Key Constraints
- Precedence: running > GO > unread-old > unread > offline > idle — a working seat
  with unread mail shows running green (attention order per walkthrough); if in doubt
  keep `resolveGlanceState()`'s existing precedence and only recolor.
- 600s threshold is a named const (`UNREAD_OLD_S = 600`), not a magic number.
- Do NOT touch `stateBySlug` population, polling, or `/api/agents` handling.

### Verification
With controller running locally: force each state (idle seat, seat with fresh unacked
via a test bus post, seat with >10-min unacked, killed tmux seat for offline, a
working seat) and eyeball all 6 colors + both pulses. Screenshot for the report.

---

## Feature 2: Header rework (spec item 6)

### Problem
Header carries an oversized digit block, lowercase title, jargon labels, and a bell
toggle the Director doesn't want in the header.

### Current State
- `scripts/cockpit_static/index.html` lines ~10-32: `<header class="cockpit-header">`,
  eyebrow "LIVE OPERATIONS · BRISEN LAB", `<h1 id="cockpit-title">Fleet cockpit</h1>`,
  `#conn` status element, `#notify-toggle` bell button.
- `cockpit.js` line ~165 sets `connEl.textContent = "live · N driveable / M seats"`.
- Bell wiring: `notifyMuted` localStorage + `/api/notify/state|mute` endpoints.

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A — form is ratified final.
- TDD/verification: N/A honest test seam (static markup); live eyeball checklist below.

### Implementation
1. Title → `FLEET COCKPIT` (all capitals, keep current type scale or slightly smaller).
2. REMOVE the oversized digit block entirely.
3. Top-right keeps `live · N driveable / M seats` — ALL words **bright green**, current
   small size. Green = healthy heartbeat; turns **red** only when the /api/agents feed
   is stale/dead (poll failure path already detectable in the fetch error handler —
   flip a `.feed-dead` class there). This supersedes the earlier same-day "relocate
   under title + mute grey" rulings.
4. Relabel jargon to plain words at build time ("agents / with terminal / attention"
   direction ratified — e.g. "driveable" → "with terminal" if it reads better; keep
   the line short).
5. REMOVE the bell (`#notify-toggle`) from the header. Banners stay ON;
   `COCKPIT_NOTIFY_ENABLED` env kill switch remains for engineers. Delete the button
   + its wiring (lines ~553-602 mute hydration) but LEAVE the controller
   `/api/notify/*` endpoints untouched (kill switch path).
6. Freed top-right/corner space: leave reserved, EMPTY (future tenant: fleet cost — parked).

### Key Constraints
- Do not remove `COCKPIT_NOTIFY_ENABLED` handling in `cockpit_controller.py`.
- Do not add anything new to the header.

### Verification
Eyeball: caps title, no digit block, green live line, no bell; kill controller feed
(stop controller, keep static open) → live line turns red.

---

## Feature 3: Copy button on open-terminal drawer (spec item 2)

### Problem
The unacked list inside the opened terminal view (`#termUnacked`) has no Copy control;
the card message panel and Lab drawer both have one.

### Current State
- `doMsgCopy()` cockpit.js lines ~330-345; `copyToClipboard()` ~317-328; `#msg-copy`
  button wired at line ~553.
- Terminal drawer: `openTerm(slug, name)` lines ~222-249, unacked list in `#termUnacked`.

### Engineering Craft Gates
- Diagnose/Prototype: N/A. TDD: N/A — thin DOM wiring; verify by live click.

### Implementation
Add a Copy button to the terminal drawer header (`#termbar`), reusing the SAME
`copyToClipboard()` + summary-format helper as `doMsgCopy` (extract the shared
formatter if needed — no copy-pasted duplicate logic), scoped to the open seat's
unacked rows. Same disabled-during-copy + "copied ✓" feedback pattern.

### Verification
Open a seat with unacked messages → click Copy → paste shows `#id · topic · from`
lines for that seat only.

---

## Files Modified
- `scripts/cockpit_static/cockpit.js` — state classes, header line, drawer copy
- `scripts/cockpit_static/cockpit.css` — `st-*` palette, pulses, header, quiet-when-healthy comment
- `scripts/cockpit_static/glance_state.js` — age-split state resolution (if resolution lives here)
- `scripts/cockpit_static/index.html` — title caps, digit block + bell removal, **add `?v=N` cache-bust to cockpit.css/cockpit.js/glance_state.js refs (Lesson #4 — currently MISSING entirely; introduce `?v=1` and bump on every future change)**

## Do NOT Touch
- `scripts/cockpit_controller.py` — no controller changes in this brief (notify endpoints stay).
- `brisen-lab/*` — cockpit deliberately diverges from Lab this round.
- `scripts/generate_cockpit_layout.py`, `cockpit_layout.json` — layout untouched.
- Msg-panel hydration region (deputy-codex parallel arc) — rebase, don't refactor it.

## Quality Checkpoints
1. All 6 states render correct colors; 2 pulse states animate.
2. Name text matches chip color (softer OK).
3. Header: caps title, no digits, green live line, red on dead feed, no bell.
4. Drawer Copy works, card-panel Copy still works.
5. `?v=1` present on all three static refs; hard-refresh shows changes.
6. `node --check` on cockpit.js + glance_state.js; focused pytest suite still green
   (`pytest tests/test_cockpit_controller.py tests/test_cockpit_wake.py -q`).

## Handoff / gate
Branch `b2/cockpit-revamp-colors-header-copy-1` in baker-master. Push, report on bus
topic `cockpit-revamp-colors-header-copy-1` with exact HEAD; lead routes codex gate
(`gates/cockpit-revamp-colors-header-copy-1`). Lead merges on PASS + re-syncs
`~/Library/Application Support/baker/cockpit/` + kickstarts controller. Do not merge.

## Verification SQL
N/A — no DB surface.
