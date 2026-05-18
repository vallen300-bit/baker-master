"""Cortex 3T runner — Stage 2 V1.

Wraps cortex reasoning with named-phase persistence into cortex_cycles +
cortex_phase_outputs Postgres tables.

Phases (1A skeleton + 1B reasoning, 1C still pending):
  Phase 1 (sense)   — create cycle row from inbound trigger
  Phase 2 (load)    — load matter cortex-config + curated + recent activity
  Phase 3 (reason)  — 3a meta + 3b specialist invocation + 3c synthesis
                      → cycle status flips to 'proposed' on success
  Phase 4-5         — STUB still; 1C will land proposal + act
  Phase 6 (archive) — finalize cycle row (ALWAYS runs, even on Phase 1-3 fail)

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
    phase3c_result: Optional[Any] = None
    proposal_id: Optional[str] = None
    aborted_reason: Optional[str] = None


def _get_store():
    """Resolve the SentinelStoreBack singleton via the canonical accessor."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


# --------------------------------------------------------------------------
# Brisen-Lab bus heartbeat — observability emit at every phase boundary.
# Phase progression MUST continue regardless of lab availability (lab is
# observability, not control plane). Helpers below have their own try/except
# AND every call site wraps with belt-and-suspenders try/except.
# --------------------------------------------------------------------------

_BRISEN_LAB_HEARTBEAT_PHASES = {"sense", "load", "reason", "propose", "archive", "failed"}


async def _post_to_brisen_lab_bus(
    *,
    topic: str,
    body: str,
    cycle: "CortexCycle",
    recipient: str = "daemon",
) -> None:
    """Internal: POST a single envelope to brisen-lab /msg/{recipient}. Never raises.

    Canonical wire contract (per `~/Desktop/baker-code/scripts/bus_post.sh`):
    - URL: POST {base}/msg/{recipient}  (recipient slug in path)
    - Body: {"kind": "dispatch", "body": <text>, "to": [<recipient>],
            "tier_required": "B", "topic": <topic>}
    - Sender is derived from the X-Terminal-Key auth header; no
      `from_terminal` field on the wire.

    Recipient defaults to `daemon` — the observability sink that does not
    raise an unread badge on any orchestrator card. Phase heartbeats route
    there; `ratify-required` envelopes pass recipient="director" since they
    are actionable (Director ratifies, lead does not).

    Skipped when BRISEN_LAB_TERMINAL_KEY_CORTEX env var is missing (logs warn
    + returns). 5s timeout via httpx.AsyncClient. Any exception path
    (timeout, network, 4xx, 5xx, missing key) collapses to a warning log.
    """
    key = os.getenv("BRISEN_LAB_TERMINAL_KEY_CORTEX")
    if not key:
        logger.warning(
            "Cortex heartbeat skipped — BRISEN_LAB_TERMINAL_KEY_CORTEX unset",
            extra={
                "cycle_id": str(getattr(cycle, "cycle_id", None)),
                "phase": topic.split("/")[-1],
                "error_class": "MissingKey",
            },
        )
        return
    base = os.getenv("BRISEN_LAB_URL", "https://brisen-lab.onrender.com").rstrip("/")
    url = f"{base}/msg/{recipient}"
    payload = {
        "kind": "dispatch",
        "body": body,
        "to": [recipient],
        "tier_required": "B",
        "topic": topic,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                url,
                headers={"X-Terminal-Key": key, "Content-Type": "application/json"},
                json=payload,
            )
    except Exception as e:
        logger.warning(
            "Cortex heartbeat post failed",
            extra={
                "cycle_id": str(getattr(cycle, "cycle_id", None)),
                "phase": topic.split("/")[-1],
                "error_class": type(e).__name__,
            },
        )


async def _emit_cortex_heartbeat(
    cycle: "CortexCycle",
    phase: str,
    status: str,
) -> None:
    """Post a phase-boundary heartbeat to brisen-lab bus.

    Best-effort: NEVER raises. Bus-post failure logs at warning and returns.
    The lab is observability, not control plane — phase progression cannot
    block on bus availability.

    Topic invariant (brisen-lab static/app.js parses tail via
    topic.split("/").pop()): cortex/<matter_slug>/cycle-phase/<phase> with
    phase in {sense, load, reason, propose, archive, failed}.
    """
    topic = f"cortex/{cycle.matter_slug}/cycle-phase/{phase}"
    body = (
        f"cycle_id={cycle.cycle_id} matter={cycle.matter_slug} "
        f"phase={phase} status={status}"
    )
    await _post_to_brisen_lab_bus(topic=topic, body=body, cycle=cycle, recipient="daemon")


