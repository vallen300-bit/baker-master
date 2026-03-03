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
        and "@lid" not in c.get("id", "")
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
    Cleans up the temp file after extraction.
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
    finally:
        try:
            filepath.unlink(missing_ok=True)
        except Exception:
            pass
