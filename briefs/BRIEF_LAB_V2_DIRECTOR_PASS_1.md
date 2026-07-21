# BRIEF: LAB_V2_DIRECTOR_PASS_1 — Director walkthrough fixes on Brisen Lab /v2 shell, skills, loops

## Context
Director eyeballed https://brisen-lab.onrender.com/v2 on 2026-07-21 and gave 9 rulings.
The 4 Lab-side ones are this brief (items 3, 7, 8, 9 of his list). The 5 cockpit-grid
ones + new refresh button are a SEPARATE brief (COCKPIT_AGENTS_VIEW_DIRECTOR_PASS_1,
baker-master repo) — do not touch `scripts/cockpit_static/` or the cockpit controller.

Repo: brisen-lab @a55a6c5 (origin/main). All refs verified against that commit.
- Shell grid: `static/v2/shell.css:61` → `.shell { grid-template-columns: 220px 176px 1fr; }` (nav sidebar 220px, subpanel 176px, content). Responsive variant at `shell.css:303` (≤720px → 148px).
- Subpanel SOON tags: `shell.css:157-168`, `shell.js:232-235` — presentation-only filter groups tagged "SOON".
- Skills render: `static/v2/skills.js:115-161` — VERTICAL nested tree (`.category` blocks → collapsible `.group` `<details>` → skill rows). Data: `static/v2/skills-data.json` — 8 categories / 25 groups / 135 skills, each category `{name, color, desc, groups:[{name, slugs[]}]}` (mapping @5a1b9e3).
- Loops: `static/v2/loops.html:115-189` renders BOTH loop cards simultaneously; `loops.js:84-106` per-card facet buttons (Description/Diagram/Agents/Prompt/Output); hash `#loop=<slug>&facet=<f>` via `writeLoopHash` (`loops.js:75-82`) + `applyFromHash` (`loops.js:121-130`). Clicking a loop name in the shell subpanel does NOT swap the content pane — both cards always visible.
- Shell nav: `shell.js:296-351` hash routing; tests `tests/test_v2_hashnav.js` (9 node tests), `tests/test_v2_nav_skeleton.py` (35 structural locks incl. cache-bust asserts at lines 129-134).
- Cache-bust: shell.css `?v=4` (index.html:11), shell.js `?v=7` (index.html:137), skills.js `?v=4` (skills.html:124), loops.js `?v=3` (loops.html:192).

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director navigates the /v2 shell — narrower nav sidebar, no dead "SOON" middle column, clicks a category in a horizontal skills bar to filter skills, clicks Research Loop / Airport Loop in the subpanel to open that loop's own view.
2. **Backend route:** none new — /v2 is a static SPA; pages mount via existing lazy routes (verified by `tests/test_v2_shell_route.py`, `test_v2_loops_route.py`, `test_v2_skills_route.py`). All changes are static HTML/CSS/JS + hash routing.
3. **Endpoint contract:** N/A — no new fetches; skills bar filters client-side from already-loaded `skills-data.json`; loops selection is hash-driven (`#loop=<slug>`), consumed by `loops.js`.
4. **State location:** static files in brisen-lab `static/v2/` (skills-data.json is the skills state; loop content is server-rendered into loops.html).
5. **UI repo (= state repo):** brisen-lab — surface: /v2 shell (Director-facing Lab).
6. **Director surface preference:** ratified 2026-07-21 — Director gave these rulings on this exact surface during his walkthrough.
7. **Gate-1+2 reviewer instruction:** "Reviewers MUST load the URL with exact query string + confirm non-error response. Code-shape review is necessary but not sufficient." (Concretely: load `/v2`, `/v2#skills`, `/v2#loops`, `/v2#loop=research-loop` on the deployed preview or local uvicorn and click through all four behaviors.)

## Estimated time: ~4-5h (B3 + B4 are real UI work)
## Complexity: Medium-High
## Prerequisites: none — main @a55a6c5 or later

