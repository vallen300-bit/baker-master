# BRIEF: LAB_UNIFY_UI_THEME_TOGGLE_1 — dark/light mode toggle, top right of /v2 shell

```yaml
brief_id: LAB_UNIFY_UI_THEME_TOGGLE_1
dispatched_by: lead
assigned_to: b2
repo: brisen-lab (worktree ~/bm-b2/brisen-lab; branch b2/lab-unify-theme-toggle-1 from origin/main)
status: PENDING
```

## Context

Director request 2026-07-21 morning (verbatim): "can we add dark /light mode
button in the top right ?" — on the new unified Lab (`/v2`, all 3 build phases
live @4e5f27a). Dark stays the DEFAULT (ratified cockpit register); light is
opt-in. Scope: shell + the three /v2 sub-pages (loops · skills · settings-logs).
The embedded cockpit (AGENTS iframe) keeps its own dark register — it is a
separate app synced from the laptop controller; out of scope (noted to
Director as a later candidate).

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director clicks a theme button top right of the Lab shell to switch dark ↔ light; choice persists across visits and applies to the sub-pages.
2. **Backend route:** NONE new — pure static-asset change. Existing verified routes serve everything: `GET /v2`, `/v2/loops`, `/v2/skills`, `/v2/settings-logs` (all live 200 anonymous 2026-07-21).
3. **Endpoint contract:** no fetches added. Theme state = `localStorage` key `labTheme` (`"dark"` default / `"light"`), same-origin shared between shell and iframed sub-pages.
4. **State location:** browser localStorage only — zero server state, zero writes.
5. **UI repo (= state repo):** brisen-lab, `static/v2/*`.
6. **Director surface preference:** Director specified the surface himself — button top right of the new Lab.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `/v2` in a browser, click the toggle both ways, confirm shell AND all three sub-page panes re-theme live (open each pane), reload to confirm persistence, and open one sub-page standalone to confirm it applies the stored theme. Code-shape review is necessary but NOT sufficient.

## Estimated time: ~2.5h
## Complexity: Low-Medium
## Prerequisites: none

## Baker Agent Vault Rails
Relevant: build-command-center, verification-surfaces, bus-and-lanes.
Ignored: memory-and-lessons, loop-runner — static theming, no DB.

## Harness V2

- **Context Contract:** read before building: this brief (whole), `static/v2/shell.css` (`:root` token block — the 13 dark tokens), `static/v2/index.html` (shell frame), `static/v2/shell.js`, the style blocks of `skills.html`, `loops.html`, `settings-logs.html` (each page's own tokens). Nothing else required.
- **Task class:** small-fix-production / medium-feature boundary (production, brisen-lab).
- **Done rubric:** terminal = Merged + Deployed + post-deploy AC passed + writeback resolved. Post-deploy AC (lead): live toggle works both ways, persists, sub-pages follow, cockpit iframe unaffected, dark default byte-equal experience for a first-time visitor. Writeback: registry status HTML note by lead.
- **Gate plan:** b2 self-test (pytest + local uvicorn + browser both themes) → push branch → blocking codex gate on pushed SHA (§7 binding) → lead merge → Render auto-deploy → lead POST_DEPLOY_AC_VERDICT on bus.

---

## Feature 1: theme toggle + light palette

### Problem
The new Lab is dark-only. Director wants a dark/light switch, top right.

### Current State
- `static/v2/shell.css` `:root` defines 13 dark tokens (`--bg #0d1117` … `--shadow`).
- Sub-pages carry their own token blocks in the same register.
- No top-right control exists; shell is sidebar + main panes.

### Engineering Craft Gates
- Diagnose: N/A — new feature.
- Prototype: N/A — standard CSS-variable theming; palette fixed below.
- TDD/verification: applies — extend the existing v2 route tests (they EXECUTE without DSN since @6830845): assert served shell HTML contains the toggle button id and each sub-page HTML contains the theme-bootstrap snippet marker.

### Implementation

1. **Theming mechanism (all four pages, identical):**
   - Keep current dark values in `:root` (dark remains default — NO visual change for a first-time visitor).
   - Add a `html[data-theme="light"]` override block redefining the SAME custom-property names. Light palette (lead-fixed, muted McKinsey-adjacent, keep accent blue):
```css
html[data-theme="light"] {
  --bg: #f6f7f9;
  --bg-subtle: #eef0f3;
  --panel: #ffffff;
  --panel-raised: #ffffff;
  --border: rgba(60, 72, 88, .28);
  --border-soft: rgba(60, 72, 88, .14);
  --text: #1c2733;
  --muted: #5a6a7a;
  --muted-strong: #3d4c5c;
  --accent: #2f6feb;
  --st-amber: #9a6700;
  --st-red: #cf222e;
  --shadow: 0 1px 3px rgba(27,35,45,.12), 0 8px 24px rgba(27,35,45,.08);
}
```
     Sub-pages: apply the same override block to each page's own token names (map 1:1 to that page's dark tokens; where a page has extra tokens — e.g. chip colors — derive sensible light values, keep status semantics: green stays green, red stays red, amber darkens for contrast on white).
   - Audit each page for hardcoded dark colors OUTSIDE the token block (grep hex values); migrate any you find to tokens rather than leaving light-mode artifacts. Report the count in the ship report.