async def _emit_cortex_ratify_required(cycle: "CortexCycle") -> None:
    """Post the ratify-required signal when entering tier_b_pending.

    Lab needs this distinct from the phase=propose heartbeat for the
    open_director_qs counter + >120s stuck badge. Best-effort: NEVER raises.
    """
    short_summary = getattr(cycle.phase3c_result, "proposal_text", None)
    if not short_summary:
        short_summary = str(cycle.phase3c_result) if cycle.phase3c_result is not None else ""
    short_summary = short_summary[:200]
    topic = f"cortex/{cycle.matter_slug}/ratify-required"
    body = (
        f"cycle_id={cycle.cycle_id} matter={cycle.matter_slug} "
        f"proposal_summary={short_summary}"
    )
    await _post_to_brisen_lab_bus(topic=topic, body=body, cycle=cycle, recipient="director")


async def _safe_emit_heartbeat(cycle: "CortexCycle", phase: str, status: str) -> None:
    """Call-site wrapper — belt-and-suspenders: even if _emit_cortex_heartbeat
    grows a regression that leaks past its own try/except, the cycle MUST
    continue. Logs + swallows.
    """
    try:
        await _emit_cortex_heartbeat(cycle, phase, status)
    except Exception as e:
        logger.warning(
            "Cortex heartbeat call-site swallowed unexpected error",
            extra={
                "cycle_id": str(getattr(cycle, "cycle_id", None)),
                "phase": phase,
                "error_class": type(e).__name__,
            },
        )


async def _safe_emit_ratify_required(cycle: "CortexCycle") -> None:
    """Call-site wrapper for ratify-required signal. Same belt-and-suspenders contract."""
    try:
        await _emit_cortex_ratify_required(cycle)
    except Exception as e:
        logger.warning(
            "Cortex ratify-required call-site swallowed unexpected error",
            extra={
                "cycle_id": str(getattr(cycle, "cycle_id", None)),
                "phase": "propose",
                "error_class": type(e).__name__,
            },
        )