## Harness V2
- **Context Contract:** builder needs ONLY: this brief, `static/v2/{shell.css,shell.js,skills.html,skills.js,skills-data.json,loops.html,loops.js,index.html}`, `tests/test_v2_hashnav.js`, `tests/test_v2_nav_skeleton.py`, ratified layout `briefs/_plans/BRISEN_LAB_UNIFICATION_RATIFIED_LAYOUT_2026-07-20.md` (baker-master repo, reference only). No bus reads, no DB, no cockpit files.
- **Task class:** production frontend (brisen-lab; Render auto-deploys from main after lead merge).
- **Done rubric / done-state class:** DONE = B1-B4 implemented, `node tests/test_v2_hashnav.js` + full pytest green, codex gate PASS, branch pushed + completion report with per-item live-check notes; NOT done at compile-clean (Lesson #8). Done-state: PR-ready (lead merges → Render deploy → Director eyeball on /v2).
- **Gate plan:** independent codex gate (bus seat `codex`) on the branch before merge; reviewer instructions block below is binding on the gate.

## Baker Agent Vault Rails
Relevant: build-command-center (Lab unification ratified layout `briefs/_plans/BRISEN_LAB_UNIFICATION_RATIFIED_LAYOUT_2026-07-20.md`), verification-surfaces.
Ignore: bus-and-lanes, loop-runner (no bus/daemon changes — "Loops" here is the UI page only).

---

## Fix B1 (Director item 7): Narrow the left nav sidebar

### Problem
Director: nav sidebar (AGENTS/LOOPS/SKILLS/…) "too wide, could be narrowed down, not to take much space."

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A.
- TDD/verification: applies — update the structural lock in `tests/test_v2_nav_skeleton.py` that pins the grid template (if present) to the new value.

### Implementation
`shell.css:61`: change first grid column `220px` → `168px`. Check the six labels
(SETTINGS & LOGS is longest) still fit on one line at default font — if not, use
`176px` (floor: no label wraps). Keep the ≤720px variant at `shell.css:303` as-is
(148px already narrower).

---

## Fix B2 (Director item 3): Kill the dead middle "SOON" column

### Problem
Director sees three columns; "the middle one, which says Soon" must go.

### Current State
Middle 176px subpanel (`shell.css:61`) renders per-section filter groups; sections
with no live content show only SOON-tagged placeholders (`shell.js:232-235`).

### Design ruling (AH1, surfaces conflict with item 9)
Do NOT delete the subpanel wholesale — item 9 (loops sub-views) NEEDS it as the
loop selector. Instead: the subpanel COLLAPSES (grid column → 0, `display:none`)
whenever the active section has no LIVE (non-SOON) entries. Effect Director sees:
AGENTS/SKILLS/etc. become two-column (no "Soon" strip); LOOPS keeps its selector
(Research Loop / Airport Loops are live entries). Remove SOON placeholder entries
from render entirely — collapsed or not, "Soon" text never renders.

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A — behavior fully specified above.
- TDD/verification: applies — node/pytest lock: sections with only-SOON groups render collapsed subpanel (grid class toggles), no element containing "SOON" in DOM.

### Implementation
1. `shell.js`: compute `hasLiveSubItems` per section; toggle a `.shell--nosub` class on the shell root; drop SOON-tagged groups from the render path (`shell.js:232-235` area).
2. `shell.css`: `.shell--nosub { grid-template-columns: <nav>px 1fr; }` (mind the 720px media variant).
3. Delete the SOON tag styles (`shell.css:157-168`) once nothing renders them.

---

## Fix B3 (Director item 8): Skills — horizontal category bar

### Problem
Director: "if I click on Skills … it's not a horizontal bar there. We discussed we
have to have a horizontal bar. With parameters."

### Current State
Vertical nested tree (`skills.js:115-161`). Data already carries everything needed:
8 categories with `name`, `color`, `desc`, 25 groups, 135 slugs (`skills-data.json`).

### Design (AH1)
Horizontal category bar pinned at the top of the skills pane: 8 pills, one per
category, in `skills-data.json` order. Each pill: category color chip + name +
parameters line (counts: `N groups · M skills`). Click = filter the tree below to
that category (toggle; active pill highlighted; second click clears back to all).
Selection persists in hash (`#skills&cat=<slug>`) so reload restores it. The
existing nested tree below stays — the bar filters it, does not replace it.

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A — pattern locked above; counts derive from existing JSON.
- TDD/verification: applies — node test on the pure filter/hash functions (follow `test_v2_hashnav.js` pattern); pytest structural lock: skills.html contains `.category-bar` with 8 children.

### Implementation
1. `skills.js`: build `.category-bar` before the tree render (data from `data.categories`; counts computed, never hardcoded); filter function + hash read/write.
2. `skills.html`: styles — `display:flex; gap; overflow-x:auto` (bar must not wrap on narrow widths; horizontal scroll OK); active state uses the category `color`.
3. Cache-bust: skills.js `?v=4`→`?v=5` in skills.html:124; update `test_v2_nav_skeleton.py` cache-bust asserts.

---

## Fix B4 (Director item 9): Loops sub-items must open their own view

### Problem
Director: clicking Research Loop / Airport Loops in the subpanel changes nothing —
both cards stay visible. "Not logical."

### Current State
Both loop cards always render (`loops.html:115-189`); subpanel clicks don't reach
the loops iframe content; facets are per-card (`loops.js:84-130`).

### Design (AH1)
Subpanel entry click routes `#loop=<slug>` through the shell (`shell.js:296-351`
hash routing) into the loops page; `loops.js` then shows ONLY the selected card
(other card `display:none`), with a small "← All loops" control (or re-click of the
active subpanel entry) restoring the both-cards view. Facet behavior inside a card
unchanged. Subpanel highlights the active loop.

### Engineering Craft Gates
- Diagnose: N/A — root cause already identified (no shell→loops selection path).
- Prototype: N/A. TDD/verification: applies — extend `test_v2_hashnav.js`: `#loop=research-loop` → visible set = [research card]; no hash → both visible; hash survives facet clicks (`writeLoopHash` interplay at `loops.js:75-82` — must not clobber the selected-loop state).

### Implementation
1. `shell.js`: subpanel LOOPS entries write `#loop=<slug>` (live entries per B2).
2. `loops.js`: `applyFromHash` (`loops.js:121-130`) additionally toggles card visibility from the `loop=` param; absent param = show all.
3. Cache-bust: loops.js `?v=3`→`?v=4` (loops.html:192), shell.js `?v=7`→`?v=8` (index.html:137); update cache-bust asserts.

---

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST load the URL referenced in the acceptance criteria (or `curl` it with
the exact query string the frontend will send) and confirm a non-error response.
Code-shape review is necessary but NOT sufficient. For this brief: run the app
locally (or deployed preview), load `/v2`, `/v2#skills`, `/v2#loops`,
`/v2#loop=research-loop`; confirm (a) no "Soon" text anywhere, (b) two-column
layout on AGENTS, three-column on LOOPS, (c) 8-pill bar filters skills, (d) loop
selection isolates one card and back. Run `node tests/test_v2_hashnav.js` +
`pytest tests/test_v2_nav_skeleton.py`.

## Files Modified
- `static/v2/shell.css` — nav width, `--nosub` collapse, SOON style removal
- `static/v2/shell.js` — SOON drop, subpanel collapse, loops entry routing (bump ?v)
- `static/v2/skills.js` + `skills.html` — category bar (bump ?v)
- `static/v2/loops.js` + `loops.html` — card isolation (bump ?v)
- `static/v2/index.html` — cache-bust bumps
- `tests/test_v2_hashnav.js`, `tests/test_v2_nav_skeleton.py` — updated + new locks

## Do NOT Touch
- `skills-data.json` — generated from vault mapping @5a1b9e3; counts must be COMPUTED from it, never edited into it
- `static/app.js` / legacy v1 page — /v2 only
- Server routes / `tests/test_v2_*_route.py` mount probes — no route changes
- baker-master repo — separate brief

## Quality Checkpoints
1. `node tests/test_v2_hashnav.js` and full pytest suite green.
2. No "SOON"/"Soon" string renders anywhere in /v2.
3. All six nav labels un-wrapped at the new sidebar width.
4. Deep-links `/v2#loop=research-loop` and `/v2#skills&cat=<slug>` restore state on cold load.
5. Cache-bust params bumped on every changed JS/CSS asset (iOS PWA).

## Verification SQL
N/A — static frontend only. Live verification = Director eyeball at https://brisen-lab.onrender.com/v2 after deploy.
