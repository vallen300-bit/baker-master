# AI_HOTEL_SITE_VIDEO_EVIDENCE_1

**Status:** QUEUED — Phase 2 (Director GO 2026-06-19; do NOT dispatch until blocker cleared)
**Priority:** Medium
**Owner-on-dispatch:** b-code pool
**Dispatched_by:** lead (AH1)
**Source:** Director ask relayed via codex-arch bus #3388; AH1 queued 2026-06-19.

## Blocker (gate before dispatch)
Object-storage substrate must exist. **Video must NOT be stored as base64 in Postgres** (photos resize small enough; video does not). If no object storage is wired, this stays QUEUED — do not bloat Postgres.

## Sequencing
Dispatch only AFTER GPS capture (AI_HOTEL_GPS_CAPTURE_1) + audio persistence + Field Notes shelf are stable and live. Video is evidence-first; Site Card extraction must not depend on it in v1.

## Design (codex-arch #3388)
- Capture page: "Add short site video" control, max 10–30s initially.
- Client limits: mp4/webm/mov where browser supports; visible size/duration cap before upload.
- Backend: validate MIME + size + duration; upload binary to object storage; store metadata row.
- DB table: `ai_hotel_capture_media` (capture_id, media_type, storage_url/key, thumbnail_url/key, duration_seconds, size_bytes, created_at).
- Generate thumbnail/poster frame; optional lightweight model summary later.
- Field Notes detail: thumbnail + play/open. List view returns thumbnail/metadata only, never binary.
- Attach to same raw capture/card via `capture_id`, like photos/audio.

## Acceptance criteria
1. Video upload links to capture_id and survives reload.
2. Oversize/too-long video rejected at/before server without losing other capture data.
3. List view does not return binary video payload.
4. Detail view plays or opens the stored video.
5. Photo/audio/GPS path unaffected when video upload fails.

## Kill criteria
1. Any video stored as base64 in Postgres = block.
2. Any video failure loses the raw capture/card = rollback.
3. Upload p95 too slow/unreliable on iPhone = keep video off.

## Carried-forward gate notes (from AI_HOTEL_OBJECT_STORAGE_R2_1 #387 review)
1. **MANDATORY (codex G3 MEDIUM):** the upload handler MUST enforce a per-media business size cap (e.g. video ≤ N MB) and pass that exact value as `File.size` to `generate_presigned_put(max_bytes=...)` BEFORE presigning. The substrate signs the exact Content-Length but does NOT impose an app-level cap below the 5 GiB hard ceiling — the caller owns this. AC: oversize file rejected client-side AND server refuses to presign above the cap.
2. **Hardening (security-review minor):** prefer `storage_health(probe=False)` on the public `/api/health` path so it does not issue a live R2 `head_bucket` on every unauthenticated hit. Use probe=True only on an auth-gated readiness check.

## Substrate now available (post-#387)
`kbl/object_storage.py` is live: `put_object`, `generate_presigned_put/get` (expiry clamped ≤300s), `delete_object`, `storage_enabled()`, `storage_health()`. Table `ai_hotel_capture_media` exists. Env vars set by lead. Build video against THIS — do not add a second storage path.

## Product rationale
Short video proves arrival flow, frontage, traffic, noise, access, parking, surrounding quality better than stills. Useful for later investor/site-review decks.
