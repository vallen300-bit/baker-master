# BRIEF: CHAT_BOTTOM_INPUT — Flip chat layout to bottom-input with auto-scroll (Claude Desktop style)

## Context
All three chat views (Ask Baker, Ask Specialist, Client PM) currently use a top-input layout where messages are prepended (newest at top). This is counterintuitive — the user types at the top, the response streams downward from the top, and to see the latest content you have to scroll down or look at the top. Every modern chat app (Claude Desktop, ChatGPT, WhatsApp) uses bottom-input with messages flowing top-to-bottom and auto-scroll to keep the latest content visible.

Director request: "The chat window can be not so long but more high. As the chat progresses, the conversation is shifting upwards. The screen, however, is on the top. So to see the latest, you have to scroll down. This is not correct."

## Estimated time: ~1h
## Complexity: Low-Medium
## Prerequisites: None
## Parallel-safe: Yes — only touches frontend files (CSS, JS, HTML)

---

## Part 1: CSS — Flip layout to bottom-input

### Current State (style.css, lines 847-858):
```css
.scan-view-body { display: flex; flex-direction: column; height: calc(100vh - 190px); }

/* Input-at-top layout (Cowork style) */
.scan-view-body.scan-top-input { flex-direction: column; }
.scan-view-body.scan-top-input .scan-form { margin-bottom: 16px; flex-shrink: 0; }
.scan-view-body.scan-top-input .scan-messages { order: 2; }
.scan-view-body.scan-top-input .upload-status { order: 1; }

.scan-messages {
  flex: 1; overflow-y: auto; padding: 10px 0;
  display: flex; flex-direction: column; gap: 14px;
  justify-content: flex-start;
}
```

### Replace with:
```css
.scan-view-body { display: flex; flex-direction: column; height: calc(100vh - 190px); }

/* Bottom-input layout (Claude Desktop style) */
.scan-view-body.scan-top-input { flex-direction: column; }
.scan-view-body.scan-top-input .scan-messages { order: 1; flex: 1; }
.scan-view-body.scan-top-input .upload-status { order: 2; }
.scan-view-body.scan-top-input .scan-form { order: 3; margin-top: 12px; margin-bottom: 0; flex-shrink: 0; }

.scan-messages {
  flex: 1; overflow-y: auto; padding: 10px 0;
  display: flex; flex-direction: column; gap: 14px;
  justify-content: flex-end;
}
```

### What changed:
1. `.scan-form` gets `order: 3` (bottom) instead of being first. `margin-top: 12px` replaces `margin-bottom: 16px`.
2. `.scan-messages` gets `order: 1` (top) and `justify-content: flex-end` — this pushes messages to the bottom of the container when there are few messages, so the first message appears near the input bar (not floating at the top of an empty space).
3. `.upload-status` gets `order: 2` (between messages and input).

### Key Constraints
- The `scan-top-input` class is used by ALL three chat views (Ask Baker, Ask Specialist, Client PM). This single CSS change fixes all three.
- `justify-content: flex-end` is crucial — without it, a single message would appear at the very top of the container with a huge empty gap before the input bar.
- The `scan-layout` (parent flex container for chat + artifact panel) stays unchanged.

---

## Part 2: JS — Flip from prepend to append + auto-scroll to bottom

### Problem
Three bubble functions use `container.prepend(div)` + `scrollTop = 0` (newest on top). Need to flip to `container.appendChild(div)` + `scrollTop = scrollHeight` (newest on bottom, auto-scroll down).

### Change 1: `appendScanBubble()` (app.js, line ~3368-3370)

Replace:
```javascript
    // Newest messages at top (Cowork style — input is at top)
    container.prepend(div);
    container.scrollTop = 0;
```

With:
```javascript
    // Newest messages at bottom (Claude Desktop style)
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
```

### Change 2: `appendSpecialistBubble()` (app.js, line ~5878-5879)

Replace:
```javascript
    container.prepend(div);
    container.scrollTop = 0;
```

With:
```javascript
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
```

### Change 3: `appendClientPMBubble()` (app.js, line ~5960-5961)

Replace:
```javascript
    container.prepend(div);
    container.scrollTop = 0;
```

With:
```javascript
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
```

### Change 4: Post-streaming scroll (specialist, line ~5851-5852)

Replace:
```javascript
    var container = document.getElementById('specialistMessages');
    if (container) container.scrollTop = 0;
```

With:
```javascript
    var container = document.getElementById('specialistMessages');
    if (container) container.scrollTop = container.scrollHeight;
```

