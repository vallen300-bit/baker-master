"""Meeting-transcript thread resolver — embedding-based.

Embeds ``signal.raw_content`` via Voyage AI and compares against stored
wiki embeddings under ``wiki/<primary_matter>/``. Returns top-3 matches
with cosine similarity >= ``KBL_STEP2_RESOLVE_THRESHOLD`` (default 0.75).

Degraded mode: Voyage unreachable -> empty paths + WARN log + cost row
with ``success=False``; caller (dispatcher) advances as new arc rather
than failing the signal. KBL-B §4.3 contract.
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
    """conn is unused — kept in the signature for uniformity with the
    metadata resolvers. ``embed_fn`` is a test-injection seam."""
    return resolve_by_embedding(
        text=signal.get("raw_content") or "",
        primary_matter=signal.get("primary_matter"),
        embed_fn=embed_fn,
    )
