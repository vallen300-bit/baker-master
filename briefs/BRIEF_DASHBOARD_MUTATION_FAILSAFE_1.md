# BRIEF: DASHBOARD_MUTATION_FAILSAFE_1 — Stop dashboard action buttons failing silently (and falsely succeeding)

## Context
Cockpit tune-up audit (2026-06-01, `tasks/dashboard-tuneup-audit.md`) Wave 2: ~21 user-facing mutation buttons (complete / dismiss / done / resolve / snooze / +1week) are fire-and-forget. Two failure modes, both Director-facing:
1. **Silent failure:** the `bakerFetch(...).then(...)` chain has no `.catch`, so a network error / rejected promise does nothing — the button looks dead.
2. **False success (worse):** several handlers apply the optimistic UI (remove the card / strike-through) inside `.then(...)` **without checking `resp.ok`** — so on a 500/401 the card disappears as if it worked, then the item reappears on reload. The Director believes an item is handled when the server rejected it.

Verified examples (all confirmed in `outputs/static/app.js`):
- `_triageDismiss` (~2855) → `POST /api/alerts/{id}/dismiss` — no `resp.ok`, no `.catch`.
- `_criticalDone` (~3154 and ~3406) → `POST /api/critical/{id}/done` — no `resp.ok`, no `.catch`.
- deadline Dismiss + +1 Week (~6109) → `POST /api/deadlines/{id}/dismiss` — no `resp.ok`, no `.catch`.
- `_completePriority` (~845) → `DELETE /api/priorities/{id}` — checks `resp.ok` (good) but no `.catch`.

All target endpoints exist and are auth-gated (`Depends(verify_api_key)`), verified in `dashboard.py`: `/api/priorities/{id}` DELETE (:11164), `/api/alerts/{id}/dismiss|resolve|acknowledge` (:2604/:2616…), `/api/critical/{id}/done|promote` (:7621/:7633), `/api/deadlines/{id}/dismiss|complete` (:7559/:7590).

### Surface contract (ui-surface-prebrief skill, V1)
1. **User action:** complete / dismiss / resolve / snooze / postpone a priority, alert, critical item, or deadline (state-changing button clicks on the AO Dashboard + Deadlines surfaces).
2. **Backend routes (verified, all auth-gated):** `DELETE /api/priorities/{priority_id}` (dashboard.py:11164); `POST /api/alerts/{alert_id}/dismiss|resolve|acknowledge` (:2604/:2616); `POST /api/critical/{deadline_id}/done`, `/api/critical/{alert_id}/promote` (:7621/:7633); `POST /api/deadlines/{deadline_id}/dismiss|complete` (:7559/:7590).
3. **Endpoint contract:** POST/DELETE, path param `{id}`, header `X-Baker-Key` (sent by `bakerFetch`). MOST take no body; EXCEPTIONS carry a JSON body — e.g. `POST /api/deadlines/{id}/reschedule` requires `{due_date}` (dashboard.py:7898, the "+1 Week" button at app.js:6115). Migrations MUST preserve existing request bodies. Success = 2xx **AND** no `{"error": ...}` in the JSON body — some endpoints return 200 + `{error}` for business failures (e.g. `/api/critical/{id}/promote` max-5, dashboard.py:7638). (codex-arch G0 fold.)
4. **State location:** `priorities` / `alerts` / `critical`/deadlines tables (Postgres) in `baker-master`.
5. **UI repo (= state repo):** `baker-master` — surface: existing dashboard buttons, hardened in place (no new surface).
6. **Director surface preference:** N/A — no new surface; existing buttons gain error-handling + a confirmed-success gate.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST simulate a FAILED mutation (offline, or a 500/401 response) and confirm (a) the card does NOT disappear and (b) a red error toast shows; AND that a successful mutation still applies the optimistic UI. Code-shape review alone is insufficient — this is a behavior fix.

## Estimated time: ~2.5h
## Complexity: Medium
## Prerequisites: none. Independent of the parked Wave 1 brief.

---

## Fix 1: Add an error-styled toast variant (backward-compatible)

### Current State
`app.js:2999` — `function _showToast(msg)` hardcodes gold styling, single arg.

### Implementation
Extend to an optional `type`:
```javascript
function _showToast(msg, type) {
    var t = document.createElement('div');
    var bg = (type === 'error') ? '#b00020' : '#c9a96e';
    var fg = (type === 'error') ? '#fff' : '#1a1a1a';
    t.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:' + bg + ';color:' + fg + ';padding:8px 20px;border-radius:8px;font-size:13px;font-weight:600;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
    t.textContent = msg;
    document.body.appendChild(t);
    // ...keep the existing auto-remove timeout exactly as-is
}
```
Existing single-arg callers are unchanged (default = gold).

## Fix 2: Add a centralized mutation helper

