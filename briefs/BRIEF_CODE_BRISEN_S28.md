# Code Brisen Brief — Session 28

**From:** AI Head | **Date:** 20 March 2026
**Priority:** E4 first, then E8

---

## Task 1: E4 — Trip Cards on Mobile

### What
Add trip intelligence cards to the mobile page (`/mobile`). Desktop already has full trip view with 6 cards — bring the same data to mobile in a touch-friendly layout.

### API Endpoints (all exist, all need `X-Baker-Key` header)

```
GET /api/trips                    → list of trips (active + upcoming)
GET /api/trips/{trip_id}          → trip details (destination, dates, contacts, event)
GET /api/trips/{trip_id}/cards    → all 6 card data in one response
```

The `/cards` endpoint returns a JSON object with keys:
- `logistics` — emails, WhatsApp messages, timezone info
- `agenda` — meetings, calendar events during the trip
- `reading` — relevant documents and prep materials
- `radar` — alerts and risks related to the trip/matter
- `timezone` — home vs destination time offset
- `objective` — trip purpose and goals

### Design Spec

1. **Trip banner at top of mobile page** (if active/upcoming trip exists)
   - Destination city + dates + event name (if any)
   - Tap to expand into full trip view

2. **Trip cards view** — vertically stacked cards, swipeable
   - Each card: header (icon + title) + collapsible content
   - Cards: Logistics, Agenda, Reading, Radar, Timezone, Objective
   - Same data as desktop but touch-optimized

3. **Dark mode** — follows existing mobile dark mode (prefers-color-scheme)

4. **No trip = no banner** — gracefully hide when no active trips

### Files to Modify
- `outputs/static/mobile.html` — add trip banner + trip view markup
- `outputs/static/mobile.js` — fetch trips API, render cards, expand/collapse
- `outputs/static/mobile.css` — trip card styles, dark mode

### Acceptance Criteria
- [ ] Trip banner shows on mobile when active trip exists
- [ ] Tap banner expands to full trip cards view
- [ ] All 6 cards render with real data from `/api/trips/{id}/cards`
- [ ] Dark mode works
- [ ] No trip = banner hidden, no errors
- [ ] Cache bust: bump ?v=N on CSS/JS includes

---

## Task 2: E8 — Mobile File Upload

### What
Let users upload PDFs and documents from the mobile page. Upload endpoint already exists (`POST /api/documents/upload`), just needs a mobile UI.

### API Endpoint (exists)

```
POST /api/documents/upload
Content-Type: multipart/form-data
X-Baker-Key: bakerbhavanga

Body: file (multipart file upload)

Response: { "document_id": 123, "filename": "contract.pdf", "status": "queued" }
```

The upload endpoint stores the file in PostgreSQL `documents` table and queues it for Haiku classification + extraction.

### Design Spec

1. **Upload button** in the mobile nav/toolbar area
   - Paperclip or document icon
   - Tap opens native file picker (accepts: .pdf, .docx, .xlsx, .csv, .txt)

2. **Upload flow**
   - User selects file → show filename + size preview
   - "Upload" button sends to API
   - Progress indicator (spinner or bar)
   - Success: "Document uploaded — Baker will analyze it shortly"
   - Error: "Upload failed — try again"

3. **Also support Share Sheet** — when user shares a file TO the mobile PWA from another app (Files, Mail, etc.)
   - This works via the Web Share Target API in the PWA manifest
   - Add `share_target` to the manifest if not already there

### Files to Modify
- `outputs/static/mobile.html` — upload button + modal/overlay
- `outputs/static/mobile.js` — file picker, upload fetch, progress
- `outputs/static/mobile.css` — upload UI styles

### Acceptance Criteria
- [ ] Upload button visible on mobile page
- [ ] Tap opens native file picker (PDF, DOCX, XLSX, CSV, TXT)
- [ ] File uploads successfully to `/api/documents/upload`
- [ ] Success/error feedback shown
- [ ] Works in dark mode
- [ ] Large files (>5MB) show warning before upload

---

## General Notes

- **API key:** `bakerbhavanga` (X-Baker-Key header)
- **Base URL:** `https://baker-master.onrender.com`
- **iOS PWA caching:** Always bump `?v=N` on CSS/JS includes after changes
- **Don't touch backend files** — AI Head handles those. Only modify `outputs/static/mobile.*`
- **Test on mobile viewport** — 375px width minimum
- **git pull before starting** — I just pushed LinkedIn integration (agent.py changed)
