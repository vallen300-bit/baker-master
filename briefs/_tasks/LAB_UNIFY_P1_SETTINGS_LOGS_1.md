# BRIEF: LAB_UNIFY_P1_SETTINGS_LOGS_1 — Settings & Logs skeleton page (token pressure · maintenance · history)

```yaml
brief_id: LAB_UNIFY_P1_SETTINGS_LOGS_1
dispatched_by: lead
assigned_to: b1
repo: brisen-lab (worktree ~/bm-b1-brisen-lab; branch b1/lab-unify-p1-settings-logs-1 from origin/main)
status: PENDING
```

## Context

Director-ratified Lab unification, Phase 1, brief 2 of 2 (see
`bm-aihead1/briefs/_plans/BRISEN_LAB_UNIFICATION_BUILD_PLAN_2026-07-20.md`,
approved "go" 2026-07-20; sidebar entry 6 "SETTINGS & LOGS — Token burn,
Maintenance works, History; detail layout: lead decides"). This page is
framed by the /v2 shell (Brief 1, b2, parallel) but MUST also render
standalone at its own URL. Cockpit register is the style reference.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director opens Settings & Logs and reads live token pressure per seat, system maintenance health, and job history.
2. **Backend routes (all EXISTING, verified by opening handlers @bcbcd55):**
   - `GET /lifecycle/status` — app.py:2917 `async def lifecycle_status()` — public read, no auth; returns `{v2_enabled, h4_watchdog, token_pressure: {slug: {state, pct, last_update_ts}}}`.
   - `GET /api/state` — app.py:2783 `async def state()` — glance snapshot incl. per-seat context.
   - `GET /api/bus_health` — app.py:2132 (access-gated: `_bus_health_access_ok` app.py:2070 — handle 401/403 as a degraded card, not an error page).
   - `GET /api/wake_health` — app.py:2000.
   - `GET /api/v2/pool_stats` — app.py:2937. · `GET /healthz` — app.py:2933.
   - History: `GET /cockpit/api/history` — bridge proxy app.py:3063 → laptop `cockpit_controller.py:2373 @app.get("/api/history")`; offline/flag-off when laptop away → fail-soft.
3. **Endpoint contract:** all GET, no params required, JSON; history returns job rows with `stale` flag (see cockpit history view for shape).
4. **State location:** brisen-lab Postgres + laptop controller — read-only page, zero writes.
5. **UI repo (= state repo):** brisen-lab, `static/v2/settings-logs.*`.
6. **Director surface preference:** ratified 2026-07-20 — Settings & Logs inside unified Lab; detail layout delegated to lead (this brief IS the lead layout).
7. **Gate-1+2 reviewer instruction:** Reviewers MUST `curl` each of the six URLs above with the exact paths and confirm non-error (or documented-degraded) responses, and load `/v2/settings-logs` in a browser. Code-shape review is necessary but NOT sufficient.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: none (merges independently of Brief 1)

## Baker Agent Vault Rails
Relevant: build-command-center, verification-surfaces, bus-and-lanes.
Ignored: memory-and-lessons, loop-runner — read-only dashboard page.

## Harness V2

- **Context Contract:** read before building: this brief (whole), the six handler signatures at the exact app.py lines in Surface contract §2 (verify, don't trust), `cockpit/static/cockpit.js` History-mode fail-soft pattern (pattern only), `cockpit/static/cockpit.css` (style tokens), one existing route test in `tests/`. Nothing else required.
- **Task class:** medium-feature (production, brisen-lab).
- **Done rubric / done-state class:** terminal state = Merged + Deployed + post-deploy AC passed + writeback resolved. Post-deploy AC (lead): live `/v2/settings-logs` — Token tab shows real per-seat pressure, Maintenance cards degrade per-card, History behaves per bridge state. Writeback: registry status HTML update by lead.
- **Gate plan:** b1 self-test (pytest + local uvicorn + literal curls of all six feeds) → push branch → blocking independent codex gate on pushed SHA (Surface contract §7 binding) → lead merge → Render auto-deploy → lead POST_DEPLOY_AC_VERDICT on bus.

---

## Feature 1: Settings & Logs page

### Problem
Token burn, maintenance health, and history live in scattered/hidden/dead
surfaces (old Token Burn link points at a dead local service; bus/delivery
health are separate pages; history is cockpit-only).

### Current State
- Old nav: `static/index.html:34` hidden dead Token Burn link → `http://127.0.0.1:3000`.
- Cockpit history view + fail-soft contract: `cockpit/static/cockpit.js` (History mode) — reuse its stale/offline handling PATTERN, not its code.

### Engineering Craft Gates
- Diagnose: N/A — new feature.
- Prototype: N/A — three-tab skeleton ratified; layout detail delegated and fixed by this brief.
- TDD/verification: applies — first test: `GET /v2/settings-logs` 200 `text/html` containing the three tab labels (FastAPI TestClient, follow existing route-test pattern in `tests/`).

### Implementation
1. `app.py` — append-only route (merge-safe with Brief 1's `/v2` route):
```python
@app.get("/v2/settings-logs")
def v2_settings_logs():
    return FileResponse("static/v2/settings-logs.html")
```
2. `static/v2/settings-logs.html` — three tabs: **Token** · **Maintenance** · **History**. Assets `/static/v2/settings-logs.js?v=1` (+ inline or small css file if needed, cockpit register tokens copied from `cockpit/static/cockpit.css`).
3. `static/v2/settings-logs.js` — vanilla JS, every fetch in try/catch:
   - **Token tab:** merge `/lifecycle/status`.token_pressure with `/api/state` per-seat context into one table: seat · pressure state (green/amber/red chip) · pct · context % · last update (relative). Sort: red > amber > green, then slug. Footer note line (literal): `No €-spend feed exists yet — this shows live token pressure and context only.` No fake numbers.
   - **Maintenance tab:** four cards — bus health (`/api/bus_health`; on 401/403/5xx render the card as `unavailable (<status>)`), wake health (`/api/wake_health`), DB pool (`/api/v2/pool_stats`), service (`/healthz`). Per-card degradation — one dead feed never blanks the page.
   - **History tab:** fetch `/cockpit/api/history`; render job rows (reuse the visual idiom of cockpit verdict cards, simplified list is fine). On network error / non-2xx: `History needs the laptop cockpit online.` If payload carries `stale:true`, show the stale banner like the cockpit does.
   - Refresh: 30s interval per active tab only; `AbortSignal.timeout(8000)` on every fetch.
   - XSS: all dynamic values via `textContent` — no innerHTML with fetched strings; no `_escHtml` helper exists, do not reference one.
4. Standalone-first: page must render correctly at `/v2/settings-logs` directly; the shell merely iframes it.

### Key Constraints
- ZERO edits to old Lab files, cockpit static, controller, any existing handler.
- `static/v2/index.html|shell.css|shell.js` belong to Brief 1 — do not create them.
- Read-only page: no POST anywhere.
- Cache-bust `?v=1`; bump on change.

### Inter-brief contract (verbatim in both briefs)
Brief 2 owns `static/v2/settings-logs.*` and route `GET /v2/settings-logs`; Brief 1 owns everything else under `static/v2/` and route `GET /v2`. Only shared touchpoint: shell sidebar entry → iframe `/v2/settings-logs`. app.py edits are separate append-only FileResponse routes — merge-safe in either order.

### Verification
1. `pytest` — new route test green; suite no regressions.
2. Local uvicorn: page 200; Token tab shows real seats from `/lifecycle/status` (or clean empty-state if machine uninitialized → `lifecycle_not_initialized` must render as a message, not a crash); Maintenance cards degrade per-card; History shows offline message locally (no bridge) — that IS the pass state locally.
3. Old `/` and all old pages untouched (git diff shows only new files + one app.py route).

## Files Modified
- `app.py` (+4 lines, one route) · `static/v2/settings-logs.html` · `static/v2/settings-logs.js` (new)

## Do NOT Touch
- Everything listed in Brief 1's Do-NOT-Touch, plus `static/v2/index.html|shell.*` (Brief 1's files).

## Quality Checkpoints
1. Every fetch has timeout + try/catch + visible degraded state.
2. No-spend-feed note present verbatim (fail-loud honesty).
3. bus_health 401/403 renders as degraded card, not error page.
4. Ship report to lead on bus (`lab-unify/p1-settings-logs`) with branch + HEAD SHA; codex gate routes on your pushed SHA.

## Verification SQL
N/A — read-only page over existing JSON endpoints; no direct DB access added.
