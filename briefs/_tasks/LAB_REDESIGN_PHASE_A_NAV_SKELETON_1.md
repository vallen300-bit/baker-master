# BRIEF: LAB_REDESIGN_PHASE_A_NAV_SKELETON_1 — second panels + facet routing + direct-open boards

```yaml
brief_id: LAB_REDESIGN_PHASE_A_NAV_SKELETON_1
dispatched_by: lead
assigned_to: b2
repo: brisen-lab (worktree ~/bm-b2/brisen-lab; branch b2/lab-redesign-phase-a-1 from origin/main)
status: PENDING
```

## Context

Director ratified the V2 redesign via Triaga 2026-07-21. Canonical record:
`briefs/_plans/BRISEN_LAB_V2_REDESIGN_PROPOSAL_2026-07-21.html` (green DIRECTOR
RULINGS callout at top = the binding amendments; note TODAY is DROPPED — 6-entry
sidebar stands). Phase A per §6 of that document: **navigation skeleton —
second panels + facet-button routing in the shell; everything else hangs off
this.** Phases B-E follow in separate briefs.

You built the /v2 shell (LAB_UNIFY_P1_SHELL_1), theme toggle, and the switch —
this extends YOUR structure.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director navigates — clicks a sidebar section, then a group
   in a NEW second panel, then facet buttons on an entity; clicking BAKER
   DASHBOARD / ARRIVALS BOARD opens the board embedded in-pane directly.
   Navigation only — no state mutation ("looking never acts", ruling 1.3;
   wake-on-open already removed @72abd358).
2. **Backend routes:** all existing, verified on origin/main @a1cfb22:
   `GET /v2` app.py:850 · `GET /v2/settings-logs` app.py:2195 · `GET /v2/skills`
   app.py:2204 · `GET /v2/loops` app.py:2213. NO new/changed server routes —
   this brief is static-asset-only.
