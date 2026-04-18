"""Email thread resolver — metadata-only (zero external-dep cost).

Walks the ``In-Reply-To`` / ``References`` message-id graph against the
``signal_queue.payload`` of prior committed signals. Falls back to a
``Re:`` / ``Fwd:`` stripped subject match. Returns up to 3 vault paths
sorted chronological (most-recent-first).

Reads (from ``signal.payload`` — all optional, resolver tolerates missing
fields):
    email_message_id   — the current signal's Message-ID
    in_reply_to        — Message-ID of the immediate parent
    references         — list of Message-IDs in the thread history
    subject            — used as fallback match key
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from kbl.resolvers import ResolveResult

logger = logging.getLogger(__name__)

_MAX_PATHS = 3
_SUBJECT_PREFIX_RE = re.compile(r"^(?:re|fwd|fw|aw|vs)\s*:\s*", re.IGNORECASE)


def _normalize_subject(raw: Any) -> str:
    """Strip ``Re: / Fwd: / Aw: / Vs:`` prefixes (possibly stacked) and
    collapse whitespace. Returns '' if raw is not a non-empty string."""
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    # Stacked Re: Re: Fwd: ...
    while True:
        new = _SUBJECT_PREFIX_RE.sub("", s, count=1)
        if new == s:
            break
        s = new.strip()
    return " ".join(s.split()).lower()


def _message_id_candidates(payload: dict[str, Any]) -> list[str]:
    """Collect Message-IDs from ``in_reply_to`` + ``references`` + self."""
    ids: list[str] = []
    seen: set[str] = set()

    def _add(value: Any) -> None:
        if not value or not isinstance(value, str):
            return
        v = value.strip()
        if v and v not in seen:
            seen.add(v)
            ids.append(v)

    _add(payload.get("email_message_id"))
    _add(payload.get("in_reply_to"))
    refs = payload.get("references")
    if isinstance(refs, list):
        for r in refs:
            _add(r)
    elif isinstance(refs, str):
        # Some headers arrive as a whitespace-separated string.
        for r in refs.split():
            _add(r)
    return ids


def _query_by_message_ids(
    conn: Any, primary_matter: str, msg_ids: list[str]
) -> list[str]:
    """Fetch vault paths of prior email signals in the same Message-ID
    graph under the same matter. Most-recent first; caps at ``_MAX_PATHS``."""
    if not msg_ids:
        return []
    # Two-sided match:
    #   (a) their email_message_id is in our (in_reply_to + references) set
    #   (b) their (in_reply_to + references) contains our email_message_id
    # For (b) we widen the JSON path lookup via generic @> containment so
    # references-array membership is checked without unnesting.
    sql = (
        "SELECT target_vault_path FROM signal_queue "
        "WHERE source = 'email' "
        "  AND primary_matter = %s "
        "  AND target_vault_path IS NOT NULL "
        "  AND target_vault_path <> '' "
        "  AND ("
        "       (payload->>'email_message_id') = ANY(%s) "
        "    OR (payload->>'in_reply_to') = ANY(%s) "
        "    OR payload->'references' ?| %s"
        "  ) "
        "ORDER BY created_at DESC "
        "LIMIT %s"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (primary_matter, msg_ids, msg_ids, msg_ids, _MAX_PATHS))
            rows = cur.fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return [r[0] for r in rows if r and r[0]]


def _query_by_subject(
    conn: Any, primary_matter: str, normalized_subject: str
) -> list[str]:
    if not normalized_subject:
        return []
    sql = (
        "SELECT target_vault_path FROM signal_queue "
        "WHERE source = 'email' "
        "  AND primary_matter = %s "
        "  AND target_vault_path IS NOT NULL "
        "  AND target_vault_path <> '' "
        "  AND lower(regexp_replace(payload->>'subject', "
        "           '^(re|fwd|fw|aw|vs)\\s*:\\s*', '', 'gi')) = %s "
        "ORDER BY created_at DESC "
        "LIMIT %s"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (primary_matter, normalized_subject, _MAX_PATHS))
            rows = cur.fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return [r[0] for r in rows if r and r[0]]


def resolve(signal: dict[str, Any], conn: Any) -> ResolveResult:
    """Email thread resolver entry point. Never calls external services."""
    payload = signal.get("payload") or {}
    primary_matter = signal.get("primary_matter")
    if not primary_matter:
        # Without a matter we cannot scope the lookup; treat as new arc.
        return ResolveResult()

    candidates = _message_id_candidates(payload)
    paths: list[str] = []
    seen: set[str] = set()

    for p in _query_by_message_ids(conn, primary_matter, candidates):
        if p not in seen:
            seen.add(p)
            paths.append(p)
        if len(paths) >= _MAX_PATHS:
            break

    if len(paths) < _MAX_PATHS:
        normalized = _normalize_subject(payload.get("subject"))
        if normalized:
            for p in _query_by_subject(conn, primary_matter, normalized):
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
                if len(paths) >= _MAX_PATHS:
                    break

    return ResolveResult(paths=tuple(paths))
