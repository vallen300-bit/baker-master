# BRIEF: LAB_UNIFY_P1_SHELL_1 — /v2 unified-Lab shell: 6-entry sidebar + cockpit embed + link entries

```yaml
brief_id: LAB_UNIFY_P1_SHELL_1
dispatched_by: lead
assigned_to: b2
repo: brisen-lab (worktree ~/bm-b2-brisen-lab; branch b2/lab-unify-p1-shell-1 from origin/main)
status: PENDING
```

## Context

Director-ratified Lab unification (layout: `bm-aihead1/briefs/_plans/BRISEN_LAB_UNIFICATION_RATIFIED_LAYOUT_2026-07-20.md`;
build plan approved "go" 2026-07-20: `briefs/_plans/BRISEN_LAB_UNIFICATION_BUILD_PLAN_2026-07-20.md`;
plan-mode revision approved same evening). Phase 1, brief 1 of 2: the new
unified shell at side door `GET /v2`. Old Lab front page (`/`) stays the
default and is NOT modified. Cockpit revamp register (9/9 LIVE) is the style
reference. Brief 2 (`LAB_UNIFY_P1_SETTINGS_LOGS_1`, b1, parallel) owns
`static/v2/settings-logs.*` — see Inter-brief contract.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director opens one Lab address and navigates the whole fleet estate from a 6-entry sidebar (open cockpit, open Baker dashboard, open Arrivals, open Settings & Logs).
2. **Backend route:** NEW `GET /v2` in `app.py` → `FileResponse("static/v2/index.html")`. Pattern precedent: `GET /` at `app.py:783` (`def index(): return FileResponse("static/index.html")`). Verified no existing `/v2` page route (only `/api/v2/pool_stats` @2937 — no FastAPI shadow).
3. **Endpoint contract (embed):** `GET /cockpit/{path:path}` app.py:3063 (proxy via laptop bridge; flag `COCKPIT_EMBED_ENABLED`; token cookie `cockpit_token`; probe endpoint `GET /api/cockpit/config` app.py:3096). No X-Frame-Options/CSP frame-ancestors anywhere in app.py or cockpit_controller.py → same-origin iframe is viable; the token/auth page renders inside the iframe on first visit (correct behavior, do not bypass).
4. **State location:** none new — shell is static navigation; cockpit state stays behind the bridge.
5. **UI repo (= state repo):** brisen-lab, `static/v2/`.
6. **Director surface preference:** ratified 2026-07-20 (workbook + "go") — Lab web, 6-entry sidebar, ACTIVE landing.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `/v2` (local uvicorn) and click every sidebar entry, and `curl -s -o /dev/null -w "%{http_code}"` each target (`/v2`, `/cockpit/api/config` probe path, `/v2/settings-logs` — 404 acceptable for settings-logs until Brief 2 merges, shell must fail-soft). Code-shape review is necessary but NOT sufficient.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: none (Brief 2 merges independently; shell must fail-soft if its page 404s)

## Baker Agent Vault Rails
Relevant: build-command-center (gate chain), verification-surfaces (live AC), bus-and-lanes (ship report to lead).
Ignored: memory-and-lessons, loop-runner, skills-and-playbooks — no agent-behavior change.

## Harness V2

- **Context Contract:** read before building: this brief (whole), `app.py:780-790` (index route pattern), `static/index.html:22-40` (old nav, source of link URLs), `cockpit/static/cockpit.css` (style tokens), one existing route test in `tests/` (TestClient pattern). Nothing else required; do NOT load old `app.js`/`styles.css` beyond the nav lines.
- **Task class:** medium-feature (production, brisen-lab).
- **Done rubric / done-state class:** terminal state = Merged + Deployed + post-deploy AC passed + writeback resolved. Post-deploy AC (lead): open live `/v2`, click all 6 entries, cockpit iframe live, old `/` unchanged. Writeback: registry status HTML update by lead.
- **Gate plan:** b2 self-test (pytest + local uvicorn walkthrough) → push branch → blocking independent codex gate on pushed SHA (reviewer instruction in Surface contract §7 is binding) → lead merge to main → Render auto-deploy → lead POST_DEPLOY_AC_VERDICT on bus.

---

## Feature 1: /v2 shell

### Problem
Ratified 6-entry structure exists only on paper; today's Lab nav is the old
Control-Room/Production split plus scattered external links.

### Current State
- `GET /` → `static/index.html` (app.py:783); static mount `/static` (app.py:129).
- Old nav markup: `static/index.html:22-40` (Control Room, Production & Lab, Loops details-group, hidden Token Burn `http://127.0.0.1:3000`, Templates `https://brisen-docs.onrender.com/templates/`, Bus/Delivery Health, hidden `/cockpit/` link).
- Cockpit style tokens: `cockpit/static/cockpit.css` (dark register, st-* palette).