3. **Endpoint contract:** handlers serve static HTML, no params read
   server-side. All new routing is CLIENT-SIDE hash params (`#cat=…`,
   `#loop=…&facet=…`, `#tab=…`, `#group=…`) — hash never reaches the server,
   so the contract cannot drift. External embeds:
   `https://baker-master.onrender.com/` + `/arrivals` — verified 2026-07-21
   (lead, live `curl -sI`): NO `X-Frame-Options`, NO CSP `frame-ancestors` →
   iframe-able. `/arrivals` auth gate disguises as 404 and renders inside the
   frame (Lesson #122 pattern, same as /cockpit/).
4. **State location:** view state = client-side only. Skills data =
   `static/v2/skills-data.json` (brisen-lab). Loops content =
   `static/v2/loops.html` fields (brisen-lab). Boards = external baker-master
   surfaces (embedded, not owned).
5. **UI repo (= state repo):** brisen-lab, `/v2` shell + sub-pages.
6. **Director surface preference:** ratified via Triaga 2026-07-21 — second
   panels + facet buttons per his workbook; DIRECT-OPEN embed for the two
   boards (his explicit ruling, replacing the link panes he saw).
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `/v2` + each hash
   route (`/v2/skills#cat=business`, `/v2/loops#loop=research-loop&facet=prompt`)
   and confirm non-error render + correct pane state. Code-shape review is
   necessary but NOT sufficient.

## Estimated time: ~4-6h
## Complexity: Medium-High
## Prerequisites: none (theme + switch already live)

## Harness V2

- **Context Contract:** this brief (whole); the RULINGS callout in
  `briefs/_plans/BRISEN_LAB_V2_REDESIGN_PROPOSAL_2026-07-21.html`;
  `static/v2/index.html` + `shell.js` + `shell.css` (your shell);
  `static/v2/skills.js` (category render/filter internals),
  `static/v2/loops.html`/`loops.js` (field structure),
  `static/v2/settings-logs.*` (tab structure); existing v2 tests in `tests/`.
  Nothing else.
- **Task class:** medium-feature (brisen-lab, production).
- **Done rubric:** terminal = Merged + Deployed + post-deploy AC + Director
  click-through. Post-deploy AC (lead): every second-panel button routes; hash
  deep-links land correctly; both boards render embedded; fallback panes fire
  on forced error. Writeback: ship report on bus.
- **Gate plan:** b2 self-test → push branch → blocking codex gate on pushed
  SHA → lead merge → Render auto-deploy → live AC → Director click-through.

---

## Feature 1: shell second panel (per-section groups)

### Problem
The workbook design has a second left panel per section (like agents-groups);
the shipped shell flattened it — sidebar goes straight to a full-bleed pane.

### Current State
`static/v2/index.html:20-34` — single sidebar, `data-view` buttons;
`shell.js:177-204` — `activate()` toggles `.view` panes and lazy-mounts iframes.

### Engineering Craft Gates
- Diagnose: N/A — feature, nothing broken.
- Prototype: N/A — pattern fixed by Director's workbook + existing cockpit
  sidebar idiom; no open design question Phase A must answer.
- TDD/verification: applies — extend the existing v2 static tests: panel
  renders expected group buttons per section; hash writes on click; iframe
  hash-forwarding string built correctly (pure-function seam — build it as
  `buildFrameHash(view, params)` so tests hit it without a DOM).

### Implementation (contract — you own the detail)
1. New `.subpanel` column between sidebar and content (shell.css; collapses on
   the existing narrow-viewport behavior — do not worsen mobile, polish is
   Phase E). Rendered from a static config object in shell.js:
   - `agents`: ACTIVE · ALL · Control Tower · Pilots · Engineering · Support ·
     Legal/Finance · Interns (slugs: `active`, `all`, `control-tower`,
     `pilots`, `engineering`, `support`, `legal-finance`, `interns`)
   - `loops`: Research Loop (`research-loop`) · Airport Loop (`airport-loop`)
   - `skills`: ALL (`all`) + the 8 categories ALREADY in
     `skills-data.json` `categories[].name` — derive slugs from that file at
     build time of the config; do NOT invent a parallel list that can drift.
   - `settings-logs`: Token (`token`) · Maintenance (`maintenance`) ·
     History (`history`)
   - `baker-dashboard`, `arrivals`: no subpanel (hidden).
2. Click → update shell `location.hash` (`#view=skills&cat=business`) → set the
   ACTIVE section iframe's hash (`frame.contentWindow.location.hash` on
   same-origin frames; for the cockpit frame set `frame.src` hash-only change —
   hash-only src changes MUST NOT reload the document; verify, and if any
   browser path reloads, fall back to contentWindow.location.hash there too).
   Cockpit currently ignores `#group=…` — that is FINE; the param contract is
   documented for the Phase C cockpit brief. Shell restores view+params from
   its own hash on load (deep-link).
3. AGENTS subpanel ships but is presentation-only until Phase C (buttons set
   the hash; cockpit filtering lands with the needs-word-circle brief). Mark
   the non-ACTIVE group buttons with a muted "soon" state — no dead-looking
   clicks (fail-loud, not fake).

### Key Constraints
- No innerHTML with dynamic strings (house rule — textContent / createElement).
- Theme tokens only — both palettes must hold (light ruling is fleet-wide).
- Existing plain-click behavior (no hash) keeps working — hash is additive.
- Cache-bust: bump `?v=` on shell.css + shell.js + every touched sub-page asset.

## Feature 2: sub-page hash consumption + loops facet row

### Problem
Sub-pages render everything at once; no way to land on a category, loop, tab,
or facet — the workbook's facet buttons don't exist.

### Current State
`skills.js` — categories render collapsed/expandable, search filter exists;
`loops.html` — per-loop fields (agents · prompt · output · description ·
diagram link) render stacked; `settings-logs.*` — tabs internal.

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A (same rationale as Feature 1).
- TDD/verification: applies — hash-parse helper (`parseLabHash(str)`) as a
  pure function with unit tests (empty/garbage/unknown-slug inputs must not
  throw and must fall back to default view).

### Implementation (contract)
1. Shared tiny helper (inline per page, or one `static/v2/hashnav.js` —
   your call): parse hash params, listen to `hashchange`.
