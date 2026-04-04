# BRIEF: CHAT_TEXTAREA_GROW — Fix textarea max-height and button alignment

## Context
The chat input was recently changed from `<input type="text">` to `<textarea>` (commit 49d15ee). However, the max-height was hardcoded to 160px (~6 lines), which is too restrictive for long messages. The user can't review their own question if it exceeds 6 lines. Additionally, the Send button and paperclip stretch vertically when the textarea grows, which looks broken.

Director request: "What if the message is more than six lines? Why only six lines?"

## Estimated time: ~15min
## Complexity: Low
## Prerequisites: Commit 49d15ee already deployed (textarea swap)

---

## Fix 1: Proportional max-height + internal scroll

### Problem
`max-height: 160px` caps the textarea at ~6 lines. Users writing detailed prompts (e.g., "Explain the Hagenauer situation including...") hit the cap and can't see their full message.

### Current State (style.css, line 879)
```css
  resize: none; overflow-y: hidden; min-height: 44px; max-height: 160px;
```

### Implementation

**File: `outputs/static/style.css`** — line 879

Replace:
```css
  resize: none; overflow-y: hidden; min-height: 44px; max-height: 160px;
```

With:
```css
  resize: none; overflow-y: auto; min-height: 44px; max-height: 40vh;
```

### What changed:
1. `max-height: 160px` → `max-height: 40vh` — scales with viewport. On a 900px-tall screen that's 360px (~18 lines). On iPad 1024px that's 410px (~20 lines). Never eats more than 40% of the screen.
2. `overflow-y: hidden` → `overflow-y: auto` — when the textarea exceeds max-height, a scrollbar appears so the user can scroll through their full message. Without this, text beyond max-height is invisible.

---

## Fix 2: Button alignment (flex-end)

### Problem
The `.scan-form` flex container defaults to `align-items: stretch`. When the textarea grows to multiple lines, the Send button and paperclip icon stretch vertically to match. This looks broken — buttons should stay at the bottom of the form.

### Current State (style.css, line 874)
```css
.scan-form { display: flex; gap: 10px; margin-top: 10px; }
```

### Implementation

**File: `outputs/static/style.css`** — line 874

Replace:
```css
.scan-form { display: flex; gap: 10px; margin-top: 10px; }
```

With:
```css
.scan-form { display: flex; gap: 10px; margin-top: 10px; align-items: flex-end; }
```

### What changed:
Buttons (Send + paperclip) now anchor to the bottom of the form row, matching Claude Desktop's behavior where the send button sits at the bottom-right of the expanding input.

---

## Fix 3: JS auto-grow cap must match CSS

### Problem
The JS `autoGrowTextarea()` function hardcodes `160` as the pixel cap. Must match the CSS `max-height`.

### Current State (app.js, line 6206-6207)
```javascript
    function autoGrowTextarea(el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 160) + 'px';
    }
```

### Implementation

**File: `outputs/static/app.js`** — line 6205-6208

Replace:
```javascript
    function autoGrowTextarea(el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 160) + 'px';
    }
```

With:
```javascript
    function autoGrowTextarea(el) {
        el.style.height = 'auto';
        var maxH = Math.round(window.innerHeight * 0.4);
        el.style.height = Math.min(el.scrollHeight, maxH) + 'px';
        el.style.overflowY = el.scrollHeight > maxH ? 'auto' : 'hidden';
    }
```

### What changed:
1. `160` → `window.innerHeight * 0.4` — calculates 40vh dynamically so it matches the CSS `max-height: 40vh` exactly.
2. `overflowY` toggle — hides scrollbar when content fits (clean look), shows it when content exceeds max (so user can scroll).

---

## Fix 4: Cache bust

**File: `outputs/static/index.html`**

Check current values and bump both by 1:
- `style.css?v=60` → `style.css?v=61`
- `app.js?v=88` → `app.js?v=89`

---

## Files Modified
- `outputs/static/style.css` — max-height 40vh, overflow-y auto, align-items flex-end
- `outputs/static/app.js` — autoGrowTextarea uses viewport-proportional cap
- `outputs/static/index.html` — cache bust only

## Do NOT Touch
- `outputs/dashboard.py` — no backend changes
- HTML structure — textareas stay as-is, no element changes
- Enter/Shift+Enter behavior — already working correctly from 49d15ee

## Quality Checkpoints
1. **Short message**: Type "hello" → textarea stays 1 line, buttons aligned at bottom
2. **Medium message** (~5 lines): Textarea grows smoothly, no scrollbar, buttons stay at bottom
3. **Long message** (~25 lines): Textarea grows to 40% of viewport, then shows internal scrollbar. User can scroll through their full message.
4. **Send resets**: After sending a long message, textarea shrinks back to 1 line
5. **All 3 views**: Ask Baker, Ask Specialist, Client PM all behave identically
6. **iPad/mobile**: 40vh scales correctly on smaller viewports
7. **Shift+Enter**: Still adds newlines, textarea grows accordingly

## Cost Impact
- Zero — pure frontend CSS/JS fix

## Rollback
Revert `max-height` to `160px`, `overflow-y` to `hidden`, remove `align-items: flex-end`, restore JS `160` constant.
