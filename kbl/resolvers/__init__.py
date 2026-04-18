"""Step 2 thread/arc resolvers.

One resolver per signal source (KBL-B §4.3). Contract:

    resolve(signal: dict, conn) -> ResolveResult

``signal`` is a dict with keys ``id``, ``source``, ``primary_matter``,
``raw_content``, ``payload``. Connection ownership stays with the caller
(``kbl.steps.step2_resolve``).

Concrete resolvers live as sibling modules:

    email, whatsapp      — metadata-only (zero external-dep cost)
    transcript, scan     — Voyage-embedding-based (degraded-mode tolerant)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CostInfo:
    """Per-call cost metadata for embedding-based resolvers only. ``None``
    on the result means the resolver did not call an external API."""

    model: str
    input_tokens: int
    cost_usd: float
    success: bool


@dataclass(frozen=True)
class ResolveResult:
    """Pure value object. ``paths`` is vault-relative (``wiki/…`` prefix);
    empty list is valid zero-Gold per CHANDA Inv 1."""

    paths: tuple[str, ...] = field(default_factory=tuple)
    cost_info: Optional[CostInfo] = None
