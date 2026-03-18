# BRIEF: Real-Time Push Alerts (D1 + E3)

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 26)
**Priority:** High — T1 alerts arrive but neither desktop nor mobile push. Director finds out 5+ min later.
**Branch:** `feat/realtime-push-alerts-1`

## Context

- Desktop badge refreshes every 5 min (app.js `setInterval`)
- Mobile badge same pattern
- No WebSocket / SSE live channel for alerts
- No browser notification API
- No service worker for push when app is backgrounded
- The compounding risk detector (F1) creates T1 alerts every 2h — these need instant visibility

## Deliverables (sequenced)

### 1. SSE Alert Stream Endpoint
- `GET /api/alerts/stream` — Server-Sent Events endpoint
- Auth: X-Baker-Key as query param (SSE doesn't support headers easily)
- Events: `{"type": "new_alert", "id": 123, "tier": 1, "title": "...", "source": "..."}`
- Server-side: poll alerts table every 10 seconds for new pending alerts since last check
- **File:** `outputs/dashboard.py`

### 2. Desktop Live Alert Banner
- Connect to `/api/alerts/stream` via EventSource
- On new T1/T2 alert: show a toast banner at top of page (auto-dismiss after 15s for T2, sticky for T1)
- T1 banners: red background, click opens Fires tab
- T2 banners: blue background, click opens Fires tab
- Also trigger browser Notification API (`new Notification(...)`) if permission granted
- On page load: request notification permission
- **Files:** `outputs/static/app.js`, `outputs/static/index.html` (add notification permission request)

### 3. Mobile Live Alert Banner
- Same SSE connection on mobile page
- Toast banner (matches mobile design)
- Browser notification on mobile Safari (if permitted)
- **Files:** `outputs/static/mobile.js`, `outputs/static/mobile.html`

### 4. Sound on T1
- Play a short notification sound on T1 alerts
- Use Web Audio API (no audio file needed — generate a short beep)
- Respect user preference: add a mute toggle in header
- **Files:** `outputs/static/app.js`, `outputs/static/mobile.js`

## Technical Notes

- SSE is simpler than WebSocket for this use case (one-direction, no state)
- The `/api/alerts/stream` endpoint should use `StreamingResponse` from FastAPI
- Poll interval: 10 seconds is fine (much better than 5 min badge refresh)
- Keep the existing 5-min badge refresh as fallback (SSE disconnects happen)
- For the server-side poll, track `last_id` to only send new alerts
- Browser Notification API requires HTTPS (Render provides this)

## DO NOT Touch
- `memory/store_back.py` — AI Head area
- `orchestrator/capability_runner.py` — AI Head area
- `orchestrator/risk_detector.py` — AI Head area
- `triggers/embedded_scheduler.py` — AI Head area

## Test
1. Open desktop dashboard, verify SSE connects (check Network tab)
2. Create a test T1 alert via `/api/scan` ("test alert")
3. Verify: toast banner appears within 10s, browser notification pops, badge updates
4. Same test on mobile
5. Mute toggle works (no sound on T1 when muted)
