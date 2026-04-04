# BRIEF: CHAT_POLISH_1 — Wider chat bubbles, compact headers, narrower artifact panel

## Context
After the bottom-input layout shipped (BRIEF_CHAT_BOTTOM_INPUT), the Director identified three UX issues:
1. Chat text has "big distances between edges" — bubbles don't use available width, text breaks awkwardly
2. The artifact panel on the right is too wide (320px), stealing space from chat
3. View headers ("Ask Baker", "Ask Specialist", "Client PM") waste ~50px of vertical space — should be a compact back arrow + label instead

Director request: "The text in the window is not going like one text. It leaves big distances between the edges. The paragraph is not a paragraph. Maybe the length of the chat window is a little bit too short. We can shift it to the right. We do not need so much space in the right-hand side."

## Estimated time: ~30min
## Complexity: Low
## Prerequisites: BRIEF_CHAT_BOTTOM_INPUT + BRIEF_CHAT_TEXTAREA_GROW already deployed
## Parallel-safe: Yes — only touches frontend files (CSS, JS, HTML)

---

## Part 1: Wider chat bubbles + proper text wrapping

### Problem
User message bubbles have `max-width: 85%`, leaving 15% empty space on each side. Baker response bubbles are `width: 100%` but markdown content inside lacks word-breaking rules, causing awkward line breaks.

### Current State (style.css, lines 860-873)
```css
.scan-msg {
  max-width: 85%; padding: 12px 16px; border-radius: var(--radius);
  font-size: 14px; line-height: 1.7;
}
.scan-msg.user {
  align-self: flex-end; background: rgba(201,169,110,0.15); color: var(--text);
  border: 1px solid rgba(201,169,110,0.25);
  border-radius: var(--radius) var(--radius) 4px var(--radius);
}
.scan-msg.baker {
  align-self: flex-start; background: var(--bg-subtle); border: 1px solid var(--border);
  max-width: 100%; width: 100%;
  border-radius: var(--radius) var(--radius) var(--radius) 4px;
}
```

### Implementation

**File: `outputs/static/style.css`**

Replace the `.scan-msg` block (lines 860-862):
```css
.scan-msg {
  max-width: 85%; padding: 12px 16px; border-radius: var(--radius);
  font-size: 14px; line-height: 1.7;
}
```

With:
```css
.scan-msg {
  max-width: 95%; padding: 12px 16px; border-radius: var(--radius);
  font-size: 14px; line-height: 1.7;
  word-break: break-word; overflow-wrap: break-word;
}
```

### What changed:
1. `max-width: 85%` → `max-width: 95%` — user bubbles now use nearly full width, minimal dead space at edges
2. `word-break: break-word; overflow-wrap: break-word;` — long words/URLs wrap properly instead of overflowing or breaking awkwardly. These properties inherit into `.md-content p` inside the bubble.

### Key Constraints
- Baker bubbles (`scan-msg.baker`) already have `max-width: 100%; width: 100%` — no change needed there.
- The `95%` still leaves a small visual margin so user bubbles don't touch the container edge.

---

## Part 2: Narrower artifact panel (320px → 260px)

### Problem
The right-side artifact panel (generated files, upload zone) takes a fixed 320px. On a typical 1440px screen, after the 240px sidebar, the chat area gets only ~880px. Reducing the panel gives more room to chat text.

### Current State (style.css, lines 919-922)
```css
.artifact-panel.open {
  width: 320px; min-width: 320px; opacity: 1;
  border-left: 1px solid var(--border);
  padding: 16px;
}
```

### Implementation

**File: `outputs/static/style.css`**

Replace:
```css
.artifact-panel.open {
  width: 320px; min-width: 320px; opacity: 1;
  border-left: 1px solid var(--border);
  padding: 16px;
}
```

With:
```css
.artifact-panel.open {
  width: 260px; min-width: 260px; opacity: 1;
  border-left: 1px solid var(--border);
  padding: 14px;
}
```

### What changed:
1. `width: 320px` → `width: 260px` — 60px narrower, giving that space to chat
2. `min-width: 320px` → `min-width: 260px` — matching
3. `padding: 16px` → `padding: 14px` — slightly tighter to keep content usable

### Key Constraints
- The artifact panel content (generated files list, upload button) must still be readable at 260px. File names may truncate with ellipsis — this is fine, they already have `text-overflow: ellipsis` styling.
- The `.artifact-panel` closed state (`width: 0`) is unchanged.

---

## Part 3: Replace view headers with compact back arrow + label

### Problem
Each chat view has a large header taking ~50px of vertical space:
- Ask Baker: `<div class="scan-view-header"><span class="scan-view-title">Ask Baker</span></div>` (24px font, 14px margin)
- Ask Specialist: Same pattern + specialist picker dropdown
- Client PM: Same pattern + client PM picker dropdown

This wastes space in the chat window. Other sidebar views already use a back arrow in the global command bar — the chat views should follow the same compact pattern.

### Current State

**index.html, lines 286-288 (Ask Baker):**
```html
    <div class="scan-view-header">
        <span class="scan-view-title">Ask Baker</span>
    </div>
```

**index.html, lines 325-329 (Ask Specialist):**
```html
    <div class="scan-view-header" style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">
        <span class="scan-view-title">Ask Specialist</span>
        <select id="specialistPicker" class="specialist-picker">
            <option value="">Select a specialist...</option>
        </select>
    </div>
```

