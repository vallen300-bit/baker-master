"""Cortex Phase 5 — act on Director's button press.

Handlers:
  cortex_approve  — final-freshness check → execute structured_actions →
                    write Gold proposals via gold_proposer.propose →
                    propagate staged curated → archive.
  cortex_edit     — save edited proposal text; cycle stays tier_b_pending.
  cortex_refresh  — re-run Phase 2 + Phase 3; replace card in place.
  cortex_reject   — archive cycle status='rejected'; write feedback_ledger.

Per Amendment A1 (briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md): cortex modules
MUST use ``kbl.gold_proposer.propose(ProposedGoldEntry)`` — NOT
``kbl.gold_writer.append`` (the caller-authorized guard rejects any frame
matching ``cortex_*`` / ``kbl.cortex``).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FRESHNESS_WINDOW_MIN = 30          # final-freshness window before cortex_approve
SSH_PROPAGATE_TIMEOUT_SEC = 30     # Mac Mini SSH-mirror subprocess cap (Quality #10)
STAGING_ROOT = Path("outputs/cortex_proposed_curated")


def _is_dry_run() -> bool:
    return os.environ.get("CORTEX_DRY_RUN", "false").strip().lower() == "true"


def _get_store():
    """Module-level indirection — tests monkeypatch this."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


# --------------------------------------------------------------------------
# Handlers (one per Director button)
# --------------------------------------------------------------------------


async def cortex_approve(*, cycle_id: str, body: dict) -> dict:
    """Director approved — execute or DRY_RUN-log."""
    cycle = _load_cycle(cycle_id)
    if not cycle:
        return {"error": "cycle_not_found"}
    if not _is_fresh(cycle_id):
        return {"warning": "freshness_check_failed", "advice": "refresh_first"}

    matter_slug = cycle.get("matter_slug")
    actions = cycle.get("structured_actions") or []

    if _is_dry_run():
        logger.info(
            "[CORTEX_DRY_RUN] cortex_approve cycle=%s matter=%s — no execute "
            "(actions=%d, gold_files=%d)",
            cycle_id, matter_slug, len(actions),
            len(body.get("selected_gold_files") or []),
        )
        _archive_cycle(cycle_id, status="approved", director_action="gold_approved")
        return {"status": "dry_run_approved",
                "actions_logged": len(actions),
                "matter_slug": matter_slug}

    # V1: structured_actions are logged-only; V2 wires to baker_actions.
    for a in actions:
        logger.info("Cortex action [logged-only V1]: %s", a)

    selected_files = list(body.get("selected_gold_files") or [])
    written = _write_gold_proposals(
        cycle_id=cycle_id, matter_slug=matter_slug,
        selected_files=selected_files, cycle_data=cycle,
    )
    _propagate_curated_via_macmini(cycle_id=cycle_id, matter_slug=matter_slug)

    _archive_cycle(cycle_id, status="approved", director_action="gold_approved")
    return {
        "status": "approved",
        "actions_logged": len(actions),
        "gold_files_written": written,
        "matter_slug": matter_slug,
    }


