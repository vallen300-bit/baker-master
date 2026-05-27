---
brief: TEMPLATES_GALLERY_BAKER_INSTALL_1
target_repo: baker-master
to: b2
from: lead
authored: 2026-05-27
estimated_time: 1-2h
complexity: Low
priority: tier-a
reply_to: lead
anchor: bus #1253 (hag-desk dispatch, Director-ratified 2026-05-27)
staged_html: /Users/dimitry/baker-vault/_ops/agents/hagenauer-desk/staging/templates-gallery-index.html
---

# BRIEF: TEMPLATES_GALLERY_BAKER_INSTALL_1 — Install Templates Gallery on Baker dashboard + brisen-docs

## Context
Hag-desk authored a 5-card visual templates gallery in canonical `mckinsey-report-html` register (cream + navy). Director ratified placement 2026-05-27 (bus #1253). This brief installs the page on `brisen-docs.onrender.com/templates/` + adds a left-sidebar link between Documents and Dossiers on the Baker dashboard opening the gallery in a new tab.

Anchor staging HTML: `/Users/dimitry/baker-vault/_ops/agents/hagenauer-desk/staging/templates-gallery-index.html` (218 lines, self-contained, no external assets).

Companion brief running in parallel: `TEMPLATES_GALLERY_LAB_INSTALL_1` (b4, brisen-lab) — installs the same external link on the Lab dashboard. No file overlap.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Open the Templates Gallery from the Baker dashboard left sidebar.
2. **Backend route:** `GET https://brisen-docs.onrender.com/templates/` — served by the brisen-docs Render static-site service from `baker-master/docs-site/templates/index.html`. No FastAPI handler in `outputs/dashboard.py`; the link is a plain external anchor, not an API call.
3. **Endpoint contract:** `GET` with no query params, no body, no auth. Expected response: `200 OK` with `Content-Type: text/html`, serving the static HTML file as-is.
4. **State location:** filesystem — `docs-site/templates/index.html` in baker-master repo (deployed to brisen-docs.onrender.com). No Postgres state, no bus events, no in-memory store.
5. **UI repo (= state repo):** `baker-master` — surface 1: gallery page at `docs-site/templates/index.html` (rendered by brisen-docs static site); surface 2: link entry in `outputs/static/index.html` (rendered by Baker dashboard).
6. **Director surface preference:** asked + ratified 2026-05-27 (bus #1253 + Director chat ratification same day) — chose web (Baker dashboard nav + brisen-docs static page) because the gallery is a directory of HTML/Word artifacts that lives most naturally as a static web page; Slack rejected as surface for ratifiable / Director-facing items 2026-05-19.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load the URL `https://brisen-docs.onrender.com/templates/` after Render auto-deploy and confirm a `200 OK` response with the gallery rendering (5 cards, cream/navy register). Code-shape review (XSS-safe anchor, valid JSON) is necessary but NOT sufficient — the brisen-docs deploy path and external URL must be verified live.

## Estimated time: 1-2h
## Complexity: Low
## Prerequisites: none (b2 baker-master mailbox is COMPLETE-flipped from PR #267)

---

## Feature 1: Drop the gallery page

### Problem
Director needs a visual templates gallery at `brisen-docs.onrender.com/templates/`. Today the path returns 404.

### Current State
- Render auto-deploys static content from `baker-master/docs-site/` to `brisen-docs.onrender.com` (separate Render static-site service; no config-as-code in repo).
- `docs-site/` already hosts ORIGINATION, ARCHITECTURE, AO, MO VIENNA, CORINTHIA, NVIDIA, AIOLA, K6S, RESEARCH, STRATEGY folders — folder-per-vertical pattern.
- No `docs-site/templates/` directory yet (`ls docs-site/templates` returns `No such file or directory`).

### Implementation
```bash
mkdir -p docs-site/templates docs-site/templates/samples
cp /Users/dimitry/baker-vault/_ops/agents/hagenauer-desk/staging/templates-gallery-index.html \
   docs-site/templates/index.html
```
Verify local render: `open docs-site/templates/index.html` — should show cream-background gallery with 5 cards (T1, T2, T4 in "Director-facing — internal reports" group; T3, T5 in "Decision-shaped — memos and proposals" group).

### Key Constraints
- Do NOT alter the staged HTML during copy. The CSS is locked to `mckinsey-report-html` register variables; any change drifts from canonical.
- The HTML is self-contained — no css/js imports — so no asset-tree to clone.

### Verification
- File exists at `docs-site/templates/index.html`.
- `head -1 docs-site/templates/index.html` returns `<!DOCTYPE html>`.
- `wc -l docs-site/templates/index.html` returns ~218.

---

## Feature 2: Stub the Sample/Blank target pages

### Problem
The staged HTML links to `/templates/samples/t1-per-line-claim-report.html`, `t1-blank-template.html`, `t2-cross-case-audit.html`, `t2-blank-template.html`, `t3-strategic-memo.html`, `t3-blank-template.html`, `t4-matter-evidence.html`, `t4-blank-template.html`, plus `.docx` files for T5. Without these files the Sample/Blank anchors 404.

### Current State
None of these paths exist on disk.

### Implementation
Grep the staged HTML for `samples/` to enumerate the exact href list:
```bash
grep -oE 'samples/[a-z0-9._-]+' /Users/dimitry/baker-vault/_ops/agents/hagenauer-desk/staging/templates-gallery-index.html | sort -u
```
For each `.html` path, create a placeholder stub. Skip the `.docx` files (binary — hag-desk lands them in a follow-up brief).

Placeholder content for each stub:
```html
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Sample placeholder</title></head>
<body style="font-family:Helvetica,Arial,sans-serif;padding:48px;color:#1a1a1a;background:#fafaf7;">
<h1 style="color:#1a3a52;margin:0 0 8px;">Sample placeholder</h1>
<p style="color:#6a6a6a;font-size:14px;">Canonical sample lands in next brief. <a href="/templates/" style="color:#1a3a52;">Back to Templates Gallery</a>.</p>
</body></html>
```

### Key Constraints
- All stubs share identical content — they are temporary, not final samples.
- Do not rename any path. The staged HTML's hrefs are the source of truth.

### Verification
- For each href in the grep output, `test -f docs-site/templates/<path>` returns true.

---

## Feature 3: Register in both manifests

### Problem
`docs-site/index.json` (used by brisen-docs landing page) and `outputs/static/presentations.json` (used by Baker dashboard "Presentations" tab) must list the new gallery so it appears in both directory listings.

### Current State
- `docs-site/index.json`: top-level `{"version":1, "updated_at":"YYYY-MM-DD", "folders":[...]}` — first folder is "ORIGINATION".
- `outputs/static/presentations.json`: same shape (mirror of docs-site/index.json with slight divergence — index.json has STRATEGY and RESEARCH, presentations.json has MO VIENNA instead).

### Implementation
Insert a new folder block at the TOP of the `folders` array in BOTH files (above "ORIGINATION"):
```json
{
  "name": "TEMPLATES",
  "slug": "templates",
  "presentations": [
    {
      "title": "★ Templates Gallery — pick by sight",
      "file": "templates/index.html",
      "created": "2026-05-27",
      "matter": "baker",
      "live": true
    }
  ]
}
```
Bump `"updated_at": "2026-05-27"` in both files.

### Key Constraints
- Do NOT reorder existing folders.
- Do NOT touch any other field. Only add the new block and bump updated_at.
- Both JSON files must parse cleanly. JSON does not allow trailing commas.

### Verification
```bash
python3 -c "import json; print(json.load(open('docs-site/index.json'))['folders'][0]['name'])"
# expected: TEMPLATES
python3 -c "import json; print(json.load(open('outputs/static/presentations.json'))['folders'][0]['name'])"
# expected: TEMPLATES
```

---

## Feature 4: Baker dashboard left-nav link

### Problem
Director wants a "Templates Gallery" link in the Baker dashboard left sidebar, positioned between Documents and Dossiers, opening the gallery in a new tab.

### Current State
`outputs/static/index.html` lines 110-117:
```html
<div class="nav-item" data-tab="documents">
    <span class="nav-label">Documents</span>
    <span class="nav-count" id="docsCount"></span>
</div>
<div class="nav-item" data-tab="dossiers">
    <span class="nav-label">Dossiers</span>
    <span class="nav-count" id="dossiersCount"></span>
</div>
```
All existing nav-items use `<div class="nav-item" data-tab="...">` — they trigger in-app tab switches via `switchTab(...)` in `app.js`. There is no existing external-link pattern in this nav.

### Implementation
Insert immediately AFTER the `data-tab="documents"` block, BEFORE the `data-tab="dossiers"` block:
```html
<a class="nav-item nav-item-external" href="https://brisen-docs.onrender.com/templates/" target="_blank" rel="noopener noreferrer">
    <span class="nav-label">Templates Gallery</span>
</a>
```
- Use `<a>` (semantic external link), not `<div>` with onclick.
- `nav-item` class inherits base styling.
- `nav-item-external` is a new modifier class — add a CSS rule in `outputs/static/styles.css` (locate via `grep -n "\.nav-item" outputs/static/styles.css`).

Inspect first: if `.nav-item` styles use element-agnostic selectors (just class), the new `<a>` inherits cleanly. If any rule depends on `div.nav-item`, add an explicit `.nav-item-external` rule with the equivalent display/padding/cursor.

The `nav-item-external` modifier should:
- Remove default anchor underline (`text-decoration: none`).
- Inherit text color from the nav (not default blue).
- Match the cursor + hover of existing `.nav-item` entries.

### Key Constraints
- Do NOT register the gallery in `switchTab()` or any `data-tab` handler — this is an external link, not an in-app view.
- Do NOT change the `data-tab="presentations"` block — Presentations stays an in-app tab.

### Verification
- Local: `python outputs/dashboard.py` → open `http://localhost:8080/` → confirm Templates Gallery appears in the exact slot between Documents and Dossiers.
- Click opens new tab to `https://brisen-docs.onrender.com/templates/`.
- Visual: anchor matches the surrounding nav-items (font, padding, hover).
- No JS console errors.

---

## Files Modified
- `docs-site/templates/index.html` (NEW)
- `docs-site/templates/samples/*.html` (NEW — ~8 placeholder stubs)
- `docs-site/index.json` (add TEMPLATES folder block at top + bump updated_at)
- `outputs/static/presentations.json` (same block + bump)
- `outputs/static/index.html` (one new `<a>` block in nav)
- `outputs/static/styles.css` (only if `.nav-item` rules need anchor support; bump `?v=` query string if changed)

## Do NOT Touch
- `outputs/dashboard.py` — no Python changes required.
- `outputs/static/app.js` — no JS changes. Native anchor `target="_blank"` handles new-tab open. Do NOT route through `switchTab()`.
- The staged HTML at `~/baker-vault/_ops/agents/hagenauer-desk/staging/templates-gallery-index.html` — that is the canonical source; copy only, never edit in-place.
- Folder ordering inside both manifests — only the new TEMPLATES block is added at the top.

## Quality Checkpoints
1. Both JSON manifests parse cleanly via `python3 -c "import json; json.load(open(...))"`.
2. Baker dashboard nav shows "Templates Gallery" between Documents and Dossiers.
3. Click opens new tab (not in-app).
4. `https://brisen-docs.onrender.com/templates/` returns 200 after Render auto-deploy.
5. Gallery page renders cream/navy register, 5 cards, no console errors.
6. Sample/Blank anchors inside the gallery resolve to placeholder stubs (no 404s).
7. `wc -l docs-site/templates/index.html` ≈ 218 (unchanged from staged).

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST load `https://brisen-docs.onrender.com/templates/` after Render auto-deploy and confirm a `200 OK` response with the gallery rendering. Code-shape review (XSS-safe anchor, valid JSON, manifest parse-clean) is necessary but NOT sufficient — the deploy path and external URL must be verified live.

## Cache-bust
If any css/js is edited as part of `.nav-item-external` styling, bump `?v=N` per Baker iOS PWA convention.

## Ship-gate
- Literal verification: `python outputs/dashboard.py` → open dashboard → confirm nav placement + click behavior. Do NOT ship "by inspection".
- After merge, wait for Render to deploy `brisen-docs.onrender.com` (separate static-site service) and confirm `/templates/` returns 200 with the gallery rendered. Don't claim ship until this probe passes.

## Reply target
Bus-post `lead` on ship with PR # + merge SHA + curl probe result of `https://brisen-docs.onrender.com/templates/`. Cross-reference `TEMPLATES_GALLERY_LAB_INSTALL_1` (b4) so the two ships can be paired in the hag-desk ack reply.
