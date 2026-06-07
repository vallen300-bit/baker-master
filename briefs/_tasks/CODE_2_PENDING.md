# B2 dispatch — BRISEN_LAB_CARD_REDESIGN_1

status: PENDING
dispatched_by: cowork-ah1
repo: brisen-lab (work in `~/bm-b2-brisen-lab`, fresh off `origin/main`)
gates: G2 /security-review + G3 codex → PR to lead (lead gates the merge in the brisen-lab lane)

## Problem
The Brisen Lab dashboard cards + board layout were redesigned and Director-ratified 2026-06-07. This is a **front-end-only** restyle + restructure. No behaviour changes.

## Canonical reference (build to match this)
`briefs/_assets/brisen-lab-card-redesign-locked.html` (in this baker-master clone — open it in a browser; it is the locked mockup). Full written spec also in cowork-ah1 memory `project_brisen_lab_card_layout_locked_design_2026_06_07.md`.

## Where the code lives (brisen-lab)
- `static/app.js` — card DOM builder (~L360–400: `state-dot` + `card-title` + `card-history-link`), the category/group map (L31–32) + category loop (L213: supervisor/worker/system/matter-desk/shared-specialist), and `terminalLabel(alias)` for display names.
- `static/styles.css` — card + layout CSS.
- `static/glance_state.js` — the working/amber/glance STATE engine. **DO NOT TOUCH** (diff must show zero changes).
- `static/index.html` — page shell.
- Registry source: baker-vault `_ops/registries/agent_registry.yml` (AG-### + display-name + group) and baker-master resolver `orchestrator/agent_identity_registry.py` (both on main). brisen-lab does NOT consume the registry today — wiring that read is part of this task (pick the cleanest path: an `app.py` endpoint that serves the resolved registry to the client, or a build/import read — propose in the PR; do NOT hardcode names/groups).

## Solution (high level)
Restyle the existing card builder to the new component, restructure the fleet render into a 3×2 titled column grid driven by registry group membership, recolour matter panels, add the bevel CSS + responsive collapse. Behaviour paths (state, wake, SSE, history) are read-only context — touched for styling hooks only, never logic.

## Files to modify
- `static/app.js` — card builder markup (pill + name + `···`), group→column mapping, `terminalLabel` source = registry.
- `static/styles.css` — `.card` bevel, 3×2 `.columns` grid, matter panel colours, responsive `@media`.
- `static/index.html` — only if a container/cache-bust bump is needed.
- `app.py` — only if adding the registry-serve endpoint.

## Files NOT to touch
- `static/glance_state.js` — the state/amber engine.
- Any wake/auto-wake, SSE, `data-card-state` / `data-alias` write paths, history-panel logic.

## Scope — what to change (presentation only)
1. **Card component** → match the mockup: `state-dot` (KEEP) · **blue AG-### pill** · **bold display name** · **`···`** (replaces the `[history]` text; SAME click → SAME history behaviour). Slug → hover `title` tooltip only.
2. **Option C bevel** (exact CSS in the mockup `.card` rule): bg `linear-gradient(180deg,#28323f,#141922)`; border `1px #36414f`; `box-shadow: inset 0 1.5px 0 rgba(255,255,255,.14), inset 0 -3px 4px rgba(0,0,0,.5), 0 5px 12px rgba(0,0,0,.6)`; hover `translateY(-1px)`, active `translateY(1px)`.
3. **Layout = 3×2 titled column grid**:
   - Row 1: **Orchestrators** (Lead, Cowork AH1, Deputy, Codex Deputy) · **Builders** (B1–B4) · **Special Agents** (Codex RT, Codex ARCH, Clerk Haiku, Clerk QWEN).
   - Row 2: **Research & Advisors** (Researcher, AID T) · **ClaimsMax Workers** (CM-1…CM-4) · **Core Engine** (Cortex).
   - Map registry group membership → these 6 columns; do NOT hardcode the lists.
4. **Matter desks** stay COLOURED like live (Hagenauer amber, Origination red); cards inside use the bevel card.
5. **Fixed widths:** 248px fleet / 264px matter. **Collapse:** `@media(max-width:1030px){.columns{flex-wrap:wrap}}`.

## Guardrails (verbatim from lead — hold these lines)
1. **CONSUME the registry** for AG-###, display-names, group membership — do NOT hardcode.
2. **HARD NO-TOUCH (Director):** wake/auto-wake, card light-up, amber "working" state, state-dot colour logic, `glance_state.js`, SSE, `data-card-state`/`data-alias`, history-link *behaviour*.
3. **Clerk names match the registry exactly:** AG-204 Clerk `[clerk]` = Qwen3 primary; AG-205 Clerk Chat `[clerk-haiku]` = Haiku fallback. Use the registry's canonical display strings.
4. **Scope = card markup/CSS + the 3×2 titled grid + responsive collapse. Nothing behavioural.**

## Key constraints
- Keep the no-innerHTML posture — build card DOM via `createElement` (XSS-safe); `···` is text, not markup.
- Bump the static cache-bust (`?v=N`) on `app.js` / `styles.css` in `index.html` so the new look shows on reload.
- If adding a registry-serve endpoint, `grep -n` the path first (no FastAPI route shadow), wrap DB/file reads in try/except, return a bounded payload.

## Verification / acceptance criteria
- Live board visually matches `brisen-lab-card-redesign-locked.html` (cards, bevel, blue pills, `···`, 3×2 grid, coloured matters) at desktop width.
- AG-###, names, group membership READ from the registry — prove it: change a display-name in the registry source → label changes with no `app.js` edit.
- `···` opens the same history panel the old `[history]` link did (handler at `app.js` L1039 still fires).
- State-dot still goes working/amber/pending/done — exercise a live working state; it must still light up. `git diff static/glance_state.js` = empty.
- `git diff` touches only `static/app.js` + `static/styles.css` (+ `index.html` cache-bust, + `app.py` if registry endpoint). No behavioural path changed.
- Responsive: below 1030px → columns wrap, no overflow, no clipping.
- `node --check static/app.js`; `python3 -c "import py_compile; py_compile.compile('app.py', doraise=True)"` if `app.py` touched; tests green.

## Surface contract
- **Surface:** Brisen Lab dashboard (`brisen-lab.onrender.com`) — Production & Lab board (FLEET + MATTER DESKS).
- **Reader:** Director (primary), AH1/AH2 operators.
- **Components touched:** agent card, fleet group layout, matter-desk panels, card CSS. NOT touched: glance/working-state engine, wake, SSE, history-panel logic.
- **States:** resting / hover / active on cards; existing dot states (quiet/working/pending/done) preserved unchanged.
- **Responsive:** desktop fixed 3×2; `<1030px` wrap 3→2→1.
- **Brand:** dark board; blue AG pill (#388bfd) sole fleet accent; matter panels amber/red.

## Gates + delivery
1. Build in `~/bm-b2-brisen-lab` off fresh `origin/main`.
2. G2 `/security-review` + G3 `codex` (bus `codex`).
3. Open PR; bus-post `cowork-ah1` (dispatched_by) AND `lead` with the PR number — **lead gates the merge**.
4. Post-merge: live AC on `brisen-lab.onrender.com` per criteria above.