**index.html, lines 366-371 (Client PM):**
```html
    <div class="scan-view-header" style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">
        <span class="scan-view-title">Client PM</span>
        <select id="clientPMPicker" class="specialist-picker">
            <option value="">Select a client...</option>
        </select>
    </div>
```

**style.css, lines 845-846:**
```css
.scan-view-header { margin-bottom: 14px; display: flex; align-items: center; }
.scan-view-title { font-size: 24px; font-weight: 700; letter-spacing: -0.3px; font-family: var(--font-heading); }
```

### Implementation

**File: `outputs/static/index.html`**

Replace Ask Baker header (lines 286-288):
```html
    <div class="scan-view-header">
        <span class="scan-view-title">Ask Baker</span>
    </div>
```

With:
```html
    <div class="scan-view-header">
        <button class="scan-back-btn" onclick="switchTab('morning-brief')" title="Back to Dashboard">&larr;</button>
        <span class="scan-view-label">Ask Baker</span>
    </div>
```

Replace Ask Specialist header (lines 325-329):
```html
    <div class="scan-view-header" style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">
        <span class="scan-view-title">Ask Specialist</span>
        <select id="specialistPicker" class="specialist-picker">
            <option value="">Select a specialist...</option>
        </select>
    </div>
```

With:
```html
    <div class="scan-view-header">
        <button class="scan-back-btn" onclick="switchTab('morning-brief')" title="Back to Dashboard">&larr;</button>
        <span class="scan-view-label">Ask Specialist</span>
        <select id="specialistPicker" class="specialist-picker">
            <option value="">Select a specialist...</option>
        </select>
    </div>
```

Replace Client PM header (lines 366-371):
```html
    <div class="scan-view-header" style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">
        <span class="scan-view-title">Client PM</span>
        <select id="clientPMPicker" class="specialist-picker">
            <option value="">Select a client...</option>
        </select>
    </div>
```

With:
```html
    <div class="scan-view-header">
        <button class="scan-back-btn" onclick="switchTab('morning-brief')" title="Back to Dashboard">&larr;</button>
        <span class="scan-view-label">Client PM</span>
        <select id="clientPMPicker" class="specialist-picker">
            <option value="">Select a client...</option>
        </select>
    </div>
```

**File: `outputs/static/style.css`**

Replace (lines 845-846):
```css
.scan-view-header { margin-bottom: 14px; display: flex; align-items: center; }
.scan-view-title { font-size: 24px; font-weight: 700; letter-spacing: -0.3px; font-family: var(--font-heading); }
```

With:
```css
.scan-view-header { margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
.scan-view-label { font-size: 15px; font-weight: 600; color: var(--text2); font-family: var(--font); }
.scan-back-btn {
  padding: 4px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg); font-size: 15px; color: var(--text2); cursor: pointer;
  font-family: var(--font); transition: all 0.15s; line-height: 1; flex-shrink: 0;
}
.scan-back-btn:hover { border-color: var(--blue); color: var(--blue); }
```

### What changed:
1. **24px bold title** → **15px semibold label** — compact, doesn't shout
2. **New back arrow button** — matches existing `.cmd-back` styling pattern but dedicated class for scan views
3. **margin-bottom: 14px** → **8px** — tighter spacing
4. **Inline styles removed** — specialist and client PM headers had `style="display:flex;align-items:center;gap:14px;margin-bottom:14px;"` which is now handled by the updated `.scan-view-header` class
5. **gap: 10px** added to `.scan-view-header` — consistent spacing between arrow, label, and picker

### Key Constraints
- The `switchTab('morning-brief')` target sends user back to the Dashboard landing page. This matches the existing `cmdBack` button behavior.
- The specialist picker and client PM picker dropdowns stay in the same header row, just after the label instead of after a big title.
- The `.scan-view-title` class is replaced by `.scan-view-label`. Search for any JS references to `.scan-view-title` — if found, update them too.

---

## Part 4: Cache bust

**File: `outputs/static/index.html`**

Check current values and bump both by 1:
- `style.css?v=N` → `style.css?v=N+1`
- `app.js?v=N` → `app.js?v=N+1`

---

## Files Modified
- `outputs/static/style.css` — bubble width 95%, word-breaking, artifact panel 260px, compact headers
- `outputs/static/index.html` — header HTML (back arrow + label), cache bust
- `outputs/static/app.js` — cache bust only (no logic changes unless `.scan-view-title` is referenced in JS)

## Do NOT Touch
- `outputs/dashboard.py` — no backend changes
- `outputs/static/mobile.html` — separate mobile layout, not in scope
- Search tab — different architecture, parked for later
- Textarea behavior — already working from previous briefs

## Quality Checkpoints
1. **Ask Baker**: Back arrow visible at top-left → click returns to Dashboard
2. **Ask Specialist**: Back arrow + "Ask Specialist" label + picker dropdown all in one compact row
3. **Client PM**: Same compact header as Specialist
4. **User bubble width**: Type a 2-sentence message → bubble fills ~95% of chat width, no large gap on left
5. **Baker bubble width**: Response fills full width as before
6. **Long words/URLs**: Paste a long URL → wraps properly, doesn't overflow
7. **Artifact panel**: Still visible on right, file names may truncate with ellipsis — acceptable
8. **Chat area wider**: Visually compare before/after — chat should feel noticeably wider
9. **iOS PWA**: Force-refresh → cache bust works, new layout loads

## Cost Impact
- Zero — pure frontend CSS/HTML change
- No API calls, no model changes

## Rollback
Revert CSS (85% → back, 320px → back, old header styles) and HTML (restore old header markup). Instant.