async def cortex_edit(*, cycle_id: str, body: dict) -> dict:
    """Save Director edits. Cycle stays tier_b_pending."""
    edits = (body.get("edits") or "").strip()
    if not edits:
        return {"warning": "no_edits_provided"}
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return {"error": "no_db_connection"}
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs
                (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 9, 'director_edit', %s::jsonb)
            """,
            (cycle_id, json.dumps({"edited_text": edits[:8000]})),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("cortex_edit failed: %s", e)
        raise
    finally:
        store._put_conn(conn)
    return {"status": "edits_saved", "char_count": len(edits)}


async def cortex_refresh(*, cycle_id: str, body: dict) -> dict:
    """Re-run Phase 2 + Phase 3; produces a new proposal_id (same cycle).

    Uses the existing Phase 3 helpers from cortex_runner; the new card is
    written by ``run_phase4_propose`` so the latest proposal_card row in
    cortex_phase_outputs supersedes the prior one (newer phase_order).
    """
    cycle = _load_cycle(cycle_id)
    if not cycle:
        return {"error": "cycle_not_found"}
    matter_slug = cycle.get("matter_slug")

    # Reconstruct minimal CortexCycle to pass through loaders
    from orchestrator.cortex_runner import CortexCycle, _phase2_load
    from orchestrator.cortex_phase3_reasoner import run_phase3a_meta_reason
    from orchestrator.cortex_phase3_invoker import run_phase3b_invocations
    from orchestrator.cortex_phase3_synthesizer import run_phase3c_synthesize
    from orchestrator.cortex_phase4_proposal import run_phase4_propose

    refreshed = CortexCycle(
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        triggered_by="refresh",
    )
    await _phase2_load(refreshed)
    refreshed.phase2_load_context["signal_text"] = (
        cycle.get("signal_text") or refreshed.phase2_load_context.get("signal_text", "")
    )
    signal_text = refreshed.phase2_load_context["signal_text"]

    phase3a = await run_phase3a_meta_reason(
        cycle_id=cycle_id, matter_slug=matter_slug,
        signal_text=signal_text,
        phase2_context=refreshed.phase2_load_context,
    )
    phase3b = await run_phase3b_invocations(
        cycle_id=cycle_id, matter_slug=matter_slug,
        signal_text=signal_text,
        capabilities_to_invoke=phase3a.capabilities_to_invoke,
        phase2_context=refreshed.phase2_load_context,
    )
    phase3c = await run_phase3c_synthesize(
        cycle_id=cycle_id, matter_slug=matter_slug,
        signal_text=signal_text,
        phase2_context=refreshed.phase2_load_context,
        phase3a_result=phase3a,
        phase3b_result=phase3b,
    )
    new_card = await run_phase4_propose(
        cycle_id=cycle_id, matter_slug=matter_slug, phase3c_result=phase3c,
    )
    return {"status": "refreshed", "new_proposal_id": new_card.proposal_id}


async def cortex_reject(*, cycle_id: str, body: dict) -> dict:
    """Reject — archive + feedback_ledger row."""
    reason = (body.get("reason") or "").strip() or "no_reason_given"
    cycle = _load_cycle(cycle_id) or {}
    _archive_cycle(cycle_id, status="rejected", director_action="gold_rejected")
    _write_feedback_ledger(
        cycle_id=cycle_id, action="ignore",
        reason=reason, target_matter=cycle.get("matter_slug"),
    )
    return {"status": "rejected", "reason": reason}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _is_fresh(cycle_id: str) -> bool:
    """True if no Director email activity referencing this matter in last 30 min.

    Fail-OPEN on DB error (Quality Checkpoint #3 — better to act than block).
    """
    cycle = _load_cycle(cycle_id) or {}
    matter_slug = cycle.get("matter_slug")
    if not matter_slug:
        return True
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return True
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM sent_emails
            WHERE created_at >= NOW() - INTERVAL '%s minutes'
              AND (subject ILIKE %s OR body ILIKE %s)
            LIMIT 1
            """,
            (FRESHNESS_WINDOW_MIN, f"%{matter_slug}%", f"%{matter_slug}%"),
        )
        row = cur.fetchone()
        cur.close()
        return row is None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("_is_fresh failed (fail-open): %s", e)
        return True
    finally:
        store._put_conn(conn)


