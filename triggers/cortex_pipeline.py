"""Cortex pipeline stub — wakes a Cortex cycle when a signal lands.

1A scope: stub only. Default OFF via ``CORTEX_LIVE_PIPELINE`` env flag.
1C wires the call site after the canonical signal_queue INSERT in
``kbl/bridge/alerts_to_signal.py`` (verified live 2026-04-28; the brief's
``triggers/pipeline.py`` reference was stale — Lesson #40 cousin).

Until 1C flips the flag, importing this module + calling
``maybe_trigger_cortex(...)`` is safe and dormant: the env-flag check
returns immediately. The function is defensive — any unexpected exception
inside the runner is logged and swallowed so the upstream signal pipeline
never breaks because of a Cortex failure.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _live_pipeline_enabled() -> bool:
    """Reads ``CORTEX_LIVE_PIPELINE`` env. Default False (1A dormant)."""
    return os.environ.get("CORTEX_LIVE_PIPELINE", "false").strip().lower() == "true"


async def maybe_trigger_cortex(
    *,
    signal_id: int,
    matter_slug: Optional[str],
) -> None:
    """Optional Cortex-cycle dispatcher.

    1A scope: stub returns immediately unless CORTEX_LIVE_PIPELINE=true.
    1C will flip the default after dry-run validation (per brief §Out of
    scope). This function MUST never raise — the caller's signal pipeline
    must continue regardless of Cortex state.
    """
    if not _live_pipeline_enabled():
        # 1A default — stub is dormant
        return
    if not matter_slug:
        # No matter → nothing to reason about; skip silently
        return
    try:
        # Imported lazily so a missing/broken cortex_runner doesn't break
        # signal-pipeline boot.
        from orchestrator.cortex_runner import maybe_run_cycle
        await maybe_run_cycle(
            matter_slug=matter_slug,
            triggered_by="signal",
            trigger_signal_id=signal_id,
        )
    except Exception as e:  # noqa: BLE001 — pipeline must continue
        logger.error(
            "Cortex cycle trigger failed for signal %s (matter=%s): %s",
            signal_id, matter_slug, e,
        )
