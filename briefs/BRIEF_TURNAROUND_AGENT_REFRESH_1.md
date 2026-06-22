# BRIEF: TURNAROUND_AGENT_REFRESH_1 — refresh tired agents from the dashboard, not terminal-by-terminal

## Context
Companion to "Stealth Flight" (WAKE_BACKGROUND_NONINTRUSIVE_1). With wakes going quiet, the Director still needs a clean way to **refresh** (force a fresh-context restart of) a tired/stale agent — today he does it manually, opening each terminal one at a time. codex-arch's addendum (#3592) defines this as the operational complement: **"wake quietly, refresh cleanly."** It is mostly dashboard UX + one endpoint on top of EXISTING lifecycle primitives — NOT a new lifecycle.

**Distinction (lock it):** Wake = tell an agent to check the bus. Refresh = safely restart a tired session with fresh context. Stealth Flight owns wake; **Turnaround** owns refresh.

Director-named **"Turnaround"** (aviation: servicing a plane between flights). Director-ratified the need 2026-06-21 (relayed via codex-arch #3592). Repo: brisen-lab.

### Surface contract
- **Surface:** Brisen Lab dashboard agent cards (AG-101…) — a per-card **Refresh** control + a fleet-level **"Refresh stale"** action. Plus a new `POST /api/refresh-agent` endpoint.
- **Trigger:** Director clicks the Refresh control on a card (or "Refresh stale" in fleet controls).
- **States (card):** `fresh` / `aging` / `stale` / `refresh_pending` / `refreshing` / `refreshed` / `refresh_failed`.
- **Auth/visibility:** Origin-gated exactly like `/api/wake` (Director browser only). Director (the slug) is never a refresh target. Busy agents queue (`refresh_pending`), never killed mid tool-call / external-send / git-push / deploy.
- **No-collateral guarantee:** refresh must NOT steal Terminal focus (reuses the lifecycle SIGTERM path, which does not foreground); a refresh must never interrupt an in-flight tool call — it drains first (existing two-phase restart).

## Estimated time: ~3–4h
## Complexity: Medium (dashboard endpoint + card UI + state model; lifecycle primitive already exists)
## Prerequisites: none hard; ships independently of Stealth Flight. (Both touch brisen-lab; coordinate merge order with whoever lands first.)

---

## Context Contract (Harness V2)
- **Task class:** fleet-infra / dashboard feature (brisen-lab repo: `app.py`, `bus.py`, `static/app.js`, `static/styles.css`, tests).
- **Deploy path:** brisen-lab Render auto-deploy on `main`. No Mac-side component (unlike Stealth Flight) — this is pure dashboard + server.
- **Done rubric:** §Verification, answered pass/fail.
- **Gate plan:** G0 design = codex-arch (this brief mirrors #3592, so likely fast). G3 code = codex. Post-deploy AC = live on the Director's dashboard.
- **Harness-V2:** applies.

---

## What already exists (scout-verified — DO NOT rebuild)
- **Restart primitive:** `lifecycle.trigger_force_fresh_context(worker_slug, reason, broadcast_fn, incident_dir="/tmp/brisen-lab-incidents")` — `bm-b1/brisen-lab/lifecycle.py:199`. Two-phase: atomic session-expiry + `lifecycle/restart` broadcast → 60s drain (`DRAIN_TIMEOUT_S=60`) → `lifecycle/forced-kill` (SIGKILL) + incident file. Guards: `director_cannot_be_force_restarted` (line 214); in-flight guard returns `already_in_flight` (lines 226-232). Idle confirm: `confirm_idle(worker_slug)` (line 279) via `POST /lifecycle/idle_confirm/{worker_slug}` (app.py:704).
- **Session age:** computed `bus.py:1269-1281` from `forge_sessions` (`session_age_seconds`, `last_seen_age_seconds`); returned per card in `/api/v2/terminals` (`bus.py:1424`).
- **Badge thresholds:** `static/app.js:183-185` — `>28800`s red (>8h), `>7200`s amber (>2h), else gray. `renderSessionAgeBadge()` app.js:179-192.
- **Busy/idle:** `is_working` = latest open session `last_seen_at ≤ WORKING_FRESH_THRESHOLD_S` (120s) — `bus.py:1282-1293`; returned in card payload (`bus.py:1425`); `/api/heartbeat` updates `last_seen_at` (app.py:335-396, supports explicit `idle:true`).
- **Wake endpoint to mirror:** `POST /api/wake` (app.py:475-503) — origin gate + alias validation.
- **Card render:** `renderCard(alias)` app.js:353-389; click handler app.js:1097-1115; static shells in `static/index.html:41-62`.
- **Audit:** `lifecycle/restart` + `lifecycle/forced-kill` already persisted to `brisen_lab_msg` with `reason`.

## Engineering Craft Gates
- **Diagnose:** N/A — net-new feature, not a bug.
- **Prototype:** N/A — UI pattern (per-card icon + fleet action) is pre-decided by codex-arch #3592 and mirrors the existing wake-click + badge; no real uncertainty.
- **TDD/verification:** applies — first vertical test: `POST /api/refresh-agent?alias=b2` calls `lifecycle.trigger_force_fresh_context` once with `reason="director_refresh_agent:alias=b2"`; then mode filters; then origin/alias guards. Live probe on the Director's dashboard for the UI.

---

## Feature 1 — `POST /api/refresh-agent` endpoint (mirror `/api/wake`)

### Implementation (app.py, copy the `/api/wake` shape at :475-503)
```python
@app.post("/api/refresh-agent")
async def refresh_agent(req: Request):
    """Director dashboard: force a fresh-context restart of a tired agent.
    Query: alias OPTIONAL (omit ⇒ fleet mode); mode = always | stale_only | idle_only (default always)."""
    if not freeze.is_v2_enabled():
        raise HTTPException(status_code=503, detail="lab_frozen")
    origin = req.headers.get("origin", "")
    expected_origin = os.environ.get("BRISEN_LAB_ORIGIN", "https://brisen-lab.onrender.com")
    if origin != expected_origin:
        raise HTTPException(status_code=403, detail="bad origin")
    alias = req.query_params.get("alias", "")
    mode = req.query_params.get("mode", "always")
    confirm_protected = req.query_params.get("confirm_protected", "") == "true"
    # codex #3852 F1: FLEET path branches BEFORE alias validation (else ?mode=stale_only 400s on alias="")
    if not alias:
        return await _refresh_fleet(mode=mode, confirm_protected=confirm_protected)
    if alias not in REFRESHABLE_SLUGS:               # codex-arch R1: NOT raw TERMINALS — see LOCKED rulings
        raise HTTPException(status_code=400, detail="not_refreshable")
    if alias == "director":                          # belt-and-braces (lifecycle also guards)
        raise HTTPException(status_code=400, detail="director_not_refreshable")
    force = req.query_params.get("force", "") == "true"   # confirm_protected parsed above (fleet branch)
    # codex #3837 F2: protected (terminal head/desk) requires explicit server confirm
    if alias in PROTECTED_SLUGS and not confirm_protected:
        raise HTTPException(status_code=409, detail="confirm_protected_required")
    age, working = _session_age_and_working(alias)   # SAME signals the cards show (bus.py:1269-1293)
    if mode == "stale_only" and (age is None or age <= 28800):
        return {"ok": True, "alias": alias, "skipped": "not_stale"}
    # codex #3837 F1: a WORKING agent is NEVER killed mid-work for ANY mode — it QUEUES.
    # trigger_force_fresh_context expires keys + broadcasts restart immediately (lifecycle.py:234-264),
    # so the busy guard MUST be here, before the call. Only an explicit force= bypasses it.
    if working and not force:
        req_id = _enqueue_refresh_request(alias, protected=(alias in PROTECTED_SLUGS),
                                          reason=f"director_refresh_agent:alias={alias}")  # Feature 3 table
        return {"ok": True, "alias": alias, "queued": "refresh_pending", "request_id": req_id}
    try:
        result = await lifecycle.trigger_force_fresh_context(
            alias, reason=f"director_refresh_agent:alias={alias}", broadcast_fn=_broadcast)
    except ValueError as e:                           # director_cannot_be_force_restarted
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "alias": alias, "result": result}
```
**Constraints:** every DB read bounded + `conn.rollback()` in except; wrap the lifecycle call in try/except (fault-tolerant). Do NOT add a new restart mechanism — call the existing primitive only.

## Feature 2 — Fleet action `POST /api/refresh-agent?mode=stale_only` (all red agents)
Same endpoint, no `alias` ⇒ iterate `REFRESHABLE_SLUGS` (R1, NOT raw `TERMINALS`), apply `mode=stale_only` (only `age>28800`), skip `director` + non-refreshable AND **skip protected/director-facing heads by default unless `confirm_protected=true` is sent** (R2), call the primitive per alias. Return a per-alias result list. **"Refresh all idle" (`mode=idle_only`) is SECONDARY/gated — not the default button.**

## Feature 3 — Card state model + busy-queue (no kill mid-work)
- Extend card glance with refresh states: `refresh_pending` (queued, agent busy), `refreshing` (SIGTERM sent, draining), `refreshed` (idle-confirmed), `refresh_failed` (forced-kill/incident).
- **Busy protection (codex-arch R3 — REAL server state, NOT optimistic UI):** if `is_working` (heartbeat ≤120s) → PERSIST `refresh_pending` server-side (new column/small table, not just a UI badge), and DRAIN it from the idle path — extend `/api/heartbeat` (currently app.py:371-396 only updates `last_seen_at` and returns) so that on `idle:true` it checks for a pending refresh for that slug and fires `trigger_force_fresh_context`; OR a bounded poller. Add a **max-defer ~10 min**: if the agent never goes idle, expire the pending refresh VISIBLY on the card with cancel/force options. Never SIGKILL a working agent. The lifecycle two-phase drain still waits for idle-confirm once triggered.
- Dashboard must SHOW `refresh_pending`/`refreshing` so the Director never opens a terminal to check.

## Feature 4 — Card Refresh control (static/app.js + index.html + styles.css)
- In `renderCard()` (after the history `···` link, ~app.js:385) add a Refresh control with `data-refresh-alias`, shown when `sessionAge[alias] > 7200` (amber/red) — fresh agents don't need it.
- Click handler (extend app.js:1097-1115): `fetch("/api/refresh-agent?alias="+alias, {method:"POST"})`; optimistic `refreshing` badge; if `is_working`, confirm "Agent is busy — queue refresh for when idle?" → `mode=idle_only`.
- Add a fleet "Refresh stale" button in the controls row → `POST /api/refresh-agent?mode=stale_only`.
- CSS in `static/styles.css` matching card design language. **Cache-bust** the static assets (`?v=N`).

## Files Modified
- `brisen-lab/scripts/generate_agent_identity_artifacts.py` — emit generated `REFRESHABLE_SLUGS` (+ JS), predicate `bus_enabled and runtime.startswith("terminal-")` (codex #3837 F3 / #3852 nit).
- `brisen-lab/agent_identity_generated.py` (+ .js) — regenerated `REFRESHABLE_SLUGS` / `PROTECTED_SLUGS`.
- `brisen-lab/db.py` — add `refresh_requests(alias, status, requested_at, expires_at, protected, reason)` DDL to the INLINE schema bootstrap (`SCHEMA_V2_SQL`, executed at startup db.py:411-412). brisen-lab has NO `migrations/` dir — do NOT create one (codex #3852 F2).
- `brisen-lab/app.py` — `/api/refresh-agent` (single + fleet) + `_session_age_and_working` + `_enqueue_refresh_request`/drain; heartbeat idle-drain (respecting the app.py:345-348 contract) OR a bounded poller.
- `brisen-lab/bus.py` — expose refresh states in the card payload (extend `/api/v2/terminals`).
- `brisen-lab/static/app.js` — Refresh control + fleet button + handlers (with `preventDefault()`+`stopPropagation()`, codex #3837 F5) + state rendering.
- `brisen-lab/static/index.html` + `styles.css` — fleet button markup + styles + cache-bust.
- `brisen-lab/tests/test_refresh_agent*.py` — endpoint + mode gating + guards + busy-queue + protected-confirm + max-defer.

## Do NOT Touch
- `lifecycle.py` two-phase restart internals — call `trigger_force_fresh_context`, don't reimplement.
- `/api/wake` and the Stealth Flight wake path — orthogonal; refresh ≠ wake.
- `director` slug refreshability; session-age thresholds (reuse 7200/28800).

## Verification
- **Done rubric (pass/fail):**
  1. Director refreshes ONE stale agent from its card, no terminal opened?
  2. "Refresh stale" refreshes all red (>8h) agents in one action, skips director + non-refreshable?
  3. A busy agent shows `refresh_pending` and is NOT killed mid-work (executes on next idle)?
  4. Refresh does NOT steal Terminal focus?
  5. A `lifecycle/restart` (and on timeout `lifecycle/forced-kill`) audit row exists per refresh?
  6. Manual terminal-by-terminal refresh is no longer the normal workflow?
- **Tests:** `cd ~/bm-b1-brisen-lab && python -m pytest tests/test_refresh_agent*.py -v`
- **Live probe:** on the Director's dashboard, refresh a known-stale card; confirm the badge transitions fresh→refreshing→refreshed and no Terminal window pops.

## POST_DEPLOY_AC_VERDICT
Emit `POST_DEPLOY_AC_VERDICT v1` after the 6 done-rubric rows pass live on the Director's dashboard.

## CODEX-ARCH G0 RULINGS — #3827 (LOCKED — implement exactly)
**Verdict:** APPROVE_WITH_RULINGS. No architecture blocker; the split correctly reuses `trigger_force_fresh_context`.

**R1 — refreshable set is NOT raw `TERMINALS`.** `TERMINALS` includes non-terminal/service/app-only runtimes (`cowork-ah1` app-claude, `cortex` service, `codex-arch` app-codex, `clerk` headless-qwen3; agent_identity_generated.py:12,16-18). Define **`REFRESHABLE_SLUGS` = terminal-refresh-capable aliases only** — exclude `director`, cortex/system/service, and app-only/headless/no-adapter slugs. Derive from the registry's runtime-type (a Terminal-backed forge session that can be SIGTERM'd + respawned). Terminal heads/desks ARE per-card refreshable (see R2).

**R2 — heads/director-facing agents:** per-card refresh ALLOWED for terminal heads/desks, but (a) require a visible warning/confirm before refresh (head-context loss; `lead` is stale-kill-exempt precisely because timer-kill can drop orchestration state — wake-handler.applescript:169-178), and (b) EXCLUDE them from the default fleet `Refresh stale` action unless an explicit `confirm_protected=true` flag is sent.

**R3 — busy queue is REAL server state, not optimistic UI.** Persist `refresh_pending` server-side; drain it from the idle path (extend `/api/heartbeat` idle:true — today it only updates `last_seen_at`, app.py:371-396 — or a bounded poller) to fire `trigger_force_fresh_context`. Add **max-defer ~10 min** → expire visibly on the card with cancel/force.

**Required test additions:** unknown/non-refreshable alias → 400; protected visible-agent refresh requires confirm; fleet `Refresh stale` skips protected aliases by default; busy `refresh_pending` persists + drains on idle heartbeat; max-defer expires visibly.

## CODEX (AG-202) FINDINGS — #3837 (LOCKED — folded; final verify gate)

1. **Busy-agent safety (F1):** `trigger_force_fresh_context` immediately expires keys + broadcasts restart (lifecycle.py:234-264). So a WORKING agent must QUEUE `refresh_pending` for **ALL modes** (not just `idle_only`) — only an explicit `force=true` bypasses. (Fixed in the endpoint sketch.)
2. **Protected confirm is SERVER-enforced (F2):** define `PROTECTED_SLUGS` (terminal heads/desks). Per-card refresh of a protected slug requires `confirm_protected=true` server-side (409 otherwise); fleet `Refresh stale` skips protected unless the flag is set. Not a UI-only warning.
3. **REFRESHABLE_SLUGS from the registry `runtime` (F3):** `AGENTS` carries `runtime` (agent_identity_generated.py:12). The generator currently leaks app-only `cowork-ah1`/`codex-arch` into `APP_TERMINALS`/`WAKEABLE` (generate_agent_identity_artifacts.py:122-135,206-208). Add a GENERATED `REFRESHABLE_SLUGS` with predicate **`bus_enabled and runtime.startswith("terminal-")`** (codex #3852 nit — `clerk-haiku` is `status: planned` but bus_enabled + terminal runtime, agent_registry.yml:169-175; include it unless status-filtering is intentional); emit a JS equivalent. Do NOT hand-list.
4. **Queue is a NEW table in the INLINE bootstrap + safe drain (F4 / #3852 F2):** add `refresh_requests(alias, status, requested_at, expires_at, protected, reason)` DDL to `db.py` `SCHEMA_V2_SQL` (executed at startup db.py:411-412) — brisen-lab has NO `migrations/` dir, do NOT create one. NOT `forge_sessions` (liveness history, db.py:247-256) or `brisen_lab_settings` (generic kv, db.py:396-404). Drain via a bounded async poller OR an explicit idle-drain AFTER the heartbeat `last_seen_at` UPDATE — but the heartbeat hard contract (app.py:345-348: "does ONLY the last_seen_at UPDATE", "MUST NOT _broadcast") must be honored/amended deliberately, not silently. Max-defer ~10 min → expire visibly with cancel/force.
5. **Fleet path before alias validation (#3852 F1):** `if not alias: return await _refresh_fleet(...)` MUST branch BEFORE the `REFRESHABLE_SLUGS` membership check (else `?mode=stale_only` 400s on `alias=""`). Test the no-alias fleet path. **Builder (#3861 nit): factor a shared `_refresh_one(alias, mode, confirm_protected, force)` that applies the busy/protected/stale guards before any lifecycle call, and have both the single endpoint AND `_refresh_fleet` call it — no guard divergence.**
6. **Stealth Flight overlap (F5):** the existing card click wakes any non-history/non-shift click (static/app.js:1097-1115). The new Refresh button (added after the history link) MUST call `preventDefault()` + `stopPropagation()` so a refresh click does not also fire a wake.

**Audit:** existing lifecycle audit suffices for the ACTUAL refresh if `reason="director_refresh_agent:alias=..."`; ADD `refresh_requests` rows for queued/expired/cancelled states so pending actions are auditable too.

## AH1 devil's-advocate
1. Refreshing a head mid-thought loses its in-session context (that IS the point of a fresh context, but warn before refreshing a VISIBLE/director-facing agent).
2. `refresh_pending` could wait forever if an agent never reports idle — add a max-defer (e.g. 10 min) then prompt the Director to force or cancel.
3. "Refresh all idle" is tempting as a one-click but could mass-reset agents the Director wanted warm — keep it secondary + confirm-gated.
4. Overlap with Stealth Flight on `bus.py`/`app.js` — sequence the merges; whoever lands second rebases.
