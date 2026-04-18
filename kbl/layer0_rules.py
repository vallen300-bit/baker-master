"""Layer 0 rules loader — source of truth for Step 0 deterministic filter.

Reads the Layer 0 rule YAML from ``baker-vault/layer0_rules.yml`` (or an
explicit override), validates shape, caches in a module-level slot. Loader
only — rule *evaluation* lives in KBL-B Step 0 (separate ticket) and
consumes this loader's output.

Env vars:
    KBL_LAYER0_RULES_PATH — full path to an alternate rules yml (wins over
        the default vault lookup). Useful for tests + ad-hoc experiments.
    BAKER_VAULT_PATH — directory containing ``layer0_rules.yml``. Required
        when KBL_LAYER0_RULES_PATH is unset. Same convention as
        ``kbl.slug_registry``.

Design rules (per ``briefs/_tasks/CODE_1_PENDING.md`` LAYER0-LOADER-1):
    - Fail loud. Missing file, malformed YAML, missing required keys, or
      per-rule schema violations all raise ``Layer0RulesError``. No silent
      defaults, no fallback content, no "graceful" missing-file behavior.
    - Rule ``match`` dict is opaque at the loader level — structure is the
      evaluator's contract, not the loader's. Loader only checks it is a
      dict (non-None).
    - Mirrors ``kbl.slug_registry`` shape so consumers can learn one pattern.

This file must not import from KBL-B Step 0 code; the dependency is the
other direction.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

_REQUIRED_RULE_KEYS = ("name", "source", "match", "detail")

_lock = threading.Lock()
_cache: Optional["Layer0Rules"] = None
_cache_source: Optional[Path] = None


class Layer0RulesError(RuntimeError):
    """Raised when the Layer 0 rules YAML is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class Layer0Rule:
    name: str
    source: str                    # "email", "whatsapp", "*" (cross-source), etc.
    match: dict[str, Any]          # predicate shape is evaluator's contract, opaque here
    detail: str


@dataclass(frozen=True)
class Layer0Rules:
    version: str                        # semver per the fixture format, e.g. "1.0.0"
    rules: tuple[Layer0Rule, ...]
    loaded_at: datetime                 # UTC; for operator debugging / hot-reload traces
    source_path: Path                   # the yml file this view was materialized from


# ----------------------------- path resolution -----------------------------


def _resolve_yaml_path(explicit: Optional[Path]) -> Path:
    """Resolve the rules file path.

    Precedence:
        1. explicit ``path`` argument to ``load_layer0_rules``
        2. ``KBL_LAYER0_RULES_PATH`` env var (full file path)
        3. ``BAKER_VAULT_PATH/layer0_rules.yml``

    Fails loud when none of the above yields an existing file.
    """
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise Layer0RulesError(f"layer0 rules file not found: {candidate}")
        return candidate

    env_override = os.environ.get("KBL_LAYER0_RULES_PATH")
    if env_override:
        candidate = Path(env_override).expanduser()
        if not candidate.is_file():
            raise Layer0RulesError(
                f"KBL_LAYER0_RULES_PATH points at missing file: {candidate}"
            )
        return candidate

    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise Layer0RulesError(
            "neither KBL_LAYER0_RULES_PATH nor BAKER_VAULT_PATH is set — "
            "required to locate layer0_rules.yml"
        )
    candidate = Path(vault).expanduser() / "layer0_rules.yml"
    if not candidate.is_file():
        raise Layer0RulesError(f"layer0 rules file not found: {candidate}")
    return candidate


# --------------------------------- parser ---------------------------------


def _parse_yaml(path: Path) -> Layer0Rules:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise Layer0RulesError(f"failed to read {path}: {e}") from e

    if not isinstance(data, dict):
        raise Layer0RulesError(f"{path}: top-level must be a mapping")

    if "version" not in data:
        raise Layer0RulesError(f"{path}: missing required top-level key `version`")
    version = data["version"]
    if not isinstance(version, str) or not version.strip():
        raise Layer0RulesError(
            f"{path}: `version` must be a non-empty string (got {version!r})"
        )

    if "rules" not in data:
        raise Layer0RulesError(f"{path}: missing required top-level key `rules`")
    rules_raw = data["rules"]
    if not isinstance(rules_raw, list):
        raise Layer0RulesError(f"{path}: `rules` must be a list (got {type(rules_raw).__name__})")

    rules: list[Layer0Rule] = []
    seen_names: set[str] = set()
    for i, raw in enumerate(rules_raw):
        if not isinstance(raw, dict):
            raise Layer0RulesError(f"{path}: rules[{i}] must be a mapping")
        missing = [k for k in _REQUIRED_RULE_KEYS if k not in raw]
        if missing:
            raise Layer0RulesError(
                f"{path}: rules[{i}] missing required key(s): {sorted(missing)}"
            )

        name = raw["name"]
        if not isinstance(name, str) or not name.strip():
            raise Layer0RulesError(
                f"{path}: rules[{i}].name must be a non-empty string (got {name!r})"
            )
        if name in seen_names:
            raise Layer0RulesError(f"{path}: rules[{i}] duplicate rule name {name!r}")
        seen_names.add(name)

        source = raw["source"]
        if not isinstance(source, str) or not source.strip():
            raise Layer0RulesError(
                f"{path}: rules[{i}] ({name}) source must be a non-empty string"
            )

        match = raw["match"]
        if not isinstance(match, dict):
            raise Layer0RulesError(
                f"{path}: rules[{i}] ({name}) match must be a mapping "
                f"(got {type(match).__name__})"
            )

        detail = raw["detail"]
        if not isinstance(detail, str):
            raise Layer0RulesError(
                f"{path}: rules[{i}] ({name}) detail must be a string"
            )

        rules.append(Layer0Rule(name=name, source=source, match=dict(match), detail=detail))

    return Layer0Rules(
        version=version,
        rules=tuple(rules),
        loaded_at=datetime.now(timezone.utc),
        source_path=path,
    )


# ----------------------------- public API -----------------------------


def load_layer0_rules(path: Optional[Path | str] = None) -> Layer0Rules:
    """Load + validate the Layer 0 rules.

    Default-path calls reuse a module-level cache so repeated loads in the
    same process return the same ``Layer0Rules`` object (important for
    Step-0-on-every-tick performance).

    Explicit ``path`` argument bypasses the cache entirely. This keeps
    test-path and ad-hoc experimentation from mutating production cache
    state.
    """
    global _cache, _cache_source

    if path is not None:
        resolved = _resolve_yaml_path(Path(path) if isinstance(path, str) else path)
        return _parse_yaml(resolved)

    if _cache is not None:
        return _cache

    with _lock:
        if _cache is None:
            resolved = _resolve_yaml_path(None)
            _cache = _parse_yaml(resolved)
            _cache_source = resolved
        return _cache


def reload() -> None:
    """Drop the cached rules; next default-path call re-reads + re-validates."""
    global _cache, _cache_source
    with _lock:
        _cache = None
        _cache_source = None
