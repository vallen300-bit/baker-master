"""Shared helpers for embedding-based resolvers (transcript + scan).

Kept separate from the individual resolvers so that the vault scan + cosine
math has one well-tested home and the two concrete resolvers stay tiny.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from kbl.exceptions import VoyageUnavailableError
from kbl.resolvers import CostInfo, ResolveResult

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.75
_THRESHOLD_ENV = "KBL_STEP2_RESOLVE_THRESHOLD"
_MAX_PATHS = 3
_WIKI_SUBDIR = "wiki"

_VOYAGE_MODEL = "voyage-3"
# Voyage-3 pricing as of 2026-04-18 per briefs/DECISIONS_PRE_KBL_A_V2.md:
# ~$0.02 per 1M input tokens.  That puts a single transcript signal well
# under one cent; we just record the per-call amount.
_VOYAGE_PRICE_PER_TOKEN = 0.02 / 1_000_000


def _resolve_threshold() -> float:
    raw = os.environ.get(_THRESHOLD_ENV)
    if not raw:
        return _DEFAULT_THRESHOLD
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD
    return parsed


def _resolve_vault_root() -> Optional[Path]:
    """Return the vault root if ``BAKER_VAULT_PATH`` is set, else ``None``.

    Embedding resolvers degrade to "new arc" (empty result) when vault is
    missing rather than raising — Step 2 degraded-mode contract.
    """
    raw = os.environ.get("BAKER_VAULT_PATH")
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.exists() else None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _parse_frontmatter(content: str) -> Optional[dict[str, Any]]:
    """Return the YAML frontmatter dict, or None if the file lacks one."""
    if not content.startswith("---"):
        return None
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    try:
        parsed = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _collect_stored_embeddings(
    matter_dir: Path,
) -> list[tuple[str, list[float]]]:
    """Scan a matter directory for files whose frontmatter stores an
    ``embedding`` list. Returns ``[(vault_path, vector), …]``.

    Files without a stored embedding are skipped — Phase 1 does not compute
    embeddings on the fly here (the Step 2 brief accepts this tradeoff and
    the §4.3 contract for transcript/scan is still honored: the resolver
    returns what it can find, empty when nothing matches).
    """
    results: list[tuple[str, list[float]]] = []
    if not matter_dir.is_dir():
        return results
    try:
        md_files = sorted(
            p for p in matter_dir.iterdir() if p.suffix == ".md" and p.is_file()
        )
    except OSError as e:
        logger.warning("resolve: failed to list %s: %s", matter_dir, e)
        return results
    for md in md_files:
        try:
            content = md.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("resolve: failed to read %s: %s", md, e)
            continue
        fm = _parse_frontmatter(content)
        if not fm:
            continue
        vec = fm.get("embedding")
        if not isinstance(vec, list) or not vec:
            continue
        try:
            floats = [float(x) for x in vec]
        except (TypeError, ValueError):
            continue
        rel = f"{_WIKI_SUBDIR}/{matter_dir.name}/{md.name}"
        results.append((rel, floats))
    return results


def _approx_input_tokens(text: str) -> int:
    """Voyage tokenizes roughly like Anthropic (~4 chars/token). Good
    enough for the cost ledger which tracks order-of-magnitude."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def resolve_by_embedding(
    *,
    text: str,
    primary_matter: Optional[str],
    embed_fn: Optional[Callable[[str], list[float]]] = None,
) -> ResolveResult:
    """Shared embedding-resolver core for transcript + scan.

    Args:
        text: query content whose embedding we compare against stored
            wiki embeddings.
        primary_matter: canonical matter slug to scope the vault scan.
        embed_fn: optional embedder callable (injected for tests).
            Defaults to ``kbl.voyage_client.embed`` lazily imported.

    Returns a ``ResolveResult``:
        - empty paths + empty cost when the vault / matter dir / query
          can't produce a useful embed (no crash on these).
        - empty paths + cost_info.success=False when Voyage was reachable
          but returned no usable embedding OR the call raised
          ``VoyageUnavailableError`` (degraded-mode contract).
        - non-empty paths + cost_info.success=True on happy path.
    """
    if not primary_matter or not text or not text.strip():
        return ResolveResult()

    vault_root = _resolve_vault_root()
    if vault_root is None:
        return ResolveResult()
    matter_dir = vault_root / _WIKI_SUBDIR / primary_matter
    stored = _collect_stored_embeddings(matter_dir)
    if not stored:
        # Nothing to compare against — skip Voyage call entirely, no cost.
        return ResolveResult()

    if embed_fn is None:
        from kbl.voyage_client import embed as _voyage_embed

        embed_fn = _voyage_embed

    approx_tokens = _approx_input_tokens(text)
    try:
        query_vec = embed_fn(text)
    except VoyageUnavailableError:
        logger.warning(
            "resolve: Voyage unavailable — degraded to new arc (%d chars)",
            len(text),
        )
        cost_failed = CostInfo(
            model=_VOYAGE_MODEL,
            input_tokens=approx_tokens,
            cost_usd=0.0,
            success=False,
        )
        return ResolveResult(cost_info=cost_failed)

    if not query_vec:
        cost_failed = CostInfo(
            model=_VOYAGE_MODEL,
            input_tokens=approx_tokens,
            cost_usd=0.0,
            success=False,
        )
        return ResolveResult(cost_info=cost_failed)

    threshold = _resolve_threshold()
    scored: list[tuple[float, str]] = []
    for path, vec in stored:
        sim = _cosine(query_vec, vec)
        if sim >= threshold:
            scored.append((sim, path))
    scored.sort(key=lambda t: t[0], reverse=True)
    paths = tuple(p for _, p in scored[:_MAX_PATHS])

    cost = CostInfo(
        model=_VOYAGE_MODEL,
        input_tokens=approx_tokens,
        cost_usd=round(approx_tokens * _VOYAGE_PRICE_PER_TOKEN, 8),
        success=True,
    )
    return ResolveResult(paths=paths, cost_info=cost)
