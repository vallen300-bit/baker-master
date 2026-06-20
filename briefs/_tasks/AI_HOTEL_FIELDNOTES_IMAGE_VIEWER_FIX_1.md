# BRIEF: AI_HOTEL_FIELDNOTES_IMAGE_VIEWER_FIX_1

**Dispatched_by:** lead (AH1) — reply-to: lead
**Owner:** b1
**Priority:** HIGH (Director can't view attached field-note photos)
**Task class:** bug-fix-production (DIAGNOSE FIRST)
**Harness-V2:** applies (emit POST_DEPLOY_AC_VERDICT)
**Source:** deputy finding bus #3425(1)

## Symptom
Field-notes card photos are attached + stored but DO NOT render in the review UI. Backend is FINE: `GET /api/ai-hotel/captures/{id}/images` returns HTTP 200 `{"images": ["data:image/jpeg;base64,…", …]}` — a list of bare data-URL STRINGS (deputy pulled + viewed them: capture 19 = 3 imgs, 17 = 6 imgs, all valid JPEGs). Repro: open any card with `image_count>0`, photos don't show.

## DIAGNOSE before fixing (Lesson #8 — exercise the live flow)
Do NOT trust this brief's hypothesis blindly. Reproduce live via Chrome MCP on prod, find the ACTUAL broken path, then fix. The detail-modal render at `outputs/static/ai-hotel.html` ~L945-953 already binds strings correctly (`t.src=src` where src is the data-URL string), so deputy's "expects objects" hypothesis may be wrong. Strongest candidates to check:
1. **`image_count` gating:** the photos block is gated by `if((c.image_count||0)>0)` (~L941). If the LIST payload (`GET /captures`) omits or zeroes `image_count` for these captures, the fetch never fires → blank. Verify what `image_count` the list actually returns for capture 19/17.
2. **Feed thumbnail path (~L775):** confirm whether the bug is the in-feed thumbnail vs the detail-modal full image. Director may mean the card preview, not the modal.
3. **A stale/cached deployed bundle** lacking the current render code (less likely post-no-cache fix, but confirm the live JS matches source).
4. **Capture-page** (`ai-hotel-capture.html`) own image preview, if that's the "review UI" Director used.

Pin the real cause, state it in the ship report, then make the minimal fix.

## Acceptance criteria
1. Live repro documented: which path was broken and why (one line, evidence-bound).
2. Opening a card with `image_count>0` renders all its photos (capture 17 = 6, 19 = 3) in the review UI.
3. Cards with no photos still render cleanly (no empty box / no error).
4. Thumbnail-in-feed + full-image-on-tap (#383 behavior) both still work — no regression.
5. Auth preserved: images only load with a valid key/session (no public leak).

## Kill criteria
1. Any regression to the #383 thumbnail/lazy-load behavior = rollback.
2. Full base64 images pulled back into the feed list payload = block (undoes #383).

## Gates
- G1: pytest (confirm no ai_hotel regression) + Chrome-MCP live repro of AC1–AC4 on prod.
- G2: /security-review only if the fix touches auth/image-serving; else N/A (declare reason).
- G3: lead merges on G1 clean.
- Post-deploy: emit POST_DEPLOY_AC_VERDICT, exercising AC2 on a real card live.
