"""Cortex Phase 6 Reconciler — vault-write-outside-counter-txn drift detector.

Brief: CORTEX_PHASE6_VAULT_RECONCILER_1.

Background
----------
Reflector commits the counter-update + idempotency-marker INSERT inside one
PG transaction (cortex_phase6_reflector.py:615-694), but the subsequent vault
write at :724-737 is filesystem-side (CHANDA #9) and lives outside that
transaction in a try/except that only logs. If the vault write throws (FS
permissions, disk full, mac-mini sync glitch), the marker is durable but
``proposed-config-deltas.md`` is silently missing. Subsequent sweeps then
skip the cycle because the marker is present.

This module is the cheap reconciler:

  1. Enumerate ``cortex_phase_outputs`` rows where
     ``artifact_type='reflector_complete'``, ordered by ``created_at ASC``,
     ``LIMIT 200`` per run.
  2. For each marker, compute the expected vault path (same logic as
     ``write_proposed_actions_to_vault``).
  3. If file missing OR cycle block (``## Cycle <cycle_id> —``) absent:
     re-emit by calling ``write_proposed_actions_to_vault`` with the same
     args the Reflector would have used. ``proposal_text`` is re-loaded
     via ``_load_proposal_text`` (not stored on the marker).
  4. Audit each re-emit to ``baker_actions``
     (action_type='cortex_reflector_reconcile').

V1 explicit drops (see brief §V1 explicit drops): no counter touches, no
ClickUp reconciliation, no alerting threshold, no missing-marker backstop,
no metrics dashboard.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Reuse Reflector helpers + constants — do NOT duplicate.
from orchestrator.cortex_phase6_reflector import (
    DEFAULT_STAGING_ROOT,
    REFLECTOR_COMPLETE_ARTIFACT,
    _get_store,
    _load_proposal_text,
    write_proposed_actions_to_vault,
)

logger = logging.getLogger(__name__)


def _vault_target_for(matter_slug: str, staging_root: Optional[Path] = None) -> Path:
    """Compute expected vault path. Mirrors write_proposed_actions_to_vault:316-317."""
    root = staging_root if staging_root is not None else DEFAULT_STAGING_ROOT
    return root / "matters" / matter_slug / "proposed-config-deltas.md"


def _has_cycle_block(target: Path, cycle_id: str) -> bool:
    """Substring check for ``## Cycle <cycle_id> —``. cycle_id is UUID;
    collision-free against other cycles' block headers."""
    if not target.exists():
        return False
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"reconciler: read failed for {target}: {e}")
        return False
    return f"## Cycle {cycle_id} \u2014" in text


