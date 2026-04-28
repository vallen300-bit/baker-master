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
# Idempotency CAS guard (CORTEX_PHASE5_IDEMPOTENCY_1)
# --------------------------------------------------------------------------


def _cas_lock_cycle(
    cycle_id: str,
    *,
    from_status: str,
    to_status: str,
    action_attempted: str,
) -> Optional[dict]:
    """Atomically transition cortex_cycles.status from `from_status` to `to_status`.

    Returns ``None`` on successful transition (cycle is now in ``to_status``).
    Returns a warning dict if no rows updated (cycle was not in ``from_status``),
    re-reading the actual current status for diagnostic.

    This is the per-handler idempotency guard: a second invocation of the same
    Director button (double-click, Slack proxy retry, etc.) sees status already
    advanced and bails out with HTTP 200 + ``warning="already_actioned"``.

    On DB exception the lock fails CLOSED — re-raises so the caller does NOT
    proceed past a botched lock (would defeat idempotency). On no-conn the
    same: returns dict with ``error="no_db_connection"`` so caller bails.
    """
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return {
            "error": "no_db_connection",
            "cycle_id": cycle_id,
            "action_attempted": action_attempted,
        }
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE cortex_cycles
            SET status=%s, updated_at=NOW()
            WHERE cycle_id=%s AND status=%s
            RETURNING cycle_id
            """,
            (to_status, cycle_id, from_status),
        )
        row = cur.fetchone()
        if row is None:
            # Re-read current status for diagnostic; HTTP 200 (idempotent retry).
            cur.execute(
                "SELECT status FROM cortex_cycles WHERE cycle_id=%s LIMIT 1",
                (cycle_id,),
            )
            current_row = cur.fetchone()
            current = current_row[0] if current_row else "<not-found>"
            conn.commit()
            cur.close()
            return {
                "warning": "already_actioned",
                "current_status": current,
                "cycle_id": cycle_id,
                "action_attempted": action_attempted,
            }
        conn.commit()
        cur.close()
        return None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("_cas_lock_cycle failed cycle=%s: %s", cycle_id, e)
        raise
    finally:
        store._put_conn(conn)


def _cas_release_to_proposed(cycle_id: str, *, from_status: str) -> None:
    """Transition cycle back to 'proposed' after a transient lock (edit/refresh).

    Used by ``cortex_edit`` (releases 'editing' → 'proposed') and
    ``cortex_refresh`` (releases 'refreshing' → 'proposed') so the cycle can
    be re-approved. Best-effort: DB errors are logged but do not raise — the
    primary work (insert / re-run Phase 3+4) already succeeded; leaving the
    cycle in '*ing' state is recoverable by the parked archive-failure
    sentinel (`_ops/ideas/2026-04-28-cortex-archive-failure-alerting.md`).
    """
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        logger.warning(
            "cortex_phase5 release-to-proposed skipped (no_db_connection) "
            "cycle=%s from=%s",
            cycle_id, from_status,
        )
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE cortex_cycles
            SET status='proposed', updated_at=NOW()
            WHERE cycle_id=%s AND status=%s
            """,
            (cycle_id, from_status),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(
            "_cas_release_to_proposed failed cycle=%s from=%s: %s",
            cycle_id, from_status, e,
        )
    finally:
        store._put_conn(conn)


# --------------------------------------------------------------------------
# Handlers (one per Director button)
# --------------------------------------------------------------------------


async def cortex_approve(*, cycle_id: str, body: dict) -> dict:
    """Director approved — execute or DRY_RUN-log.

    CORTEX_PHASE5_IDEMPOTENCY_1: CAS-locks 'proposed' → 'approving' before any
    other DB read or write. Double-fire (Director double-click / Slack retry)
    bails with ``warning="already_actioned"`` and HTTP 200.
    """
    guard = _cas_lock_cycle(
        cycle_id,
        from_status="proposed",
        to_status="approving",
        action_attempted="approve",
    )
    if guard is not None:
        return guard

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
        _archive_cycle(
            cycle_id, status="approved", director_action="gold_approved",
            from_status="approving",
        )
        return {"status": "dry_run_approved",
                "actions_logged": len(actions),
                "matter_slug": matter_slug}

    # V1: structured_actions are logged-only; V2 wires to baker_actions.
    for a in actions:
        logger.info("Cortex action [logged-only V1]: %s", a)

    selected_files = list(body.get("selected_gold_files") or [])
    gold_result = _write_gold_proposals(
        cycle_id=cycle_id, matter_slug=matter_slug,
        selected_files=selected_files, cycle_data=cycle,
    )
    _propagate_curated_via_macmini(cycle_id=cycle_id, matter_slug=matter_slug)

    _archive_cycle(
        cycle_id, status="approved", director_action="gold_approved",
        from_status="approving",
    )

    # Partial-failure surfacing (CORTEX_PHASE5_IDEMPOTENCY_1 OBS-2):
    # cycle archive proceeded (status='approved') but Director sees discrepancy
    # in response payload when GOLD writes failed in whole or in part.
    written = gold_result["written"]
    total = gold_result["total"]
    base_response = {
        "actions_logged": len(actions),
        "gold_files_written": written,
        "matter_slug": matter_slug,
    }
    if total > 0 and written == 0:
        return {
            **base_response,
            "status": "approved_with_errors",
            "warning": "all_gold_proposals_failed",
            "cycle_id": cycle_id,
            "gold_files_attempted": total,
            "errors": gold_result["errors"],
        }
    if total > 0 and written < total:
        return {
            **base_response,
            "status": "approved_with_partial_errors",
            "warning": "some_gold_proposals_failed",
            "cycle_id": cycle_id,
            "gold_files_attempted": total,
            "failed_files": gold_result["failed_files"],
        }
    return {**base_response, "status": "approved"}


