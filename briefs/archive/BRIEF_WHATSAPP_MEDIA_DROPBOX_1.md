# BRIEF: WHATSAPP_MEDIA_DROPBOX_1 — Persist WhatsApp media to Dropbox per PM

## Context
WhatsApp media attachments (images, PDFs, docs) are downloaded and text-extracted at webhook time, but the actual files are deleted immediately after. When AO PM receives a photo from Caroline (e.g. DHL tracking), it can reference the extracted text but cannot link to the image itself. Director wants media stored in each PM's Dropbox section as a shared reference point between Director and PM agents.

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: None (Dropbox client, WAHA media download, PM signal detector all exist)

---

## Feature 1: Add media columns to whatsapp_messages

### Problem
`whatsapp_messages` has no columns for media metadata. After text extraction, all trace of the original file is lost.

### Current State
Table has 8 columns: `id, sender, sender_name, chat_id, full_text, timestamp, is_director, ingested_at`.
File: `memory/store_back.py` lines 952-977 — `store_whatsapp_message()`.

### Implementation

**Step 1a: ALTER TABLE migration** — add to `_ensure_tables()` in `memory/store_back.py` (after the CREATE TABLE for whatsapp_messages, around line 950):

```python
# WHATSAPP-MEDIA-DROPBOX-1: media metadata columns
cur.execute("""
    ALTER TABLE whatsapp_messages
    ADD COLUMN IF NOT EXISTS media_mimetype TEXT,
    ADD COLUMN IF NOT EXISTS media_dropbox_path TEXT,
    ADD COLUMN IF NOT EXISTS media_size_bytes INTEGER
""")
```

**Step 1b: Update `store_whatsapp_message()`** — add optional params and include in INSERT:

```python
def store_whatsapp_message(self, msg_id: str, sender: str = None,
                           sender_name: str = None, chat_id: str = None,
                           full_text: str = None, timestamp: str = None,
                           is_director: bool = False,
                           media_mimetype: str = None,
                           media_dropbox_path: str = None,
                           media_size_bytes: int = None) -> bool:
    """Upsert a full WhatsApp message. Returns True on success."""
    conn = self._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO whatsapp_messages
                (id, sender, sender_name, chat_id, full_text, timestamp, is_director,
                 media_mimetype, media_dropbox_path, media_size_bytes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                full_text = EXCLUDED.full_text,
                media_mimetype = COALESCE(EXCLUDED.media_mimetype, whatsapp_messages.media_mimetype),
                media_dropbox_path = COALESCE(EXCLUDED.media_dropbox_path, whatsapp_messages.media_dropbox_path),
                media_size_bytes = COALESCE(EXCLUDED.media_size_bytes, whatsapp_messages.media_size_bytes),
                ingested_at = NOW()
        """, (msg_id, sender, sender_name, chat_id, full_text, timestamp, is_director,
              media_mimetype, media_dropbox_path, media_size_bytes))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        logger.error(f"store_whatsapp_message failed: {e}")
        conn.rollback()
        return False
    finally:
        self._put_conn(conn)
```