### Engineering Craft Gates
- Diagnose: N/A — new feature, no bug.
- Prototype: N/A — layout ratified in Director workbook; no open design question.
- TDD/verification: applies — first test: `GET /v2` returns 200 with `text/html` and the response body contains all six ratified sidebar labels (add to existing FastAPI TestClient suite, follow the pattern of existing route tests in `tests/`).

### Implementation
1. `app.py` — append near the `index()` route (keep append-only for merge safety with Brief 2):
```python
@app.get("/v2")
def v2_shell():
    return FileResponse("static/v2/index.html")
```
2. `static/v2/index.html` — shell: left sidebar (6 entries, ratified order + spelling):
   AGENTS · LOOPS · SKILLS · BAKER DASHBOARD · ARRIVALS BOARD · SETTINGS & LOGS.
   Content region fills the rest. Assets referenced as `/static/v2/shell.css?v=1`, `/static/v2/shell.js?v=1`.
3. `static/v2/shell.js` — view switch:
   - AGENTS (default/landing): `<iframe src="/cockpit/">` full-bleed. Before showing, probe `fetch('/api/cockpit/config', {signal: AbortSignal.timeout(4000)})`; on network error / timeout / non-2xx-and-non-401 show a slim banner above the iframe: `Cockpit offline — laptop controller unreachable` (keep iframe rendered; the gate/auth page inside it is legitimate).
   - LOOPS, SKILLS: placeholder panes — "LOOPS — arriving Phase 3" / "SKILLS — arriving Phase 2", cockpit-register styling.
   - BAKER DASHBOARD / ARRIVALS BOARD: plain `<a target="_blank" rel="noopener noreferrer">` link panes. Copy the exact hrefs from the old nav at `static/index.html` (single-source; do NOT invent URLs — if Arrivals has no link in the old nav, grep static/index.html + app.js for the arrivals URL and use that; if genuinely absent, render the entry with "link pending" and SAY SO in the ship report — fail loud, don't guess).
   - SETTINGS & LOGS: `<iframe src="/v2/settings-logs">`; on 404 (Brief 2 not yet merged) show "Settings & Logs — arriving with the parallel build" fallback via iframe load-error probe.
4. `static/v2/shell.css` — copy the needed tokens (colors, fonts, card idiom) from `cockpit/static/cockpit.css`; do not `@import` old `static/styles.css`.
5. XSS: no user input rendered; still use `textContent` / `createTextNode` for any dynamic strings (no `_escHtml` helper exists — do not reference one).

### Key Constraints
- ZERO edits to `static/index.html`, `static/app.js`, `static/styles.css`, cockpit static, controller, any existing `/api` handler.
- `static/v2/settings-logs.*` belongs to Brief 2 — do not create it.
- No new dependencies; vanilla JS only; every fetch in try/catch with visible fallback.
- Cache-bust `?v=1` on both assets (bump on every future change).

### Inter-brief contract (verbatim in both briefs)
Brief 2 owns `static/v2/settings-logs.*` and route `GET /v2/settings-logs`; Brief 1 owns everything else under `static/v2/` and route `GET /v2`. Only shared touchpoint: shell sidebar entry → iframe `/v2/settings-logs`. app.py edits are separate append-only FileResponse routes — merge-safe in either order.

### Verification
1. `pytest` — new route test green; full suite no regressions.
2. `uvicorn app:app` local: `/v2` 200; six entries present; AGENTS iframe loads `/cockpit/` (auth/gate page acceptable); SETTINGS & LOGS shows fallback pane while Brief 2 unmerged; external links open correct URLs.
3. `curl -s -o /dev/null -w "%{http_code}" localhost:8000/` unchanged 200 and byte-identical `static/index.html` (git diff empty on old files).

## Files Modified
- `app.py` (+4 lines, one route) · `static/v2/index.html` · `static/v2/shell.css` · `static/v2/shell.js` (all new)

## Do NOT Touch
- `static/index.html` / `app.js` / `styles.css` — old Lab stays default until Director "switch".
- `cockpit/` anything — cockpit embeds unchanged (ratified).
- `_refresh_one` / lifecycle / bus handlers — unrelated lanes.

## Quality Checkpoints
1. Old `/` byte-identical (git diff shows zero old-file changes).
2. All six labels spelled exactly as ratified.
3. Fail-soft: cockpit-off and settings-logs-404 both show banners, never blank.
4. `?v=1` cache-bust on both assets.
5. Ship report to lead on bus (`lab-unify/p1-shell`) with branch + HEAD SHA; codex gate routes on your pushed SHA.

## Verification SQL
N/A — no database surface in this brief (static shell + one FileResponse route).