2. **Bootstrap snippet — inline `<head>` script, ALL FOUR pages, before CSS paint** (prevents flash-of-wrong-theme):
```html
<script>try{if(localStorage.getItem("labTheme")==="light")document.documentElement.setAttribute("data-theme","light")}catch(e){}</script>
```
3. **Toggle button (shell only):** fixed top-right of the shell main area (`position: fixed; top: 10px; right: 14px; z-index` above panes), cockpit-register styling, accessible: `<button id="theme-toggle" type="button" aria-label="Switch color theme">`. Label shows the TARGET mode (`LIGHT` when dark active, `DARK` when light active) — or a sun/moon glyph pair with the same aria semantics; your call, note it in the ship report.
4. **Toggle behavior (`shell.js`):** on click — flip `data-theme` on `documentElement`, write `localStorage.labTheme` in try/catch, and re-broadcast to mounted iframes. Sub-pages: listen for `window.addEventListener("storage", ...)` and apply theme changes live (same-origin iframes receive storage events from the shell's write; the shell tab itself gets no storage event — apply directly). No postMessage needed.
5. **Standalone-first:** each sub-page opened directly applies the stored theme via its bootstrap snippet (no toggle button on sub-pages — the shell hosts the control).
6. **Cache-bust:** bump every static asset you touch (`shell.css`/`shell.js` now `?v=3` → `?v=4`; sub-page assets bump their own `?v=`).

### Key Constraints
- Cockpit iframe (AGENTS pane) untouched — no theme propagation into `/cockpit/`.
- Old Lab pages, `static/loops/*` boards, cockpit static, controller, all existing handlers: ZERO edits. (The two absorbed loop BOARDS keep their own dark art direction — only the /v2 loops INDEX page re-themes.)
- Dark default: a visitor with no localStorage sees today's exact experience.
- No server round-trips, no cookies, no new endpoints.

### Verification
1. `pytest` — extended route tests green (no-DSN run must EXECUTE them); suite no regressions.
2. Local uvicorn browser: toggle both ways in shell → shell + all three sub-page panes re-theme live; reload persists; standalone sub-page follows stored theme; private window (no storage) = dark default; cockpit pane visually unchanged.
3. Contrast spot-check in light mode: body text, muted text, status chips legible on white/near-white panels.
4. `git diff --stat` vs origin/main: only the four /v2 pages' HTML/CSS/JS + tests.

## Files Modified
- `static/v2/shell.css` + `static/v2/index.html` + `static/v2/shell.js` (toggle + palette + bootstrap) · `static/v2/skills.html|.js`, `static/v2/loops.html|.js`, `static/v2/settings-logs.html|.js` (palette + bootstrap + live-apply as needed) · existing v2 route tests extended

## Do NOT Touch
- `static/loops/*.html` (absorbed boards — own art direction) · old Lab static · cockpit/ · controller · app.py (no route changes needed) · baker-vault.

## Quality Checkpoints
1. No flash-of-wrong-theme on any page (bootstrap snippet before CSS).
2. Zero hardcoded-dark leftovers in light mode (grep audit reported).
3. First-time visitor experience byte-identical dark.
4. Ship report to lead on bus (`lab-unify/theme-toggle`) with branch + HEAD SHA; codex gate on pushed SHA.

## Verification SQL
N/A — browser-only state.
