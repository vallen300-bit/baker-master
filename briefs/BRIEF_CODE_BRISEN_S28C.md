# Code Brisen Brief — Session 28C (Final Backlog)

**From:** AI Head | **Date:** 20 March 2026
**Priority:** D5 first (quick), then E5, then D4

---

## Task 1: D5 — Inline Alert Editing

### What
Let Director edit alert title, matter assignment, and tags directly in the Fires tab without opening a separate view.

### API Endpoint (just added)

```
PATCH /api/alerts/{alert_id}
X-Baker-Key: bakerbhavanga
Content-Type: application/json

Body (any combination):
{
  "title": "Updated title",
  "matter_slug": "Hagenauer",
  "tags": ["legal", "deadline"],
  "tier": 2,
  "board_status": "in_progress"
}

Response: {"status": "updated", "id": 123, "fields": ["title", "matter_slug"]}
```

### Design Spec

1. **Edit icon** on each alert card (pencil icon, top-right)
2. **Inline edit mode** — tap pencil:
   - Title becomes editable text input
   - Matter becomes a dropdown (populated from known matters)
   - Tags become editable chips (add/remove)
   - Tier shows 1/2/3 selector
3. **Save/Cancel buttons** replace the edit icon while editing
4. **Optimistic update** — UI updates immediately, PATCH in background
5. **Error handling** — revert on failure, show toast

### Files to Modify
- `outputs/static/index.html` — edit mode markup on alert cards
- `outputs/static/app.js` — edit toggle, PATCH call, matter dropdown population
- CSS as needed

### Acceptance Criteria
- [ ] Pencil icon on alert cards
- [ ] Inline editing of title, matter, tags, tier
- [ ] PATCH /api/alerts/{id} called on save
- [ ] Optimistic update with error revert
- [ ] Works in both desktop Fires tab and mobile alerts

---

## Task 2: E5 — Voice Input on Mobile

### What
Hold-to-talk button on the mobile page. Use the browser's **Web Speech API** — free, no backend needed, works in Chrome and Safari.

### Design Spec

1. **Microphone button** next to the send button in the chat input area
2. **Hold-to-talk interaction:**
   - Tap: starts recording, button turns red, shows "Listening..."
   - Speak: real-time transcription appears in the text input
   - Tap again (or release after 30s): stops recording, text stays in input
   - User can edit the transcribed text before sending
3. **Implementation:** Use `webkitSpeechRecognition` (Chrome/Safari):
   ```javascript
   const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
   recognition.continuous = true;
   recognition.interimResults = true;
   recognition.lang = 'en-US';  // Director speaks English primarily

   recognition.onresult = (event) => {
     const transcript = Array.from(event.results)
       .map(r => r[0].transcript).join('');
     inputField.value = transcript;
   };
   ```
4. **Fallback:** If Web Speech API not available (Firefox, some Android), hide the mic button
5. **Language:** Default English, but Director also uses German/French — add a small language toggle if easy (en/de/fr)

### Files to Modify
- `outputs/static/mobile.html` — mic button markup
- `outputs/static/mobile.js` — Web Speech API integration
- `outputs/static/mobile.css` — mic button styles, recording state

### Acceptance Criteria
- [ ] Mic button visible on mobile (hidden if API unavailable)
- [ ] Tap starts recording, button shows recording state
- [ ] Real-time transcription in text input
- [ ] Tap again stops recording
- [ ] Transcribed text editable before send
- [ ] Works in Chrome and Safari on iOS

---

## Task 3: D4 — Dashboard Tab Customization

### What
Let Director pin, reorder, and hide tabs in the desktop dashboard.

### Design Spec

1. **Tab reorder** — drag-and-drop tab headers to reorder
2. **Pin/unpin** — right-click tab → "Pin" (pinned tabs always show first)
3. **Hide** — right-click tab → "Hide" (hidden tabs accessible via "..." overflow)
4. **Persist** — save tab order to localStorage so it survives page refresh
5. **Reset** — "Reset layout" option in the overflow menu

### Implementation Notes
- Use HTML5 Drag and Drop API for tab reordering
- Store in `localStorage.setItem('baker_tab_order', JSON.stringify([...]))`
- On page load, reorder tabs according to stored preference
- Context menu via a small custom dropdown (not browser right-click)

### Files to Modify
- `outputs/static/index.html` — draggable attributes on tabs, context menu markup
- `outputs/static/app.js` — drag handlers, localStorage, context menu logic
- CSS for drag states and context menu

### Acceptance Criteria
- [ ] Tabs can be dragged to reorder
- [ ] Order persists across page refreshes
- [ ] Right-click/long-press shows pin/hide options
- [ ] Hidden tabs accessible via overflow
- [ ] Reset returns to default order

---

## General Notes
- **git pull before starting** — chain improvements + PATCH alerts just pushed
- **API key:** `bakerbhavanga`
- **Cache bust:** bump ?v=N
- **Don't touch backend files**
- D5 is quickest — start there to unblock the Director immediately
