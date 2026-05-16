"""
Send WhatsApp messages via WAHA API.
Used by Baker to push alerts and respond to Director.
"""
import enum
import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("baker.output.whatsapp")

WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "https://baker-waha.onrender.com")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")
WAHA_API_KEY = os.getenv("WAHA_API_KEY_SEND", "") or os.getenv("WHATSAPP_API_KEY", "")
DIRECTOR_WHATSAPP = "41799605092@c.us"  # Director's number, no + prefix


def _phone_root(chat_id: str) -> str:
    """Extract the phone-digit prefix from a WhatsApp chat id.

    `41799605092@c.us` -> `41799605092`. `41799605092@s.whatsapp.net` ->
    `41799605092`. `10110470463618@lid` -> `10110470463618`. Empty string for
    unparseable input.
    """
    if not chat_id or "@" not in chat_id:
        return ""
    return chat_id.split("@", 1)[0]


# All phone digit-roots whose sends MUST short-circuit through the resolver
# and which trigger asymmetric Director-fail-closed handling on LID-DB error.
# Maintain as an explicit literal — adding a number is a one-line change here,
# and tests parametrized over this set automatically cover any addition.
DIRECTOR_PHONE_ROOTS = frozenset({
    "41799605092",   # Director Swiss primary (+41 79 960 50 92)
    "447588690632",  # Director-controlled Baker UK number (+44 7588 690632) — pre-protected
})

# Sanity assertion at module import: canonical DIRECTOR_WHATSAPP digits must
# be in the set. If someone changes one without the other, import fails loud.
assert _phone_root(DIRECTOR_WHATSAPP) in DIRECTOR_PHONE_ROOTS, (
    f"DIRECTOR_WHATSAPP {DIRECTOR_WHATSAPP!r} digit-root not in "
    f"DIRECTOR_PHONE_ROOTS {sorted(DIRECTOR_PHONE_ROOTS)!r} — fix the constants."
)


