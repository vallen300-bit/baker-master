"""Cortex 3T runner — Stage 2 V1 (sub-brief 1A: cycle skeleton + Phase 1/2/6).

Wraps cortex reasoning with named-phase persistence into cortex_cycles +
cortex_phase_outputs Postgres tables.

1A scope (this brief):
  Phase 1 (sense)   — create cycle row from inbound trigger
  Phase 2 (load)    — load matter cortex-config + curated + recent activity
  Phase 3-5         — STUB; cycle parks at status='awaiting_reason'
  Phase 6 (archive) — finalize cycle row (ALWAYS runs, even on Phase 1/2 fail)

1B will land Phase 3a/3b/3c (reasoning).
1C will land Phase 4 (proposal) + Phase 5 (act) + scheduler + dry-run + rollback.

Spec:         _ops/ideas/2026-04-27-cortex-3t-formalize-spec.md (RA-22)
Architecture: _ops/processes/cortex-architecture-final.md (RA-23)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 5-min absolute cycle timeout (RA-23 Q5+ ratification — caps worst-case
# cascading-specialist exposure). Override via env for tests.
CYCLE_TIMEOUT_SECONDS = int(os.getenv("CORTEX_CYCLE_TIMEOUT_SECONDS", "300"))


@dataclass
class CortexCycle:
    """Mirror of cortex_cycles row + transient phase artifacts during execution."""
    cycle_id: str
    matter_slug: str
    triggered_by: str  # 'signal' / 'director' / 'cron' / 'gold_comment' / 'refresh'
    trigger_signal_id: Optional[int] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_phase: str = "sense"
    status: str = "in_flight"
    cost_tokens: int = 0
    cost_dollars: float = 0.0
    # Transient — not persisted on row, used during cycle execution:
    phase2_load_context: dict = field(default_factory=dict)
    aborted_reason: Optional[str] = None


def _get_store():
    """Resolve the SentinelStoreBack singleton via the canonical accessor."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


async def maybe_run_cycle(
    *,
    matter_slug: str,
    triggered_by: str,
    trigger_signal_id: Optional[int] = None,
    director_question: Optional[str] = None,
) -> CortexCycle:
    """Entry point — wraps the full cycle in a 5-min asyncio.wait_for.

    1A scope: Phase 1 (sense) + Phase 2 (load) + Phase 6 (archive).
    Status terminates at 'awaiting_reason' (1B/1C land Phase 3-5).
    """
    try:
        return await asyncio.wait_for(
            _run_cycle_inner(
                matter_slug=matter_slug,
                triggered_by=triggered_by,
                trigger_signal_id=trigger_signal_id,
                director_question=director_question,
            ),
            timeout=CYCLE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Cortex cycle timed out after %ds (matter=%s, signal=%s)",
            CYCLE_TIMEOUT_SECONDS, matter_slug, trigger_signal_id,
        )
        # Best-effort cycle-row update to status='failed' on timeout. The
        # cycle row may or may not exist yet (timeout could fire before
        # Phase 1 commits); UPDATE is safe either way.
        try:
            store = _get_store()
            conn = store._get_conn()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE cortex_cycles SET status='failed', "
                        "completed_at=NOW() "
                        "WHERE matter_slug=%s AND trigger_signal_id IS NOT DISTINCT FROM %s "
                        "AND status='in_flight'",
                        (matter_slug, trigger_signal_id),
                    )
                    conn.commit()
                    cur.close()
                finally:
                    store._put_conn(conn)
        except Exception as e:
            logger.error(f"Failed to mark timed-out cycle as failed: {e}")
        raise


async def _run_cycle_inner(
    *,
    matter_slug: str,
    triggered_by: str,
    trigger_signal_id: Optional[int],
    director_question: Optional[str],
) -> CortexCycle:
    """The real cycle — split out so asyncio.wait_for can wrap it.

    Phase 6 archive ALWAYS fires (Quality Checkpoint #10). If Phase 1/2
    raise, status is set to 'failed' before archive; otherwise 1A leaves
    the cycle at 'awaiting_reason'.
    """
    cycle = CortexCycle(
        cycle_id=str(uuid.uuid4()),
        matter_slug=matter_slug,
        triggered_by=triggered_by,
        trigger_signal_id=trigger_signal_id,
    )

    cycle_failed = False
    try:
        # Phase 1 — sense (create cycle row + sense artifact)
        await _phase1_sense(cycle)

        # Phase 2 — load matter context
        cycle.current_phase = "load"
        await _phase2_load(cycle)

        # Phase 3-5 — STUBS in 1A (1B/1C territory)
        cycle.current_phase = "reason"
        cycle.status = "awaiting_reason"
        logger.info(
            "Cortex 1A scope: Phase 3-5 not yet implemented; cycle %s parked "
            "at status=awaiting_reason",
            cycle.cycle_id,
        )
    except Exception as e:
        cycle_failed = True
        cycle.status = "failed"
        cycle.aborted_reason = str(e)[:500]
        logger.error(
            "Cortex cycle %s failed during phase=%s: %s",
            cycle.cycle_id, cycle.current_phase, e,
        )
    finally:
        # Phase 6 — archive ALWAYS runs, even on failure.
        cycle.current_phase = "archive"
        try:
            await _phase6_archive(cycle)
        except Exception as e:
            logger.error(f"Phase 6 archive itself failed for cycle {cycle.cycle_id}: {e}")

    if cycle_failed:
        # Re-raise the original failure so callers see it, even though the
        # archive row is now durable.
        raise RuntimeError(
            f"Cortex cycle {cycle.cycle_id} failed at phase={cycle.current_phase}: "
            f"{cycle.aborted_reason}"
        )

    return cycle


