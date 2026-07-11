# B2 SHIP REPORT — BRISEN_LAB_WIP_MATERIALS_PANEL_1

- **Brief:** `briefs/_tasks/BRISEN_LAB_WIP_MATERIALS_PANEL_1.md`
- **Dispatch:** bus #4504 (from `lead`, `dispatched_by: cowork-ah1`) — ship-report → **cowork-ah1**
- **PR:** #432 — https://github.com/vallen300-bit/baker-master/pull/432
- **Branch:** `b2/brisen-lab-wip-materials-panel-1` off `main` (@ fa9bc67)
- **Commit:** 89b3cc99
- **Date:** 2026-06-28

## What shipped
A read-only cockpit **"Work in progress"** panel: left-nav entry → topic dropdown → file list → in-cockpit iframe render, sourced from the vault mirror's `wiki/_wip/<topic>/` subtree. No DB, no new deps.

## Files (5)
- `wip_materials.py` (new, +178) — `list_topics` / `list_files` / `safe_path`.
- `outputs/dashboard.py` (+166) — `GET /wip`, `GET /wip/list`, `GET /wip/file` (+ `_WIP_PAGE_TEMPLATE`).
- `outputs/static/index.html` — nav item + `viewWip` iframe + app.js cache-bust `v131`→`v132`.
- `outputs/static/app.js` (+13) — `TAB_VIEW_MAP` entry + `switchTab` dispatch + `loadWipTab`.
- `tests/test_wip_materials.py` (new, +244) — 32 tests.

## Done rubric (answered)
1. **Reuse vault-mirror resolver, no hardcode.** `safe_path` reuses `vault_mirror._normalize_and_resolve` (realpath fold + `wiki/` prefix guard); `WIP_ROOT` derives from `vault_mirror.mirror_path()`. No `~/baker-vault` literal.
2. **Path traversal is THE risk — defended in depth.** bare-segment rejection (no `/ \ .. `, dotfiles) → `_normalize_and_resolve` → WIP_ROOT containment (stricter than `wiki/`) → `.html`/`.md` allowlist → existence check. All four brief probes 404; two symlink-escape classes (outside-wiki, inside-wiki-outside-_wip) rejected.
3. **`?key=` gated, not header-only.** All three routes call `_mcp_verify_key`; page renders inside iframe via `?key=`. Unauth → 401.
4. **In-cockpit.** Nav item embeds `/wip?key=` in a `viewWip` iframe; the page self-drives topic→list→file render. The `?key=` choice is exactly the brief's "works in a tab/iframe where headers can't be set."
5. **Anti-shadow.** `grep -n '"/wip' outputs/dashboard.py` clean before add (no first-match shadowing).

## Quality checkpoints
1. ✅ No prior `/wip*` route. 2. ✅ Traversal test first, all probes 404. 3. ✅ Gated; unauth 401. 4. ✅ Dropdown lists `_wip/` subfolders, file click renders in-pane. 5. ✅ Mobile `@media max-width:640px` (list stacks above content, select full-width). 6. ⏳ `POST_DEPLOY_AC_VERDICT v1` after lead deploys → topic `post-deploy-ac/BRISEN_LAB_WIP_MATERIALS_PANEL_1`.

## Ship gate — literal pytest
```
$ python3 -m pytest tests/test_wip_materials.py
======================== 32 passed, 8 warnings in 0.44s ========================
```
Live-flow smoke via TestClient + temp mirror confirmed page/list/file/traversal behaviour end-to-end. `node --check outputs/static/app.js` OK.

## G2 /security-review — MANDATORY, run pre-ship
**PASS — no HIGH/MEDIUM.** Two LOW defense-in-depth, non-blocking:
- Content iframe runs vault HTML same-origin (no sandbox/CSP). Deliberately not sandboxed — WIP studies are interactive HTML needing scripts; no untrusted write path (private-vault git only). Future CSP/sandbox follow-up if an untrusted source is ever added.
- `_mcp_verify_key` `==` vs `compare_digest` — pre-existing, brief says do-NOT-touch that internal.

## Gate plan status
G0 codex (recommended) · G1 static (AH1) · **G2 /security-review ✅ PASS** · G3 architect (only if helper grows — it didn't). Awaiting cowork-ah1 review → merge → deploy → AC.
