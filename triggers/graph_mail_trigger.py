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
from urllib.parse import quote

from kbl.graph_client import GraphClient
from config.settings import GraphConfig
from triggers.state import trigger_state
from triggers.sentinel_health import report_success, report_failure, should_skip_poll

logger = logging.getLogger(__name__)

_SOURCE = "graph_mail_poll"          # watermark/cursor key
_FOLDER = "Inbox"
_SELECT = "id,conversationId,subject,from,receivedDateTime,body,isDraft,hasAttachments"
# M365_GRAPH_ATTACHMENT_FETCH_DIAG_1: do NOT use $select on the /attachments
# COLLECTION. Graph 400s with "Could not find a property named contentBytes"
# when contentBytes is named in a collection $select (confirmed on Render, bus
# #4348) — the very bug that left hasAttachments=true messages with 0 stored.
# Requesting the collection WITHOUT $select returns full fileAttachment objects
# (id, name, contentType, size, isInline AND contentBytes), which is exactly
# what _capture_graph_attachments needs. $top is fine; $select is not.
_attachment_store_missing_logged = False

# M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1: a message id's namespace (standard vs
# immutable) is NOT reliably derivable from its prefix OR character class —
# live-data probe (G2 codex F1) found AAMk ids WITH '-'/'_' (standard) and AAQk
# ids WITHOUT them (immutable). So we do NOT classify. Instead the by-id
# attachment fetch is ATTEMPT-THEN-FALLBACK: try the id in its native namespace
# first (never regresses the working standard path), and only on failure retry
# once carrying Prefer: IdType="ImmutableId" (catches immutable-form ids). This
# is namespace-agnostic by construction.
_IMMUTABLE_ID_HEADER = {"Prefer": 'IdType="ImmutableId"'}

# Surfaced, never-silently-dropped counter: incremented whenever a message with
# hasAttachments=true yields zero persisted attachment rows because the by-id
# Graph fetch FAILED on BOTH attempts (not because the message is genuinely
# attachment-empty). Exposed for the regression test + any future health probe.
_attachment_fetch_failures = 0


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


def fetch_attachment_raw_value(
    client: GraphClient,
    real_message_id: str,
    attachment_id: str,
    max_retries: int = 0,
):
    """F4 (BAKER_M365_LARGE_ATTACHMENT_FETCH_1): shared raw-byte attachment fetch.

    GET /users/{u}/messages/{realid}/attachments/{attid}/$value -> raw bytes,
    for BOTH fileAttachment (incl. >5 MiB, where the collection omits
    contentBytes) AND message/rfc822 itemAttachment (.eml MIME). Returns
    ``(payload_bytes, content_type)`` or ``None`` (referenceAttachment $value 405,
    or any fetch failure — caller leaves/records the row metadata_only).

    ``max_retries`` forwards to ``get_bytes`` 429/503 backoff (the backfill passes
    >0 to honor Retry-After; forward ingest passes 0 — a poll must not block).

    DELIBERATELY SEPARATE from ``_fetch_attachments_page`` (deputy-codex F4): that
    path carries the documented ``$select=contentBytes`` 400 quirk and must not be
    broadened. This is a single-attachment $value GET, no $select. URL-encodes the
    user, message id, and attachment id (base64 ids carry '/' '+').
    """
    if not real_message_id or not attachment_id:
        return None
    user = quote(client.cfg.mail_user, safe="")
    mid = quote(real_message_id, safe="")
    aid = quote(attachment_id, safe="")
    path = f"/users/{user}/messages/{mid}/attachments/{aid}/$value"
    return client.get_bytes(path, max_retries=max_retries)


def _insert_live_attachment(
    *,
    message_id: str,
    filename: str,
    mime_type: str,
    payload_bytes: bytes,
    provider_attachment_id: str | None = None,
):
    """Best-effort routed persistence (>5MiB->R2, <=5MiB->Neon); never breaks ingest.

    (Name retained from the pre-R2 helper — same role, now size-routed + carrying
    provider_attachment_id — so the live-poll parity + capture tests keep patching
    one stable seam.)"""
    global _attachment_store_missing_logged
    if not payload_bytes:
        return None
    try:
        from kbl.attachment_store import insert_attachment_routed
    except (ImportError, ModuleNotFoundError) as e:
        if not _attachment_store_missing_logged:
            logger.warning("Graph attachment store unavailable (non-fatal): %s", type(e).__name__)
            _attachment_store_missing_logged = True
        return None
    try:
        return insert_attachment_routed(
            message_id=message_id,
            source="graph",
            filename=filename,
            mime_type=mime_type,
            payload_bytes=payload_bytes,
            provider_attachment_id=provider_attachment_id,
        )
    except Exception as e:
        logger.warning("Graph attachment persist failed (non-fatal): %s", type(e).__name__)
        return None


def _persist_attachment_meta(
    *,
    message_id: str,
    filename: str,
    mime_type: str,
    size_bytes,
    provider_attachment_id: str,
):
    """Record a byte-empty attachment row (referenceAttachment / fetch failure) so
    the attachment is never a SILENT drop — it shows as metadata_only, eligible
    for a later on-demand read-path or backfill fetch. Best-effort."""
    if not provider_attachment_id:
        return None
    try:
        from kbl.attachment_store import insert_attachment_meta
    except (ImportError, ModuleNotFoundError):
        return None
    try:
        return insert_attachment_meta(
            message_id=message_id,
            source="graph",
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            meta_key=provider_attachment_id,
        )
    except Exception as e:
        logger.warning("Graph attachment meta-record failed (non-fatal): %s", type(e).__name__)
        return None


