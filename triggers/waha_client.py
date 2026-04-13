"""
WAHA (WhatsApp HTTP API) client for Baker.
Wraps REST endpoints for chat listing, message fetching, and media download.

Used by:
  - scripts/extract_whatsapp.py (backfill)
  - triggers/waha_webhook.py (live media download)
"""
import logging
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from config.settings import config

logger = logging.getLogger("baker.waha_client")

# WAHA returns media URLs pointing to its internal address.
# These must be rewritten to the public Render URL.
_LOCAL_URL_PREFIX = "http://0.0.0.0:10000"


def _headers() -> dict:
    h = {}
    if config.waha.api_key:
        h["X-Api-Key"] = config.waha.api_key
    return h


def _rewrite_media_url(url: str) -> str:
    """Rewrite local WAHA media URLs to public Render URL."""
    if url and url.startswith(_LOCAL_URL_PREFIX):
        return url.replace(_LOCAL_URL_PREFIX, config.waha.base_url, 1)
    return url


# ------------------------------------------------------------------
# Session status (WAHA-SILENT-GUARD-1)
# ------------------------------------------------------------------

def get_session_status(session: str = None) -> dict:
    """WAHA-SILENT-GUARD-1: Check WAHA session status.
    Returns {"status": "WORKING", ...} or {"error": "..."}.
    """
    if session is None:
        session = config.waha.session
    try:
        resp = httpx.get(
            f"{config.waha.base_url}/api/sessions/{session}",
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------------
# LID Resolution (WHATSAPP-LID-RESOLUTION-1)
# ------------------------------------------------------------------

_lid_mem_cache: dict[str, Optional[str]] = {}


def resolve_lid(lid: str) -> Optional[str]:
    """Resolve a @lid WhatsApp ID to a @c.us phone number.

    Resolution order:
    1. In-memory cache (instant)
    2. PostgreSQL whatsapp_lid_map table (fast)
    3. WAHA API GET /api/{session}/lids/{lid} (network call)

    Returns @c.us phone string or None if unresolvable.
    Caches result at all levels (including None to avoid re-querying).
    """
    if not lid or not lid.endswith("@lid"):
        return None

    # 1. Memory cache
    if lid in _lid_mem_cache:
        return _lid_mem_cache[lid]

    # 2. PostgreSQL cache
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        cached = store.get_lid_phone(lid)
        if cached:
            _lid_mem_cache[lid] = cached
            return cached
    except Exception:
        pass

    # 3. WAHA API
    phone = None
    try:
        lid_escaped = lid.replace("@", "%40")
        url = f"{config.waha.base_url}/api/{config.waha.session}/lids/{lid_escaped}"
        resp = httpx.get(url, headers=_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            pn = data.get("pn")
            if pn:
                phone = pn
                logger.info(f"LID resolved via API: {lid} → {phone}")
    except Exception as e:
        logger.warning(f"WAHA LID API call failed for {lid}: {e}")

    # Cache result (even None — avoids re-querying unresolvable LIDs)
    _lid_mem_cache[lid] = phone
    if phone:
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.cache_lid_phone(lid, phone, source="api")
        except Exception:
            pass

    return phone


# ------------------------------------------------------------------
# Contacts endpoint (INTERACTION-PIPELINE-1)
# ------------------------------------------------------------------

def list_contacts(limit: int = 500) -> list[dict]:
    """
    GET /api/contacts/all?session={session}&limit=N
    Returns WhatsApp address book contacts with real display names.
    """
    url = f"{config.waha.base_url}/api/contacts/all"
    params = {"session": config.waha.session, "limit": limit}
    try:
        with httpx.Client(timeout=30, headers=_headers()) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
        contacts = resp.json()
        return [
            c for c in contacts
            if c.get("id", "").endswith("@c.us")
            and not c.get("isGroup", False)
            and not c.get("isMe", False)
        ]
    except Exception as e:
        logger.warning(f"list_contacts failed: {e}")
        return []


# ------------------------------------------------------------------
# Chat & message endpoints
# ------------------------------------------------------------------

def list_chats(limit: int = 200) -> list[dict]:
    """
    GET /api/{session}/chats?limit=N
    Returns chat objects, filtering out broadcasts and lid-type entries.
    """
    url = f"{config.waha.base_url}/api/{config.waha.session}/chats"
    with httpx.Client(timeout=30, headers=_headers()) as client:
        resp = client.get(url, params={"limit": limit})
        resp.raise_for_status()
    chats = resp.json()
    return [
        c for c in chats
        if not c.get("id", "").startswith("status@")
    ]


def fetch_messages(
    chat_id: str,
    limit: int = 100,
    download_media: bool = False,
) -> list[dict]:
    """
    GET /api/{session}/chats/{chatId}/messages
    Returns messages in chronological order (oldest first).
    """
    url = f"{config.waha.base_url}/api/{config.waha.session}/chats/{chat_id}/messages"
    params = {
        "limit": limit,
        "downloadMedia": str(download_media).lower(),
    }
    with httpx.Client(timeout=60, headers=_headers()) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    messages = resp.json()
    messages.reverse()  # API returns newest-first; we want chronological
    return messages


# ------------------------------------------------------------------
# Media download & text extraction
# ------------------------------------------------------------------

_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "video/mp4": ".mp4",
}

# Media types we can extract text from (skip audio/video)
_EXTRACTABLE_MIMES = {
    "image/jpeg", "image/png", "image/webp", "image/heic",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv",
}


def is_extractable(mimetype: str) -> bool:
    """Return True if we can extract text from this media type."""
    return mimetype.split(";")[0].strip().lower() in _EXTRACTABLE_MIMES


def download_media_file(media_url: str) -> Optional[Path]:
    """
    Download a media file from WAHA to /tmp.
    Rewrites internal URLs to public Render URL.
    Returns Path to temp file, or None on failure.
    """
    url = _rewrite_media_url(media_url)
    if not url:
        return None
    try:
        with httpx.Client(timeout=60, headers=_headers()) as client:
            resp = client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "application/octet-stream")
        ext = _MIME_TO_EXT.get(content_type.split(";")[0].strip().lower(), ".bin")

        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=ext, prefix="wa_media_"
        )
        tmp.write(resp.content)
        tmp.close()
        logger.info(f"Downloaded media: {url} -> {tmp.name} ({len(resp.content)} bytes)")
        return Path(tmp.name)
    except Exception as e:
        logger.warning(f"Media download failed for {url}: {e}")
        return None


def extract_media_text(filepath: Path, mimetype: str = "") -> str:
    """
    Extract text from a downloaded media file.
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


# ------------------------------------------------------------------
# PM media Dropbox persistence (WHATSAPP-MEDIA-DROPBOX-1)
# ------------------------------------------------------------------

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