def _load_cycle(cycle_id: str) -> dict:
    """Load cortex_cycles row + most-recent synthesis artifact."""
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return {}
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT matter_slug, proposal_id, status FROM cortex_cycles "
            "WHERE cycle_id=%s LIMIT 1",
            (cycle_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return {}
        matter_slug, proposal_id, status = row
        cur.execute(
            """
            SELECT payload FROM cortex_phase_outputs
            WHERE cycle_id=%s AND artifact_type='synthesis'
            ORDER BY created_at DESC LIMIT 1
            """,
            (cycle_id,),
        )
        synth_row = cur.fetchone()
        cur.close()
        synth = synth_row[0] if synth_row else {}
        if isinstance(synth, str):
            try:
                synth = json.loads(synth)
            except Exception:
                synth = {}
        synth = synth or {}
        return {
            "cycle_id": cycle_id,
            "matter_slug": matter_slug,
            "proposal_id": proposal_id,
            "status": status,
            "structured_actions": synth.get("structured_actions") or [],
            "proposal_text": synth.get("proposal_text") or "",
            "synthesis_confidence": synth.get("synthesis_confidence") or 0.0,
            "signal_text": synth.get("signal_text") or "",
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("_load_cycle failed: %s", e)
        return {}
    finally:
        store._put_conn(conn)


def _write_gold_proposals(
    *,
    cycle_id: str,
    matter_slug: Optional[str],
    selected_files: list[str],
    cycle_data: dict,
) -> int:
    """For each selected_file build + propose a ProposedGoldEntry.

    Per Amendment A1: cortex modules MUST go through gold_proposer (NOT
    gold_writer). Returns count of entries successfully written.
    """
    if not selected_files:
        return 0
    from kbl.gold_proposer import ProposedGoldEntry, propose
    today = datetime.now(timezone.utc).date().isoformat()
    written = 0
    proposal_text = cycle_data.get("proposal_text") or ""
    confidence = float(cycle_data.get("synthesis_confidence") or 0.0)
    for filename in selected_files:
        topic = f"Cortex cycle {cycle_id[:8]} — {filename}"
        snippet = proposal_text[:600] if proposal_text else "(no synthesis text)"
        entry = ProposedGoldEntry(
            iso_date=today,
            topic=topic,
            proposed_resolution=(
                f"Director approved curated update via Cortex Phase 5. "
                f"Source file: {filename}. Synthesis excerpt: {snippet}"
            ),
            proposer="cortex-3t",
            cortex_cycle_id=cycle_id,
            confidence=confidence,
        )
        try:
            propose(entry, matter=matter_slug)
            written += 1
        except Exception as e:
            logger.error(
                "gold_proposer.propose failed for cycle=%s file=%s: %s",
                cycle_id, filename, e,
            )
    return written


def _propagate_curated_via_macmini(*, cycle_id: str, matter_slug: Optional[str]) -> None:
    """SSH-mirror staged curated → wiki/matters/<slug>/curated/ on Mac Mini.

    V1 fallback: log-only when no MAC_MINI_HOST env var configured. Wrapped
    in subprocess.run with 30s timeout (Quality Checkpoint #10).
    """
    staging = STAGING_ROOT / cycle_id
    if not staging.is_dir() or not matter_slug:
        return
    staged_files = sorted(f.name for f in staging.glob("*.md"))
    if not staged_files:
        return
    target_remote = f"~/baker-vault/wiki/matters/{matter_slug}/curated/"
    macmini_host = os.environ.get("MAC_MINI_HOST")
    if not macmini_host:
        logger.info(
            "Curated propagation log-only (MAC_MINI_HOST unset) cycle=%s files=%s target=%s",
            cycle_id, staged_files, target_remote,
        )
        return
    try:
        cmd = [
            "rsync", "-az",
            f"{staging}/",
            f"{macmini_host}:{target_remote}",
        ]
        subprocess.run(
            cmd, check=True, timeout=SSH_PROPAGATE_TIMEOUT_SEC, capture_output=True,
        )
        logger.info(
            "Curated propagated cycle=%s host=%s files=%d",
            cycle_id, macmini_host, len(staged_files),
        )
    except subprocess.TimeoutExpired:
        logger.error(
            "Curated propagation timed out (>%ds) cycle=%s",
            SSH_PROPAGATE_TIMEOUT_SEC, cycle_id,
        )
    except Exception as e:
        logger.error("Curated propagation failed cycle=%s: %s", cycle_id, e)


def _archive_cycle(
    cycle_id: str,
    *,
    status: str,
    director_action: Optional[str] = None,
) -> None:
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE cortex_cycles
            SET status=%s, director_action=%s,
                completed_at=COALESCE(completed_at, NOW()),
                current_phase='archive'
            WHERE cycle_id=%s
            """,
            (status, director_action, cycle_id),
        )
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs
                (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'archive', 10, 'final_archive', %s::jsonb)
            """,
            (cycle_id, json.dumps({"status": status, "director_action": director_action})),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("_archive_cycle failed: %s", e)
        raise
    finally:
        store._put_conn(conn)


def _write_feedback_ledger(
    *,
    cycle_id: str,
    action: str,
    reason: str,
    target_matter: Optional[str] = None,
) -> None:
    """INSERT row into feedback_ledger.

    Schema (migrations/20260418_loop_infrastructure.sql):
        action_type TEXT NOT NULL,
        target_matter TEXT,
        target_path TEXT,
        signal_id BIGINT,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        director_note TEXT
    """
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return
    try:
        cur = conn.cursor()
        payload = {"cycle_id": cycle_id, "reason": reason, "source": "cortex_phase5"}
        cur.execute(
            """
            INSERT INTO feedback_ledger
                (action_type, target_matter, payload, director_note)
            VALUES (%s, %s, %s::jsonb, %s)
            """,
            (action, target_matter, json.dumps(payload), reason[:500]),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("_write_feedback_ledger failed: %s", e)
    finally:
        store._put_conn(conn)
