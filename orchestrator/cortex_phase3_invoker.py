"""Cortex Phase 3b — invoke selected specialists.

Per RA-23 Q5: 60s timeout per invocation, 2 retries on
``asyncio.TimeoutError``, fail-forward (one capability's failure does
not raise; Phase 3c synthesizes from partial outputs).

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md``.

EXPLORE deltas vs the brief snippet (Lesson #44):
  - ``run_single`` is a method on ``CapabilityRunner`` (not a top-level
    function) and takes a ``CapabilityDef`` object (not a slug string).
    Verified at ``capability_runner.py:590`` + ``research_executor.py:185``.
  - Sync method, returns ``AgentResult`` (with ``answer``, ``total_input_tokens``,
    ``total_output_tokens``, ``elapsed_ms``). Wrapped in ``asyncio.to_thread``
    + ``asyncio.wait_for`` for timeout enforcement.
  - Cost: ``CapabilityRunner`` already calls ``log_api_cost`` internally
    on every Anthropic round-trip — Phase 3b MUST NOT also log (would
    double-count Prometheus). We compute cycle-row deltas via
    ``calculate_cost_eur`` (silent — no DB write).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SPECIALIST_TIMEOUT_S = 60          # RA-23 Q5
SPECIALIST_MAX_RETRIES = 2         # RA-23 Q5 (so 3 total attempts)
PHASE3B_MODEL_FOR_COST = "claude-opus-4-6"  # cycle-row cost calc only
STAGING_ROOT = Path("outputs/cortex_proposed_curated")


@dataclass
class SpecialistOutput:
    capability_slug: str
    output_text: str
    success: bool
    cost_tokens: int = 0
    cost_dollars: float = 0.0
    error: str | None = None
    duration_seconds: float = 0.0
    attempts: int = 0


@dataclass
class Phase3bResult:
    outputs: list[SpecialistOutput] = field(default_factory=list)
    total_cost_tokens: int = 0
    total_cost_dollars: float = 0.0


# --------------------------------------------------------------------------
# Patchable module-level helpers
# --------------------------------------------------------------------------


def _get_store():
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _get_capability_runner():
    """Return a fresh CapabilityRunner. Patchable in tests."""
    from orchestrator.capability_runner import CapabilityRunner
    return CapabilityRunner()


def _get_capability_def(slug: str):
    """Look up CapabilityDef from the registry. Returns None if missing."""
    from orchestrator.capability_registry import CapabilityRegistry
    registry = CapabilityRegistry.get_instance()
    return registry.get_by_slug(slug)


def _calc_cost_eur(in_tokens: int, out_tokens: int) -> float:
    """Best-effort cost estimate for cycle-row accumulation. Silent on
    failure; capability_runner already logged the canonical Prometheus
    row, so we don't re-log here (avoids double-count).
    """
    try:
        from orchestrator.cost_monitor import calculate_cost_eur
        return float(calculate_cost_eur(PHASE3B_MODEL_FOR_COST, in_tokens, out_tokens))
    except Exception as e:
        logger.warning(f"calculate_cost_eur failed (non-fatal): {e}")
        return 0.0


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


async def run_phase3b_invocations(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    capabilities_to_invoke: list[str],
    phase2_context: dict,
) -> Phase3bResult:
    """Invoke each capability sequentially with bounded resilience.

    Cap-5 + sequential keeps total Phase 3b time bounded under the
    outer 5-min cycle umbrella (worst case 5×60s × 3 attempts = 15min,
    but timeout-then-fail-forward pattern keeps median far lower).
    """
    result = Phase3bResult()
    for slug in capabilities_to_invoke:
        out = await _invoke_one(
            matter_slug=matter_slug,
            signal_text=signal_text,
            capability_slug=slug,
            phase2_context=phase2_context,
        )
        result.outputs.append(out)
        result.total_cost_tokens += out.cost_tokens
        result.total_cost_dollars += out.cost_dollars
        await _persist_specialist_output(cycle_id, out)

    await _bump_cycle_cost(cycle_id, result.total_cost_tokens, result.total_cost_dollars)
    return result


# --------------------------------------------------------------------------
# Single-invocation engine
# --------------------------------------------------------------------------


def _build_specialist_question(
    matter_slug: str,
    signal_text: str,
    phase2_context: dict,
) -> str:
    """Compose the single-shot question fed to the specialist.

    Includes signal + matter brain excerpt + curated knowledge index.
    Kept under ~6KB so the invocation cost stays bounded.
    """
    matter_brain = (phase2_context or {}).get("matter_config", "")[:3000]
    state = (phase2_context or {}).get("state", "")[:1500]
    curated = (phase2_context or {}).get("curated", {}) or {}
    curated_index = ", ".join(sorted(curated.keys())[:20])
    return (
        f"# Cortex specialist invocation — matter '{matter_slug}'\n\n"
        f"## Signal\n{signal_text or '(empty)'}\n\n"
        f"## Matter Brain\n{matter_brain}\n\n"
        f"## Current State\n{state}\n\n"
        f"## Curated Knowledge Index\n{curated_index}\n"
    )


async def _invoke_one(
    *,
    matter_slug: str,
    signal_text: str,
    capability_slug: str,
    phase2_context: dict,
) -> SpecialistOutput:
    """One capability invocation with 60s timeout + 2 retries."""
    cap = _get_capability_def(capability_slug)
    if cap is None:
        logger.warning(
            "Phase 3b: capability '%s' not found in registry — recording failure",
            capability_slug,
        )
        return SpecialistOutput(
            capability_slug=capability_slug,
            output_text="",
            success=False,
            error=f"capability '{capability_slug}' not in active registry",
            attempts=0,
        )

    runner = _get_capability_runner()
    question = _build_specialist_question(matter_slug, signal_text, phase2_context)

    last_err: str | None = None
    total_attempts = SPECIALIST_MAX_RETRIES + 1  # 1 + 2 retries = 3 attempts
    for attempt in range(1, total_attempts + 1):
        t0 = time.monotonic()
        try:
            agent_result = await asyncio.wait_for(
                asyncio.to_thread(runner.run_single, cap, question),
                timeout=SPECIALIST_TIMEOUT_S,
            )
            elapsed = time.monotonic() - t0
            in_tokens = int(getattr(agent_result, "total_input_tokens", 0) or 0)
            out_tokens = int(getattr(agent_result, "total_output_tokens", 0) or 0)
            return SpecialistOutput(
                capability_slug=capability_slug,
                output_text=getattr(agent_result, "answer", "") or "",
                success=True,
                cost_tokens=in_tokens + out_tokens,
                cost_dollars=_calc_cost_eur(in_tokens, out_tokens),
                duration_seconds=elapsed,
                attempts=attempt,
            )
        except asyncio.TimeoutError:
            last_err = f"timeout after {SPECIALIST_TIMEOUT_S}s on attempt {attempt}"
            logger.warning(f"Phase 3b {capability_slug} attempt {attempt}: {last_err}")
        except Exception as e:
            last_err = f"exception on attempt {attempt}: {e}"
            logger.warning(f"Phase 3b {capability_slug} attempt {attempt}: {last_err}")

    # All retries failed — fail-forward (do NOT raise)
    return SpecialistOutput(
        capability_slug=capability_slug,
        output_text="",
        success=False,
        error=last_err,
        duration_seconds=0.0,
        attempts=total_attempts,
    )


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


async def _persist_specialist_output(cycle_id: str, out: SpecialistOutput) -> None:
    """INSERT cortex_phase_outputs row + write staging curated file (if OK).

    Persistence failures here log but do NOT raise — fail-forward applies
    to the persistence layer too (the cycle should keep going even if a
    single artifact write fails). The cycle-level cost bump happens later
    via _bump_cycle_cost.
    """
    payload = json.dumps({
        "capability_slug": out.capability_slug,
        "success": out.success,
        "output_text": out.output_text,
        "error": out.error,
        "cost_tokens": out.cost_tokens,
        "cost_dollars": out.cost_dollars,
        "duration_seconds": out.duration_seconds,
        "attempts": out.attempts,
    }, default=str)
    store = _get_store()
    conn = store._get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order,
                    artifact_type, payload)
                VALUES (%s, 'reason', 4, 'specialist_invocation', %s::jsonb)
                """,
                (cycle_id, payload),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"_persist_specialist_output failed: {e}")
        finally:
            store._put_conn(conn)

    # Staging curated file (Phase 5 / 1C will relocate to canonical wiki
    # via Mac Mini SSH-mirror). Only on success + non-empty output.
    if out.success and out.output_text:
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            staging_dir = STAGING_ROOT / cycle_id
            staging_dir.mkdir(parents=True, exist_ok=True)
            staging_file = staging_dir / f"{out.capability_slug}-{today}.md"
            staging_file.write_text(
                f"# {out.capability_slug} output — cycle {cycle_id} — {today}\n\n"
                f"{out.output_text}\n",
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to write staging curated file: {e}")


async def _bump_cycle_cost(cycle_id: str, tokens: int, dollars: float) -> None:
    """UPDATE cortex_cycles cost columns by Phase 3b totals."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cortex_cycles "
            "SET cost_tokens = cost_tokens + %s, "
            "    cost_dollars = cost_dollars + %s "
            "WHERE cycle_id=%s",
            (tokens, dollars, cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"_bump_cycle_cost failed: {e}")
    finally:
        store._put_conn(conn)
