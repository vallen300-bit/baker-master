# BRIEF: SCAN-CONTEXT-SCOPE-1 — Scoped Scan Conversations Per Matter/Tab

**Author:** AI Head (baker-ai-dev) via Cowork
**Date:** 2026-03-10
**Priority:** HIGH (Director-reported UX issue)
**Baker Decision ID:** 7970
**Estimated effort:** Medium — frontend state management + 1 backend tweak

---

## Problem

When the Director clicks a matter in the left sidebar (e.g. "Oskolkov-RG7") and then clicks "Open in Scan", the Scan view opens but:

1. **Questions are not scoped to the matter** — Baker answers generically instead of filtering to Oskolkov-RG7 documents/context
2. **Conversation bleeds across tabs** — the same Q&A persists when navigating to other matters or tabs. Each matter should have its own conversation.

## Current Architecture

### Frontend (`outputs/static/app.js`)
- `scanHistory` — single global array (line ~1364). All Scan messages go here regardless of context.
- `_currentMatterSlug` — already tracked when clicking a matter (line 2762), but **never passed to the Scan API**
- "Open in Scan" button (line 783) calls `switchTab('ask-baker')` but does NOT pass the matter slug
- `sendScanMessage()` (line 1355) posts to `/api/scan` with `{ question, history }` — no `project` field

### Backend (`outputs/dashboard.py`)
- `ScanRequest` model (line 144-147) **already accepts** `project` and `role` as optional scope filters
- The Scan pipeline already knows how to filter by project — it's just never receiving it from the frontend

## Fix — 3 Changes

### 1. Frontend: Per-context conversation history

Replace the single `scanHistory` array with a keyed map:

```javascript
// Before:
var scanHistory = [];

// After:
var _scanHistories = {};  // keyed by context: 'global', 'matter:oskolkov-rg7', etc.
var _scanCurrentContext = 'global';

function getScanHistory() {
    if (!_scanHistories[_scanCurrentContext]) _scanHistories[_scanCurrentContext] = [];
    return _scanHistories[_scanCurrentContext];
}
```

When switching to a matter's Scan view, set `_scanCurrentContext = 'matter:' + matterSlug`. When using the global "Ask Baker" tab directly (no matter), use `'global'`.

### 2. Frontend: Pass matter slug to Scan API

In `sendScanMessage()`, include the project scope:

```javascript
// Line ~1377, in the fetch body:
body: JSON.stringify({
    question: question,
    history: getScanHistory().slice(-10),
    project: _scanCurrentContext.startsWith('matter:')
        ? _scanCurrentContext.replace('matter:', '')
        : null
}),
```

### 3. Frontend: "Open in Scan" passes matter context

Change line 783 from:
```javascript
html += '<button class="footer-btn primary" onclick="switchTab(\'ask-baker\')">Open in Scan</button>';
```

To:
```javascript
html += '<button class="footer-btn primary" onclick="openMatterScan(\'' + esc(alert.matter_slug || '') + '\')">Open in Scan</button>';
```

Add helper:
```javascript
function openMatterScan(matterSlug) {
    if (matterSlug) {
        _scanCurrentContext = 'matter:' + matterSlug;
    } else {
        _scanCurrentContext = 'global';
    }
    // Clear the message display and show this context's history
    renderScanHistory();
    switchTab('ask-baker');
    // Pre-fill placeholder with context
    var input = document.getElementById('scanInput');
    if (input && matterSlug) {
        input.placeholder = 'Ask about ' + matterSlug.replace(/-/g, ' ') + '...';
    }
}
```

### 4. Frontend: Render context-specific history on tab switch

Add a `renderScanHistory()` function that clears the messages container and re-renders from `getScanHistory()`. Call it whenever `_scanCurrentContext` changes.

Show a small context badge at the top of the Scan view:
```
[Oskolkov-RG7] ×   ← click × to return to global context
```

### 5. Same pattern for Specialist tab

The Specialist tab (`sendSpecialistMessage`) has the same issue — `_specialistHistory` is global. Apply the same per-context pattern. Lower priority — can be a follow-up commit.

---

## Backend — No Changes Needed

The `/api/scan` endpoint already accepts `project` as an optional field in `ScanRequest` (line 146). When populated, it scopes the retrieval to that project/matter. This is already built and tested — just never called from the frontend.

---

## Files to Modify

| File | Changes |
|------|---------|
| `outputs/static/app.js` | `scanHistory` → `_scanHistories` map, `sendScanMessage()` passes project, `openMatterScan()` helper, `renderScanHistory()`, context badge UI |

---

## Verification

1. Click "Oskolkov-RG7" in sidebar → "Open in Scan" → ask "What is the current status?" → Baker answers about Oskolkov-RG7 specifically
2. Navigate to "Hagenauer" matter → "Open in Scan" → different conversation, Oskolkov Q&A not visible
3. Go back to "Oskolkov-RG7" → previous conversation restored
4. Use global "Ask Baker" tab directly → no matter scope, generic Baker
5. Context badge shows current matter, × clears it back to global

---

## Success Criteria

- [ ] Each matter has its own Scan conversation history
- [ ] "Open in Scan" from a matter auto-scopes queries to that matter
- [ ] Global "Ask Baker" remains unscoped
- [ ] Navigating between matters preserves each conversation
- [ ] Context badge visible when scoped to a matter
- [ ] No backend changes needed — frontend only
