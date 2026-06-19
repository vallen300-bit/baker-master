---
status: PENDING
brief_id: AI_HOTEL_GPS_CAPTURE_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-19
task_class: feature
harness_v2: applies
gate_plan: G1 self-test (pytest AC1-AC10) → G2 /security-review → G3 codex (bus codex) → AH1 merge → POST_DEPLOY_AC_VERDICT v1
design: lead GPS DESIGN v1 (#3382) + codex-arch review ACCEPT-WITH-CHANGES (#3384). Director GO + ratified "GPS address = verified evidence, separate from dictated" (#3381).
---

# BRIEF — AI_HOTEL_GPS_CAPTURE_1 — capture exact GPS location on field capture

## Context
Director (trip site-scouting): "add the exact GPS location… the location is very important for me to research."
The phone reads its GPS at capture time (`navigator.geolocation`) WITH permission; Baker cannot recover location
remotely after the fact. GPS becomes **hard evidence** — far better than dictated guesses, which `site_visit`
intentionally leaves null (anti-hallucination). Director ratified: the GPS-derived address is **verified evidence,
stored separately from any dictated `address_or_location_clue`** (evidence vs claim).

**RACI:** accountable=lead, responsible=b1, design=lead+codex-arch (#3382/#3384), gate=codex (G3). **Complexity:** Medium.

## Substrate (live)
POST `/api/ai-hotel/form-drafts` + the capture insert (`outputs/dashboard.py` ~L9771, raw capture committed
BEFORE transcription) · `ai_hotel_captures` · Field Notes shelf (`outputs/static/ai-hotel.html`) · capture page
(`outputs/static/ai-hotel-capture.html`). GPS is **capture-level evidence** (one per capture), linked to all its cards.

## Engineering Craft Gates
- **Diagnose:** N/A (new feature). **Prototype:** N/A (design reviewed).
- **TDD:** APPLIES. First vertical test: a site capture with a GPS payload → coords stored on `ai_hotel_captures`,
  permission-denied path still saves the capture. Then build.

## Scope

### 1. Client capture (`ai-hotel-capture.html`)
- GPS request fires from a **user gesture** (a "📍 Tag location" button + the Site-visit submit path) — NOT silent
  page load (iOS permission is more reliable tied to a tap). `getCurrentPosition({enableHighAccuracy:true, timeout:10000, maximumAge:0})`.
- Permission-denied / timeout / unavailable → **save the capture WITHOUT GPS** (non-blocking) + set status; show "Location not added".
- Show captured accuracy ("±8 m") + allow **retry** before submit. If `gps_captured_at` is **>10 min** old at submit,
  show a stale warning + allow retry; still save if Director proceeds.
- Payload: `gps_lat, gps_lng, gps_accuracy_m, gps_captured_at` (ISO), `gps_capture_method ∈ {auto_site_visit, manual_tag_location}`.

### 2. Persistence — migration `migrations/20260619c_ai_hotel_captures_gps.sql` (NEW)
Add to `ai_hotel_captures`: `gps_lat DOUBLE PRECISION`, `gps_lng DOUBLE PRECISION`, `gps_accuracy_m REAL`,
`gps_captured_at TIMESTAMPTZ`, `gps_address TEXT`, `gps_address_source TEXT`,
`gps_address_status TEXT` (`not_requested|ok|permission_denied|timeout|low_accuracy|geocode_failed`).
**CHECK constraints:** `gps_lat BETWEEN -90 AND 90`; `gps_lng BETWEEN -180 AND 180`;
`gps_accuracy_m IS NULL OR gps_accuracy_m >= 0`; `gps_address_source IN ('google','nominatim') OR gps_address_source IS NULL`.

### 3. Reverse-geocode (server-side, single-shot at insert, NON-blocking)
- Run ONCE at capture insert, never on Field Notes render. Nonblocking + non-fatal: failure → `gps_address=null`,
  `gps_address_status='geocode_failed'`, coords still saved.
- Provider: **Google Geocoding API if a key exists in env** (best street-address quality, ~$5/1k = negligible);
  else **OSM Nominatim** with an explicit `User-Agent` + a 1 req/s rate-limit guard. b1 checks env for an existing
  maps/geocoding key. **No client-side geocode key exposure** — server-only.
- GPS-derived address goes to `gps_address` — **separate from dictated `address_or_location_clue`** (Director ratified).

### 4. Display (`ai-hotel.html`)
- **Accuracy tiers:** ≤50 m = verified; 50–150 m = "approx."; >150 m = low-accuracy (flagged, not primary).
- **Compact-row location preference:** (1) `gps_address` if ≤50 m; (2) `gps_address (approx.)` if 50–150 m;
  (3) dictated clue if GPS absent/low-accuracy; (4) "Location missing".
- **Detail view** always shows separately: coordinates, accuracy, captured_at, address_source, dictated clue,
  + an **"Open in Maps"** deep link **generated from lat/lng, URL-encoded** (`https://maps.google.com/?q=<lat>,<lng>`
  + Apple `geo:`), opened in a new tab — **never built from the free-text address**.
- List feed returns GPS **metadata** for compact display (small); auth-only.

### 5. Privacy
- GPS fields are auth-gated; **NOT embedded into Qdrant / wiki / vector memory** unless separately Director-ratified.

## Acceptance criteria (pytest — NOT "by inspection")
- AC1: site capture WITH GPS payload → coords + accuracy + captured_at stored on `ai_hotel_captures`.
- AC2: permission-denied → capture + form draft still created (no GPS, `status='permission_denied'`).
- AC3: reverse-geocode failure → coords stored, `gps_address=null`, `status='geocode_failed'`.
- AC4: stale GPS (>10 min) → client warns + allows retry/proceed (capture still saves).
- AC5: low-accuracy (>150 m) is visibly flagged, NOT shown as exact (compact row not primary).
- AC6: existing captures (null GPS) render cleanly — no errors, "Location missing".
- AC7: CHECK constraints reject out-of-range lat/lng on insert.
- AC8: Maps deep link is built from lat/lng (URL-encoded), not free-text address.
- AC9: GPS fields are NOT written to vector/Qdrant/wiki memory.
- AC10: reverse-geocode runs once at insert, not on the captures GET (no per-render geocode).

## Files Modified
- `outputs/dashboard.py` — accept GPS payload on form-drafts/capture; reverse-geocode at insert; GPS in captures GET metadata.
- `migrations/20260619c_ai_hotel_captures_gps.sql` — NEW.
- `outputs/static/ai-hotel-capture.html` — geolocation capture + permission/stale/retry UX + status copy.
- `outputs/static/ai-hotel.html` — accuracy-tiered location display + Maps link in detail.
- `tests/test_ai_hotel_gps.py` — NEW (AC1–AC10).

## Do NOT Touch
- Dictated `address_or_location_clue` semantics (stays a separate claim field). Applied migrations.
- The #380/#381/#383 raw-save / lazy-image / audio paths — extend, don't break.

## Done rubric
DONE = AC1–AC10 pytest green (paste tail) + `py_compile` clean + live exercise on the deployed page (tag a real
location → coords + address + Maps link on the card) + codex G3 PASS + `POST_DEPLOY_AC_VERDICT v1`. Compile-clean ≠ done.

## Kill criteria
- Any capture lost because GPS/geocode failed → rollback. Any client-side geocode key exposure → block.
- Any low-accuracy fix displayed as exact → block. Any reverse-geocode call in the list-render loop → block.
- Any fabricated coordinate/address presented as GPS → block.

## Gate plan
G1 pytest → G2 `/security-review` → G3 codex (bus `lead`→`codex`, topic `gate-request/prNNN`) → lead merge →
b1 `POST_DEPLOY_AC_VERDICT v1`. Branch `b1/ai-hotel-gps-capture-1` → PR baker-master `main`. Bus-post ship + gate-request + post-deploy. Reply target: lead.
