# BRIEF: COCKPIT_REVAMP_SPLIT_VIEW_SIDEBAR_1 — true split view + left sidebar navigation

## Context
Spec items **4 (true split view)** and **5 (left sidebar navigation)** of the
Director-ratified cockpit revamp (`briefs/_plans/COCKPIT_REVAMP_SPEC_20260719.md`
@d5e25efa). They interlock structurally (one layout restructure), so one brief.
Second brief of the b2 lane — start AFTER COCKPIT_REVAMP_COLORS_HEADER_COPY_1 is
merged (same files; serial avoids conflicts).

## Estimated time: ~5-7h
## Complexity: High
## Prerequisites: COCKPIT_REVAMP_COLORS_HEADER_COPY_1 merged to main.

## Baker Agent Vault Rails
Relevant: build-command-center, verification-surfaces.
Ignore: bus-and-lanes, memory-and-lessons, loop-runner.

## Harness V2
- **Context Contract:** inputs = this brief + spec items 4/5 + the three static files
  + `cockpit_layout.json` (read-only); no controller code loads beyond reading
  `/api/agents` shape from the sibling brief; no vault/Lab reads.
- **Task class:** production implementation — frontend layout restructure, local
  surface, no DB, no external API. Highest-risk item of the revamp (replaces the
  modal interaction model).
- **Done rubric / done-state class:** done = branch pushed + Verification items 1-7
  literally exercised (screen-recording or screenshots for 1-2 and 5) + Lab-bridge
  check (item 6) + report with exact HEAD. Done-state class: gate-verified merge;
  prototype probe deleted; no `#veil` dead code.
- **Gate plan:** codex gate on `gates/cockpit-revamp-split-view-sidebar-1`; lead
  merges on PASS + App Support re-sync + controller kickstart + post-deploy AC
  (split view + one live terminal via bridge).

## UI-surface prebrief (6 checks)
Same surface as sibling brief: local cockpit http://127.0.0.1:7800/ from
`scripts/cockpit_static/`. Ratified in live walkthrough on this exact surface.
Terminal panes are same-origin iframes (`/term/<slug>/`) — no cross-origin issues in
the split pane. Remote Lab bridge proxies the same static dir + terminal routes;
verify the split view once through the bridge before reporting done.

---

## Feature 1: True split view (spec item 4 — replaces modal + blur)

### Problem
Opening a terminal today = full-screen modal (`#veil` blur + `#term` overlay). Grid
becomes unusable; Director wants to keep watching the fleet while driving one seat.

### Current State
- `openTerm(slug, name)` cockpit.js lines ~222-249: adds `open` class to `#veil` +
  `#term`, injects same-origin iframe `#termframe`, Esc handled via capture-phase
  listener inside the iframe.
- DOM: `#veil`, `#term`, `#termbar`, `#term-title`, `#termframe`, `#termUnacked`
  (index.html ~90 lines).
- Grid: plate/card layout from `cockpit_layout.json` (43 cards, 6 plates).

### Engineering Craft Gates
- Diagnose: N/A — feature, not a bug.
- Prototype: applies — flex/grid geometry with a live iframe pane has real unknowns
  (iframe resize behavior, focus stealing, ttyd reflow). Before wiring everything,
  make a throwaway static probe: grid + iframe side-by-side, confirm ttyd reflows on
  container resize and that clicks outside the iframe do NOT steal terminal focus.
  Absorb findings into the real layout; delete the probe file before PR.
- TDD/verification: N/A honest unit seam for layout; verification = live checklist
  below + existing pytest suite must stay green.

### Implementation
1. Three-column app shell: **left sidebar | middle live grid | right terminal pane**.
   CSS grid on `<body>`/app container; terminal pane hidden (width 0) when no seat open.
2. Open behavior: clicking a driveable card opens the seat in the right pane. Grid
   stays LIVE, UNBLURRED, CLICKABLE. Kill `#veil` blur path entirely.
3. Clicking another card while a pane is open SWITCHES the right pane to that seat
   (tear down old iframe, inject new — reuse current `openTerm` internals).
4. Esc / X closes the pane (keep the iframe capture-phase Esc pattern; X in pane bar).
5. Keystroke discipline: keys reach the terminal ONLY when cursor/focus is in the
   pane. No global key capture; do not autofocus the iframe on grid clicks other than
   the opening click.
6. Keep the pane bar (`#termbar`): title + unacked list + Copy button (from sibling
   brief) + X.
7. Grid reflow: when the pane opens, grid compresses into the middle column (cards
   wrap; plate grouping preserved). Ttyd iframe must reflow on pane resize (probe
   finding from Prototype gate).

## Feature 2: Left sidebar navigation (spec item 5 — supersedes top-tab ruling)

### Problem
43 cards always render in one flat view; Director wants an ACTIVE-first view with
group navigation.