async def cortex_edit(*, cycle_id: str, body: dict) -> dict:
    """Save Director edits. Cycle stays tier_b_pending.

    CORTEX_PHASE5_IDEMPOTENCY_1: CAS-locks 'proposed' → 'editing' before INSERT;
    on success, releases back to 'proposed' so the cycle can be re-approved.
    """
    edits = (body.get("edits") or "").strip()
    if not edits:
        return {"warning": "no_edits_provided"}

    guard = _cas_lock_cycle(
        cycle_id,
        from_status="proposed",
        to_status="editing",
        action_attempted="edit",
    )
    if guard is not None:
        return guard

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

    # Release back to 'proposed' so cycle is re-approvable.
    _cas_release_to_proposed(cycle_id, from_status="editing")
    return {"status": "edits_saved", "char_count": len(edits)}


async def cortex_refresh(*, cycle_id: str, body: dict) -> dict:
    """Re-run Phase 2 + Phase 3; produces a new proposal_id (same cycle).

    Uses the existing Phase 3 helpers from cortex_runner; the new card is
    written by ``run_phase4_propose`` so the latest proposal_card row in
    cortex_phase_outputs supersedes the prior one (newer phase_order).

    CORTEX_PHASE5_IDEMPOTENCY_1: CAS-locks 'proposed' → 'refreshing' before
    Phase-2/3 work; releases back to 'proposed' on success so the cycle can
    be re-approved with the new card.
    """
    guard = _cas_lock_cycle(
        cycle_id,
        from_status="proposed",
        to_status="refreshing",
        action_attempted="refresh",
    )
    if guard is not None:
        return guard

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
    # Release back to 'proposed' so cycle is re-approvable with new card.
    _cas_release_to_proposed(cycle_id, from_status="refreshing")
    return {"status": "refreshed", "new_proposal_id": new_card.proposal_id}


async def cortex_reject(*, cycle_id: str, body: dict) -> dict:
    """Reject — archive + feedback_ledger row.

    CORTEX_PHASE5_IDEMPOTENCY_1: CAS-locks 'proposed' → 'rejecting' before any
    other DB read or write. Final transition to 'rejected' happens in
    ``_archive_cycle`` with the hardened ``from_status='rejecting'`` guard.
    """
    guard = _cas_lock_cycle(
        cycle_id,
        from_status="proposed",
        to_status="rejecting",
        action_attempted="reject",
    )
    if guard is not None:
        return guard

    reason = (body.get("reason") or "").strip() or "no_reason_given"
    cycle = _load_cycle(cycle_id) or {}
    _archive_cycle(
        cycle_id, status="rejected", director_action="gold_rejected",
        from_status="rejecting",
    )
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
) -> dict:
    """For each selected_file build + propose a ProposedGoldEntry.

    Per Amendment A1: cortex modules MUST go through gold_proposer (NOT
    gold_writer).

    CORTEX_PHASE5_IDEMPOTENCY_1 (OBS-2): returns a rich result dict so the
    caller can surface partial-failure to Director::

        {
            "written": int,                 # count succeeded
            "total": int,                   # count attempted
            "failed_files": list[str],      # filenames that failed
            "errors": list[str],            # str(exception) per failure
        }

    Per-file try/except continues across siblings (one bad file shouldn't
    kill the rest); aggregate failure visibility now lives in the return
    shape rather than the prior int (which silently lost the discrepancy).
    """
    result = {"written": 0, "total": len(selected_files), "failed_files": [], "errors": []}
    if not selected_files:
        return result
    from kbl.gold_proposer import ProposedGoldEntry, propose
    today = datetime.now(timezone.utc).date().isoformat()
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
            result["written"] += 1
        except Exception as e:
            logger.error(
                "gold_proposer.propose failed for cycle=%s file=%s: %s",
                cycle_id, filename, e,
            )
            result["failed_files"].append(filename)
            result["errors"].append(str(e))
    return result


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
    from_status: Optional[str] = None,
) -> Optional[dict]:
    """Archive cycle — terminal status transition + final_archive artifact.

    CORTEX_PHASE5_IDEMPOTENCY_1: when ``from_status`` is supplied, the UPDATE
    is gated by ``WHERE status=<from_status>`` and ``RETURNING cycle_id``. If
    no rows match (cycle was not in the expected intermediate '*ing' state),
    the function logs a warning and returns a warning dict WITHOUT inserting
    a duplicate ``final_archive`` row. Callers may ignore the return value
    for backward compatibility (``None`` on success).

    When ``from_status`` is ``None`` the call falls back to the legacy
    unconditional UPDATE — preserved for any caller that hasn't been migrated
    yet.
    """
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        if from_status is not None:
            cur.execute(
                """
                UPDATE cortex_cycles
                SET status=%s, director_action=%s,
                    completed_at=COALESCE(completed_at, NOW()),
                    current_phase='archive'
                WHERE cycle_id=%s AND status=%s
                RETURNING cycle_id
                """,
                (status, director_action, cycle_id, from_status),
            )
            if cur.fetchone() is None:
                # Cycle was not in the expected intermediate state.
                # Log + return warning; do NOT insert final_archive (would
                # otherwise create a duplicate audit row on double-fire).
                logger.warning(
                    "cortex_archive_cycle_unexpected_state cycle=%s expected=%s target=%s",
                    cycle_id, from_status, status,
                )
                conn.commit()
                cur.close()
                return {
                    "warning": "archive_unexpected_state",
                    "cycle_id": cycle_id,
                    "expected_from_status": from_status,
                    "target_status": status,
                }
        else:
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
        return None
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
