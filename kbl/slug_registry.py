"""Matter slug registry loader — single source of truth.

Reads `baker-vault/slugs.yml` at import-time-first-use, validates shape,
caches in a module-level dict. Consumers import the public functions below
instead of hardcoding slug lists.

Env var:
    BAKER_VAULT_PATH — directory containing slugs.yml. Required; fail
    loudly if unset or if slugs.yml missing.

Lifecycle (status field in yml):
    active   — offered to model, accepted by validator, router reads
    retired  — NOT offered, accepted (historical signals), not routed
    draft    — NOT offered, NOT accepted (in-session candidates)

Schema design in `briefs/_drafts/SLUG_REGISTRY_DESIGN.md`.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

_VALID_STATUSES = frozenset({"active", "retired", "draft"})

_lock = threading.Lock()
_cache: Optional["_Registry"] = None


@dataclass(frozen=True)
class _Entry:
    slug: str
    status: str
    description: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _Registry:
    version: int
    entries: dict[str, _Entry]                # canonical slug -> entry
    alias_index: dict[str, str]               # normalized alias -> canonical slug


class SlugRegistryError(RuntimeError):
    """Raised when the YAML source is missing, malformed, or inconsistent."""


def _normalize_key(raw: str) -> str:
    """Case-insensitive, whitespace-collapsed comparison key."""
    return " ".join(raw.lower().split())


def _resolve_yaml_path() -> Path:
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise SlugRegistryError(
            "BAKER_VAULT_PATH env var not set — required to locate slugs.yml"
        )
    path = Path(vault).expanduser() / "slugs.yml"
    if not path.is_file():
        raise SlugRegistryError(f"slug registry file not found: {path}")
    return path


def _parse_yaml(path: Path) -> _Registry:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise SlugRegistryError(f"failed to read {path}: {e}") from e

    if not isinstance(data, dict):
        raise SlugRegistryError(f"{path}: top-level must be a mapping")

    version = data.get("version")
    if not isinstance(version, int):
        raise SlugRegistryError(f"{path}: `version` must be an int (got {version!r})")

    matters = data.get("matters")
    if not isinstance(matters, list) or not matters:
        raise SlugRegistryError(f"{path}: `matters` must be a non-empty list")

    entries: dict[str, _Entry] = {}
    alias_index: dict[str, str] = {}

    for i, raw_entry in enumerate(matters):
        if not isinstance(raw_entry, dict):
            raise SlugRegistryError(f"{path}: matters[{i}] must be a mapping")

        slug = raw_entry.get("slug")
        if not isinstance(slug, str) or not slug:
            raise SlugRegistryError(f"{path}: matters[{i}].slug must be a non-empty string")
        if slug in entries:
            raise SlugRegistryError(f"{path}: duplicate canonical slug {slug!r}")

        status = raw_entry.get("status")
        if status not in _VALID_STATUSES:
            raise SlugRegistryError(
                f"{path}: matters[{i}] ({slug}) status={status!r} not in {sorted(_VALID_STATUSES)}"
            )

        description = raw_entry.get("description", "")
        if not isinstance(description, str):
            raise SlugRegistryError(f"{path}: matters[{i}] ({slug}) description must be a string")

        aliases_raw = raw_entry.get("aliases", [])
        if not isinstance(aliases_raw, list):
            raise SlugRegistryError(f"{path}: matters[{i}] ({slug}) aliases must be a list")
        for a in aliases_raw:
            if not isinstance(a, str) or not a:
                raise SlugRegistryError(
                    f"{path}: matters[{i}] ({slug}) alias must be non-empty string (got {a!r})"
                )

        # Alias collision check — canonical slug itself also registered so
        # an alias like "cupial" under a different slug is rejected.
        canonical_key = _normalize_key(slug)
        if canonical_key in alias_index:
            raise SlugRegistryError(
                f"{path}: slug {slug!r} collides with alias of {alias_index[canonical_key]!r}"
            )
        alias_index[canonical_key] = slug

        seen_for_this = {canonical_key}
        normalized_aliases: list[str] = []
        for a in aliases_raw:
            key = _normalize_key(a)
            if key in seen_for_this:
                raise SlugRegistryError(
                    f"{path}: matters[{i}] ({slug}) duplicate alias {a!r}"
                )
            seen_for_this.add(key)
            if key in alias_index and alias_index[key] != slug:
                raise SlugRegistryError(
                    f"{path}: alias {a!r} maps to both {alias_index[key]!r} and {slug!r}"
                )
            alias_index[key] = slug
            normalized_aliases.append(key)

        entries[slug] = _Entry(
            slug=slug,
            status=status,
            description=description,
            aliases=tuple(normalized_aliases),
        )

    return _Registry(version=version, entries=entries, alias_index=alias_index)


def _get_registry() -> _Registry:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = _parse_yaml(_resolve_yaml_path())
    return _cache


# ------------------------------ public API ------------------------------


def reload() -> None:
    """Drop the cached registry; next call re-reads + re-validates the yml."""
    global _cache
    with _lock:
        _cache = None


def registry_version() -> int:
    return _get_registry().version


def canonical_slugs() -> set[str]:
    """All slugs regardless of status."""
    return set(_get_registry().entries.keys())


def active_slugs() -> set[str]:
    """Slugs with status == active."""
    return {s for s, e in _get_registry().entries.items() if e.status == "active"}


def is_canonical(slug: Optional[str]) -> bool:
    """None is always valid (null matter)."""
    if slug is None:
        return True
    return slug in _get_registry().entries


def normalize(raw: Optional[str]) -> Optional[str]:
    """Map raw model output to a canonical slug, or None.

    Rules:
        None / empty / 'none' / 'null' -> None
        Exact canonical match           -> slug
        Alias match (case-insensitive,
                     whitespace-collapsed) -> canonical slug
        No match                        -> None
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    key = _normalize_key(raw)
    if not key or key in {"none", "null"}:
        return None
    return _get_registry().alias_index.get(key)


def describe(slug: str) -> str:
    """Return the description for a known slug; raise if unknown."""
    entry = _get_registry().entries.get(slug)
    if entry is None:
        raise KeyError(slug)
    return entry.description


def aliases_for(slug: str) -> list[str]:
    """Return normalized aliases for a known slug (empty list if none).

    Normalized = lowercase, whitespace-collapsed (the form used for matching).
    Raises KeyError if slug is not canonical.
    """
    entry = _get_registry().entries.get(slug)
    if entry is None:
        raise KeyError(slug)
    return list(entry.aliases)
