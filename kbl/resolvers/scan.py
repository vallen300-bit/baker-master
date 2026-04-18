"""Scan-query thread resolver — embedding-based.

Same mechanism as the transcript resolver, but uses
``payload['director_context_hint']`` as the query text when present (scan
queries tend to be terse — the hint gives the embedder more to work with).
Falls back to ``raw_content``.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from kbl.resolvers import ResolveResult
from kbl.resolvers._embedding import resolve_by_embedding


def resolve(
    signal: dict[str, Any],
    conn: Any,
    *,
    embed_fn: Optional[Callable[[str], list[float]]] = None,
) -> ResolveResult:
    payload = signal.get("payload") or {}
    hint = payload.get("director_context_hint")
    if isinstance(hint, str) and hint.strip():
        query = hint
    else:
        query = signal.get("raw_content") or ""
    return resolve_by_embedding(
        text=query,
        primary_matter=signal.get("primary_matter"),
        embed_fn=embed_fn,
    )
