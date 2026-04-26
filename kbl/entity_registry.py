"""Legal-entity slug registry loader — single source of truth.

Reads `baker-vault/entities.yml` at first-call, validates shape, caches in a
module-level dict. API mirrors `kbl.people_registry` and `kbl.slug_registry`.

The vault yml schema currently mirrors slugs.yml (slug, status, description,
aliases). This brief intentionally does NOT add legal-form / jurisdiction /
parent_entity fields — schema migration to richer shapes is tracked separately
(see BRIEF_KBL_PEOPLE_ENTITY_LOADERS_1 §"Out of scope"). Fields not described
here are tolerated when the loader runs (forward-compat) but ignored.

Env var:
    BAKER_VAULT_PATH — directory containing entities.yml. Required.

Lifecycle: active | retired | draft (same as slug_registry).

Linked: KBL_PEOPLE_ENTITY_LOADERS_1.
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
class Entity:
    slug: str
    status: str
    description: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _Registry:
    version: int
    entries: dict[str, Entity]
    alias_index: dict[str, str]


@dataclass(frozen=True)
class LintIssue:
    code: str
    message: str


class EntityRegistryError(RuntimeError):
    """Raised when the YAML source is missing, malformed, or inconsistent."""


class RegistryVersionError(EntityRegistryError):
    """Raised when the registry yml is missing a `version` integer field."""


def _normalize_key(raw: str) -> str:
    return " ".join(raw.lower().split())


def _resolve_yaml_path() -> Path:
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise EntityRegistryError(
            "BAKER_VAULT_PATH env var not set — required to locate entities.yml"
        )
    path = Path(vault).expanduser() / "entities.yml"
    if not path.is_file():
        raise EntityRegistryError(f"entity registry file not found: {path}")
    return path


def _parse_yaml(path: Path) -> _Registry:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise EntityRegistryError(f"failed to read {path}: {e}") from e

    if not isinstance(data, dict):
        raise EntityRegistryError(f"{path}: top-level must be a mapping")

    ver = data.get("version")
    if not isinstance(ver, int):
        raise RegistryVersionError(
            f"{path}: `version` must be an int (got {ver!r})"
        )

    entities = data.get("entities")
    if not isinstance(entities, list) or not entities:
        raise EntityRegistryError(f"{path}: `entities` must be a non-empty list")

    entries: dict[str, Entity] = {}
    alias_index: dict[str, str] = {}

    for i, raw_entry in enumerate(entities):
        if not isinstance(raw_entry, dict):
            raise EntityRegistryError(f"{path}: entities[{i}] must be a mapping")

        slug = raw_entry.get("slug")
        if not isinstance(slug, str) or not slug:
            raise EntityRegistryError(
                f"{path}: entities[{i}].slug must be a non-empty string"
            )
        if slug in entries:
            raise EntityRegistryError(f"{path}: duplicate canonical slug {slug!r}")

        status = raw_entry.get("status")
        if status not in _VALID_STATUSES:
            raise EntityRegistryError(
                f"{path}: entities[{i}] ({slug}) status={status!r} not in "
                f"{sorted(_VALID_STATUSES)}"
            )

        description = raw_entry.get("description", "")
        if not isinstance(description, str):
            raise EntityRegistryError(
                f"{path}: entities[{i}] ({slug}) description must be a string"
            )

        aliases_raw = raw_entry.get("aliases", [])
        if not isinstance(aliases_raw, list):
            raise EntityRegistryError(
                f"{path}: entities[{i}] ({slug}) aliases must be a list"
            )
        for a in aliases_raw:
            if not isinstance(a, str) or not a:
                raise EntityRegistryError(
                    f"{path}: entities[{i}] ({slug}) alias must be non-empty "
                    f"string (got {a!r})"
                )

        canonical_key = _normalize_key(slug)
        if canonical_key in alias_index:
            raise EntityRegistryError(
                f"{path}: slug {slug!r} collides with alias of "
                f"{alias_index[canonical_key]!r}"
            )
        alias_index[canonical_key] = slug

        seen_for_this = {canonical_key}
        normalized_aliases: list[str] = []
        for a in aliases_raw:
            key = _normalize_key(a)
            if key in seen_for_this:
                raise EntityRegistryError(
                    f"{path}: entities[{i}] ({slug}) duplicate alias {a!r}"
                )
            seen_for_this.add(key)
            if key in alias_index and alias_index[key] != slug:
                raise EntityRegistryError(
                    f"{path}: alias {a!r} maps to both "
                    f"{alias_index[key]!r} and {slug!r}"
                )
            alias_index[key] = slug
            normalized_aliases.append(key)

        entries[slug] = Entity(
            slug=slug,
            status=status,
            description=description,
            aliases=tuple(normalized_aliases),
        )

    return _Registry(version=ver, entries=entries, alias_index=alias_index)


def _get_registry() -> _Registry:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = _parse_yaml(_resolve_yaml_path())
    return _cache


# ------------------------------ public API ------------------------------


def load() -> dict[str, Entity]:
    """Force-load and return slug -> Entity mapping (cached after first call)."""
    return dict(_get_registry().entries)


def reload() -> None:
    """Drop the cached registry; next call re-reads + re-validates the yml."""
    global _cache
    with _lock:
        _cache = None


def version() -> int:
    return _get_registry().version


def is_canonical(slug: Optional[str]) -> bool:
    if slug is None:
        return True
    return slug in _get_registry().entries


def get(slug: str) -> Optional[Entity]:
    return _get_registry().entries.get(slug)


def canonical_slugs() -> set[str]:
    return set(_get_registry().entries.keys())


def active_slugs() -> set[str]:
    return {s for s, e in _get_registry().entries.items() if e.status == "active"}


def normalize(raw: Optional[str]) -> Optional[str]:
    if raw is None or not isinstance(raw, str):
        return None
    key = _normalize_key(raw)
    if not key or key in {"none", "null"}:
        return None
    return _get_registry().alias_index.get(key)


def lint(path: Path) -> list[LintIssue]:
    """Pure lint of an entities.yml at `path`. No I/O beyond the supplied path."""
    issues: list[LintIssue] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        return [LintIssue("SHAPE", f"failed to read {path}: {e}")]

    if not isinstance(data, dict):
        return [LintIssue("SHAPE", f"{path}: top-level must be a mapping")]

    if not isinstance(data.get("version"), int):
        issues.append(LintIssue("VERSION_MISSING", "`version` must be an integer"))

    entities = data.get("entities")
    if not isinstance(entities, list):
        issues.append(LintIssue("SHAPE", "`entities` must be a list"))
        return issues

    seen_slugs: set[str] = set()
    seen_aliases: dict[str, str] = {}

    for i, entry in enumerate(entities):
        if not isinstance(entry, dict):
            issues.append(LintIssue("SHAPE", f"entities[{i}] must be a mapping"))
            continue
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug:
            issues.append(LintIssue("SHAPE", f"entities[{i}].slug missing/empty"))
            continue
        if slug in seen_slugs:
            issues.append(LintIssue("DUP_SLUG", f"duplicate slug {slug!r}"))
            continue
        seen_slugs.add(slug)

        status = entry.get("status")
        if status not in _VALID_STATUSES:
            issues.append(
                LintIssue("BAD_STATUS", f"entities[{i}] ({slug}) status={status!r}")
            )

        canonical_key = _normalize_key(slug)
        if canonical_key in seen_aliases and seen_aliases[canonical_key] != slug:
            issues.append(
                LintIssue(
                    "DUP_ALIAS",
                    f"slug {slug!r} collides with alias of "
                    f"{seen_aliases[canonical_key]!r}",
                )
            )
        seen_aliases[canonical_key] = slug

        for a in entry.get("aliases", []) or []:
            if not isinstance(a, str) or not a:
                continue
            key = _normalize_key(a)
            if key in seen_aliases and seen_aliases[key] != slug:
                issues.append(
                    LintIssue(
                        "DUP_ALIAS",
                        f"alias {a!r} maps to both "
                        f"{seen_aliases[key]!r} and {slug!r}",
                    )
                )
            seen_aliases[key] = slug

    return issues