### Change 5: Post-streaming scroll (Ask Baker, line ~3606)

Find:
```javascript
    if (container) container.scrollTop = 0;
```

**Context:** This is in the `sendScanMessage()` function, at the end after streaming completes. Replace `scrollTop = 0` with `scrollTop = container.scrollHeight`.

Search for ALL occurrences of `container.scrollTop = 0` in the chat-related functions and replace with `container.scrollTop = container.scrollHeight`. There should be ~4-5 occurrences total.

### Change 6: History restore scroll

When switching specialists or restoring per-context history (specialist picker change handler, line ~6050-6056), messages are re-rendered. The loop currently appends via the bubble functions (which now use `appendChild`). After the loop, scroll to bottom:

The existing code already calls `appendSpecialistBubble` in a loop, which after our change will use `appendChild`. The final `scrollTop = scrollHeight` in the bubble function handles this automatically. **No additional change needed.**

### Key Constraints
- **Do NOT add "smart scroll pause"** in this brief. That's a nice-to-have for later. For now, always auto-scroll to bottom. The user can scroll up manually; it will jump back to bottom on next token, which is acceptable for v1.
- The `scrollTop = container.scrollHeight` line in the streaming token handler (where `setSafeHTML` is called) is already handled by the fact that the reply element grows at the bottom — the browser keeps it in view. But to be safe, add an explicit scroll-to-bottom after each token render inside `sendScanMessage()`.

### Change 7: Auto-scroll during streaming tokens (Ask Baker)

In `sendScanMessage()`, after the `setSafeHTML(replyEl, ...)` line (app.js, line ~3486), add:

```javascript
                        // Auto-scroll to keep latest content visible
                        var _scanMsgs = document.getElementById('scanMessages');
                        if (_scanMsgs) _scanMsgs.scrollTop = _scanMsgs.scrollHeight;
```

### Change 8: Auto-scroll during streaming tokens (Ask Specialist)

In `sendSpecialistMessage()`, after the `setSafeHTML(replyEl, ...)` token render line, add:

```javascript
                        var _specMsgs = document.getElementById('specialistMessages');
                        if (_specMsgs) _specMsgs.scrollTop = _specMsgs.scrollHeight;
```

### Change 9: Auto-scroll during streaming tokens (Client PM)

In `sendClientPMMessage()`, after the `setSafeHTML(replyEl, ...)` token render line, add:

```javascript
                        var _pmMsgs = document.getElementById('clientPMMessages');
                        if (_pmMsgs) _pmMsgs.scrollTop = _pmMsgs.scrollHeight;
```

---

## Part 3: Cache bust

### Implementation

**File: `outputs/static/index.html`**

- `app.js?v=85` → `app.js?v=86` (or current +1)
- `style.css?v=57` → `style.css?v=58` (or current +1)

Check the CURRENT values before bumping — Code Brisen from the Client PM brief may have already bumped them.

---

## Files Modified
- `outputs/static/style.css` — Flip layout order (messages top, input bottom), justify-content change
- `outputs/static/app.js` — 3 bubble functions (prepend → appendChild), ~5 scrollTop fixes, 3 streaming auto-scroll additions
- `outputs/static/index.html` — Cache bust only

## Do NOT Touch
- `outputs/dashboard.py` — No backend changes
- `orchestrator/*` — No backend changes
- HTML structure — The `scan-view-body`, `scan-form`, `scan-messages` elements stay exactly where they are in the DOM. CSS `order` handles the visual reordering. Do NOT move HTML elements around.

## Quality Checkpoints
1. **Ask Baker**: Type a question → response streams at bottom → input bar stays at very bottom of viewport → latest text always visible without scrolling
2. **Ask Specialist**: Same behavior as Ask Baker
3. **Client PM**: Same behavior as Ask Baker
4. **History restore**: Switch tabs and come back → messages display in chronological order (oldest at top, newest at bottom)
5. **Long response**: Ask a complex question → as response streams, chat auto-scrolls to keep latest text visible
6. **Empty state**: Open Ask Baker with no history → input bar at bottom, empty space above (no awkward floating messages)
7. **Multiple messages**: Send 5+ questions → conversation reads naturally top-to-bottom
8. **iOS PWA**: Force-refresh on iOS → verify `?v=N` cache bust works, new layout loads
9. **Artifact panel**: Verify artifact panel still works alongside the new layout

## Cost Impact
- Zero — pure frontend CSS/JS change
- No API calls, no model changes

## Rollback
Revert the CSS `order` properties and change `appendChild` back to `prepend`. The old layout is restored instantly.
