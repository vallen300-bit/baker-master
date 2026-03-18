# BRIEF: Mobile Alerts View (E2)

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 26)
**Priority:** High — Director has real-time alert notifications now but no way to triage on mobile
**Branch:** `feat/mobile-alerts-view-1`

## Context

- Real-time push alerts just shipped (SSE + toast banners + browser notifications)
- Desktop has full Fires tab with bulk dismiss, source filter, matter grouping
- Mobile has NO alerts view — just the badge count
- Director gets T1 notification on phone, taps it... and can only ask Baker about it in chat
- 95 pending alerts, Director needs to triage from phone

## Deliverables

### 1. Mobile Alerts Tab
- Add a third tab to mobile: Baker | Specialist | **Alerts**
- Or: make badge click open an alerts overlay/sheet instead of a tab
- Design preference: bottom sheet (swipe up from badge) — feels more native on mobile
- **Files:** `outputs/static/mobile.html`, `outputs/static/mobile.js`, `outputs/static/mobile.css`

### 2. Alert Card Design
- Each alert as a compact card: tier badge (colored dot), title, source, time ago
- T1: red left border, T2: blue, T3: gray
- Tap to expand: shows full body
- Swipe right: dismiss (with undo toast for 3 seconds)
- **Files:** `outputs/static/mobile.js`, `outputs/static/mobile.css`

### 3. Quick Filter Chips
- Top of alerts view: "All", "T1", "T2", "T3" filter chips
- Plus source filter: "Pipeline", "Deadline", "Intelligence"
- Active chip is highlighted
- **Files:** `outputs/static/mobile.js`, `outputs/static/mobile.css`

### 4. Bulk Actions
- "Dismiss all T3" button at bottom
- Uses existing `POST /api/alerts/bulk-dismiss` endpoint
- Count refreshes after dismiss
- **Files:** `outputs/static/mobile.js`

### 5. Badge → Alert View Navigation
- Tapping the alert badge (red dot in header) opens the alerts view
- SSE toast notifications: tapping the toast also navigates to alerts view
- **Files:** `outputs/static/mobile.js`

## API Endpoints (existing)
- `GET /api/alerts` — returns pending alerts (all tiers)
- `POST /api/alerts/{id}/dismiss` — dismiss single alert
- `POST /api/alerts/bulk-dismiss` — bulk dismiss by IDs or tier
- `GET /api/alerts/stream?key=...` — SSE stream (already connected)

## Design Notes
- Follow existing mobile design (dark mode via prefers-color-scheme)
- Match ClaimsMax banking-grade style: clean, minimal, blue accent
- Touch-friendly: min 44px tap targets, swipe gestures
- Cache bust: bump CSS/JS version numbers

## DO NOT Touch
- Backend Python files — all stable from Session 26
- `outputs/dashboard.py` — unless adding a minor query param to `/api/alerts`

## Test
1. Open /mobile on iPhone
2. Badge shows count, tap opens alerts view
3. Cards render with tier colors
4. Swipe to dismiss works
5. Filter chips work
6. "Dismiss all T3" clears low-priority alerts
7. SSE toast tap navigates to alerts