### Implementation
Add near `bakerFetch` (`app.js:25`):
```javascript
// Mutation wrapper: runs onOk ONLY after a confirmed-ok response; on any
// failure (non-ok status OR network error) shows a red toast and runs onErr.
// Returns nothing (callers pass UI updates as callbacks). Prevents the
// fire-and-forget + false-success bugs (DASHBOARD_MUTATION_FAILSAFE_1).
async function _mutate(url, opts, onOk, onErr) {
    try {
        var resp = await bakerFetch(url, opts);
        if (!resp.ok) throw new Error('http_' + resp.status);
        // codex-arch fold: some endpoints return HTTP 200 + {"error": "..."}
        // for business failures (e.g. /api/critical/{id}/promote max-5,
        // dashboard.py:7638). Treat that as failure, NOT success.
        var data = null;
        try { data = await resp.clone().json(); } catch (e) { data = null; }
        if (data && data.error) {
            _showToast(data.error, 'error');
            if (onErr) onErr(new Error(data.error));
            return;
        }
        if (onOk) onOk(resp, data);
    } catch (e) {
        _showToast('Action failed — not saved. Try again.', 'error');
        if (onErr) onErr(e);
    }
}
```

## Fix 3: Migrate the fire-and-forget mutation sites — ONE AT A TIME

### Constraint (lessons.md — batch migration = 19 bugs)
Migrate each site individually: edit → `py_compile` is N/A (JS) → eyeball the diff → move on. Do NOT sed-replace across all sites.

### Method
1. Enumerate every mutation site where a UI/DOM success follows `bakerFetch` — **BOTH `.then(...)` chains AND `await` style** (codex-arch fold: the `.then`-only grep misses async/await handlers):
   ```
   grep -nE "bakerFetch\([^)]*method:\s*'(POST|DELETE|PUT|PATCH)'" outputs/static/app.js
   ```
   Then ALSO inspect every `await bakerFetch(...POST/DELETE/PUT/PATCH...)` whose next lines mutate the DOM without checking `resp.ok` — confirmed async/await offenders: `resolveAlert` (app.js:3538-3540), `dismissAlert` (~3546-3548), `confirmBrowserAction` (~3626-3628), `cancelBrowserAction` (~3639-3641). For each site, success-UI must move behind the confirmed-ok (+ no-JSON-error) gate. ~21 user-action buttons qualify; the ~70 total includes form-saves that already handle errors — scope to **action buttons** (complete/dismiss/done/resolve/snooze/cancel/postpone/promote/add-to-promised).
   **PRESERVE, do not break:** `_triagePromoteCritical` / `_triageAddToPromised` / `_criticalQuickAdd` already parse `d.error` (app.js:2970-2974). Migrating them to the JSON-error-aware `_mutate` must KEEP that behavior (the `data.error` path), not regress it to HTTP-only.
2. Convert each from:
   ```javascript
   bakerFetch(url, { method: 'POST' }).then(function() { card.remove(); });
   ```
   to:
   ```javascript
   _mutate(url, { method: 'POST' }, function() { card.remove(); });
   ```
   The optimistic UI moves INTO the `onOk` callback so it only runs on a confirmed-ok response.
3. Seed list (verified — start here, then grep for the rest): `_completePriority` (~845), `_triageDismiss` (~2855), `_criticalDone` (~3154, ~3406), deadline Dismiss + +1 Week (~6109), `resolveAlert` (~3536), `dismissAlert` (~3544), `cancelBrowserAction` (~3637).

### Key Constraints
- Preserve each handler's existing success behavior exactly (same DOM updates, same toast text) — only gate it behind confirmed-ok + add the error path.
- Where a handler reloads a tab on success (e.g. `loadDeadlinesTab()`), put that in `onOk`.
- Bump the `app.js` `?v=N` cache-bust in `index.html` (iOS PWA).

### Verification
- DevTools: set network offline, click a Dismiss/Done button → card stays + red "Action failed" toast; no silent no-op.
- Force a 500 (or point at a bad id) → same: card stays, error toast, item still present on reload.
- Online happy path → card removes / strikes through exactly as before.

## Files Modified
- `outputs/static/app.js` — `_showToast` (type arg), new `_mutate` helper, ~21 mutation-site migrations.
- `outputs/static/index.html` — `?v=N` cache-bust bump.

## Do NOT Touch
- The mutation backend endpoints (they work; this is a frontend reliability fix).
- Form-save / non-action-button `bakerFetch` calls that already handle errors.
- `bakerFetch` itself.

## Quality Checkpoints
1. Failed-mutation behavior verified on desktop AND iPhone PWA (offline + 500 cases).
2. Happy-path optimistic UI unchanged for every migrated button.
3. No remaining mutation site (`.then` OR `await`) where UI success follows `bakerFetch` without a confirmed-ok + no-JSON-error gate, across all action buttons.
4. 200-with-JSON-error case verified: force a `{"error": ...}` 200 (e.g. promote at max-5) → red toast with the server message, NO optimistic UI applied (codex-arch-required test case).
5. No console errors after migration.

## Gate plan
- **G0** — codex-arch PASS-WITH-CHANGES (#1608, 2026-06-02); 3 folds applied to this v2: JSON-error success gate, async/await enumeration, body-bearing endpoint contract. Re-confirm the delta with codex-arch before dispatch.
- **G1** — AH1 fold/static review.
- **G2** — `/security-review` NOT required (no auth/data-model change; frontend error-handling only). Confirm at G0.
- **G3** — AH2 deputy gate, focus on the behavior change (failed mutation no longer false-succeeds).

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST exercise a failed mutation (offline or forced non-2xx) and confirm the card does NOT disappear + a red error toast shows, AND that the success path is unchanged. Code-shape review is necessary but NOT sufficient.
