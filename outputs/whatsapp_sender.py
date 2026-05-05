"""
Send WhatsApp messages via WAHA API.
Used by Baker to push alerts and respond to Director.
"""
import json
import logging
import os
import httpx

logger = logging.getLogger("baker.output.whatsapp")

WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "https://baker-waha.onrender.com")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")
WAHA_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
DIRECTOR_WHATSAPP = "41799605092@c.us"  # Director's number, no + prefix

_BAKER_SIGNATURE = "📋 *Baker AI — Office of Dimitry Vallen*\n\n"


def _resolve_to_active_chat_id(chat_id: str) -> str:
    """Route to the contact's most-recent active chat_id.

    Why: WhatsApp can migrate a contact's chat from @c.us / @s.whatsapp.net to
    @lid (privacy-preserving). After migration the legacy address becomes a
    dead chat — sends silently 4xx. We pick the chat_id from this contact's
    most recent inbound message: that is, by definition, the live route.

    Behaviour-driven (not static map) because some contacts have a LID
    mapping but still receive on the legacy address (Director). We must not
    break those by force-routing to a dormant LID.

    Fails open: returns input chat_id on any error.
    """
    if not chat_id or not chat_id.endswith("@c.us"):
        return chat_id
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return chat_id
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT chat_id FROM whatsapp_messages "
                "WHERE sender = %s ORDER BY timestamp DESC LIMIT 1",
                (chat_id,),
            )
            row = cur.fetchone()
            cur.close()
            if row and row[0] and row[0] != chat_id:
                logger.info(f"WhatsApp recipient {chat_id} routed to active chat {row[0]}")
                return row[0]
            return chat_id
        except Exception as e:
            logger.warning(f"Active-chat lookup failed for {chat_id}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return chat_id
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Active-chat resolution unavailable: {e}")
        return chat_id


def _log_send_to_baker_actions(
    requested_chat_id: str,
    actual_chat_id: str,
    text: str,
    success: bool,
    http_status: int = 0,
    error_message: str = "",
) -> None:
    """Audit every WhatsApp send attempt to baker_actions.
    Required by .claude/rules/api-safety.md (all writes log to baker_actions).
    Fails silently — logging must never break the send path.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            payload = {
                "requested_chat_id": requested_chat_id,
                "actual_chat_id": actual_chat_id,
                "text_preview": text[:200],
                "http_status": http_status,
            }
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, target_task_id, target_space_id, payload,
                     trigger_source, success, error_message)
                VALUES (%s, NULL, NULL, %s::jsonb, %s, %s, %s)
                """,
                (
                    "whatsapp_send",
                    json.dumps(payload),
                    "whatsapp_sender",
                    success,
                    error_message[:500] if error_message else None,
                ),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning(f"baker_actions audit insert failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"baker_actions audit unavailable: {e}")


def send_whatsapp(text: str, chat_id: str = DIRECTOR_WHATSAPP) -> bool:
    """Send a text message via WAHA. Returns True on success.
    Messages to external contacts get a Baker signature prefix.
    Messages to the Director himself are sent without signature.
    """
    requested_chat_id = chat_id

    # Filter: suppress cost alerts to Director (noisy, not actionable)
    if chat_id == DIRECTOR_WHATSAPP and any(kw in text.lower() for kw in ['cost alert', 'budget exceeded', 'daily spend', 'circuit breaker']):
        logger.info(f"WhatsApp cost alert to Director suppressed: {text[:80]}...")
        return True

    if chat_id != DIRECTOR_WHATSAPP:
        text = _BAKER_SIGNATURE + text

    # Signature gate runs on canonical @c.us; resolve to active LID after.
    actual_chat_id = _resolve_to_active_chat_id(chat_id)

    http_status = 0
    error_message = ""
    success = False
    try:
        headers = {}
        if WAHA_API_KEY:
            headers["X-Api-Key"] = WAHA_API_KEY
        with httpx.Client(timeout=15, headers=headers) as client:
            resp = client.post(
                f"{WAHA_BASE_URL}/api/sendText",
                json={
                    "session": WAHA_SESSION,
                    "chatId": actual_chat_id,
                    "text": text,
                },
            )
            http_status = resp.status_code
            if resp.is_success:
                logger.info(f"WhatsApp sent to {actual_chat_id}: {text[:80]}...")
                success = True
            else:
                body = (resp.text or "")[:500]
                error_message = f"HTTP {resp.status_code}: {body}"
                logger.error(f"WhatsApp send failed to {actual_chat_id}: {error_message}")
    except Exception as e:
        error_message = f"{type(e).__name__}: {e}"
        logger.error(f"WhatsApp send exception to {actual_chat_id}: {error_message}")

    _log_send_to_baker_actions(
        requested_chat_id=requested_chat_id,
        actual_chat_id=actual_chat_id,
        text=text,
        success=success,
        http_status=http_status,
        error_message=error_message,
    )
    return success