def _fetch_attachments_page(client: GraphClient, message_id: str):
    """By-id attachment fetch, ATTEMPT-THEN-FALLBACK (G2 codex F1).

    Returns (page_or_None, used_immutable). Tries the id in its NATIVE namespace
    first (no Prefer — never regresses standard AAMk ids); only if that returns
    None retries once with Prefer: IdType="ImmutableId" (catches immutable AAQk
    ids). Namespace-agnostic: no prefix/char-class guessing. None iff BOTH fail.

    URL-ENCODES the message id (and mail_user, belt-and-suspenders per codex-arch
    #4337): standard AAMk ids are base64 and contain '/' and '+', which break the
    URL path route when interpolated raw (a '/' splits the path -> Graph 400/404
    -> attachments silently dropped). quote(..., safe="") percent-encodes them.
    """
    user = quote(client.cfg.mail_user, safe="")
    mid = quote(message_id, safe="")
    path = f"/users/{user}/messages/{mid}/attachments"
    # NO $select: contentBytes in a collection $select makes Graph 400 (bus #4348).
    # Bare collection GET returns full fileAttachment objects incl contentBytes.
    params = {"$top": 50}
    page = client.get(path, params=params)                       # attempt 1: native
    if page is not None:
        return page, False
    page = client.get(path, params=params, extra_headers=_IMMUTABLE_ID_HEADER)  # attempt 2: immutable
    return page, True


def _capture_graph_attachments(client: GraphClient, m: dict) -> int:
    """Store Graph file attachments for a live message, non-fatally.

    M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1:
    - The by-id attachment READ uses the real per-message id (m['id']) and is
      attempt-then-fallback (native, then Prefer: IdType="ImmutableId"). A fetch
      that fails on BOTH attempts for a hasAttachments=true message is surfaced
      LOUDLY (ERROR + counter), never silently dropped.
    - The STORE KEY (conversationId-keying, Option (a) #4317) is thread_id =
      (conversationId or id), MATCHING email_messages.message_id and the
      baker_email_attachment_read lookup (email_trigger.py:933 keys every email
      source by thread_id). Persisting attachments under the real per-message id
      would key them by a value the read tool never queries — the systemic
      mismatch that made captured attachments unreachable.
    """
    global _attachment_fetch_failures
    fetch_id = m.get("id")
    if not m.get("hasAttachments") or not fetch_id:
        return 0
    # Read by the real message id; store under thread_id (conversationId-or-id).
    store_key = m.get("conversationId") or fetch_id
    try:
        page, used_immutable = _fetch_attachments_page(client, fetch_id)
        if page is None:
            # Both native + ImmutableId failed for a message that declares
            # attachments — silent-skip class bug (Lesson #107). Surface loudly;
            # do NOT let it look like a true-empty message.
            _attachment_fetch_failures += 1
            logger.error(
                "Graph attachment fetch FAILED on both native + ImmutableId "
                "(hasAttachments=true, 0 stored) — attachments NOT persisted, "
                "surfaced (count=%d)",
                _attachment_fetch_failures,
            )
            return 0
        stored = 0
        for att in page.get("value", []):
            if att.get("isInline"):
                continue
            graph_att_id = att.get("id")
            name = att.get("name", "")
            ctype = att.get("contentType") or "application/octet-stream"
            payload = None
            encoded = att.get("contentBytes")
            if encoded:
                try:
                    payload = base64.b64decode(encoded)
                except Exception as e:
                    logger.warning("Graph attachment decode failed (non-fatal): %s", type(e).__name__)
                    payload = None
            if payload is None:
                # F1: contentBytes absent (large fileAttachment / rfc822
                # itemAttachment) OR decode failed — DO NOT silently skip. Fetch
                # the raw bytes by $value (F4 shared helper). This is the fix for
                # the 2,628-row byte-empty residue going forward.
                raw = fetch_attachment_raw_value(client, fetch_id, graph_att_id) if graph_att_id else None
                if raw is not None:
                    payload, fetched_ct = raw
                    if fetched_ct:
                        ctype = fetched_ct
            if payload is None:
                # $value unavailable (referenceAttachment 405 / fetch failure):
                # record metadata_only so the attachment is NEVER a silent drop.
                _persist_attachment_meta(
                    message_id=store_key, filename=name, mime_type=ctype,
                    size_bytes=att.get("size"), provider_attachment_id=graph_att_id,
                )
                continue
            att_row_id = _insert_live_attachment(
                message_id=store_key,
                filename=name,
                mime_type=ctype,
                payload_bytes=payload,
                provider_attachment_id=graph_att_id,
            )
            if att_row_id:
                stored += 1
        if stored == 0:
            # Fetch SUCCEEDED but nothing persisted — surfaced (not silent), yet
            # distinct from the FAILED path above: this is benign (all-inline /
            # signature images), so WARNING + no failure-counter bump.
            logger.warning(
                "Graph attachments: hasAttachments=true but 0 file rows stored "
                "(fetch ok via %s namespace — likely all-inline).",
                "immutable" if used_immutable else "native",
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
