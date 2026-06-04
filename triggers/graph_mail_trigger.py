"""M365_GRAPH_MAIL_POLL_2: Microsoft Graph inbound mail poller (delta query).

Independent source adapter — mirrors triggers/exchange_poller.py. Produces
thread dicts and hands them to the shared sink _process_email_threads().
Dormant unless BAKER_USE_GRAPH=true (GraphClient.is_ready() is the single gate).
Never raises to the scheduler; one failure must not affect other pollers.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from kbl.graph_client import GraphClient
from config.settings import GraphConfig
from triggers.state import trigger_state
from triggers.sentinel_health import report_success, report_failure, should_skip_poll

logger = logging.getLogger(__name__)

_SOURCE = "graph_mail_poll"          # watermark/cursor key
_FOLDER = "Inbox"
_SELECT = "id,conversationId,subject,from,receivedDateTime,body,isDraft"


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