def reconcile_vault_writes(
    *,
    limit: int = 200,
    staging_root: Optional[Path] = None,
) -> dict:
    """Find reflector_complete markers whose vault file is missing or
    incomplete; re-emit the vault block for each.

    Returns counts: ``{checked, missing_file, missing_block, re_emitted,
    re_emit_failed, errors}``.

    V1: pure vault-write-replay. No counter touches; no ClickUp.
    """
    counts = {
        "checked": 0,
        "missing_file": 0,
        "missing_block": 0,
        "re_emitted": 0,
        "re_emit_failed": 0,
        "errors": 0,
    }

    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        counts["errors"] += 1
        counts["error"] = "no_db_conn"
        return counts

    markers: list[tuple] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT po.cycle_id,
                       po.payload,
                       po.created_at,
                       cc.matter_slug
                  FROM cortex_phase_outputs po
                  JOIN cortex_cycles cc ON cc.cycle_id = po.cycle_id
                 WHERE po.artifact_type = %s
                 ORDER BY po.created_at ASC
                 LIMIT %s
                """,
                (REFLECTOR_COMPLETE_ARTIFACT, int(limit)),
            )
            markers = list(cur.fetchall())
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"reconciler enumerate failed: {e}")
        counts["errors"] += 1
        counts["error"] = str(e)[:200]
        store._put_conn(conn)
        return counts

    counts["checked"] = len(markers)
    if not markers:
        store._put_conn(conn)
        logger.info(f"phase6_reconciler: {counts}")
        return counts

    # Replay date — block represents replay date, not original cycle date
    # (per brief §Architect-review: replay date semantics).
    today_iso = datetime.now(timezone.utc).date().isoformat()

    try:
        for cycle_id, payload, marker_created_at, matter_slug in markers:
            try:
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                if not isinstance(payload, dict):
                    payload = {}

                cycle_id_str = str(cycle_id)
                target = _vault_target_for(matter_slug, staging_root=staging_root)
                file_exists = target.exists()
                block_present = _has_cycle_block(target, cycle_id_str)

                if file_exists and block_present:
                    continue

                if not file_exists:
                    counts["missing_file"] += 1
                else:
                    counts["missing_block"] += 1

                proposal_text = _load_proposal_text(conn, cycle_id_str)
                triaga_outcome = payload.get("outcome") or "stale"
                cited_ids = payload.get("cited_ids") or []
                if not isinstance(cited_ids, list):
                    cited_ids = []

                # Re-check immediately before append (idempotency: filesystem
                # race with sweep on a never-written cycle). Cheap.
                if target.exists() and _has_cycle_block(target, cycle_id_str):
                    continue

                try:
                    vault_path = write_proposed_actions_to_vault(
                        cycle_id=cycle_id_str,
                        matter_slug=matter_slug,
                        proposal_text=proposal_text or "",
                        cited_ids=cited_ids,
                        triaga_outcome=triaga_outcome,
                        today_iso=today_iso,
                        staging_root=staging_root,
                    )
                    counts["re_emitted"] += 1
                except Exception as e:
                    counts["re_emit_failed"] += 1
                    logger.error(
                        f"reconciler re-emit failed for {cycle_id_str} "
                        f"({matter_slug}): {e}"
                    )
                    try:
                        store.log_baker_action(
                            action_type="cortex_reflector_reconcile",
                            target_task_id=cycle_id_str,
                            payload={
                                "matter_slug": matter_slug,
                                "outcome": triaga_outcome,
                                "cited_ids": cited_ids,
                                "marker_created_at": (
                                    marker_created_at.isoformat()
                                    if hasattr(marker_created_at, "isoformat")
                                    else str(marker_created_at)
                                ),
                                "replay_date": today_iso,
                                "vault_path": str(target),
                                "reason": (
                                    "missing_file" if not file_exists
                                    else "missing_block"
                                ),
                            },
                            trigger_source="cortex_phase6_reconciler",
                            success=False,
                            error_message=str(e)[:500],
                        )
                    except Exception as audit_err:
                        logger.warning(
                            f"reconciler audit-on-failure failed for "
                            f"{cycle_id_str}: {audit_err}"
                        )
                    continue

                try:
                    store.log_baker_action(
                        action_type="cortex_reflector_reconcile",
                        target_task_id=cycle_id_str,
                        payload={
                            "matter_slug": matter_slug,
                            "outcome": triaga_outcome,
                            "cited_ids": cited_ids,
                            "marker_created_at": (
                                marker_created_at.isoformat()
                                if hasattr(marker_created_at, "isoformat")
                                else str(marker_created_at)
                            ),
                            "replay_date": today_iso,
                            "vault_path": str(vault_path),
                            "reason": (
                                "missing_file" if not file_exists
                                else "missing_block"
                            ),
                        },
                        trigger_source="cortex_phase6_reconciler",
                        success=True,
                    )
                except Exception as audit_err:
                    logger.warning(
                        f"reconciler audit failed for {cycle_id_str}: {audit_err}"
                    )
            except Exception as inner:
                # Per-marker isolation — one bad row doesn't kill the run.
                counts["errors"] += 1
                logger.error(
                    f"reconciler unexpected error for cycle "
                    f"{cycle_id!s}: {inner}"
                )
                continue
    finally:
        store._put_conn(conn)

    logger.info(f"phase6_reconciler: {counts}")
    return counts


def reconcile_vault_writes_sync(
    *,
    limit: int = 200,
    staging_root: Optional[Path] = None,
) -> dict:
    """Sync wrapper for APScheduler. ``reconcile_vault_writes`` is already
    sync (no asyncio inside); this wrapper exists for API symmetry with
    ``sweep_pending_cycles_sync`` and gives the scheduler a stable handle
    if the implementation later flips async."""
    return reconcile_vault_writes(limit=limit, staging_root=staging_root)


__all__ = [
    "reconcile_vault_writes",
    "reconcile_vault_writes_sync",
]
