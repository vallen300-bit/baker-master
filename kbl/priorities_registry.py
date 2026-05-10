"""Priorities registry loader — Director-curated Triaga source-of-truth.

Reads ``${BAKER_VAULT_PATH}/wiki/_priorities.yml`` lazily on first use,
validates shape, caches in a module-level singleton. Mirrors the
``slug_registry`` pattern (module-level cache + ``threading.Lock`` +
``_get_registry()`` double-checked-lock function) — NOT the
``_get_global_instance()`` style used by ``SentinelRetriever`` /
``SentinelStoreBack``.

Divergence from ``slug_registry``:
    - Fail-soft on file-missing at runtime (returns empty registry,
      logs warning ONCE) — ``_priorities.yml`` is Director-curated
      content, not infrastructure-critical (vault-mirror lag must not
      blank the cockpit sidebar).
    - Fail-LOUD on schema violation at parse time (matches slug_registry).

Schema (v1, ratified 2026-04-29):
    schema_version: 1
    ratified_at: ISO-8601 string
    categories: [list of category enum strings]
    matters:
      - slug: <canonical-slug>            # singular form
        OR
        slugs: [<slug-a>, <slug-b>, ...]  # plural form (multi-slug row)
        when: <free string>
        importance: critical|high|medium|low|frozen
        category: <one of categories>
        triaga_ref: <Q-ref string>
        description: <free string>
        notes: [list]                     # may be empty

Multi-slug rows are exploded one Priority per slug at parse time.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Severity ordering: lower index = higher importance.
IMPORTANCE_ORDER = ("critical", "high", "medium", "low", "frozen")
_VALID_IMPORTANCE = frozenset(IMPORTANCE_ORDER)


_lock = threading.Lock()
_cache: Optional["_PrioritiesRegistry"] = None
_missing_file_warned = False
_parse_error_warned = False


@dataclass(frozen=True)
class Priority:
    slug: str
    when: str
    importance: str
    category: str
    triaga_ref: str
    description: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PrioritiesRegistry:
    schema_version: int
    ratified_at: str
    categories: frozenset[str]
    priorities: tuple[Priority, ...]               # exploded; one per (slug, row)
    by_slug: dict[str, tuple[Priority, ...]]       # slug -> all priorities for that slug
    # loaded=True only after a successful _parse_yaml(); empty/fail-soft sentinels
    # keep loaded=False so registry_version() / registry_ratified_at() return None
    # even on a legitimate parsed file where schema_version happens to be 0.
    loaded: bool = False


class PrioritiesRegistryError(RuntimeError):
    """Raised when ``_priorities.yml`` is malformed or violates schema."""


def _resolve_yaml_path() -> Path:
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise PrioritiesRegistryError(
            "BAKER_VAULT_PATH env var not set — required to locate _priorities.yml"
        )
    return Path(vault).expanduser() / "wiki" / "_priorities.yml"


def _empty_registry() -> _PrioritiesRegistry:
    return _PrioritiesRegistry(
        schema_version=0,
        ratified_at="",
        categories=frozenset(),
        priorities=(),
        by_slug={},
    )


def _parse_yaml(path: Path) -> _PrioritiesRegistry:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise PrioritiesRegistryError(f"failed to read {path}: {e}") from e

    if not isinstance(data, dict):
        raise PrioritiesRegistryError(f"{path}: top-level must be a mapping")

    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int):
        raise PrioritiesRegistryError(
            f"{path}: schema_version must be an int (got {schema_version!r})"
        )

    ratified_at = data.get("ratified_at", "")
    if not isinstance(ratified_at, str):
        raise PrioritiesRegistryError(
            f"{path}: ratified_at must be a string (got {type(ratified_at).__name__})"
        )

    categories_raw = data.get("categories", [])
    if not isinstance(categories_raw, list):
        raise PrioritiesRegistryError(f"{path}: categories must be a list")
    for c in categories_raw:
        if not isinstance(c, str) or not c:
            raise PrioritiesRegistryError(
                f"{path}: each category must be a non-empty string (got {c!r})"
            )
    categories = frozenset(categories_raw)

    matters = data.get("matters")
    if not isinstance(matters, list):
        raise PrioritiesRegistryError(f"{path}: matters must be a list")

    exploded: list[Priority] = []
    by_slug: dict[str, list[Priority]] = {}

    for i, raw_row in enumerate(matters):
        if not isinstance(raw_row, dict):
            raise PrioritiesRegistryError(f"{path}: matters[{i}] must be a mapping")

        # Slug or slugs (mutually exclusive — a row carries either, not both).
        slug_singular = raw_row.get("slug")
        slugs_plural = raw_row.get("slugs")

        if slug_singular is not None and slugs_plural is not None:
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}] has both 'slug' and 'slugs'; pick one"
            )

        if slug_singular is not None:
            if not isinstance(slug_singular, str) or not slug_singular:
                raise PrioritiesRegistryError(
                    f"{path}: matters[{i}].slug must be a non-empty string"
                )
            row_slugs: list[str] = [slug_singular]
        elif slugs_plural is not None:
            if not isinstance(slugs_plural, list) or not slugs_plural:
                raise PrioritiesRegistryError(
                    f"{path}: matters[{i}].slugs must be a non-empty list"
                )
            row_slugs = []
            for s in slugs_plural:
                if not isinstance(s, str) or not s:
                    raise PrioritiesRegistryError(
                        f"{path}: matters[{i}].slugs entry must be a non-empty string"
                    )
                row_slugs.append(s)
        else:
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}] must have 'slug' or 'slugs'"
            )

        when = raw_row.get("when", "")
        if not isinstance(when, str):
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}].when must be a string"
            )

        importance = raw_row.get("importance")
        if importance not in _VALID_IMPORTANCE:
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}].importance={importance!r} not in {sorted(_VALID_IMPORTANCE)}"
            )

        category = raw_row.get("category")
        if not isinstance(category, str) or not category:
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}].category must be a non-empty string"
            )
        if categories and category not in categories:
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}].category={category!r} not in declared categories {sorted(categories)}"
            )

        triaga_ref = raw_row.get("triaga_ref", "")
        if not isinstance(triaga_ref, str):
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}].triaga_ref must be a string"
            )

        description = raw_row.get("description", "")
        if not isinstance(description, str):
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}].description must be a string"
            )

        notes_raw = raw_row.get("notes", []) or []
        if not isinstance(notes_raw, list):
            raise PrioritiesRegistryError(
                f"{path}: matters[{i}].notes must be a list"
            )
        for n in notes_raw:
            if not isinstance(n, str):
                raise PrioritiesRegistryError(
                    f"{path}: matters[{i}].notes entries must be strings"
                )
        notes = tuple(notes_raw)

        for slug in row_slugs:
            p = Priority(
                slug=slug,
                when=when,
                importance=importance,
                category=category,
                triaga_ref=triaga_ref,
                description=description,
                notes=notes,
            )
            exploded.append(p)
            by_slug.setdefault(slug, []).append(p)

    return _PrioritiesRegistry(
        schema_version=schema_version,
        ratified_at=ratified_at,
        categories=categories,
        priorities=tuple(exploded),
        by_slug={k: tuple(v) for k, v in by_slug.items()},
        loaded=True,
    )


def _get_registry() -> _PrioritiesRegistry:
    """Return the cached registry; lazy-load on first call.

    Fail-soft on file-missing (empty registry, warn once) AND on schema
    violation (empty sentinel cached so we don't re-parse on every call;
    `reload()` clears the cache + retries). Director must see the LOUD
    error log to fix the YAML.
    """
    global _cache, _missing_file_warned, _parse_error_warned
    if _cache is None:
        with _lock:
            if _cache is None:
                try:
                    path = _resolve_yaml_path()
                except PrioritiesRegistryError as e:
                    if not _missing_file_warned:
                        logger.warning("priorities_registry unavailable: %s", e)
                        _missing_file_warned = True
                    _cache = _empty_registry()
                    return _cache

                if not path.is_file():
                    if not _missing_file_warned:
                        logger.warning(
                            "priorities_registry: %s not found; sidebar will use legacy fallback",
                            path,
                        )
                        _missing_file_warned = True
                    _cache = _empty_registry()
                    return _cache

                try:
                    _cache = _parse_yaml(path)
                except PrioritiesRegistryError as parse_err:
                    # Schema violation: log LOUD (Director must fix YAML),
                    # cache empty sentinel so we don't re-parse on every call
                    # (parse-storm). reload() clears the cache + retries.
                    if not _parse_error_warned:
                        logger.error(
                            "priorities_registry SCHEMA VIOLATION in %s: %s — sidebar in legacy fallback until reload()",
                            path, parse_err,
                        )
                        _parse_error_warned = True
                    _cache = _empty_registry()
                    return _cache
    return _cache


# ------------------------------ public API ------------------------------


def reload() -> None:
    """Drop the cached registry; next call re-reads + re-validates the yml."""
    global _cache, _missing_file_warned, _parse_error_warned
    with _lock:
        _cache = None
        _missing_file_warned = False
        _parse_error_warned = False


def get_all() -> list[Priority]:
    """All priorities, exploded per-slug.

    Multi-slug rows in ``_priorities.yml`` produce one ``Priority`` entry
    per slug. Order matches file order (stable for sort breakers).
    Returns ``[]`` if the file is missing (fail-soft).
    """
    return list(_get_registry().priorities)


def get_all_for_slug(slug: str) -> list[Priority]:
    """All Priority rows that include ``slug`` (single + multi-slug rows)."""
    return list(_get_registry().by_slug.get(slug, ()))


def get_by_slug(slug: str) -> Optional[Priority]:
    """First matching Priority for ``slug``; ``None`` if not in priorities.

    A slug appearing in multiple priority rows returns the highest-importance
    row (critical > high > medium > low > frozen). Tie-broken by file order.
    """
    rows = _get_registry().by_slug.get(slug)
    if not rows:
        return None
    return min(rows, key=lambda p: IMPORTANCE_ORDER.index(p.importance))


def severity_for(slug: str) -> Optional[str]:
    """Highest importance enum across all priority rows for ``slug``.

    Returns ``None`` if the slug is not in priorities.
    """
    p = get_by_slug(slug)
    return p.importance if p else None


def category_for(slug: str) -> Optional[str]:
    """Category attribution for ``slug``.

    A slug in multiple priority rows may carry multiple categories; returns
    the highest-importance row's category for sidebar bucketing.
    """
    p = get_by_slug(slug)
    return p.category if p else None


def is_active_priority(slug: str) -> bool:
    """True if ``slug`` appears in any priority row."""
    return slug in _get_registry().by_slug


def registry_version() -> Optional[int]:
    """``schema_version`` from ``_priorities.yml`` (None if file missing/unparsed)."""
    reg = _get_registry()
    return reg.schema_version if reg.loaded else None


def registry_ratified_at() -> Optional[str]:
    """``ratified_at`` from ``_priorities.yml`` (None if file missing/unparsed)."""
    reg = _get_registry()
    return reg.ratified_at if reg.loaded else None
