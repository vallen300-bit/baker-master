"""Natural-person slug registry loader — single source of truth.

Reads `baker-vault/people.yml` at first-call, validates shape, caches in a
module-level dict. Mirrors `kbl.slug_registry` for matters; API parity is
intentional so call sites can swap registry by namespace.

Env var:
    BAKER_VAULT_PATH — directory containing people.yml. Required; fail
    loudly if unset or if people.yml missing. Silent-empty is the worst
    failure mode (every slug becomes "uncanonical") so the loader raises.

Lifecycle (status field in yml):
    active   — offered to model, accepted by validator
    retired  — NOT offered, accepted (historical signals)
    draft    — NOT offered, NOT accepted (in-session candidates)

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
class Person:
    slug: str
    status: str
    description: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _Registry:
    version: int
    entries: dict[str, Person]
    alias_index: dict[str, str]


@dataclass(frozen=True)
class LintIssue:
    code: str
    message: str


class PeopleRegistryError(RuntimeError):
    """Raised when the YAML source is missing, malformed, or inconsistent."""


class RegistryVersionError(PeopleRegistryError):
    """Raised when the registry yml is missing a `version` integer field."""


def _normalize_key(raw: str) -> str:
    return " ".join(raw.lower().split())


def _resolve_yaml_path() -> Path:
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise PeopleRegistryError(
            "BAKER_VAULT_PATH env var not set — required to locate people.yml"
        )
    path = Path(vault).expanduser() / "people.yml"
    if not path.is_file():
        raise PeopleRegistryError(f"people registry file not found: {path}")
    return path


def _parse_yaml(path: Path) -> _Registry:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise PeopleRegistryError(f"failed to read {path}: {e}") from e

    if not isinstance(data, dict):
        raise PeopleRegistryError(f"{path}: top-level must be a mapping")

    ver = data.get("version")
    if not isinstance(ver, int):
        raise RegistryVersionError(
            f"{path}: `version` must be an int (got {ver!r})"
        )

    people = data.get("people")
    if not isinstance(people, list) or not people:
        raise PeopleRegistryError(f"{path}: `people` must be a non-empty list")

    entries: dict[str, Person] = {}
    alias_index: dict[str, str] = {}

    for i, raw_entry in enumerate(people):
        if not isinstance(raw_entry, dict):
            raise PeopleRegistryError(f"{path}: people[{i}] must be a mapping")

        slug = raw_entry.get("slug")
        if not isinstance(slug, str) or not slug:
            raise PeopleRegistryError(
                f"{path}: people[{i}].slug must be a non-empty string"
            )
        if slug in entries:
            raise PeopleRegistryError(f"{path}: duplicate canonical slug {slug!r}")

        status = raw_entry.get("status")
        if status not in _VALID_STATUSES:
            raise PeopleRegistryError(
                f"{path}: people[{i}] ({slug}) status={status!r} not in "
                f"{sorted(_VALID_STATUSES)}"
            )

        description = raw_entry.get("description", "")
        if not isinstance(description, str):
            raise PeopleRegistryError(
                f"{path}: people[{i}] ({slug}) description must be a string"
            )

        aliases_raw = raw_entry.get("aliases", [])
        if not isinstance(aliases_raw, list):
            raise PeopleRegistryError(
                f"{path}: people[{i}] ({slug}) aliases must be a list"
            )
        for a in aliases_raw:
            if not isinstance(a, str) or not a:
                raise PeopleRegistryError(
                    f"{path}: people[{i}] ({slug}) alias must be non-empty string "
                    f"(got {a!r})"
                )

        canonical_key = _normalize_key(slug)
        if canonical_key in alias_index:
            raise PeopleRegistryError(
                f"{path}: slug {slug!r} collides with alias of "
                f"{alias_index[canonical_key]!r}"
            )
        alias_index[canonical_key] = slug

        seen_for_this = {canonical_key}
        normalized_aliases: list[str] = []
        for a in aliases_raw:
            key = _normalize_key(a)
            if key in seen_for_this:
                raise PeopleRegistryError(
                    f"{path}: people[{i}] ({slug}) duplicate alias {a!r}"
                )
            seen_for_this.add(key)
            if key in alias_index and alias_index[key] != slug:
                raise PeopleRegistryError(
                    f"{path}: alias {a!r} maps to both "
                    f"{alias_index[key]!r} and {slug!r}"
                )
            alias_index[key] = slug
            normalized_aliases.append(key)

        entries[slug] = Person(
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


def load() -> dict[str, Person]:
    """Force-load and return slug -> Person mapping (cached after first call)."""
    return dict(_get_registry().entries)


def reload() -> None:
    """Drop the cached registry; next call re-reads + re-validates the yml."""
    global _cache
    with _lock:
        _cache = None


def version() -> int:
    """Return the `version` integer from the registry yml."""
    return _get_registry().version


def is_canonical(slug: Optional[str]) -> bool:
    """None is always valid (null person)."""
    if slug is None:
        return True
    return slug in _get_registry().entries


def get(slug: str) -> Optional[Person]:
    """Return the Person record for a canonical slug, or None if unknown."""
    return _get_registry().entries.get(slug)


def canonical_slugs() -> set[str]:
    """All slugs regardless of status."""
    return set(_get_registry().entries.keys())


def active_slugs() -> set[str]:
    """Slugs with status == active."""
    return {s for s, e in _get_registry().entries.items() if e.status == "active"}


def normalize(raw: Optional[str]) -> Optional[str]:
    """Map raw input to a canonical slug, or None."""
    if raw is None or not isinstance(raw, str):
        return None
    key = _normalize_key(raw)
    if not key or key in {"none", "null"}:
        return None
    return _get_registry().alias_index.get(key)


def lint(path: Path) -> list[LintIssue]:
    """Pure lint of a people.yml at `path`. No I/O beyond the supplied path.

    Issues surfaced:
      - VERSION_MISSING: top-level `version` is missing or non-int.
      - DUP_SLUG: duplicate canonical slug across entries.
      - DUP_ALIAS: alias collides with another slug or alias (case-insensitive,
        whitespace-collapsed).
      - BAD_STATUS: status not in {active, retired, draft}.
      - SHAPE: structural problem (top-level not a mapping, people not a list,
        entry not a mapping, missing/empty slug, etc.).

    Empty list = clean.
    """
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

    people = data.get("people")
    if not isinstance(people, list):
        issues.append(LintIssue("SHAPE", "`people` must be a list"))
        return issues

    seen_slugs: set[str] = set()
    seen_aliases: dict[str, str] = {}  # normalized -> canonical slug

    for i, entry in enumerate(people):
        if not isinstance(entry, dict):
            issues.append(LintIssue("SHAPE", f"people[{i}] must be a mapping"))
            continue
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug:
            issues.append(LintIssue("SHAPE", f"people[{i}].slug missing/empty"))
            continue
        if slug in seen_slugs:
            issues.append(LintIssue("DUP_SLUG", f"duplicate slug {slug!r}"))
            continue
        seen_slugs.add(slug)

        status = entry.get("status")
        if status not in _VALID_STATUSES:
            issues.append(
                LintIssue("BAD_STATUS", f"people[{i}] ({slug}) status={status!r}")
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