async def maybe_run_cycle(
    *,
    matter_slug: str,
    triggered_by: str,
    trigger_signal_id: Optional[int] = None,
    director_question: Optional[str] = None,
) -> CortexCycle:
    """Entry point — wraps the full cycle in a 5-min asyncio.wait_for.

    1A+1B scope: Phase 1 (sense) + Phase 2 (load) + Phase 3 (reason) +
    Phase 6 (archive). Phase 3 success terminates at status='proposed';
    Phase 3 failure terminates at status='failed'. 1C will add Phase 4-5.
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
            "Cortex cycle timed out",
            extra={
                "cycle_id": None,
                "phase": "timeout",
                "error_class": "TimeoutError",
                "matter_slug": matter_slug,
                "timeout_seconds": CYCLE_TIMEOUT_SECONDS,
                "trigger_signal_id": trigger_signal_id,
            },
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
            logger.error(
                "Failed to mark timed-out cycle as failed",
                extra={
                    "cycle_id": None,
                    "phase": "timeout_recovery",
                    "error_class": type(e).__name__,
                    "matter_slug": matter_slug,
                },
            )
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
    raise, status is set to 'failed' before archive. Phase 3 catches its
    own exceptions (sets status='failed' / aborted_reason) so the cycle
    return value is always usable; the cycle still archives the failure.
    """
    cycle = CortexCycle(
        cycle_id=str(uuid.uuid4()),
        matter_slug=matter_slug,
        triggered_by=triggered_by,
        trigger_signal_id=trigger_signal_id,
    )
    cycle_failed = False
    proposal_card_posted = False
    try:
        # Phase 1 — sense (create cycle row + sense artifact)
        await _phase1_sense(cycle)
        await _safe_emit_heartbeat(cycle, "sense", "ok")

        # Phase 2 — load matter context
        cycle.current_phase = "load"
        await _phase2_load(cycle)
        # Plumb signal_text into context so Phase 3 has it. Director-
        # triggered cycles use director_question; signal-triggered cycles
        # need a signal_queue lookup that's 1C scope (per Obs #1 from PR
        # #71 review). 1B leaves signal_text empty for those.
        cycle.phase2_load_context["signal_text"] = director_question or ""
        await _safe_emit_heartbeat(cycle, "load", "ok")

        # Phase 3 — reasoning (3a meta + 3b specialist + 3c synthesize)
        cycle.current_phase = "reason"
        await _phase3_reason(cycle)
        await _safe_emit_heartbeat(cycle, "reason", cycle.status)

        # Phase 4 — propose (1C). Posts Slack card + flips status to
        # 'tier_b_pending' inside _phase4_propose. Director button press
        # later reaches Phase 5 via /cortex/cycle/{id}/action endpoint
        # which archives the cycle. Phase 4 only fires if Phase 3 produced
        # a synthesis; otherwise we fall through to the archive below.
        if cycle.phase3c_result is not None and cycle.status == "proposed":
            cycle.current_phase = "propose"
            try:
                if await _phase4_propose(cycle):
                    await _safe_emit_heartbeat(cycle, "propose", "tier_b_pending")
                    await _safe_emit_ratify_required(cycle)
                    proposal_card_posted = True
            except Exception as e:
                logger.error(
                    "Phase 4 failed",
                    extra={
                        "cycle_id": str(cycle.cycle_id),
                        "phase": "propose",
                        "error_class": type(e).__name__,
                        "matter_slug": getattr(cycle, "matter_slug", None),
                    },
                )
                cycle.status = "failed"
                cycle.aborted_reason = f"phase4_error: {str(e)[:400]}"
    except Exception as e:
        cycle_failed = True
        cycle.status = "failed"
        cycle.aborted_reason = str(e)[:500]
        logger.error(
            "Cortex cycle failed",
            extra={
                "cycle_id": str(cycle.cycle_id),
                "phase": cycle.current_phase,
                "error_class": type(e).__name__,
                "matter_slug": getattr(cycle, "matter_slug", None),
            },
        )
        await _safe_emit_heartbeat(cycle, cycle.current_phase, "failed")
    finally:
        # Phase 6 archive: skipped when Phase 4 successfully posted the
        # proposal card. The cycle is now 'tier_b_pending' awaiting
        # Director's button press; Phase 5 (via the action endpoint)
        # owns the archive in that path. Otherwise we still archive on
        # the failure / no-synthesis path.
        if not proposal_card_posted:
            cycle.current_phase = "archive"
            try:
                await _phase6_archive(cycle)
            except Exception as e:
                logger.error(
                    "Phase 6 archive itself failed",
                    extra={
                        "cycle_id": str(cycle.cycle_id),
                        "phase": "archive",
                        "error_class": type(e).__name__,
                        "matter_slug": getattr(cycle, "matter_slug", None),
                    },
                )
                # CORTEX_ARCHIVE_FAILURE_ALERTING_1: persist `archive_failed`
                # terminal state best-effort so cortex_stuck_cycle_sentinel
                # Detector B can find it. If THIS write also fails, Detector A
                # remains the safety net for cycles still in transient status.
                try:
                    from memory.store_back import SentinelStoreBack
                    _store = SentinelStoreBack._get_global_instance()
                    _conn = _store._get_conn()
                    if _conn:
                        try:
                            _cur = _conn.cursor()
                            _cur.execute(
                                "UPDATE cortex_cycles SET status='archive_failed', "
                                "completed_at=NOW() WHERE cycle_id=%s",
                                (str(cycle.cycle_id),),
                            )
                            _conn.commit()
                            _cur.close()
                        finally:
                            _store._put_conn(_conn)
                except Exception:
                    pass  # Detector A safety net

        # Archive-boundary heartbeat fires for EVERY cycle terminal —
        # whether Phase 6 actually ran (status=proposed/archive_failed/failed)
        # or was skipped because Phase 4 posted the proposal card
        # (status=tier_b_pending). Symmetric "cycle finalized" signal so the
        # lab can flip the Cortex card on any terminal state.
        await _safe_emit_heartbeat(cycle, "archive", cycle.status)

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
# Phase 3 — reason (1B: 3a meta + 3b specialist invocation + 3c synthesis)
# --------------------------------------------------------------------------


