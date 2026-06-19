# BRIEF: AI_HOTEL_OBJECT_STORAGE_R2_1

**Dispatched_by:** lead (AH1) — reply-to: lead
**Owner:** deputy-codex
**Priority:** MEDIUM (gatekeeper for AI_HOTEL_SITE_VIDEO_EVIDENCE_1)
**Task class:** infra-foundation
**Harness-V2:** applies (new external substrate; emit POST_DEPLOY_AC_VERDICT)
**Director GO:** 2026-06-19 (storage-prep approved; R2 over S3 — no egress fees)

## Why
Site-visit cards need video clips. Video must NOT live in Postgres (base64 = block, per codex-arch #3388). We have NO object storage wired today (confirmed: no boto3/S3/R2 config in repo; photos+audio are base64 in PG). This brief lays the substrate so the video brief becomes a clean follow-on. Build the storage layer ONLY — do not build the video capture UI here.

## Scope (this brief)
A reusable, fault-tolerant object-storage module + a media-metadata table. Cloudflare R2 (S3-compatible, zero egress). No video UI, no capture-page changes.

## Deliverables
1. **`kbl/object_storage.py`** (or `tools/object_storage.py` — match repo convention) — thin S3-compatible client over R2 using `boto3` (endpoint = R2 S3 API). Functions:
   - `put_object(key, data, content_type) -> {key, size_bytes}` — server-side upload.
   - `generate_presigned_put(key, content_type, max_bytes, expires=300) -> url` — direct browser upload (so binaries never round-trip through the app server).
   - `generate_presigned_get(key, expires=300) -> url` — short-lived read URL for playback.
   - `delete_object(key)`.
   - All wrapped in try/except; every failure returns a structured error, never raises into a request handler (fault-tolerant hard rule).
2. **Config / env** — `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_ENDPOINT` (or derive). Read from env; NEVER hard-code. Document the 5 vars in the ship report for me to set in Render + 1Password. A `storage_enabled()` guard returns False cleanly when vars absent (so prod without keys degrades gracefully, doesn't 500).
3. **Migration** — `ai_hotel_capture_media` table: `id`, `capture_id` (FK to ai_hotel_captures), `media_type` (enum: video/image/audio), `storage_key` (R2 object key), `thumbnail_key` (nullable), `content_type`, `size_bytes`, `duration_seconds` (nullable), `created_at`. CHECK constraints on media_type + size_bytes >= 0. Idempotent, scoped by conrelid (don't repeat the GPS migration conname nit).
4. **`boto3` added to `requirements.txt`** (pin a version).
5. **Health probe** — extend `/api/baker/health` (or existing health surface) with a non-fatal `object_storage: ok|disabled|error` line so I can verify wiring live without uploading.

## Acceptance criteria
1. With R2 env vars set: `put_object` round-trips a test blob; `generate_presigned_get` URL fetches it back. (gate via a live-credential test that auto-skips when env absent, mirroring the TEST_DATABASE_URL pattern.)
2. With env vars ABSENT: module imports clean, `storage_enabled()` is False, no handler 500s, health shows `object_storage: disabled`.
3. Migration applies idempotently; re-run is a no-op; `ai_hotel_capture_media` exists with constraints.
4. Presigned PUT enforces `max_bytes` and content-type (oversize/wrong-type rejected by R2 policy or pre-sign conditions).
5. No R2 secret ever logged or returned in any API response.
6. Existing AI-Hotel photo/audio/GPS paths untouched (regression: full ai_hotel suite green).

## Kill criteria
1. Any secret logged or exposed in a response = block.
2. Any object-storage failure that 500s a request handler = block (must degrade soft).
3. Binaries proxied through the app server instead of presigned direct-to-R2 = block (defeats the purpose).
4. Editing an already-applied migration = block (new migration only).

## Foot-guns
- R2 endpoint is `https://<account_id>.r2.cloudflarestorage.com`; region must be `auto` for boto3.
- Presigned URLs must be SHORT-lived (≤5 min) — they are bearer credentials.
- Don't enable Qdrant embedding of any media (out of scope; separate ratification).
- I (lead) will create the R2 bucket + API token + set the 5 Render/1P env vars — list them explicitly in the ship report. Do NOT attempt to provision the R2 account yourself (Tier-C infra/procurement = my lane).

## Gates
- G1: pytest (live-cred test auto-skips without env; degrade-soft test runs always) + py_compile + singleton check.
- G2: /security-review (new external substrate + presigned-URL surface — mandatory).
- G3: lead routes to codex (auth/secret-handling surface) before merge.
- Post-deploy: I set env vars, then emit/confirm POST_DEPLOY_AC_VERDICT (health shows object_storage: ok; presigned round-trip live).

## Next (not this brief)
On merge + env live → dispatch AI_HOTEL_SITE_VIDEO_EVIDENCE_1 (design already in briefs/_tasks/, codex-arch #3388 shape) against this substrate.
