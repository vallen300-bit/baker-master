---
brief: TEMPLATES_GALLERY_LAB_INSTALL_1
target_repo: brisen-lab
to: b4
from: lead
authored: 2026-05-27
estimated_time: 30-45min
complexity: Low
priority: tier-a
reply_to: lead
anchor: bus #1253 (hag-desk dispatch, Director-ratified 2026-05-27)
parallel_brief: TEMPLATES_GALLERY_BAKER_INSTALL_1 (b2, baker-master — runs in parallel; no file overlap)
---

# BRIEF: TEMPLATES_GALLERY_LAB_INSTALL_1 — Add Templates Gallery as third nav-btn in Brisen Lab sidebar

## Context
Director ratified 2026-05-27 (bus #1253). Director explicit on placement 2026-05-27 chat: *"We have Production & Lab, then below we have Business. So it has to go below Business link. 3rd from the left top in the left side bar."*

This brief adds a third Templates Gallery item to the Brisen Lab left sidebar, positioned directly below the existing "Business" button. The item opens `https://brisen-docs.onrender.com/templates/` in a new tab — it is an external link, not an in-app view switcher.

Companion brief running in parallel: `TEMPLATES_GALLERY_BAKER_INSTALL_1` (b2, baker-master) — installs the gallery page itself + the same external link on the Baker dashboard. No file overlap.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Open the Templates Gallery from the Brisen Lab left sidebar (new tab).
2. **Backend route:** `GET https://brisen-docs.onrender.com/templates/` — external static-site URL served by the brisen-docs Render service (deployed from `baker-master/docs-site/templates/` by the parallel brief `TEMPLATES_GALLERY_BAKER_INSTALL_1`). No brisen-lab backend route is touched. The link is a plain external anchor, not an API call.
3. **Endpoint contract:** `GET` with no query params, no body, no auth. Expected response: `200 OK` with `Content-Type: text/html`.
4. **State location:** external — filesystem in `baker-master/docs-site/templates/index.html`, served by the brisen-docs Render static-site service. No brisen-lab Postgres state, no bus events, no in-memory store touched by this brief.
5. **UI repo (= state repo):** the link host repo is `brisen-lab` (where the new anchor lives, in `static/index.html`). The link target repo is `baker-master` (where the gallery HTML lives). Cross-repo by design: Lab is the operator surface, brisen-docs is the document host.
6. **Director surface preference:** asked + ratified 2026-05-27 (bus #1253 + Director chat directive same day: *"3rd from the left top in the left side bar"*) — chose web (Lab left-nav external link opening new tab) because the gallery is a static documents directory hosted on brisen-docs; Lab serves as a launcher, not a renderer.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `https://brisen-docs.onrender.com/templates/` in a browser via the newly-added Lab sidebar anchor and confirm a `200 OK` response with the gallery rendering. Code-shape review (XSS-safe anchor, valid HTML, CSS specificity) is necessary but NOT sufficient — the click-to-new-tab behavior, the absence of in-app view-switch on click, and the iPhone PWA cache-bust must all be verified on a real browser session.

## Estimated time: 30-45min
## Complexity: Low
## Prerequisites: brief `TEMPLATES_GALLERY_BAKER_INSTALL_1` ships the gallery page at the URL. Until that lands, the Lab link target returns 404. The Lab brief itself can ship in parallel (the link is correct; the page lands when the companion deploys).

---

## Feature 1: Add the third nav item

### Problem
Lab sidebar today has two buttons (Production & Lab, Business) — both internal view-switchers. There is no slot for an external Templates Gallery link.

### Current State
`static/index.html` lines 16-22:
```html
<div class="layout">
    <nav class="left-nav">
      <button class="nav-btn" data-view="production" id="nav-production">Production &amp; Lab</button>
      <button class="nav-btn" data-view="business" id="nav-business">Business</button>
      <div class="nav-footer">
        <span id="freeze-indicator" class="freeze-ok" title="BRISEN_LAB_V2_ENABLED">v2 live</span>
      </div>
    </nav>
```
The two existing `nav-btn` elements are bound by a click-handler in `static/app.js` that switches `state.activeView`. Existing handler selector must be verified — see Implementation step 3.

`static/index.html` line 7: stylesheet currently at `?v=11` — bump on cache-bust.

### Implementation

**Step 1 — Add the new element**

Insert immediately AFTER the `nav-business` button, BEFORE `<div class="nav-footer">`:
```html
<a class="nav-btn nav-btn-external" href="https://brisen-docs.onrender.com/templates/" target="_blank" rel="noopener noreferrer" id="nav-templates">Templates Gallery ↗</a>
```
- `<a>` (not `<button>`) for semantic external navigation.
- `nav-btn` class inherits base styling.
- `nav-btn-external` is a new modifier class — defined in step 2.
- The `↗` glyph signals external new-tab open. Mirror the `header-link` glyph pattern from line 12 (`Baker Master ↗`).

**Step 2 — Define the CSS modifier**

Inspect existing `.nav-btn` rules in `static/styles.css` first:
```bash
grep -n "\.nav-btn" static/styles.css
```
Append a new block (or merge near existing `.nav-btn` rules):
```css
.nav-btn-external {
    text-decoration: none;
    display: block;
    /* No active-view state for external link. */
}
```
If the existing `.nav-btn` selector is element-specific (e.g. `button.nav-btn { ... }`), redefine the relevant base rules on `.nav-btn` directly so the anchor inherits them. The goal: external link visually matches the two existing buttons (font, padding, hover) but never carries the "active" highlight applied to the current view.

The `:hover` behavior should match — verify by visual inspection in the deployed preview.

**Step 3 — Tighten the view-switcher selector**

In `static/app.js`, find the click-handler that binds on `.nav-btn`. Search for `nav-btn` and `data-view`. If the selector is bare `.nav-btn`, change it to `.nav-btn[data-view]` so the new anchor (no `data-view` attribute) is excluded from view-switching logic.

If the existing handler already uses `.nav-btn[data-view]`, no JS change is required.

**Step 4 — Cache-bust**

In `static/index.html` line 7, bump:
```html
<link rel="stylesheet" href="/static/styles.css?v=11">
```
to:
```html
<link rel="stylesheet" href="/static/styles.css?v=12">
```
Required for iOS PWA cache invalidation per Lab convention.

### Key Constraints
- Do NOT add `data-view` to the new anchor — that would falsely route it through the view-switcher.
- Do NOT bind any JS click-handler to `#nav-templates` — native anchor `target="_blank"` handles open-in-new-tab.
- Do NOT touch the `Production & Lab` or `Business` button markup or handlers — they stay exactly as they are.

### Verification
- Render preview → three items visible in left nav (Production & Lab / Business / Templates Gallery ↗).
- Templates Gallery has the external-link glyph and no active highlight.
- Click opens new tab to `https://brisen-docs.onrender.com/templates/`.
- Click Production & Lab / Business → in-app view still switches as before (no regression on existing handlers).
- iPhone PWA force-refresh: new button appears (cache-bust verified).
- Chrome console: no errors on page load or click.

---

## Files Modified
- `static/index.html` — one new `<a>` block in left-nav; bump `?v=11` to `?v=12` on stylesheet link.
- `static/styles.css` — add `.nav-btn-external` modifier (or expand `.nav-btn` selector specificity).
- `static/app.js` — ONLY if the view-switcher selector needs tightening to `.nav-btn[data-view]`.

## Do NOT Touch
- `bus.py`, `app.py`, `db.py` — pure UI change, no server-side work.
- The existing `#nav-production` / `#nav-business` button handlers — they stay exactly as they are.
- The matter cards or business view — orthogonal to this brief.
- The SSE wiring or wake-state logic — orthogonal.

## Quality Checkpoints
1. Three nav items render in correct order (Production & Lab / Business / Templates Gallery ↗).
2. External link opens new tab; never switches the in-app view.
3. Existing nav-btn clicks still flip view (regression check).
4. CSS hover state on the new anchor visually matches existing buttons.
5. Cache-bust `?v=` bumped.
6. No JS console errors on page load, click, or view-switch.
7. iPhone PWA force-refresh shows the new button.

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST load `https://brisen-docs.onrender.com/templates/` via the newly-added Lab sidebar anchor on the deployed Render preview and confirm `200 OK` with the gallery rendering. Code-shape review (XSS-safe anchor, valid HTML, CSS specificity) is necessary but NOT sufficient — verify click-to-new-tab behavior, absence of in-app view-switch on click, and iPhone PWA cache-bust on a real browser session.

## Ship-gate
- Literal Chrome MCP smoke against the deployed Render preview URL after merge — confirm button visible + click behavior correct. Do NOT ship "by inspection".
- No SSE/state regression — verify Production & Lab card flips still work after the change.

## Reply target
Bus-post `lead` on ship with PR # + merge SHA + Render deploy URL probe result. Cross-reference companion brief `TEMPLATES_GALLERY_BAKER_INSTALL_1` so the two ships can be paired in the hag-desk ack reply.
