"""Cortex Lite policy helpers.

CORTEX_LITE_REBASE_1: centralizes the temporary 14-day Cortex Lite operating
shape. Lite mode preserves Director-invoked + gated-signal Cortex cycles but
prevents broad matter fanout and runaway direct-fire fallback while usefulness
is being proven. Specialist-cap clamp intentionally deferred (full Cortex
CAP5_LIMIT preserved); only allowlist + direct-fire-off are in this v1.
"""
from __future__ import annotations

import os

TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_LITE_MATTERS = ("oskolkov", "hagenauer-rg7")

# Hard-coded Lite constants (not env-tunable in v1 — keep surface minimal).
LITE_DIRECT_FIRE_ALLOWED = False
LITE_STALE_PENDING_HOURS = 72.0


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in TRUE_VALUES


def lite_enabled() -> bool:
    """True when Cortex Lite restrictions are active.

    Default false so deploy is behavior-preserving until AH1 explicitly flips
    the env flag after Director ratification.
    """
    return _truthy_env("CORTEX_LITE_ENABLED", "false")


def lite_matters() -> set[str]:
    """Matter allowlist used only when Lite is enabled."""
    raw = os.environ.get("CORTEX_LITE_MATTERS", "").strip()
    if not raw:
        return set(DEFAULT_LITE_MATTERS)
    return {part.strip() for part in raw.split(",") if part.strip()}


def matter_allowed(matter_slug: str) -> bool:
    """True when a matter may run Cortex under the current policy."""
    if not matter_slug:
        return False
    if not lite_enabled():
        return True
    return matter_slug in lite_matters()


def direct_fire_allowed() -> bool:
    """Whether the signal pipeline may bypass the pre-review gate and run a cycle.

    In Lite mode direct-fire is hard-off (constant). Emergency rollback to the
    legacy fallback is CORTEX_LITE_ENABLED=false, not a per-feature env.
    """
    if not lite_enabled():
        return True
    return LITE_DIRECT_FIRE_ALLOWED


def stale_pending_hours() -> float:
    """Age (hours) after which tier_b_pending cycles are flagged stale in UI/API."""
    return LITE_STALE_PENDING_HOURS
