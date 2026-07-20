# BRIEF: LAB_UNIFY_P3_LOOPS_1 — LOOPS first-class pages (Research Loop · Airport Loop)

```yaml
brief_id: LAB_UNIFY_P3_LOOPS_1
dispatched_by: lead
assigned_to: b1
repo: brisen-lab (worktree ~/bm-b1/brisen-lab; branch b1/lab-unify-p3-loops-1 from origin/main)
status: PENDING
```

## Context

Director-ratified Lab unification, Phase 3, brief 1 (loop page frame — the
"1-2 briefs" of build plan §Phase 3; the optional diagram brief comes later).
Source: `bm-aihead1/briefs/_plans/BRISEN_LAB_UNIFICATION_BUILD_PLAN_2026-07-20.md`
+ ratified layout sidebar entry 2: "LOOPS — named loops as first-class
entities. Initial two: Research Loop (today 'Villa Gabbiano') and Airport
Loop (today 'Aukera financing'). Each: interactive diagram + loop description
on the same page (agents involved, prompt, output). Airport diagram 'to be
created later' per Director note."

Phases 1+2 are LIVE (`/v2` shell @d69e2f6, `/v2/settings-logs` @81346e1,
`/v2/skills` @2cf7605). This brief replaces the LOOPS "arriving Phase 3"
placeholder — the LAST placeholder in the shell. The two existing loop
command boards already carry rich system maps + loop descriptions; this
brief ABSORBS them into the /v2 frame (lazy iframe, byte-untouched), adds a
first-class loop index with the ratified description fields, and marks the
Airport diagram as deferred per the Director's workbook note.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director opens LOOPS in the Lab sidebar, picks a named loop, reads its description (agents involved, prompt, output), and views its live command board.
2. **Backend route:** NEW `GET /v2/loops` in brisen-lab `app.py` — append-only FileResponse, exact pattern of the three verified live routes `app.py` `@app.get("/v2")` / `/v2/settings-logs` / `/v2/skills` (all confirmed live 200 anonymous 2026-07-21).
3. **Endpoint contract:** GET, no params, no auth. Embedded boards served by the EXISTING StaticFiles mount — both verified live 2026-07-21: `GET /static/loops/villa-gabbiano.html` 200, `GET /static/loops/lilienmatt-aukera-financing.html` 200. No new API endpoints, no cross-origin fetch.
4. **State location:** static HTML in brisen-lab (`static/loops/*.html`) — the boards ARE the state surface; read-only, zero writes.
5. **UI repo (= state repo):** brisen-lab, `static/v2/loops.*`.
6. **Director surface preference:** ratified 2026-07-20 — LOOPS is sidebar entry 2 of the unified Lab; Airport diagram explicitly deferred by Director workbook note.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `/v2/loops` in a browser, open both loop boards through it, and confirm both render identically to their direct `/static/loops/...` URLs (byte-untouched absorption). Code-shape review is necessary but NOT sufficient.

## Estimated time: ~2.5h
## Complexity: Low-Medium
## Prerequisites: none (Phases 1+2 live; no other brief in flight on static/v2/)

## Baker Agent Vault Rails
Relevant: build-command-center, verification-surfaces, bus-and-lanes.
Ignored: memory-and-lessons, loop-runner — read-only frame page, no DB.

## Harness V2

