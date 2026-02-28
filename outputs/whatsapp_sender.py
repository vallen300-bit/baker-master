"""
Send WhatsApp messages via WAHA API.
Used by Baker to push alerts and respond to Director.
"""
import logging
import os
import httpx

logger = logging.getLogger("baker.output.whatsapp")

WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "https://baker-waha.onrender.com")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")
WAHA_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
DIRECTOR_WHATSAPP = "41799605092@c.us"  # Director's number, no + prefix

def send_whatsapp(text: str, chat_id: str = DIRECTOR_WHATSAPP) -> bool:
    """Send a text message via WAHA. Returns True on success."""
    try:
        headers = {}
        if WAHA_API_KEY:
            headers["X-Api-Key"] = WAHA_API_KEY
        with httpx.Client(timeout=15, headers=headers) as client:
            resp = client.post(
                f"{WAHA_BASE_URL}/api/sendText",
                json={
                    "session": WAHA_SESSION,
                    "chatId": chat_id,
                    "text": text,
                },
            )
            resp.raise_for_status()
            logger.info(f"WhatsApp sent to {chat_id}: {text[:80]}...")
            return True
    except Exception as e:
        logger.error(f"WhatsApp send failed: {e}")
        return False
