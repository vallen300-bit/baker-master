# BRIEF: CLERK_WORKBENCH_3 — Clerk Qwen3 launcher surface (the "button" / Cockpit entry point)

## Context
Phase 1 (`CLERK_WORKBENCH_1`, PR #301) built the headless Qwen3 runtime; Phase 2
(`CLERK_WORKBENCH_2`, PR #304) added the back-end surface:
- `POST /api/clerk/run` (JSON `{task, approval_token?}`, X-Baker-Key) → starts an async session, returns `{session_id, status}`.
- `GET /clerk/edit/<session_id>` → editable workbench (review + Save).
- `POST /api/clerk/save/<session_id>` → writes to Dropbox working folder / approved vault path.
- `GET /api/clerk/session/<session_id>` → status poll. Backed by PG `clerk_sessions`.

**The gap (Director priority 2026-06-06):** there is NO click-surface to *start* a run. Today
the Director must hand-craft a raw `POST /api/clerk/run` with a JSON body and an `X-Baker-Key`
header — there is no page where he types a task and presses a button. Qwen3 Clerk is "live via API";
this phase makes it "live with a button". No runtime/endpoint logic changes — this is the entry point.

### Surface contract
- **New surface:** `GET /clerk` — a self-contained launcher page: a task textarea + a **Run** button.
  On Run: `POST /api/clerk/run` (key from `localStorage`, same pattern as the edit page), then
  redirect the browser to `/clerk/edit/<session_id>`. One uninterrupted Director flow: type task →
  Run → review → Save.
- **AUTH FOLD (G0 deputy-codex #1970, HIGH flow-blocker):** today `GET /clerk/edit/<id>` is
  `Depends(verify_api_key)` (dashboard.py:6884) and `verify_api_key` only reads the `X-Baker-Key`
  HEADER (dashboard.py:109-121). A top-level browser `window.location.assign()` navigation CANNOT
  attach that header → the redirect would 401 on the Director's first click (probe-confirmed). Fold:
  convert `/clerk/edit/<id>` into a browser-openable HTML **shell** that embeds NO session content and
  NO secret, then client-fetches the already-auth-gated `GET /api/clerk/session/<id>` with the
  `X-Baker-Key` from `localStorage` and renders via `textContent`/`value` (XSS-safe). Same no-secret-
  in-markup invariant as the launcher. The session DATA stays protected by the API; only the empty
  shell is public. (`/clerk/edit` shell behavior is therefore IN scope — see Do-NOT-Touch note.)
- **Cockpit entry point:** a visible nav link/button in the existing dashboard sidebar (Operations
  section) that opens `/clerk`. Director never types a URL.
- **Recent sessions (small, optional-but-preferred):** the launcher lists the last ~10 `clerk_sessions`
  (id, truncated task, status, created_at) each linking to its `/clerk/edit/<id>`, so an interrupted
  review is one click to resume. Served by a new bounded `GET /api/clerk/sessions?limit=10`.
- **Auth:** `GET /clerk` is an HTML shell (no secret in markup); every data call carries `X-Baker-Key`.
  The new list endpoint is `Depends(verify_api_key)`.
- **KEY-SOURCE FOLD (G3 codex #1977, HIGH integration gap):** the Clerk shells are standalone inline-JS
  pages, NOT served through `app.js`. The dashboard obtains its key by `fetch('/api/client-config')` →
  `BAKER_CONFIG.apiKey = data.apiKey` (app.js:15-18) — it NEVER writes the key to `localStorage`.
  So a shell that reads only `localStorage` lands with NO key on a normal Director click → Run + Recent
  Sessions are dead. Fix: BOTH `/clerk` and `/clerk/edit` shells must obtain the key the same way the
  dashboard does — `await fetch('/api/client-config')` on load, hold `data.apiKey` in a module var, and
  use it for every `X-Baker-Key` call; keep `localStorage` only as a fallback. Mirror app.js:15-18 exactly.
- **States:** empty (ready for a task) / submitting (button disabled, "Starting…") / error (key missing
  or run rejected — show the message inline, do not redirect).
- **Mobile:** desktop dashboard surface only this phase; cache-bust any new/edited static asset (`?v=N`).

## Estimated time: ~0.5–1 day
## Complexity: Medium
## Task class: cross-layer feature (one HTML route + one bounded read endpoint + Cockpit nav wiring)
## Harness-V2: applies — G0 codex (deputy-codex) design PASS before build; G1/G2/G3 + POST_DEPLOY_AC on ship.

---

## SCOPE — Phase 3

1. **`GET /clerk`** (`outputs/dashboard.py`) — `response_class=HTMLResponse`. Self-contained inline
   HTML/CSS/JS mirroring `_clerk_edit_html` (lines 597-694): same `apiKey()` localStorage reader,
   same light/dark CSS register. A `<textarea id="task">` + a **Run** `<button>`. Run handler:
   `fetch("/api/clerk/run", {method:"POST", headers:{"Content-Type":"application/json","X-Baker-Key":key}, body: JSON.stringify({task})})`
   → on `ok`, read `session_id`, `window.location.assign("/clerk/edit/"+session_id)`; on non-ok, show
   the error text inline and re-enable the button. No secret rendered into the page source.
2. **`GET /api/clerk/sessions`** (`outputs/dashboard.py`) — `Depends(verify_api_key)`; bounded
   `SELECT session_id, task, status, created_at FROM clerk_sessions ORDER BY created_at DESC LIMIT %s`
   (default 10, hard-cap 50); truncate `task` server-side to ~120 chars for the list payload; wrap in
   try/except with `conn.rollback()`; return `{sessions: [...]}`. Reuse the existing PG connection
   helper used by `_clerk_fetch_session` (do NOT open a new pool pattern).
3. **Cockpit nav entry** — add a visible "Clerk" link/button to the dashboard sidebar Operations
   section that opens `/clerk`. The sidebar lives in `outputs/static/index.html` (sidebar-nav).
   **WARNING (G0 deputy-codex #1970):** `#operationsSubList` is wiped on load — `_renderMatterSection`
   does `container.textContent = ''` (app.js:1652) then appends (app.js:1686-1711). A static Clerk
   link placed INSIDE that div is erased. Put the link OUTSIDE the dynamic sub-list (or append it
   after render). It must render without an API round-trip and survive nav collapse/expand. Cache-bust
   `app.js?v=N` at `index.html:579` if app.js changes.
4. **`/clerk/edit/<id>` shell refactor (the AUTH FOLD)** — drop `Depends(verify_api_key)` from the
   `GET /clerk/edit/<id>` HTML route ONLY; rewrite `_clerk_edit_html` (dashboard.py:597-694) so the
   shell embeds NO `draft_content`/`error`/session text server-side. The page client-fetches
   `GET /api/clerk/session/<id>` (stays auth-gated) with the localStorage key and populates the
   textarea/status via `value`/`textContent`. Save flow already client-fetches — unchanged. Unknown id
   surfaces a clean "not found" client-side (the API returns 404). Update the existing edit-endpoint
   tests (tests/test_clerk_workbench_endpoints.py:192,195) to the new shell contract.

## Out of scope / Do NOT touch
- The Qwen3 runtime (`orchestrator/clerk_runtime.py`), the denylist, SSRF guard, escalation — frozen + verified.
- `POST /api/clerk/run`, `/api/clerk/save`, `/clerk/edit`, `/api/clerk/session` request/response logic — reuse as-is.
- The `clerk_sessions` schema — read-only here; no migration. (`GET /api/clerk/sessions` only SELECTs.)
- The Haiku Terminal-picker Clerk — stays the conversational fallback; untouched.
- Render env wiring — already live (paid `qwen/qwen3-coder`); no env change this phase.
- **EXCEPTION (AUTH FOLD):** the `/clerk/edit` shell + `_clerk_edit_html` ARE now in scope (scope item 4)
  — convert to a no-secret browser-openable shell. The `/api/clerk/run|save|session` request/response
  logic stays reuse-only; only the `/clerk/edit` HTML route's auth + content-embedding changes.

## Acceptance Criteria
- **AC1** `GET /clerk` returns the launcher HTML; page source contains NO API key (key only read from `localStorage` at runtime).
- **AC2** Typing a task + Run does a real `POST /api/clerk/run` and redirects to `/clerk/edit/<session_id>` for that session.
- **AC3** Run with no/blank task is rejected client-side (button no-op + inline hint) AND the endpoint's existing 400-on-empty still holds.
- **AC4** Missing/invalid `X-Baker-Key` → the Run shows an inline auth error, does NOT redirect, does NOT 500.
- **AC5** `GET /api/clerk/sessions` returns the last ≤10 sessions, bounded + rollback-safe; auth-gated (no key → 401/403); unknown/empty table → `{sessions: []}`, not an error.
- **AC6** A "Clerk" entry is visible in the Cockpit sidebar and opens `/clerk` in one click.
- **AC7** The list renders task text via `createTextNode`/escaping (no `innerHTML` of session task) — XSS-safe, same invariant as the edit page.
- **AC8 (auth fold)** `GET /clerk/edit/<id>` opens in a browser with NO header (the redirect works); the shell source contains NO session content/secret; the doc loads via client `fetch /api/clerk/session/<id>` which STILL returns 401 without a key. Updated edit tests pass.
- **AC9 (key-source fold, G3 #1977)** With EMPTY `localStorage`, opening `/clerk` (or clicking the Cockpit Clerk link) still authenticates: the shell `fetch('/api/client-config')`, uses `data.apiKey`, and Run + Recent Sessions work. Regression: a test proves the launcher path obtains the key via `/api/client-config` (not localStorage-only). Both `/clerk` and `/clerk/edit` covered.
- **POST_DEPLOY_AC** (live prod, paid Qwen3): open the Cockpit → click Clerk → type a benign task → Run → land on `/clerk/edit` → session reaches `ready` → Save to Dropbox working folder. Full button→doc→save round-trip, no raw API call.

## Gate plan (Harness V2)
G0 codex design (deputy-codex posts design to `lead`; Medium, but it's a Director-facing UI surface +
a new read endpoint) → build → G1 lead pytest (literal) → G2 `/security-review` (auth on the new
endpoint, launcher XSS / no-secret-in-markup, bounded query) → G3 codex → AH1 merge → POST_DEPLOY_AC.

## Context Contract (for deputy-codex)
- Mirror `_clerk_edit_html` for the launcher: same `apiKey()` localStorage reader, same CSS register, same X-Baker-Key fetch pattern. Do NOT invent a new auth scheme.
- The launcher is a thin shell — it only POSTs `/api/clerk/run` then redirects to the existing edit page. All run/poll/save logic already exists; reuse it.
- `GET /api/clerk/sessions` reuses the existing PG helper + must be bounded (LIMIT, default 10 / cap 50) + try/except + `conn.rollback()`. No unbounded SELECT.
- No secret in any served HTML. XSS-safe rendering of any session/task text (createTextNode / escape).
- No migration, no runtime change, no Render env change — this is the entry point only.
- Cache-bust any edited static asset (`?v=N`) — iOS/Cockpit cache requirement.

## Files Modified (expected)
- `outputs/dashboard.py` — `GET /clerk` launcher route + `GET /api/clerk/sessions` list endpoint + `/clerk/edit` shell auth-fold (drop header-dep on the HTML route, `_clerk_edit_html` no longer embeds session content).
- `outputs/static/index.html` and/or `outputs/static/app.js` — Cockpit sidebar "Clerk" entry, placed OUTSIDE `#operationsSubList` (+ `?v=N` bump).
- `tests/test_clerk_workbench_endpoints.py` — update edit-shell tests (:192,:195) to the no-auth-on-shell / client-fetch contract.

## Do NOT Touch
- `orchestrator/clerk_runtime.py` — runtime/denylist/SSRF/escalation frozen.
- `/api/clerk/run` + `/api/clerk/save` + `/api/clerk/session` request/response logic — reuse, don't modify (these stay auth-gated). Only the `/clerk/edit` HTML shell route changes (scope item 4).
- `clerk_sessions` migration / schema — read-only this phase.