### Current State
- No view switching exists; only localStorage key is `cockpit.notifyMuted`.
- Plate labels in `cockpit_layout.json`:
  "Control Tower & VERIFICATION" / "ENGINEERING , TECHNICAL & STAFF MANAGEMENT" /
  "PILOTS & PILOT TEAMS" / "FLIGHTS SUPPORT & DOMAIN SPECIFIC" /
  "LEGAL ,FINANCIAL , PR, MARKETING & COMMUNICATIONS" / "INTERNS".

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A — nav model fully specified.
- TDD/verification: applies — the view-filter function (cards × view → visible set +
  per-group grey counts + badge set) is a pure function; implement it as one and add
  unit vectors (mirror the `glance_state.js` vector pattern) before wiring DOM.

### Implementation
1. Sidebar entries, in order: **ACTIVE** (default home) · **ALL** · **Pilots** ·
   **Control Tower** · **Engineering** · **Support** · **Legal/Finance** · **Interns**.
   Map plate labels → plain words:
   - "PILOTS & PILOT TEAMS" → Pilots
   - "Control Tower & VERIFICATION" → Control Tower
   - "ENGINEERING , TECHNICAL & STAFF MANAGEMENT" → Engineering
   - "FLIGHTS SUPPORT & DOMAIN SPECIFIC" → Support
   - "LEGAL ,FINANCIAL , PR, MARKETING & COMMUNICATIONS" → Legal/Finance
   - "INTERNS" → Interns
   Mapping lives in ONE const in cockpit.js keyed on plate label (fail-soft: unknown
   plate → its raw label).
2. **ACTIVE view** = all non-grey seats (any `st-*` state except `st-idle`, per the
   palette from the sibling brief) + one collapsed count line per group for grey
   seats ("Engineering — 5 quiet", click to expand that group inline).
3. **Red alert badge** on a group entry when any of its seats is in an
   attention state (`st-unread`, `st-unread-old`, `st-go`, `st-offline`) while you're
   in another view. Quiet-when-healthy: badge only for attention, no green badges.
4. View choice persisted across sessions: localStorage key `cockpit.view`
   (hydrate on load, default ACTIVE).
5. Narrow screens: sidebar collapses to icons, expands on hover (CSS media query +
   hover expansion; no JS breakpoint logic unless necessary).
6. Sidebar is RESERVED for future buttons — add NOTHING else now (parked candidates:
   bus health, brief queue, kill switches, Lab link — do not build).

### Key Constraints
- Terminal pane + sidebar + grid must coexist: sidebar stays visible when a pane is
  open (three columns).
- Do not change `/api/agents` polling cadence or controller code.
- Do not restyle cards beyond what layout compression requires — palette is the
  sibling brief's territory.
- Cache-bust: bump `?v=N` on all changed static refs (Lesson #4).

### Verification
1. Split view: open seat → grid live + clickable; click second card → pane switches;
   Esc and X close; typing in grid does NOT reach terminal; typing in pane does.
2. Ttyd reflows on pane open/close/resize (no frozen or mis-sized terminal).
3. ACTIVE view: exactly non-grey seats + grey count lines; expand works.
4. Badges: put an unacked message on a Pilots seat while in Engineering view → red
   badge on Pilots entry; ack it (or open it) → badge clears.
5. View persists across reload; narrow window → icon sidebar, hover expands.
6. Verify once through the Lab bridge (/cockpit/ remote path) — split view + one
   terminal session.
7. `node --check` cockpit.js; pytest cockpit suites green; unit vectors for the
   view-filter function pass.

## Files Modified
- `scripts/cockpit_static/index.html` — three-column shell, sidebar, pane markup, `?v=N` bumps
- `scripts/cockpit_static/cockpit.js` — split-view open/switch/close, view filter, badges, persistence
- `scripts/cockpit_static/cockpit.css` — columns, sidebar, collapse behavior, pane sizing
- (only if a vector harness is added) small test file colocated with existing test pattern

## Do NOT Touch
- `scripts/cockpit_controller.py` — zero controller changes.
- `scripts/generate_cockpit_layout.py` / `cockpit_layout.json` — read-only input;
  group mapping happens client-side.
- `brisen-lab/*` — untouched this round.

## Quality Checkpoints
1. All verification items above pass locally AND once via the Lab bridge.
2. No `#veil` blur remnants; modal path fully removed, no dead code left.
3. Sidebar contains exactly the 8 specified entries, nothing else.
4. localStorage keys: only `cockpit.view` added.
5. Prototype probe file deleted before PR.

## Handoff / gate
Branch `b2/cockpit-revamp-split-view-sidebar-1`. Report exact HEAD on bus topic
`cockpit-revamp-split-view-sidebar-1`; lead routes codex gate. Lead merges on PASS +
re-syncs App Support + kickstarts controller. Do not merge.

## Verification SQL
N/A — no DB surface.