- **Context Contract:** read before building: this brief (whole), `static/v2/shell.js` + `static/v2/index.html` (current LOOPS placeholder + the settings-logs/skills lazy-iframe pattern — NOTE b2's Phase-2 shell edits are already on main, branch from origin/main AFTER @2cf7605), `static/v2/skills.html` (register reference for an index-style /v2 page), the two loop board files (content only — you will not edit them), one existing route test in `tests/`. Nothing else required.
- **Task class:** medium-feature (production, brisen-lab).
- **Done rubric / done-state class:** terminal = Merged + Deployed + post-deploy AC passed + writeback resolved. Post-deploy AC (lead): live `/v2/loops` shows both loop cards with description fields; both boards mount and match their direct URLs; shell LOOPS entry mounts the page; placeholder gone. Writeback: registry status HTML update by lead.
- **Gate plan:** b1 self-test (pytest + local uvicorn + browser) → push branch → blocking independent codex gate on pushed SHA (Surface contract §7 binding) → lead merge → Render auto-deploy → lead POST_DEPLOY_AC_VERDICT on bus.

---

## Feature 1: /v2/loops index + absorbed boards

### Problem
The two loop command boards live behind an old-Lab dropdown as raw static
links; loops are not first-class entities in the new shell, and the LOOPS
sidebar entry is still a placeholder.

### Current State
- `static/v2/index.html`: LOOPS placeholder pane (`view-loops`, "arriving Phase 3").
- `static/v2/shell.js`: two lazy fail-soft iframe mounts (settings-logs, skills) — the pattern to replicate a third time.
- Old nav: `static/index.html:24-27` "Loops" dropdown → the two static boards (stays untouched until Director "switch").
- Boards: `static/loops/villa-gabbiano.html` (687 lines, own agent system map + 6-step loop description) · `static/loops/lilienmatt-aukera-financing.html` (987 lines, airport-metaphor system map).

### Engineering Craft Gates
- Diagnose: N/A — new feature, no bug.
- Prototype: N/A — pattern is the third repetition of the proven lazy-iframe pane; loop descriptions supplied verbatim below.
- TDD/verification: applies — first test BEFORE page build: `GET /v2/loops` 200 `text/html` containing both loop names (FastAPI TestClient, existing pattern); plus assertions that both `static/loops/*.html` files exist and are byte-identical to git HEAD (guard against accidental edits).

### Implementation

1. **`app.py`** — append-only route (verify first: `grep -n "v2/loops" app.py` → must be absent):
```python
@app.get("/v2/loops")
def v2_loops():
    return FileResponse("static/v2/loops.html")
```

2. **`static/v2/loops.html` + `static/v2/loops.js?v=1`** — vanilla JS, cockpit register tokens. Layout:
   - Header: `LOOPS` + sub-line `Named loops as first-class entities · 2 loops`.
   - Two loop cards, each with these EXACT description fields (ratified columns: agents involved · prompt · output), copy verbatim:

     **Card 1 — Research Loop** (matter: Villa Il Gabbiano DD)
     - Agents involved: `AO Desk (starts round, lifts HOLD) · Researcher (Q1–Q11 evidence lanes) · Russo (Q12–Q13 specialist lane) · Research Loop Coordinator (ClickUp grid monitor) · Watchdog (48h chase) · Human gate (judgment calls only)`
     - Prompt: `Run the Villa DD research round: dispatch the loaded question lanes, monitor the ClickUp grid for stalls and missing owners, chase silence after 48 hours, escalate legal / tax / sanctions / valuation / investment conclusions to humans — no AI judgment.`
     - Output: `Evidence landed per question lane on the ClickUp grid + visible blockers and chase items on the command board.`
     - Board: lazy iframe → `/static/loops/villa-gabbiano.html`.

     **Card 2 — Airport Loop** (matter: Lilienmatt / Aukera financing)
     - Agents involved: `Director (starts loop) · Baker (captures signals) · ClickUp (holds status) · Orchestrator Desk (routes candidates) · matter desks (known matters) · human nudge (follow-up)`
     - Prompt: `Run airport check-in over arriving signals: match each signal to a loop manifest, issue boarding passes for known loops, send weak signals to the security belt for triage, park unclear items in the unsorted box, and hand desks an evidence + next-move package.`
     - Output: `Routed signal dispositions in ClickUp + desk packages (evidence + next move) + the live command board.`
     - Deferred-diagram note, verbatim: `Interactive diagram: to be created later (Director note, 2026-07-20 workbook). The command board below is the current system map.`
     - Board: lazy iframe → `/static/loops/lilienmatt-aukera-financing.html`.
   - Board iframes: lazy-mount on first expand (cards start with board collapsed, description visible), `loading="lazy"`, fail-soft: on iframe error show `Board unavailable.` — never a blank pane. A "open full board ↗" link (`target="_blank" rel="noopener"`) next to each board for full-window viewing.
   - XSS: all text is static copy from this brief — still use `textContent` for any JS-written strings as standing habit; no innerHTML with variables.
3. **Shell integration**: replace the LOOPS placeholder pane in `static/v2/index.html` with the same lazy fail-soft iframe pattern (`/v2/loops`; error → fallback pane); extend `static/v2/shell.js` (currently `?v=2` after Phase 2 — bump to `?v=3`; bump any other asset you touch).
4. Standalone-first: `/v2/loops` must render correctly opened directly; the shell merely iframes it.

### Key Constraints
- ZERO edits to `static/loops/*.html` (byte-untouched — absorption, not rewrite), old Lab pages, cockpit, controller, existing handlers, `static/v2/settings-logs.*`, `static/v2/skills.*`.
- Read-only page: no POST, no new API endpoints, no DB.
- Old-Lab "Loops" dropdown stays — it retires only at Director "switch".
- No new diagram work — the Airport diagram is explicitly deferred; do not improvise one.

### Verification
1. `pytest` — new route test green; suite no regressions.
2. Local uvicorn: `/v2/loops` renders both cards with all description fields; expanding a card mounts its board; boards render identical to direct URLs; "open full board" links work.
3. `/v2` shell: LOOPS entry mounts the page; placeholder gone; AGENTS/SKILLS/SETTINGS panes unaffected.
4. `git diff --stat` vs origin/main: only new files + one app.py route + index.html/shell.js LOOPS pane swap.

## Files Modified
- `app.py` (+4 lines, one route) · `static/v2/loops.html` · `static/v2/loops.js` (new) · `static/v2/index.html` + `static/v2/shell.js` (LOOPS pane swap, cache-bust bump) · `tests/test_v2_loops_route.py` (new)

## Do NOT Touch
- `static/loops/*.html` (the absorbed content — byte-identical or the AC fails).
- Old Lab static files, cockpit/, controller, all existing app.py handlers.
- `static/v2/settings-logs.*` (b1 item-2, live) · `static/v2/skills.*` (b2 item-3, live).
- baker-vault (nothing there is needed).

## Quality Checkpoints
1. Byte-identical guard test on both absorbed boards.
2. Every dynamic mount has fail-soft + visible degraded state.
3. Deferred-diagram note present verbatim (ratified Director note, not a TODO).
4. Ship report to lead on bus (`lab-unify/p3-loops`) with branch + HEAD SHA; codex gate routes on your pushed SHA.

## Verification SQL
N/A — static frame page; no DB access.
