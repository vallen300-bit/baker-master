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


# CORTEX_3T_FORMALIZE_1C Amendment A2 ---------------------------------------


def _pipeline_dispatch_enabled() -> bool:
    """Reads ``CORTEX_PIPELINE_ENABLED`` env. Default False until DRY_RUN
    on the AO matter passes (Step 30). Distinct from
    ``CORTEX_LIVE_PIPELINE``: that flag controls whether the runner
    actually exits its dormant stub; this flag controls whether the
    upstream ``alerts_to_signal`` dispatch call site fires at all.
    """
    return os.environ.get("CORTEX_PIPELINE_ENABLED", "false").strip().lower() == "true"


def maybe_dispatch(*, signal_id: int, matter_slug: Optional[str]) -> None:
    """Sync entry point used by ``kbl/bridge/alerts_to_signal.py`` after the
    ``signal_queue`` INSERT commits.

    Behaviour:
      * Returns immediately when ``CORTEX_PIPELINE_ENABLED`` is unset.
      * Otherwise drives ``maybe_trigger_cortex`` on a dedicated event
        loop (the bridge tick is sync; we own the loop here).

    Never raises. Cortex is best-effort; the upstream signal_queue write
    has already committed and must not be torn down by a Cortex failure.
    """
    if not _pipeline_dispatch_enabled():
        return
    if not matter_slug:
        return
    try:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Caller is inside an event loop already (unexpected for
                # the bridge tick today, but defensive). Schedule the
                # dispatch as a fire-and-forget task.
                loop.create_task(
                    maybe_trigger_cortex(
                        signal_id=signal_id, matter_slug=matter_slug,
                    )
                )
                return
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(
            maybe_trigger_cortex(
                signal_id=signal_id, matter_slug=matter_slug,
            )
        )
    except Exception as e:  # noqa: BLE001 — never propagate
        logger.error(
            "cortex_pipeline.maybe_dispatch failed for signal %s (matter=%s): %s",
            signal_id, matter_slug, e,
        )
