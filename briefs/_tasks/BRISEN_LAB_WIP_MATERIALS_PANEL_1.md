# BRIEF: BRISEN_LAB_WIP_MATERIALS_PANEL_1 — Cockpit "Work-in-progress materials" panel

## Context
WIP HTML artifacts (e.g. the airport↔Baker loop study) live only in a volatile agent clone's
`outputs/`. Director wants a durable, browsable home in the Brisen Lab cockpit: a left-nav
**"Work in progress"** entry + a **topic dropdown** that lists and opens saved HTMLs. Source of
truth = vault `wiki/_wip/<topic>/` (files arrive via vault git, as today). Director request 2026-06-28.

### Surface contract
- **Surface:** Brisen Lab cockpit (`baker-master.onrender.com`) — left nav + new `/wip` page.
- **Entry point:** left-nav item **"Work in progress"**.
- **Interaction:** topic `<select>` → file list → click renders HTML in an in-cockpit iframe.
- **States:** loading · empty-topic ("no materials yet") · file-render · error (missing/bad path).
- **Auth/visibility:** `?key=` gated (same secret as cockpit); not publicly reachable.
- **Data source:** vault-mirror `wiki/_wip/<topic>/*.{html,md}`; subfolder = topic. First topic: `airport-loop`.
- **Out of scope (v1):** upload/edit/delete, search, metadata beyond name + modified time.

## Estimated time: ~3–4h
## Complexity: Low–Medium
## Prerequisites: none (read-only; no DB, no new deps)
## dispatched_by: cowork-ah1 (set on dispatch) · ship-report → cowork-ah1

---

## Fix/Feature 1: WIP materials browser

### Problem
No cockpit surface exists to browse/open WIP HTMLs. They risk being lost in clone churn.

### Current State (verified in `outputs/dashboard.py`)
- `FileResponse, HTMLResponse, JSONResponse` already imported (line ~29); `StaticFiles` mounted
  at `/static` (~1520). **No missing-import risk** — reuse these.
- HTML-serve pattern in use: `return FileResponse(str(path))` (~4571, 4590) and
  `HTMLResponse(...)` (~7434 `/clerk`).
- Auth: `verify_api_key(x_baker_key: Header)` (~109) for header-gated JSON; `_mcp_verify_key(request)`
  (~1557) accepts `?key=` query param — **use this for the browser-opened page + file serve** so it
  works in a tab/iframe where headers can't be set.
- Vault is cloned/pulled to a local mirror on startup (SOT_OBSIDIAN_1_PHASE_D, ~1401). **Reuse the
  existing vault-mirror path resolver — do NOT hardcode `~/baker-vault`.** Grep for the mirror dir
  variable used by that startup block and the `target_vault_path` usage (~15207) before coding.

### Engineering Craft Gates
- **Diagnose:** N/A — net-new feature, no bug/repro.
- **Prototype:** N/A — standard nav-item + `<select>` + content-pane; no real UI/state uncertainty.
- **TDD/verification:** APPLIES. Public seam = `GET /wip/list` + `GET /wip/file`. Write the
  **path-traversal rejection test FIRST** (vertical), then the happy-path listing test, then implement.

### Implementation
1. **Pre-check (anti-shadow):** `grep -n '"/wip' outputs/dashboard.py` — confirm no existing `/wip*`
   route before adding (FastAPI registers first match).
2. **Helper** `wip_materials.py` (keeps `dashboard.py` lean):
   - `WIP_ROOT = <vault-mirror>/wiki/_wip` (resolved from the existing mirror path var).
   - `list_topics() -> list[str]` — immediate subfolders of `WIP_ROOT` (sorted).
   - `list_files(topic) -> list[dict]` — `.html`/`.md` files in `WIP_ROOT/<topic>/`, each
     `{name, modified}`; bounded (cap 200).
   - `safe_path(topic, name) -> Path|None` — resolve, then assert the resolved real path is inside
     `WIP_ROOT` (`os.path.realpath` + `.startswith`); reject `..`, absolute, symlink-escape,
     non-`.html/.md` extension. Returns None on any violation.
   - All FS access in try/except; return `[]`/None on error (fault-tolerant).
3. **Routes** (`dashboard.py`):
   - `GET /wip` (HTMLResponse, `?key=` via `_mcp_verify_key`) → page: left-nav highlight, a topic
     `<select>` (populated from `list_topics()`), a file list `<ul>`, and a content `<iframe>`.
   - `GET /wip/list?topic=<slug>` (JSONResponse, gated) → `list_files(topic)` with `href`
     = `/wip/file?topic=<slug>&name=<file>&key=<key>`.
   - `GET /wip/file?topic=<slug>&name=<file>` (gated) → `p = safe_path(...)`; if None → 404;
     `.html` → `FileResponse(p, media_type="text/html")`; `.md` → render or serve as text.
4. **Left-nav entry:** add **"Work in progress"** item to the existing nav block (grep the nav
   render to match the existing item pattern); link → `/wip?key=<key>`. Cache-bust any new static
   asset with `?v=N`.

### Key Constraints
- **Path traversal is THE risk.** Serve ONLY real paths inside `WIP_ROOT`; allowlist `.html`/`.md`.
- v1 is **read-only** — no upload/edit/delete. Files land via vault git.
- Same auth as the cockpit; no new public/unauthenticated surface.
- Don't touch unrelated routes or the auth internals.

### Verification
- `GET /wip/list?topic=airport-loop` returns the 2 HTMLs + the log md.
- `GET /wip/file?topic=airport-loop&name=baker-loop-airport-metaphor-v2.html` renders.
- Traversal probes return 404: `name=../../slugs.yml`, `topic=..`, absolute path, `name=x.py`.
- Empty/missing topic → graceful "no materials yet".

---

## Files Modified
- `outputs/dashboard.py` — 3 routes + nav entry (cite route/function names, not line numbers — volatile).
- `wip_materials.py` (new) — listing + `safe_path` guard.

## Do NOT Touch
- `verify_api_key` / `_mcp_verify_key` internals — reuse, don't modify.
- Vault startup-mirror block — read the path var, don't change the clone/pull logic.
- Unrelated cockpit routes.

## Quality Checkpoints
1. No `/wip*` route already exists (grep before add).
2. Path-traversal test written FIRST and passing; all 4 probes 404.
3. Page loads gated (`?key=`); unauth → 401/redirect.
4. Topic dropdown lists `_wip/` subfolders; file click renders in-pane.
5. Mobile: page usable on a phone width (cockpit is a PWA).
6. Post-deploy AC live, then `POST_DEPLOY_AC_VERDICT v1` on bus topic
   `post-deploy-ac/BRISEN_LAB_WIP_MATERIALS_PANEL_1`.

## Gate Plan
- G0 Codex: recommended (path-resolution correctness, cross-vendor).
- G1 static (AH1): yes.
- **G2 /security-review: MANDATORY** — new route serving files from a path = traversal surface.
- G3 Architect: only if the helper grows beyond a thin lister.

## Verification SQL
```sql
-- N/A — feature is filesystem-only (no DB reads/writes).
```