class _RecipientCheck(enum.Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    DEGRADED = "degraded"  # Non-Director only: LID-DB unreachable; allow + alarm.


_BAKER_SIGNATURE = "📋 *Baker AI — Office of Dimitry Vallen*\n\n"


def _resolve_to_active_chat_id(chat_id: str) -> str:
    """Route to the contact's most-recent active chat_id.

    Director's number is short-circuited on phone-digit match (handles
    @c.us, @s.whatsapp.net, future UK number, anything in DIRECTOR_PHONE_ROOTS).
    The behaviour-driven resolver below is correct only for *external* contacts
    whose own thread is the only place their number appears as sender.
    Director appears as sender across every chat he types in (WAHA captures
    his iPhone outbound), so the resolver must not run for him in any form.

    Why: 2026-05-08 incident — three T1 alerts mis-routed to a counterparty
    after Director typed a message to that counterparty on his iPhone. See
    `_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani.md`.

    Fails open: returns input chat_id on any error (non-Director only;
    Director short-circuit runs before any DB access).
    """
    if not chat_id or not chat_id.endswith("@c.us"):
        return chat_id
    if _phone_root(chat_id) in DIRECTOR_PHONE_ROOTS:
        return chat_id  # Hard short-circuit — never resolve any Director-owned address.
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


def _lid_belongs_to_phone(lid_chat_id: str, expected_phone_digits: str) -> Optional[bool]:
    """Look up whatsapp_lid_map. Returns True if the LID is registered for
    the given phone digits, False if explicitly absent, None on any DB error.

    Note: whatsapp_lid_map.phone is stored as `<digits>@c.us`, NOT bare digits.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM whatsapp_lid_map "
                "WHERE lid = %s AND phone = %s LIMIT 1",
                (lid_chat_id, f"{expected_phone_digits}@c.us"),
            )
            row = cur.fetchone()
            cur.close()
            return row is not None
        except Exception as e:
            logger.warning(f"whatsapp_lid_map lookup failed for {lid_chat_id}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return None
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"whatsapp_lid_map unavailable: {e}")
        return None


def _recipient_id_compatible(requested: str, actual: str) -> _RecipientCheck:
    """Classify whether `actual` is a safe resolution of `requested`.

    Asymmetric Director-fail-closed:
    - If `_phone_root(requested) in DIRECTOR_PHONE_ROOTS`, any non-SAFE outcome
      (including DB-unreachable on @lid lookup) collapses to UNSAFE — Director-
      target sends never run in DEGRADED mode.
    - Non-Director targets follow the standard SAFE/UNSAFE/DEGRADED triage.
    """
    if requested == actual:
        return _RecipientCheck.SAFE
    if _phone_root(requested) == _phone_root(actual):
        return _RecipientCheck.SAFE
    if not actual.endswith("@lid"):
        return _RecipientCheck.UNSAFE

    lookup = _lid_belongs_to_phone(actual, _phone_root(requested))
    if lookup is True:
        return _RecipientCheck.SAFE
    if lookup is False:
        return _RecipientCheck.UNSAFE

    # lookup is None -> DB error. Asymmetric Director-fail-closed kicks in.
    if _phone_root(requested) in DIRECTOR_PHONE_ROOTS:
        return _RecipientCheck.UNSAFE
    return _RecipientCheck.DEGRADED


def _alarm_slack_lid_db_degraded(requested: str, actual: str) -> None:
    """Alarm Slack #cockpit when recipient-id assertion runs in DEGRADED mode
    (LID-map DB unreachable, allowed-but-could-not-verify). Non-fatal."""
    try:
        from outputs.slack_notifier import post_to_channel
        from config.settings import config
        msg = (
            f"⚠️ Baker WhatsApp recipient-id assertion DEGRADED — "
            f"requested={requested} resolved={actual}. LID-map DB unreachable; "
            f"send was allowed. Investigate whatsapp_lid_map / Postgres health."
        )
        channel = config.slack.cockpit_channel_id
        post_to_channel(channel, msg, unfurl_links=False, unfurl_media=False)
    except Exception as e:
        logger.warning(f"Slack LID_MAP_UNAVAILABLE alarm dispatch failed (non-fatal): {e}")


def _log_send_to_baker_actions(
    requested_chat_id: str,
    actual_chat_id: str,
    text: str,
    success: bool,
    http_status: int = 0,
    error_message: str = "",
    path_taken: str = "unknown",
) -> None:
    """Audit every WhatsApp send attempt to baker_actions.
    Required by .claude/rules/api-safety.md (all writes log to baker_actions).
    Fails silently — logging must never break the send path.

    `path_taken` (v0.3, BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1): identifies
    which send-path branch executed. One of:
      - short_circuit_director
      - resolver_returned_clean
      - aborted_assertion_unsafe
      - lid_map_unavailable_fallback
      - lid_map_unavailable_director_fail_closed
    Default `unknown` so any future caller that forgets to pass it is visible
    in audit + logs (warning emitted below).
    """
    if path_taken == "unknown":
        logger.warning(
            f"baker_actions audit row written without path_taken (requested={requested_chat_id}); "
            f"caller missed BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1 contract."
        )
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
                "path_taken": path_taken,
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


# Director-facing allowlist. Add new values only after Director ratification.
# Anchor: Director directive 2026-05-15 — "Baker NEVER WhatsApps me about its own
# internal infrastructure. Counterparty / legal / deadline / VIP / financial only."
# Brief: BRIEF_BAKER_WA_DIRECTOR_FILTER_1.
DIRECTOR_WA_ALLOWED_KINDS = frozenset({
    "counterparty",      # AO / Hagenauer / Cupial / MOHG action or message
    "legal_threat",      # Steininger-ORF type media or legal escalation
    "deadline",          # Hard deadlines requiring Director action
    "vip_signal",        # VIP contact event (call, email, message) needing decision
    "financial",         # Investment / capital call / payment / banking event
    "director_inbound",  # Reply to Director's own outbound WA (user-initiated thread)
    "kbl_critical",      # KBL CRITICAL (Anthropic circuit / KBL cost cap) — Director-actionable infra; 5-min bucket dedupe upstream
})


def _log_director_blocked(text: str, kind: Optional[str]) -> None:
    """Audit a Director-bound WA send that was blocked at the chokepoint.

    Writes a `whatsapp_blocked` row to baker_actions for later review. Fails
    silently — the block itself must always proceed even if audit fails.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            payload = {
                "reason": "director_kind_not_allowlisted",
                "kind": kind,
                "text_preview": text[:200],
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
                    "whatsapp_blocked",
                    json.dumps(payload),
                    "whatsapp_sender",
                    False,
                    None,
                ),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning(f"whatsapp_blocked audit insert failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"whatsapp_blocked audit unavailable: {e}")


def send_whatsapp(
    text: str,
    chat_id: str = DIRECTOR_WHATSAPP,
    *,
    kind: Optional[str] = None,
) -> bool:
    """Send a text message via WAHA. Returns True on success.

    Messages to external contacts get a Baker signature prefix.
    Messages to the Director himself are sent without signature.

    Director-bound calls (any chat_id whose phone digit-root is in
    DIRECTOR_PHONE_ROOTS — Swiss primary or UK Baker-managed Director
    number) MUST pass an allowlisted `kind=` value or get blocked at the
    chokepoint (returns False, no HTTP call, audited as `whatsapp_blocked`
    in baker_actions). For non-Director chat_ids, `kind=` is not required.
    Allowlist: `DIRECTOR_WA_ALLOWED_KINDS`. Anchor: Director directive
    2026-05-15 ("Baker NEVER WhatsApps me about its own internal
    infrastructure"). Uses the existing DIRECTOR_PHONE_ROOTS primitive so
    adding a new Director-controlled number is a one-line change there.
    """
    requested_chat_id = chat_id

    # BAKER_WA_DIRECTOR_FILTER_1 chokepoint — Director-bound must have allowlisted kind.
    # Filter on phone-root set (not literal DIRECTOR_WHATSAPP) so the UK
    # Baker-managed Director number gets the same protection as the Swiss one.
    if _phone_root(chat_id) in DIRECTOR_PHONE_ROOTS:
        if kind is None or kind not in DIRECTOR_WA_ALLOWED_KINDS:
            logger.warning(
                "WA_DIRECTOR_BLOCKED: dropped Director-bound send. "
                "chat_id=%r kind=%r (allowed=%s). text_preview=%r",
                chat_id,
                kind,
                sorted(DIRECTOR_WA_ALLOWED_KINDS),
                text[:120],
            )
            _log_director_blocked(text, kind)
            return False

    # Filter: suppress cost alerts to Director (noisy, not actionable)
    if chat_id == DIRECTOR_WHATSAPP and any(kw in text.lower() for kw in ['cost alert', 'budget exceeded', 'daily spend', 'circuit breaker']):
        logger.info(f"WhatsApp cost alert to Director suppressed: {text[:80]}...")
        return True

    if chat_id != DIRECTOR_WHATSAPP:
        text = _BAKER_SIGNATURE + text

    # Signature gate runs on canonical @c.us; resolve to active LID after.
    actual_chat_id = _resolve_to_active_chat_id(chat_id)

    verdict = _recipient_id_compatible(requested_chat_id, actual_chat_id)
    requested_is_director = _phone_root(requested_chat_id) in DIRECTOR_PHONE_ROOTS

    # Determine path_taken first, then act consistently.
    if verdict == _RecipientCheck.SAFE and requested_is_director and requested_chat_id == actual_chat_id:
        path_taken = "short_circuit_director"
    elif verdict == _RecipientCheck.UNSAFE and requested_is_director:
        # Director-target collapsed from DEGRADED-grade outcome to UNSAFE per asymmetric policy.
        path_taken = "lid_map_unavailable_director_fail_closed"
    elif verdict == _RecipientCheck.UNSAFE:
        path_taken = "aborted_assertion_unsafe"
    elif verdict == _RecipientCheck.DEGRADED:
        path_taken = "lid_map_unavailable_fallback"
    else:  # SAFE, non-short-circuit
        path_taken = "resolver_returned_clean"

    if verdict == _RecipientCheck.UNSAFE:
        error_message = (
            f"recipient-id assertion FAILED: requested={requested_chat_id} "
            f"resolved={actual_chat_id} path_taken={path_taken}"
        )
        logger.error(f"WhatsApp send aborted: {error_message}")
        _log_send_to_baker_actions(
            requested_chat_id=requested_chat_id,
            actual_chat_id=actual_chat_id,
            text=text,
            success=False,
            http_status=0,
            error_message=error_message,
            path_taken=path_taken,
        )
        return False

    if verdict == _RecipientCheck.DEGRADED:
        # Non-Director only (Director DEGRADED has been collapsed to UNSAFE above).
        logger.warning(
            f"WhatsApp send DEGRADED: requested={requested_chat_id} "
            f"resolved={actual_chat_id} — LID-map DB unreachable, allowing"
        )
        _alarm_slack_lid_db_degraded(requested_chat_id, actual_chat_id)
        # Fall through to HTTP POST.

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
        path_taken=path_taken,
    )
    return success