### Key Constraints
- COALESCE on UPDATE prevents overwriting media fields if message is re-upserted without media data
- `conn.rollback()` in except block (Lesson #2)

---

## Feature 2: Upload media to Dropbox at webhook time

### Problem
WAHA media URLs expire (24-48h). Must capture the file at webhook time, not later.

### Current State
File: `triggers/waha_webhook.py` lines 792-815. Media is downloaded via `download_media_file()`, text extracted via `extract_media_text()`, then temp file is deleted via `os.unlink()`.

### Implementation

**Step 2a: Add Dropbox upload helper** to `triggers/waha_client.py` (after `extract_media_text`, ~line 194):

```python
# --- PM media Dropbox persistence ---
_FALLBACK_MEDIA_FOLDER = "/Baker-Project/WhatsApp-Media"
MAX_MEDIA_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — skip Dropbox upload for large video/audio


def _get_pm_media_folder(pm_slug: str) -> str:
    """Get Dropbox media folder for a PM from PM_REGISTRY. Falls back to generic folder."""
    if not pm_slug:
        return _FALLBACK_MEDIA_FOLDER
    try:
        from orchestrator.capability_runner import PM_REGISTRY
        config = PM_REGISTRY.get(pm_slug, {})
        return config.get("media_folder", _FALLBACK_MEDIA_FOLDER)
    except Exception:
        return _FALLBACK_MEDIA_FOLDER


def upload_media_to_dropbox(filepath: Path, sender_name: str, mimetype: str,
                            pm_slug: str = None) -> tuple:
    """
    Upload a WhatsApp media file to the appropriate PM's Dropbox folder.
    Returns (dropbox_path, size_bytes) or (None, 0) on failure.
    Skips upload if file exceeds MAX_MEDIA_UPLOAD_BYTES (10 MB).

    Folder structure:
      {PM_FOLDER}/{sender_name}/{YYYY-MM-DD}_{filename}
    """
    from datetime import date

    size_bytes = filepath.stat().st_size
    if size_bytes > MAX_MEDIA_UPLOAD_BYTES:
        logger.warning(f"Skipping Dropbox upload: {mimetype} too large ({size_bytes} bytes, limit {MAX_MEDIA_UPLOAD_BYTES})")
        return None, size_bytes  # still return size for DB record

    base_folder = _get_pm_media_folder(pm_slug)
    safe_sender = "".join(c for c in (sender_name or "Unknown") if c.isalnum() or c in " _-").strip()
    if not safe_sender:
        safe_sender = "Unknown"

    date_prefix = date.today().isoformat()
    filename = f"{date_prefix}_{filepath.name}"
    dropbox_path = f"{base_folder}/{safe_sender}/{filename}"

    try:
        from triggers.dropbox_client import DropboxClient
        client = DropboxClient._get_global_instance()
        result = client.upload_file(str(filepath), dropbox_path)
        actual_path = result.get("path_display", dropbox_path)
        logger.info(f"Media uploaded to Dropbox: {actual_path} ({size_bytes} bytes)")
        return actual_path, size_bytes
    except Exception as e:
        logger.warning(f"Dropbox media upload failed (non-fatal): {e}")
        return None, 0
```

**NOTE:** No hardcoded `_PM_MEDIA_FOLDERS` dict. The `_get_pm_media_folder()` reads directly from `PM_REGISTRY` (Feature 3). Single source of truth.

**Step 2b: Modify webhook handler** in `triggers/waha_webhook.py`. Replace the media handling block (lines 792-815) with:

```python
    # --- Media handling: download, extract text, persist to Dropbox ---
    media_text = ""
    media_mimetype = None
    media_dropbox_path = None
    media_size_bytes = None
    if has_media:
        try:
            from triggers.waha_client import (
                download_media_file, extract_media_text, is_extractable,
                upload_media_to_dropbox,
            )

            media = payload.get("media") or {}
            media_url = media.get("url", "")
            mimetype = media.get("mimetype", "")
            media_mimetype = mimetype or None

            if media_url:
                filepath = download_media_file(media_url)
                if filepath:
                    try:
                        # 1. Upload to Dropbox FIRST (before extraction, which may be slow)
                        try:
                            from orchestrator.pm_signal_detector import detect_relevant_pms_whatsapp
                            pm_slugs = detect_relevant_pms_whatsapp(sender_name, message_body or "")
                            pm_slug = pm_slugs[0] if pm_slugs else None
                        except Exception:
                            pm_slug = None

                        media_dropbox_path, media_size_bytes = upload_media_to_dropbox(
                            filepath, sender_name, mimetype, pm_slug=pm_slug,
                        )

                        # 2. Extract text (images → Vision, docs → extractors)
                        if is_extractable(mimetype):
                            media_text = extract_media_text(filepath, mimetype)
                            if media_text:
                                logger.info(f"Extracted {len(media_text)} chars from WA media ({mimetype})")
                    finally:
                        # 3. Clean up temp file — ALWAYS runs, even if extract/upload fails
                        try:
                            import os
                            os.unlink(filepath)
                        except OSError:
                            pass
        except Exception as e:
            logger.warning(f"WhatsApp media processing failed (continuing with text only): {e}")
```

**Step 2c: Pass media metadata to store** — update the `store.store_whatsapp_message()` call (line ~830):

```python
    # ARCH-7: Store full WhatsApp message to PostgreSQL
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.store_whatsapp_message(
            msg_id=msg_id,
            sender=sender,
            sender_name=sender_name,
            chat_id=sender,
            full_text=combined_body,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else None,
            is_director=(sender == DIRECTOR_WHATSAPP),
            media_mimetype=media_mimetype,
            media_dropbox_path=media_dropbox_path,
            media_size_bytes=media_size_bytes,
        )
    except Exception as _e:
        logger.warning(f"Failed to store WhatsApp msg {msg_id} to PostgreSQL (non-fatal): {_e}")
```

### Key Constraints
- Dropbox upload is **non-fatal** — if it fails, text extraction still works as before
- **File size cap**: Files > 10 MB are skipped for Dropbox upload (video/audio can be 10-50MB+, `upload_file()` reads entire file into memory). Size is still recorded in DB. Logged as warning.
- **Temp file lifecycle — caller owns cleanup**: Currently `extract_media_text` deletes the file in its `finally` block (waha_client.py line ~193). This creates a conflict: Dropbox upload needs the file, but extraction deletes it. **Fix**: Remove the `finally: unlink` from `extract_media_text()` — the webhook handler's `finally` block is the single cleanup point. Both callers (webhook + backfill script) already do their own cleanup.
- **Upload BEFORE extraction**: Dropbox upload runs first, then text extraction. This ensures the file is persisted even if the Vision API times out on a large image.
- **PM detection uses `message_body`**: `detect_relevant_pms_whatsapp(sender_name, message_body or "")` — passes the caption text so keyword-based PM routing works for captioned media (e.g., image with "RG7 update" routes to ao_pm).

```python
def extract_media_text(filepath: Path, mimetype: str = "") -> str:
    """Extract text from a downloaded media file.
    Images → Claude Vision. Documents → text extractors.
    Returns extracted text, or empty string on failure.
    NOTE: Caller is responsible for cleaning up the temp file.
    """
    from tools.ingest.extractors import IMAGE_EXTENSIONS

    ext = filepath.suffix.lower()
    try:
        if ext in IMAGE_EXTENSIONS:
            from tools.ingest.extractors import extract_image
            return extract_image(filepath, image_type="auto")
        else:
            from tools.ingest.extractors import extract
            return extract(filepath)
    except Exception as e:
        logger.warning(f"Media text extraction failed for {filepath.name}: {e}")
        return ""
    # REMOVED: finally block that deleted filepath — caller owns cleanup
```

### Verification
```sql
-- Check media was stored
SELECT id, sender_name, media_mimetype, media_dropbox_path, media_size_bytes
FROM whatsapp_messages
WHERE media_dropbox_path IS NOT NULL
ORDER BY ingested_at DESC LIMIT 10;
```

---

## Feature 3: PM media folder configuration

### Problem
Each PM needs a known Dropbox folder for its media. The mapping must be easy to extend when new PMs are added.

### Current State
`PM_REGISTRY` in `orchestrator/capability_runner.py` (line 44) holds all PM config. No media folder field exists.

### Implementation

Add `"media_folder"` to each PM entry in `PM_REGISTRY` (orchestrator/capability_runner.py):

For `ao_pm` (after `"peer_pms": ["movie_am"]`, ~line 96):
```python
        "media_folder": "/Baker-Project/01_Projects/Active_Projects/Oskolkov/Media and Files",
```

For `movie_am` (after `"peer_pms": ["ao_pm"]`, ~line 112):
```python
        "media_folder": "/Baker-Project/01_Projects/Active_Projects/MOVIE/Media and Files",
```

The `_get_pm_media_folder()` helper in `waha_client.py` (defined in Feature 2) already reads from `PM_REGISTRY`. No hardcoded folder mapping exists — single source of truth.

### Key Constraints
- New PMs get media support automatically by adding `media_folder` to their registry entry
- If no `media_folder` configured, falls back to `_FALLBACK_MEDIA_FOLDER` (`/Baker-Project/WhatsApp-Media`)

### Also add MIME extensions for non-extractable types

In `waha_client.py`, add to `_MIME_TO_EXT` dict (~line 112):
```python
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "video/mp4": ".mp4",
```
This ensures non-extractable media gets proper file extensions in Dropbox instead of `.bin`.

---

## Files Modified
- `memory/store_back.py` — ALTER TABLE + updated `store_whatsapp_message()` with 3 new params
- `triggers/waha_webhook.py` — Media block: add Dropbox upload + PM detection + pass metadata to store
- `triggers/waha_client.py` — Add `upload_media_to_dropbox()`, `_get_pm_media_folder()`. Remove `finally: unlink` from `extract_media_text()`
- `orchestrator/capability_runner.py` — Add `media_folder` to PM_REGISTRY entries

## Do NOT Touch
- `outputs/whatsapp_sender.py` — outbound only, no media changes needed
- `scripts/extract_whatsapp.py` — backfill script, separate concern (can add media backfill later)
- `orchestrator/agent.py` — PM tool definitions unchanged (agents read `media_dropbox_path` via `baker_raw_query`)
- `triggers/dropbox_client.py` — `upload_file()` works as-is, no changes needed

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('triggers/waha_client.py', doraise=True)"`
4. `python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"`
5. After deploy: send a test image via WhatsApp → verify Dropbox upload + DB record
6. Verify text extraction still works (not broken by removing `finally: unlink`)
7. Verify fallback: send image from unknown sender → check `WhatsApp-Media/` folder
8. Check Render memory stays stable (no /tmp accumulation — `os.unlink` still runs in webhook)

## Verification SQL
```sql
-- After sending a test image via WhatsApp:
SELECT id, sender_name, media_mimetype, media_dropbox_path, media_size_bytes, ingested_at
FROM whatsapp_messages
WHERE media_dropbox_path IS NOT NULL
ORDER BY ingested_at DESC LIMIT 5;

-- Confirm schema migration ran:
SELECT column_name FROM information_schema.columns
WHERE table_name = 'whatsapp_messages' AND column_name LIKE 'media_%';
-- Expected: media_mimetype, media_dropbox_path, media_size_bytes
```

## Memory Impact
- **Render**: Zero. Files downloaded to /tmp, uploaded to Dropbox, deleted. Same as today plus one HTTP upload.
- **Dropbox**: ~50-500KB per media file. Typical volume: a few files/day.
- **PostgreSQL**: 3 new TEXT/INTEGER columns, nullable. Negligible.