2. `skills.js`: `#cat=<slug>` → filter to that category (reuse the existing
   search/filter machinery), auto-expand, scroll to top of it. `all` or absent
   → current behavior. Unknown slug → current behavior (never blank).
3. `loops.js`/`loops.html`: `#loop=<slug>` scrolls/activates that loop card.
   Facet-button row per loop card: **Diagram · Description · Agents Involved ·
   Prompt · Output** — each button shows that field's section and hides the
   others (Description = default). `#facet=<slug>` deep-links. Content =
   the fields ALREADY on the page; no new content authoring (Phase B fills
   gaps). Missing field (e.g. Airport diagram "to be created later") → button
   renders disabled with "later" note — never a blank pane.
4. `settings-logs`: `#tab=<slug>` activates that tab.

### Key Constraints
- Standalone-first (pages open directly, not just in the shell) — same habit
  as the theme bootstrap.
- Skills FACET layout (Full Description / Source / Location / Templates /
  Agents-with-skill / HTML links as buttons) is **Phase B — do NOT build it
  here**; only `#cat=` landing ships in Phase A.

## Feature 3: direct-open board embeds (Baker + Arrivals)

### Problem
Director ruled: sidebar click opens the board itself, embedded — not a pane
with a link button.

### Current State
`index.html:71-89` — both are `.link-pane` with external `<a target=_blank>`.

### Engineering Craft Gates
- Diagnose: N/A. TDD: applies — reuse/extend the existing lazy-mount test
  pattern (probe-fail → fallback pane, probe-ok → iframe present).
- Prototype: **applies** — one real uncertainty: browser third-party storage
  partitioning may break the boards' token/localStorage auth inside a
  cross-origin iframe. Answer it FIRST, cheaply: hand-edit a local copy of the
  shell (or devtools-inject an iframe on the live /v2) pointing at both URLs,
  and check the gate/board renders in Chrome. Throwaway — nothing persisted.
  If auth genuinely cannot survive embedding, STOP, report on bus, and ship
  Feature 3 as fallback-to-link-pane only (fail-loud to lead; do not fake it).

### Implementation (contract)
1. Replace both link panes with the lazy fail-soft iframe pattern from
   shell.js (`mountSkills` idiom): mount on first activation. For the probe,
   a cross-origin `fetch` cannot read status — use `{mode: "no-cors"}` and
   treat only network-error/timeout as failure, OR skip the probe and mount
   directly with an iframe `onload`/timeout fallback — your call, document it.
2. Slim header strip above each embed: board name + "Open ↗" external link
   (same URL, target=_blank) — the escape hatch stays.
3. Failure → existing `.view-fallback` pattern with the link pane as fallback
   content (the current behavior, demoted to fallback).

### Key Constraints
- Do not proxy the boards through brisen-lab (no server changes, no auth
  forwarding — the boards' own gates handle access, Lesson #122).
- rel/referrerpolicy hygiene identical to existing embeds.

---

## Files Modified
- `static/v2/index.html` — subpanel markup, board panes, cache-busts
- `static/v2/shell.js` — subpanel config/render, hash routing, board mounts
- `static/v2/shell.css` — subpanel column
- `static/v2/skills.js` — `#cat=` consumption
- `static/v2/loops.html` / `loops.js` — facet row + `#loop=`/`#facet=`
- `static/v2/settings-logs.js` — `#tab=`
- `tests/` — extend existing v2 static tests + pure-helper units

## Do NOT Touch
- `app.py` — zero server changes in Phase A
- `static/v2/skills-data.json` — read-only source of category truth
- Old-Lab `static/app.js` / retired routes — out of scope
- Theme bootstrap blocks — working, fleet-ratified

## Quality Checkpoints
1. Every subpanel button routes; deep-link hashes restore full state on load.
2. Both boards render embedded (Director-authenticated click-through) OR
   fail-soft to link pane — never blank.
3. Light + dark themes hold on every new element.
4. Standalone sub-page opens still work.
5. All existing v2 tests green; cache-busts bumped on every touched asset.
6. Unknown/garbage hash never throws, never blanks a pane.
