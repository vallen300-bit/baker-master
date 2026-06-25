"""M365_GRAPH_MAIL_POLL_2: Microsoft Graph inbound mail poller (delta query).

Independent source adapter — mirrors triggers/exchange_poller.py. Produces
thread dicts and hands them to the shared sink _process_email_threads().
Dormant unless BAKER_USE_GRAPH=true (GraphClient.is_ready() is the single gate).
Never raises to the scheduler; one failure must not affect other pollers.
"""
from __future__ import annotations
import base64
import logging
from datetime import datetime, timezone

from kbl.graph_client import GraphClient
from config.settings import GraphConfig
from triggers.state import trigger_state
from triggers.sentinel_health import report_success, report_failure, should_skip_poll

logger = logging.getLogger(__name__)

_SOURCE = "graph_mail_poll"          # watermark/cursor key
_FOLDER = "Inbox"
_SELECT = "id,conversationId,subject,from,receivedDateTime,body,isDraft,hasAttachments"
_ATTACHMENT_SELECT = "id,name,contentType,size,contentBytes,isInline"
_attachment_store_missing_logged = False

# M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1: messages whose id is in immutable-id form
# (base64url: contains '-' or '_') are NOT addressable by a default-namespace
# by-id read. Graph resolves them only when the request carries
# Prefer: IdType="ImmutableId". Standard (AAMk) ids use base64 ('+'/'/') and must
# be read WITHOUT the header. We detect the form per-message and set the header
# only for immutable ids, so the working AAMk path is never regressed.
_IMMUTABLE_ID_HEADER = {"Prefer": 'IdType="ImmutableId"'}

# Surfaced, never-silently-dropped counter: incremented whenever a message with
# hasAttachments=true yields zero persisted attachment rows because the by-id
# Graph fetch FAILED (not because the message is genuinely attachment-empty).
# Exposed for the regression test + any future health probe.
_attachment_fetch_failures = 0


def _is_immutable_message_id(message_id: str) -> bool:
    """True if message_id is in Graph immutable-id form (base64url: '-'/'_').

    Standard Exchange ids are base64 and use '+' and '/'; immutable ids are
    base64url and use '-' and '_'. The presence of a base64url-only char is the
    canonical discriminator (Microsoft Graph immutable-id contract).
    """
    return ("-" in message_id) or ("_" in message_id)


def attachment_fetch_failures() -> int:
    """Read the surfaced attachment-fetch-failure counter (test/health hook)."""
    return _attachment_fetch_failures


def _html_to_text(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:10000]              # cap, mirroring exchange_poller


def _to_thread(m: dict) -> dict | None:
    if m.get("isDraft"):
        return None
    sender = (m.get("from") or {}).get("emailAddress") or {}
    body = (m.get("body") or {})
    text_block = (
        f"Email Thread: {m.get('subject','(no subject)')}\n"
        f"From: {sender.get('name','')} <{sender.get('address','')}>\n"
        f"Date: {m.get('receivedDateTime','')}\n\n"
        f"{_html_to_text(body.get('content',''))}"
    )
    return {
        "text": text_block,
        "metadata": {
            "source": "graph",
            "thread_id": m.get("conversationId") or m.get("id"),
            "subject": m.get("subject", ""),
            "primary_sender": sender.get("name", ""),
            "primary_sender_email": sender.get("address", ""),
            "received_date": m.get("receivedDateTime", ""),
        },
    }


def _insert_live_attachment(
    *,
    message_id: str,
    filename: str,
    mime_type: str,
    payload_bytes: bytes,
):
    """Best-effort live attachment persistence; never breaks Graph ingest."""
    global _attachment_store_missing_logged
    if not payload_bytes:
        return None
    try:
        from kbl.attachment_store import insert_attachment
    except (ImportError, ModuleNotFoundError) as e:
        if not _attachment_store_missing_logged:
            logger.warning("Graph attachment store unavailable (non-fatal): %s", type(e).__name__)
            _attachment_store_missing_logged = True
        return None
    try:
        return insert_attachment(
            message_id=message_id,
            source="graph",
            filename=filename,
            mime_type=mime_type,
            payload_bytes=payload_bytes,
        )
    except Exception as e:
        logger.warning("Graph attachment persist failed (non-fatal): %s", type(e).__name__)
        return None