async def _phase3_reason(cycle: CortexCycle) -> None:
    """Run 3a → 3b → 3c. Cost accumulates onto the cycle as we go.

    Phase 3 catches its own exceptions: on failure, cycle.status is set
    to 'failed' and aborted_reason is captured, but no exception is
    re-raised — Phase 6 still archives. This asymmetry vs Phase 1/2 is
    intentional: Phase 3 is best-effort reasoning, and a single specialist
    failure is fail-forward (handled by 3b internally); only DB-persist
    failures in 3a/3c get caught here.
    """
    from orchestrator.cortex_phase3_reasoner import run_phase3a_meta_reason
    from orchestrator.cortex_phase3_invoker import run_phase3b_invocations
    from orchestrator.cortex_phase3_synthesizer import run_phase3c_synthesize

    signal_text = cycle.phase2_load_context.get("signal_text", "")

    try:
        # 3a — meta-reasoning + capability selection
        phase3a = await run_phase3a_meta_reason(
            cycle_id=cycle.cycle_id,
            matter_slug=cycle.matter_slug,
            signal_text=signal_text,
            phase2_context=cycle.phase2_load_context,
        )
        cycle.cost_tokens += phase3a.cost_tokens
        cycle.cost_dollars += phase3a.cost_dollars

        # 3b — specialist invocations (cap-5 enforced in 3a)
        phase3b = await run_phase3b_invocations(
            cycle_id=cycle.cycle_id,
            matter_slug=cycle.matter_slug,
            signal_text=signal_text,
            capabilities_to_invoke=phase3a.capabilities_to_invoke,
            phase2_context=cycle.phase2_load_context,
        )
        cycle.cost_tokens += phase3b.total_cost_tokens
        cycle.cost_dollars += phase3b.total_cost_dollars

        # 3c — synthesis → cycle status flips to 'proposed'
        phase3c = await run_phase3c_synthesize(
            cycle_id=cycle.cycle_id,
            matter_slug=cycle.matter_slug,
            signal_text=signal_text,
            phase2_context=cycle.phase2_load_context,
            phase3a_result=phase3a,
            phase3b_result=phase3b,
        )
        cycle.cost_tokens += phase3c.cost_tokens
        cycle.cost_dollars += phase3c.cost_dollars
        cycle.phase3c_result = phase3c
        cycle.status = "proposed"  # 1C Phase 4 reads phase3c_result + flips to tier_b_pending
    except Exception as e:
        logger.error(
            "Phase 3 failed",
            extra={
                "cycle_id": str(cycle.cycle_id),
                "phase": "reason",
                "error_class": type(e).__name__,
                "matter_slug": getattr(cycle, "matter_slug", None),
            },
        )
        cycle.status = "failed"
        cycle.aborted_reason = f"phase3_error: {str(e)[:400]}"
        # Do NOT re-raise — Phase 6 archives the failure terminal state.


# --------------------------------------------------------------------------
# Phase 4 — propose (1C wiring; delegate to cortex_phase4_proposal module)
# --------------------------------------------------------------------------


async def _phase4_propose(cycle: CortexCycle) -> bool:
    """Render + post the proposal card. Imports lazily so cortex_runner
    keeps zero hard dependency on Phase 4 at import time.

    Returns True iff the card was successfully built and persisted —
    that's the gate that signals to the runner to skip Phase 6 archive
    (Phase 5 owns the archive on the button-press path). Tests can
    monkey-patch this function and return None / False to keep the 1B-
    style Phase-3-isolated assertion semantics.
    """
    from orchestrator.cortex_phase4_proposal import run_phase4_propose
    card = await run_phase4_propose(
        cycle_id=cycle.cycle_id,
        matter_slug=cycle.matter_slug,
        phase3c_result=cycle.phase3c_result,
    )
    cycle.proposal_id = card.proposal_id
    cycle.status = "tier_b_pending"
    return True


# --------------------------------------------------------------------------
# Phase 6 — archive (always runs unless Phase 4 successfully posted)
# --------------------------------------------------------------------------


async def _phase6_archive(cycle: CortexCycle) -> None:
    """Finalize cycle row and write an archive artifact.

    1A+1B scope: success terminates at status='proposed' (Phase 3c flip);
    Phase 4-5 are 1C territory. On Phase 1/2/3 failure, status='failed'
    is set before this runs so archive persists the terminal state.
    """
    archive_payload = json.dumps({
        "reason": cycle.aborted_reason or "1B scope — Phase 4-5 stub; awaiting 1C",
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
