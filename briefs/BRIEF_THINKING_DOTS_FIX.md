# BRIEF: Thinking Dots Persistence Fix

**Author:** AI Head
**Date:** 2026-03-17
**Status:** READY FOR CODE BRISEN
**Effort:** ~1 hour

---

## Problem

When the user asks Baker a question in the Scan chat, thinking dots (three pulsing dots + "Baker is thinking...") appear briefly then **disappear before the answer starts streaming**. The user cannot tell if Baker is still working or hung.

The gap: Baker's pipeline takes 3-8 seconds for retrieval + augmentation before the first token streams. During this time, the SSE connection is open but silent — no events are sent.

## Root Cause

**Backend:** The SSE stream sends zero events between connection and first Claude token. The pipeline does classification, retrieval, augmentation, Claude call — all before any token event is emitted.

**Frontend (`app.js` line 1974):** Thinking dots are set via the existing `showLoading()` pattern. Line 2010 clears them on first token. The dots SHOULD persist, but can vanish if the browser read cycle gets an empty buffer or keepalive during the silent phase.

## Fix — Two Parts

### Part 1: Backend — Send progress events during pipeline phases

**File:** `outputs/dashboard.py` — in the scan streaming functions

Send lightweight SSE events during each pipeline phase so the frontend knows Baker is alive:

```python
# In the SSE generator function, before retrieval:
yield f"data: {json.dumps({'status': 'retrieving'})}\n\n"

# After retrieval, before augmentation:
yield f"data: {json.dumps({'status': 'thinking'})}\n\n"

# After augmentation, before Claude call:
yield f"data: {json.dumps({'status': 'generating'})}\n\n"
```

Find the SSE generator functions — there are multiple paths:
- `_scan_chat_legacy()` — single-pass RAG
- `_scan_chat_agentic()` — agent loop
- `_scan_chat_capability()` — capability framework

Each should emit status events at key phases.

### Part 2: Frontend — Update thinking dots with phase labels

**File:** `outputs/static/app.js` — in `sendScanMessage()`

Handle the new `data.status` events in the SSE reader loop (around line 2008). When a status event arrives and no tokens have been received yet, update the thinking indicator label using the existing `showLoading()` helper or equivalent safe DOM methods:

Status label mapping:
- `retrieving` -> "Searching memory..."
- `thinking` -> "Analyzing context..."
- `generating` -> "Writing response..."

The user experience becomes:
1. **"Baker is thinking..."** — immediately on send
2. **"Searching memory..."** — when retrieval starts
3. **"Analyzing context..."** — when augmentation starts
4. **"Writing response..."** — when Claude generation starts
5. **First token appears** — dots replaced by streaming text

IMPORTANT: Use the existing `showLoading()` function or safe DOM methods (textContent, createElement) for updating the indicator. All user-provided text must go through `esc()`. Do not construct HTML strings from untrusted data.

### Part 3: Safety net — CSS animation persistence

**File:** `outputs/static/style.css`

Verify the thinking dots CSS animation runs indefinitely (infinite iteration count). This should already be correct.

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Add `yield` status events in SSE generator functions |
| `outputs/static/app.js` | Handle `data.status` events, update thinking label via safe DOM methods |
| `outputs/static/style.css` | Verify animation is infinite (likely already correct) |
| `outputs/static/index.html` | Bump cache version |

## Finding the SSE generators

Search for these patterns in `dashboard.py`:
- `yield f"data:` — all SSE event emission points
- `def _scan_chat_legacy` — single-pass streaming
- `def _scan_chat_agentic` — agent loop streaming
- `def _scan_chat_capability` — capability streaming
- `async def _stream_` — any streaming generator functions

The status events should be added early in each generator, before the Claude API call.

## Testing

1. Ask Baker any question in Scan chat
2. Dots should persist with changing labels through all phases
3. First token should cleanly replace the dots
4. If Baker errors, dots should be replaced by error message (already handled)
5. Test on slow queries (agent/capability path) — dots should show for 5-10 seconds

## Design

- Same thinking dots animation (three pulsing dots)
- Label changes smoothly — no flash/flicker between phases
- Font: 12px, color: var(--text3), same as current
- No additional UI elements — just the label text changes
