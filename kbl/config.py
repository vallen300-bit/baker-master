"""Reads KBL config from yq-sourced shell env.

The wrapper `scripts/kbl-pipeline-tick.sh` sources
`baker-vault/config/env.mac-mini.yml` into flat `KBL_<NESTED>_<KEY>=value`
env vars using yq (see §7 of the KBL-A brief). List-typed YAML values are
comma-joined by the yq expression; cfg_list re-splits on ",".
"""

from __future__ import annotations

import os


def _envkey(key: str) -> str:
    return f"KBL_{key.upper()}"


def cfg(key: str, default: str = "") -> str:
    """Get a scalar config value. Returns default if unset or empty string."""
    raw = os.getenv(_envkey(key), "")
    return raw if raw else default


def cfg_list(key: str, default: list[str] | None = None) -> list[str]:
    """Get a comma-separated list config value. Empty string → empty list
    (unless default overrides)."""
    raw = os.getenv(_envkey(key), "")
    if not raw:
        return list(default) if default else []
    return [x.strip() for x in raw.split(",") if x.strip()]


def cfg_bool(key: str, default: bool = False) -> bool:
    """Accepts 'true'/'false'/'1'/'0'/'yes'/'no' case-insensitive."""
    raw = os.getenv(_envkey(key), "").strip().lower()
    if not raw:
        return default
    return raw in ("true", "1", "yes", "on")


def cfg_int(key: str, default: int = 0) -> int:
    try:
        raw = os.getenv(_envkey(key), "")
        return int(raw) if raw else default
    except (ValueError, TypeError):
        return default


def cfg_float(key: str, default: float = 0.0) -> float:
    try:
        raw = os.getenv(_envkey(key), "")
        return float(raw) if raw else default
    except (ValueError, TypeError):
        return default