def _capture_graph_attachments(client: GraphClient, m: dict) -> int:
    """Store Graph file attachments for a live message, non-fatally.

    M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1: sets Prefer: IdType="ImmutableId" when
    the message id is in immutable form, so the by-id attachment read succeeds
    (it silently failed before, dropping attachments while the body persisted).
    A failed fetch on a hasAttachments=true message is surfaced LOUDLY (ERROR +
    counter), never silently dropped.
    """
    global _attachment_fetch_failures
    if not m.get("hasAttachments") or not m.get("id"):
        return 0
    message_id = m.get("id")
    extra_headers = _IMMUTABLE_ID_HEADER if _is_immutable_message_id(message_id) else None
    try:
        page = client.get(
            f"/users/{client.cfg.mail_user}/messages/{message_id}/attachments",
            params={"$select": _ATTACHMENT_SELECT, "$top": 50},
            extra_headers=extra_headers,
        )
        if page is None:
            # Fetch FAILED for a message that declares attachments — this is the
            # silent-skip class bug (Lesson #107). Surface it loudly; do NOT let
            # it look like a true-empty message.
            _attachment_fetch_failures += 1
            logger.error(
                "Graph attachment fetch FAILED (hasAttachments=true, 0 stored): "
                "id_form=%s — attachments NOT persisted, surfaced (count=%d)",
                "immutable" if extra_headers else "standard",
                _attachment_fetch_failures,
            )
            return 0
        stored = 0
        for att in page.get("value", []):
            if att.get("isInline"):
                continue
            encoded = att.get("contentBytes")
            if not encoded:
                continue
            try:
                payload = base64.b64decode(encoded)
            except Exception as e:
                logger.warning("Graph attachment decode failed (non-fatal): %s", type(e).__name__)
                continue
            att_id = _insert_live_attachment(
                message_id=message_id,
                filename=att.get("name", ""),
                mime_type=att.get("contentType") or "application/octet-stream",
                payload_bytes=payload,
            )
            if att_id:
                stored += 1
        if stored == 0:
            # Fetch SUCCEEDED but nothing persisted — surfaced (not silent), yet
            # distinct from the FAILED path above: this is benign (all-inline /
            # signature images), so WARNING + no failure-counter bump.
            logger.warning(
                "Graph attachments: hasAttachments=true but 0 file rows stored "
                "(fetch ok — likely all-inline). id_form=%s",
                "immutable" if extra_headers else "standard",
            )
        return stored
    except Exception as e:
        # An exception on a hasAttachments=true message also dropped attachments —
        # surface loudly + count, same class as the None-fetch failure above.
        _attachment_fetch_failures += 1
        logger.error(
            "Graph attachment capture FAILED (hasAttachments=true): %s — "
            "attachments NOT persisted, surfaced (count=%d)",
            type(e).__name__,
            _attachment_fetch_failures,
        )
        return 0


def poll_graph_mail() -> list:
    """Pull new mail via delta query. Returns thread dicts (same shape as poll_exchange).

    RAISES on a ready-but-None response (G0 Finding 1): GraphClient never raises and
    returns None on token/HTTP failure (401/403/429/500). When is_ready() is True, a
    None from the delta/nextLink call is a FAILURE, not an empty inbox — raise so the
    caller reports failure and does NOT advance the watermark/cursor. A genuinely empty
    inbox returns a real page with value:[] (no raise). Returns [] only when dormant.
    """
    client = GraphClient(GraphConfig())
    if not client.is_ready():
        return []                    # dormant gate — no token, no HTTP

    results: list = []
    cursor = trigger_state.get_cursor(_SOURCE)   # stored @odata.deltaLink, or None on first run
    if cursor:
        page = client.get_url(cursor)            # host-pinned follow
    else:
        page = client.get(
            f"/users/{client.cfg.mail_user}/mailFolders/{_FOLDER}/messages/delta",
            params={"$select": _SELECT, "$top": 50},
        )
    if page is None:                 # ready but no response → auth/HTTP/429 failure, NOT empty
        raise RuntimeError("graph mail: delta call returned None while ready (auth/HTTP failure)")

    guard = 0
    while page is not None and guard < 50:       # bounded pagination
        guard += 1
        for m in page.get("value", []):
            if "@removed" in m:                  # delta tombstone
                continue
            t = _to_thread(m)
            if t:
                _capture_graph_attachments(client, m)
                results.append(t)
        nxt = page.get("@odata.nextLink")
        delta = page.get("@odata.deltaLink")
        if nxt:
            page = client.get_url(nxt)
            if page is None:         # mid-pagination failure → raise BEFORE persisting a partial cursor
                raise RuntimeError("graph mail: nextLink page returned None (HTTP failure mid-pagination)")
            continue
        if delta:
            trigger_state.set_cursor(_SOURCE, delta)   # persist ONLY on clean completion
        break
    return results


def check_new_graph_messages():
    """Scheduler entry — every GRAPH_MAIL_CHECK_INTERVAL seconds. Independent try/except.

    Fully inert when dormant (G0 v2 Finding 3): if BAKER_USE_GRAPH is off, return BEFORE
    any should_skip_poll / set_watermark / report_success — zero DB or health side effects,
    so a disabled source never looks 'healthy' in sentinel_health.
    """
    if not GraphClient(GraphConfig()).is_ready():
        return                       # dormant — zero side effects at all
    if should_skip_poll("graph_mail"):
        return
    try:
        threads = poll_graph_mail()
        if threads:
            logger.info("Graph mail: %d new threads to process", len(threads))
            from triggers.email_trigger import _process_email_threads
            _process_email_threads(threads)
        trigger_state.set_watermark(_SOURCE, datetime.now(timezone.utc))
        report_success("graph_mail")
    except Exception as e:
        report_failure("graph_mail", str(e))
        logger.error("Graph mail trigger failed (non-fatal): %s", type(e).__name__)