# --------------------------------------------------------------------------
# Phase 1 — sense
# --------------------------------------------------------------------------


async def _phase1_sense(cycle: CortexCycle) -> None:
    """INSERT into cortex_cycles + write a sense artifact row.

    Trusts upstream classification — does NOT re-classify (per architecture
    §3 step 2).
    """
    payload = json.dumps({
        "triggered_by": cycle.triggered_by,
        "matter_slug": cycle.matter_slug,
        "trigger_signal_id": cycle.trigger_signal_id,
    })
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise RuntimeError("Phase 1 sense: no DB connection")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by,
                trigger_signal_id, current_phase, status)
            VALUES (%s, %s, %s, %s, 'sense', 'in_flight')
            """,
            (cycle.cycle_id, cycle.matter_slug, cycle.triggered_by,
             cycle.trigger_signal_id),
        )
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order,
                artifact_type, payload)
            VALUES (%s, 'sense', 1, 'cycle_init', %s::jsonb)
            """,
            (cycle.cycle_id, payload),
        )
        conn.commit()
        cur.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        store._put_conn(conn)


# --------------------------------------------------------------------------
# Phase 2 — load
# --------------------------------------------------------------------------


async def _phase2_load(cycle: CortexCycle) -> None:
    """Load matter cortex-config + curated knowledge + recent activity.

    Loader implementation lives in orchestrator/cortex_phase2_loaders.py
    so this module stays thin. Persists merged context to
    cortex_phase_outputs and bumps cortex_cycles.last_loaded_at.
    """
    from orchestrator.cortex_phase2_loaders import load_phase2_context

    context = await load_phase2_context(cycle.matter_slug)
    cycle.phase2_load_context = context

    payload = json.dumps(context, default=str)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise RuntimeError("Phase 2 load: no DB connection")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order,
                artifact_type, payload)
            VALUES (%s, 'load', 2, 'phase2_context', %s::jsonb)
            """,
            (cycle.cycle_id, payload),
        )
        cur.execute(
            "UPDATE cortex_cycles SET current_phase='load', "
            "last_loaded_at=NOW() WHERE cycle_id=%s",
            (cycle.cycle_id,),
        )
        conn.commit()
        cur.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        store._put_conn(conn)


# --------------------------------------------------------------------------
# Phase 6 — archive (always runs)
# --------------------------------------------------------------------------


async def _phase6_archive(cycle: CortexCycle) -> None:
    """Finalize cycle row and write an archive artifact.

    1A scope: status remains 'awaiting_reason' on success (1B/1C land
    Phase 3-5). On failure, _run_cycle_inner sets cycle.status='failed'
    BEFORE this runs, so archive persists the terminal status.

    Archive payload includes the reason: '1A scope — Phase 3-5 stub;
    awaiting 1B/1C' on success, or the captured aborted_reason on failure.
    """
    archive_payload = json.dumps({
        "reason": cycle.aborted_reason or "1A scope — Phase 3-5 stub; awaiting 1B/1C",
        "final_phase_before_archive": cycle.current_phase,
        "final_status": cycle.status,
    })
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise RuntimeError("Phase 6 archive: no DB connection")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order,
                artifact_type, payload)
            VALUES (%s, 'archive', 6, 'cycle_archive', %s::jsonb)
            """,
            (cycle.cycle_id, archive_payload),
        )
        cur.execute(
            """
            UPDATE cortex_cycles
            SET current_phase='archive',
                status=%s,
                completed_at=NOW(),
                cost_tokens=%s,
                cost_dollars=%s
            WHERE cycle_id=%s
            """,
            (cycle.status, cycle.cost_tokens, cycle.cost_dollars,
             cycle.cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        store._put_conn(conn)
