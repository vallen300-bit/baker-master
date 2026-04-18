"""WhatsApp thread resolver — metadata-only (zero external-dep cost).

Matches signals in the same ``chat_id`` within a 90-day sliding window
under the same ``primary_matter``, returns the most recent vault paths.
No Voyage call, no external API.

Reads (from ``signal.payload``):
    chat_id        — the WhatsApp chat-id (``<number>@c.us`` or group ``@g.us``)
    sent_at        — ISO 8601 string; used to anchor the 90-day window.
                     Falls back to ``now()`` when absent.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from kbl.resolvers import ResolveResult

logger = logging.getLogger(__name__)

_MAX_PATHS = 3
_DEFAULT_WINDOW_DAYS = 90
_WINDOW_ENV = "KBL_STEP2_WA_WINDOW_DAYS"


def _window_days() -> int:
    raw = os.environ.get(_WINDOW_ENV)
    if not raw:
        return _DEFAULT_WINDOW_DAYS
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_WINDOW_DAYS
    return parsed if parsed > 0 else _DEFAULT_WINDOW_DAYS


def resolve(signal: dict[str, Any], conn: Any) -> ResolveResult:
    payload = signal.get("payload") or {}
    primary_matter = signal.get("primary_matter")
    chat_id = payload.get("chat_id")
    if not primary_matter or not isinstance(chat_id, str) or not chat_id.strip():
        return ResolveResult()

    window = _window_days()
    sent_at = payload.get("sent_at")
    # When the caller supplies sent_at, use it as the anchor (so
    # back-dated ingestion doesn't skew the window). Otherwise anchor
    # on now() at the DB level.
    if isinstance(sent_at, str) and sent_at:
        anchor_clause = "(%s::timestamptz - (%s || ' days')::interval)"
        anchor_params: tuple[Any, ...] = (sent_at, str(window))
    else:
        anchor_clause = "(now() - (%s || ' days')::interval)"
        anchor_params = (str(window),)

    sql = (
        "SELECT target_vault_path FROM signal_queue "
        "WHERE source = 'whatsapp' "
        "  AND primary_matter = %s "
        "  AND (payload->>'chat_id') = %s "
        "  AND target_vault_path IS NOT NULL "
        "  AND target_vault_path <> '' "
        "  AND created_at >= " + anchor_clause + " "
        "ORDER BY created_at DESC "
        "LIMIT %s"
    )
    params: tuple[Any, ...] = (primary_matter, chat_id) + anchor_params + (_MAX_PATHS,)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    paths = tuple(r[0] for r in rows if r and r[0])
    return ResolveResult(paths=paths)
