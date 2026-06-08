# BRIEF: DASHBOARD_COCKPIT_WAVE1_QUICKWINS_1 — Plug AO auth hole, fix silent PM-threads panel, de-fake the AO headline, surface scheduler liveness

> **⚠️ G0-REVISE CORRECTION 2026-06-08 (codex #2484) — READ FIRST, OVERRIDES BODY BELOW:**
> 1. **Fixes 2/3/4 ONLY. Fix 1 (AO auth) is PARKED. G2 /security-review NOT required.**
>    Ignore any stranded "Fix 1" / "auth hole" / "G2 mandatory" text below (Context L4,
>    Files-Modified, Do-NOT-Touch, Quality-Checkpoints #3/#5, Verification-curl auth lines,
>    Gate-instructions). Do NOT touch get_ao_dashboard's decorator/auth.
> 2. **Fix 4 visibility:** cortexFeedCard is hidden unless events/lint/pending exist
>    (app.js ~10348-10356) — place the scheduler pill somewhere ALWAYS visible, or keep the
>    card rendered whenever scheduler status is known.
> 3. **Live anchors drifted** (grep to confirm): AO literal dashboard.py:14865; AO render
>    app.js:10078/:10123; PM raw fetch app.js:11139/:11173.


## Context
The Baker Cockpit was tuned-up-audited 2026-06-01 (read-only 7-dimension workflow audit, 39 findings, saved to `tasks/dashboard-tuneup-audit.md`). This brief is **Wave 1** — the four highest impact-per-effort fixes, all small and surgical. One of them is a **live auth hole**, so this brief is security-sensitive: G2 `/security-review` is mandatory before merge.

All four fixes were verified against the live handlers by AH1 at brief-authoring time (file:line below are confirmed, not inferred).

### Surface contract (ui-surface-prebrief skill, V1)
1. **User action:** (a) view the AO relationship dashboard; (b) open a Client-PM thread + its replay; (c) read the AO investment headline; (d) see at-a-glance whether Cortex auto-cycles are alive.
2. **Backend routes (all verified):**
   - `GET /api/dashboard/ao` at `outputs/dashboard.py:12662` — `async def get_ao_dashboard()` — **currently NO auth dependency** (the bug).
   - `GET /api/pm/threads/{pm_slug}` at `outputs/dashboard.py:13002` — `dependencies=[Depends(verify_api_key)]` (already auth-gated → frontend 401s).
   - `GET /api/pm/threads/{pm_slug}/{thread_id}/turns` at `outputs/dashboard.py:13039` — auth-gated.
   - `GET /api/health/scheduler` at `outputs/dashboard.py:1831` — public, returns `{alive, heartbeat_age_seconds, scheduler_running, job_count}` (already exists; frontend just needs to poll it).
3. **Endpoint contracts:** all four are `GET`, no body. The three auth-gated routes require header `X-Baker-Key` (validated by `verify_api_key`, `dashboard.py:105`). `/api/health/scheduler` requires nothing.
4. **State location:** `pm_project_state`, `whatsapp_messages`, AO matter tables (Postgres) for `/api/dashboard/ao`; `scheduler_heartbeat` watermark via `triggers.state.trigger_state` for the health route. All in `baker-master`.
5. **UI repo (= state repo):** `baker-master` — surface: the web dashboard (`outputs/static/index.html` + `app.js`). No cross-repo surface.
6. **Director surface preference:** N/A — no new Director-facing surface choice; all four fixes harden existing dashboard panels in place. (No Slack/email alternative in scope.)
7. **Gate-1+2 reviewer instruction:** Reviewers MUST `curl` each touched route with the exact header the frontend sends and confirm a non-error response (401 BEFORE auth fix is expected only on `/api/dashboard/ao` with no key; 200 WITH key). Code-shape review is necessary but NOT sufficient.

## Estimated time: ~2h
## Complexity: Low
## Prerequisites: none. All four fixes are independent and can ship in one PR.

---

## Fix 1 (P1, SECURITY): Plug the `/api/dashboard/ao` auth hole — ⛔ PARKED 2026-06-08 (Director directive)

> **PARKED — DO NOT IMPLEMENT in this dispatch.** Director 2026-06-08: "leave AO matter
> state parked for later." Fix 1 (the auth dependency on `/api/dashboard/ao`) is OUT OF
> SCOPE for the tonight dispatch. It will ship in a separate security-scoped brief later.
> Because Fix 1 is parked, the mandatory G2 `/security-review` gate is NOT required for
> this dispatch (Fixes 2/3/4 are presentation-only, no auth/data-exposure change). Build
> Fixes 2, 3, 4 only.

### Problem
`GET /api/dashboard/ao` returns AO relationship state — PM state, comms gaps, orbit contacts, deadlines, decisions, pending insights — to **any unauthenticated caller**. Every sibling dashboard route is gated with `Depends(verify_api_key)`; this one was missed.

### Current State
`outputs/dashboard.py:12662`:
```python
@app.get("/api/dashboard/ao")
async def get_ao_dashboard():
    """Aggregated AO relationship dashboard data."""
```

### Implementation
Add the auth dependency (one-line change), matching the sibling pattern at `dashboard.py:801` / `:860`:
```python
@app.get("/api/dashboard/ao", dependencies=[Depends(verify_api_key)])
async def get_ao_dashboard():
    """Aggregated AO relationship dashboard data."""
```

### Key Constraints
- `Depends` and `verify_api_key` are already imported/defined (`dashboard.py:23`, `:105`) — no new imports.
- **The frontend caller already sends the key:** `app.js:9996` uses `bakerFetch('/api/dashboard/ao', { timeout: 15000 })`, and `bakerFetch` (`app.js:25`) injects `X-Baker-Key`. So adding the dependency will NOT break the panel. Confirm this before and after.
- Do not change the handler body.

### Verification
- `curl -s -o /dev/null -w "%{http_code}" https://baker-master.onrender.com/api/dashboard/ao` → expect **401** (was 200).
- `curl -s -H "X-Baker-Key: $KEY" .../api/dashboard/ao` → expect **200** with JSON.
- Load the AO Dashboard tab in the cockpit → still renders (proves the keyed frontend path works).

---

## Fix 2 (P1): Client-PM threads panel 401s + fails silent in production

### Problem
The Client-PM tab's thread list and thread-replay always fail in production: two raw `fetch()` calls omit `X-Baker-Key`, the auth-gated routes return 401, and the catch swallows it — the panel looks dead.

### Current State
`outputs/static/app.js:11093` (list) and `:11128` (replay) use raw `fetch(...)` instead of `bakerFetch(...)`.

### Implementation
Swap both raw `fetch(` calls to `bakerFetch(` so the key is sent. Exact edits:

`app.js:~11093`:
```javascript
        var res = await bakerFetch('/api/pm/threads/' + encodeURIComponent(pmSlug));
```
`app.js:~11128`:
```javascript
        var res = await bakerFetch('/api/pm/threads/' + encodeURIComponent(pmSlug) +
                              '/' + encodeURIComponent(threadId) + '/turns');
```

### Key Constraints
- `bakerFetch` returns the same `Response` object as `fetch`, so `res.ok` / `await res.json()` downstream is unchanged.
- Do not alter the render functions (`renderPMThreadList`, replay rendering) — only the fetch call.
- Bump the `app.js` cache-bust `?v=N` in `index.html` (iOS PWA requirement).

### Verification
- Open Client-PM tab → thread list loads (no longer "failed/empty").
- Click a thread → replay loads.
- DevTools Network: both requests carry `X-Baker-Key` and return 200.

---

## Fix 3 (P1): AO "EUR 66.5M" headline is hardcoded but shown as live

### Problem
`outputs/dashboard.py:12825` returns `"investment_total": "EUR 66.5M"` as a hardcoded literal inside `relationship_status`, rendered as a live headline on the AO Dashboard. It misleads the Director on a flagship relationship and can silently drift from reality. (Note: a prior real AO total was EUR 67.3M — the displayed figure itself is suspect; see AH1 flag to Director.)

### Current State
`outputs/dashboard.py:12822-12828`:
```python
    return {
        "relationship_status": {
            "investment_total": "EUR 66.5M",
            ...
```
Frontend renders it at `app.js:10033` / `:10078` (Relationship Status cell).

### Implementation
Do **not** invent a new number. Make the figure honestly sourced + dated so it can never again masquerade as live:
1. Backend (`dashboard.py` near :12825): replace the bare literal with a named, dated constant and emit an explicit as-of field. Define near the top of the handler (or module-level):
   ```python
   # AO investment headline — STATIC figure, owned by AO Desk. Update both the
   # value and the date together. Source: AO Desk confirmation (see brief flag).
   AO_INVESTMENT_TOTAL = "EUR 66.5M"
   AO_INVESTMENT_TOTAL_AS_OF = "2026-06-01"  # date this figure was last confirmed
   ```
   Then in the return:
   ```python
       "relationship_status": {
           "investment_total": AO_INVESTMENT_TOTAL,
           "investment_total_as_of": AO_INVESTMENT_TOTAL_AS_OF,
           ...
   ```
2. Frontend (`app.js:10033`/`:10078`): render the value with an explicit staleness cue, e.g. `EUR 66.5M` followed by a muted `as of 2026-06-01` label sourced from `investment_total_as_of`. Use `document.createTextNode` / existing `esc()` — no innerHTML string concat of the value.

### Key Constraints
- Financial-figure lesson (`tasks/lessons.md`): a figure on a Director-facing surface must carry value + date. This fix adds the date; it does NOT certify the value.
- If `investment_total_as_of` is absent (older cached response), the frontend must degrade gracefully (show the value with no date, not "undefined").

### Verification
- AO Dashboard headline shows the figure **with** an "as of <date>" cue.
- `curl -H "X-Baker-Key: $KEY" .../api/dashboard/ao | jq .relationship_status` shows both `investment_total` and `investment_total_as_of`.

---

## Fix 4 (P2): Surface scheduler liveness so the Director can see if Cortex auto-cycles are alive

### Problem
There is no UI signal for whether the scheduler (which fires Cortex auto-cycles + pollers) is alive. If it dies silently, the cockpit looks normal. The backend endpoint already exists and is unused by the frontend.

### Current State
`GET /api/health/scheduler` (`dashboard.py:1831`, public) returns:
```json
{"alive": true, "heartbeat_age_seconds": 42, "scheduler_running": true, "job_count": 12}
```
The Cortex feed card lives at `app.js:10271` (`loadCortexFeed()`), element id `cortexFeedCard` (`app.js:10299`).

### Implementation
1. In `loadCortexFeed()` (or alongside it), `await bakerFetch('/api/health/scheduler')` (no key needed, but bakerFetch is harmless and consistent).
2. Render a small status pill in the `cortexFeedCard` header: green "Scheduler alive (Xs ago)" when `alive === true`, red "Scheduler STALE — Xs" when `false`. Use `heartbeat_age_seconds` for the age text.
3. Fail-safe: if the fetch throws, show a muted "scheduler status unknown" pill — never leave it blank and never throw out of `loadCortexFeed`.

### Key Constraints
- Pure additive frontend change + one read of an existing endpoint. No backend change.
- Wrap the fetch in try/catch — a health-check failure must not break the Cortex feed render.
- Cache-bust `?v=N`.

### Verification
- AO Dashboard Cortex card shows a green "Scheduler alive" pill in normal state.
- Temporarily point at a stale heartbeat (or mock `alive:false`) → pill goes red. Revert.

---

## Files Modified
- `outputs/dashboard.py` — Fix 1 (add auth dep, :12662), Fix 3 (named dated constant + as-of field, :12825).
- `outputs/static/app.js` — Fix 2 (two `fetch`→`bakerFetch`, :11093/:11128), Fix 3 (render as-of cue, :10033/:10078), Fix 4 (scheduler pill in `cortexFeedCard`, :10271).
- `outputs/static/index.html` — `?v=N` cache-bust bump for `app.js`.

## Do NOT Touch
- The `get_ao_dashboard()` handler body — EXCEPT the single scoped Fix 3 change to the `relationship_status` return dict (the named constant + `investment_total_as_of` field). Fix 1 is the decorator line only; no other body/query logic changes. (G0 nit: this line previously contradicted Fix 3 — resolved.)
- Any other route's auth dependency — this brief scopes ONE auth fix; do not sweep others (that is a separate Wave-2 item with its own keep-or-cut review).
- `renderPMThreadList` / replay render internals.
- The numeric VALUE `66.5M` — only its presentation/sourcing changes; the value is an AO-Desk decision flagged separately.

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean.
2. AO Dashboard, Client-PM, Cortex card all render on **desktop and iPhone PWA** (cache-bust verified).
3. `/api/dashboard/ao` returns 401 without key, 200 with key.
4. No raw `fetch(` left for the two PM-threads calls (`grep -n "fetch('/api/pm/threads" app.js` returns nothing).
5. G2 `/security-review` run (auth change).

## Verification SQL / curl
```bash
# auth hole closed
curl -s -o /dev/null -w "no-key:%{http_code}\n" https://baker-master.onrender.com/api/dashboard/ao
curl -s -o /dev/null -w "with-key:%{http_code}\n" -H "X-Baker-Key: $BAKER_KEY" https://baker-master.onrender.com/api/dashboard/ao
# headline now dated
curl -s -H "X-Baker-Key: $BAKER_KEY" https://baker-master.onrender.com/api/dashboard/ao | jq '.relationship_status | {investment_total, investment_total_as_of}'
# scheduler liveness reachable
curl -s https://baker-master.onrender.com/api/health/scheduler | jq .
```

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST `curl` each touched route with the exact header the frontend sends and confirm a non-error response (per Verification block). G2 `/security-review` is **mandatory** — Fix 1 closes a live unauthenticated data-exposure hole. Code-shape review (XSS-safe, syntactically valid) is necessary but NOT sufficient.

---

## AH1 flag to Director (out of band, not b1's task)
The displayed AO figure `EUR 66.5M` may itself be wrong — a prior confirmed AO total was `EUR 67.3M` (`tasks/lessons.md` financial-figures entry). Fix 3 only dates/sources the presentation; the correct value is an **AO Desk** confirmation. Recommend AO Desk confirms the live number before next AO touchpoint.
