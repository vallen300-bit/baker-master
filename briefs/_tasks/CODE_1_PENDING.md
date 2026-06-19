---
status: PENDING
brief_id: AI_HOTEL_FIELDNOTES_THUMBNAIL_LAZYIMG_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-19
task_class: bug-fix
harness_v2: applies
gate_plan: G1 self-test (pytest) → G2 /security-review → G3 codex (bus codex) → AH1 merge → POST_DEPLOY_AC_VERDICT v1
priority: HIGH — this is the true cause of Director "can't see my card" (feed = 7.1 MB for 14 notes; his card alone 2.56 MB; page hangs on "Loading…" on a phone).
---

# BRIEF — AI_HOTEL_FIELDNOTES_THUMBNAIL_LAZYIMG_1 — make Field Notes load fast (thumbnails + lazy full images)

## Context
Director couldn't see his saved site card in the AI-Hotel dashboard Field Notes. Diagnosed LIVE via Chrome MCP:
the page render is correct and the API returns the card — but `GET /api/ai-hotel/captures` inlines **full-
resolution image base64 for every capture**. Live measured: total feed **7,131,729 bytes for 14 captures**;
the Director's own card (cap 17) = **2.56 MB**. On a phone/cellular that takes 10-30s+, so the section sits on
"Loading field notes…" and looks frozen. The earlier no-cache PR #382 is unrelated hygiene — THIS is the cure.

**RACI:** accountable=lead, responsible=b1, gate=codex (G3). **Complexity:** Low-Medium.

## Current State (verified live this session)
- List endpoint `GET /api/ai-hotel/captures` — `outputs/dashboard.py:9664` — builds `images[]` as full
  `data:...;base64,...` URLs from `ai_hotel_capture_images` (+ legacy parent `image_b64`). No size reduction.
- Renderer `outputs/static/ai-hotel.html` `buildNoteCard` (~L661) uses `imgsOf(c)` → `c.images[0]` as the thumb
  and the rest as a strip — all full-res.
- AC10 (audio) already established the pattern: **metadata/thumbnail in list, full payload only on tap.** Mirror it for images.
- `_ai_hotel_resize_for_db` (`dashboard.py:9333`) already uses PIL to decode+resize — reuse for thumbnailing.

## Engineering Craft Gates
- **Diagnose:** APPLIES. Symptom reproduced live (7.1 MB feed, hang on "Loading"); root cause = full base64 in list.
  Feedback loop: `curl -s .../api/ai-hotel/captures?limit=100 -H 'X-Baker-Key: …' | wc -c` (expect <300 KB after fix).
- **Prototype:** N/A. **TDD:** APPLIES — assert the list payload carries thumbnails not full images, first.

## Fix
1. **List view returns thumbnails only.** In `ai_hotel_captures` (the GET), replace full `images[]` with:
   - `thumb` — the FIRST image decoded + resized to ~160px longest-edge JPEG base64 (small, ~5-15 KB).
   - `image_count` — integer.
   - DROP the full `images[]` / `image` full-res base64 from the LIST response.
   Generate the thumb server-side via a small PIL helper (reuse `_ai_hotel_resize_for_db` patterns; cap ~160px,
   quality ~70). Wrap in try/except — a bad image yields `thumb=null`, never breaks the feed (keep fail-soft).
2. **Full images on tap.** Add `GET /api/ai-hotel/captures/{id}/images` (`Depends(verify_api_key)`, `{id}` int-
   param) returning the ordered full `data:` URLs for that capture only. `openNoteDetail` fetches it lazily.
3. **Frontend** `ai-hotel.html`: card thumb uses `c.thumb`; detail view calls the new images endpoint to show
   full photos (mirror the existing lazy audio fetch at ~L747). Show "Loading photos…" placeholder in detail.
4. (Optional, if cheap) cache the generated thumb in a new nullable `ai_hotel_capture_images.thumb_b64` column
   to avoid re-resizing each request — only if it doesn't balloon scope; otherwise resize on the fly (14 imgs is cheap).

## Acceptance criteria (pytest — NOT "by inspection")
- AC1: `GET /api/ai-hotel/captures` response total size is small — assert NO full-res `image_b64`/`images[]`
  full data-URLs in the list; each item has `thumb` (or null) + `image_count`. (Target <300 KB for the live 14-row feed.)
- AC2: `GET /api/ai-hotel/captures/{id}/images` returns the ordered full image data-URLs for that capture, auth-gated.
- AC3: a capture with no images → `thumb=null`, `image_count=0`, feed still returns it (fail-soft).
- AC4: a corrupt/undecodable stored image → `thumb=null`, never 500, feed still serves other captures.

## Files Modified
- `outputs/dashboard.py` — thumbnail in list + new `/captures/{id}/images` endpoint.
- `outputs/static/ai-hotel.html` — thumb in card, lazy full-image fetch in detail.
- `tests/test_ai_hotel_thumbnails.py` — NEW (AC1–AC4).

## Do NOT Touch
- The audio metadata/lazy pattern (#381 — keep). Applied migrations. POST form-drafts/confirm/discard.

## Done rubric
DONE = AC1–AC4 pytest green (paste tail) + `py_compile` clean + LIVE `curl … | wc -c` shows the feed dropped
from ~7 MB to <300 KB + the card renders in <2s on the deployed dashboard + codex G3 PASS + POST_DEPLOY_AC v1
(include the before/after byte count). Compile-clean ≠ done.

## Kill criteria
- List still ships full-res base64 (feed not materially smaller) → not done.
- Thumbnail generation can 500 the feed → stop (fail-soft is mandatory).

## Gate plan
G1 pytest → G2 `/security-review` → G3 codex (bus `lead`→`codex`) → lead merge → b1 POST_DEPLOY_AC v1.
Branch `b1/ai-hotel-fieldnotes-thumbnail-lazyimg-1` → PR baker-master `main`. Bus-post ship + gate-request + post-deploy. Reply target: lead.
