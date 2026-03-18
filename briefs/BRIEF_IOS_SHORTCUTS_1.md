# BRIEF: iOS Shortcuts — Ask Baker & Baker Vision

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 26)
**Priority:** Medium — Director uses Baker on iPhone daily, shortcuts save friction
**Branch:** `feat/ios-shortcuts-1`

## Context

- `/mobile` page works well (PWA, camera, voice readback)
- `/api/scan` (SSE) and `/api/scan/image` (Haiku Vision) endpoints exist
- Director wants "Ask Baker" and "Baker Vision" share sheet shortcuts
- iOS Shortcuts app can make HTTP requests and process responses

## Deliverables

### 1. Shortcut definition files
Create two `.shortcut` files (or document the manual setup steps) in `docs/ios-shortcuts/`:

**Ask Baker:**
- Trigger: Share sheet (text) or Siri ("Ask Baker")
- Input: text from share sheet, or ask for input via dialog
- Action: POST to `/api/scan` with `{"message": "<input>", "mode": "quick"}`
- Since `/api/scan` uses SSE, the shortcut needs a simpler endpoint...

### 2. New endpoint: POST /api/scan/quick
- Non-streaming version of `/api/scan` for iOS Shortcuts (SSE not supported)
- Accept JSON: `{"message": "string"}`
- Auth: X-Baker-Key header
- Return JSON: `{"response": "string", "tier": 1}`
- Internally: call the same pipeline as scan_chat but collect the full response
- Timeout: 30s max (iOS Shortcuts has ~30s timeout)
- **File:** `outputs/dashboard.py`

### 3. New endpoint: POST /api/scan/image/quick
- Non-streaming version of `/api/scan/image` for iOS Shortcuts
- Accept: multipart form with image file
- Auth: X-Baker-Key header
- Return JSON: `{"response": "string"}`
- Internally: same as existing `/api/scan/image` but returns JSON instead of SSE
- **File:** `outputs/dashboard.py`

### 4. Documentation: `docs/ios-shortcuts/README.md`
- Step-by-step setup for both shortcuts
- Screenshots not needed, just clear text instructions
- Include the exact Shortcut actions sequence

## Technical Notes

- iOS Shortcuts can do HTTP POST with headers and JSON body
- iOS Shortcuts CANNOT handle SSE — need synchronous JSON endpoints
- Keep timeout under 30s (iOS kills long requests)
- For quick endpoint, use the legacy single-pass RAG (not agentic) to stay within timeout
- Image endpoint should auto-resize if needed (existing logic in `/api/scan/image`)

## DO NOT Touch
- `memory/store_back.py` — stable
- `orchestrator/deadline_manager.py` — stable
- `triggers/embedded_scheduler.py` — stable
- `triggers/email_trigger.py` — stable

## Test
1. `curl -X POST https://baker-master.onrender.com/api/scan/quick -H "X-Baker-Key: bakerbhavanga" -H "Content-Type: application/json" -d '{"message": "What meetings do I have today?"}'`
2. Verify response within 30s
3. Test image endpoint with a sample photo
