"""Cortex stuck-cycle sentinel — BRIEF_CORTEX_ARCHIVE_FAILURE_ALERTING_1.

Runs every 5 min via APScheduler (`triggers/embedded_scheduler.py`). Two
detectors per run, each posting Director DMs and writing a dedup row in
`baker_actions` so the same cycle is alerted at most once per failure mode.

  Detector A — STUCK MACHINE-TRANSIENT STATUS:
      cortex_cycles row in 'in_flight' / 'awaiting_reason' / 'proposed'
      with started_at > 15 minutes ago. These three statuses are
      machine-transient: an in-flight cycle past 15 min indicates the
      runner crashed mid-phase or a phase await hung. tier_b_pending is
      EXPLICITLY EXCLUDED (V1 design call) — it's by-design human-blocked
      and a separate "Director-decision-pending nudge" sentinel is parked
      for V2.

  Detector B — ARCHIVE-FAILED:
      cortex_cycles row in 'archive_failed' status. Phase 6 archive code
      itself raised; `orchestrator/cortex_runner.py` writes this terminal
      state best-effort before swallowing. Different action_type from
      Detector A so both fire independently.

Dedup: per (cycle_id × failure-mode). One Slack alert per row per mode.
Implementation: atomic INSERT…SELECT WHERE NOT EXISTS pattern (mirror of
PR #80 gate). If the dedup row already exists the INSERT writes 0 rows
and we skip the Slack post.

Slack: posts to Director DM (`D0AFY28N030`) via
`outputs.slack_notifier.post_to_channel` — same path used by
`triggers/audit_sentinel.py`.

Never raises. The scheduler thread must continue regardless of DB or
Slack failures.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sentinel.cortex_stuck_cycle_sentinel")

# --- constants ---------------------------------------------------------------

DIRECTOR_DM_CHANNEL = "D0AFY28N030"

# Machine-transient stuck statuses. tier_b_pending excluded by design — see
# module docstring + brief §"Defaults" rev 2.
STUCK_STATUSES: Tuple[str, ...] = (
    "in_flight",
    "awaiting_reason",
    "proposed",
)

STUCK_THRESHOLD_MINUTES = 15

ACTION_TYPE_STUCK = "cortex_alert_stuck"
ACTION_TYPE_ARCHIVE_FAILED = "cortex_alert_archive_failed"


# --- helpers -----------------------------------------------------------------


def _format_alert_text(row: Dict[str, Any], mode: str) -> str:
    """Build a Slack-friendly alert message for one stuck-cycle row.

    `row` keys: cycle_id, matter_slug, status, started_at, current_phase, age_seconds.
    `mode` is one of 'stuck' / 'archive_failed' (controls header + framing).
    """
    cycle_id = row.get("cycle_id")
    matter_slug = row.get("matter_slug") or "(unknown)"
    status = row.get("status") or "(unknown)"
    current_phase = row.get("current_phase") or "(unknown)"
    age_seconds = row.get("age_seconds")
    age_minutes = (
        f"{age_seconds / 60:.1f} min" if age_seconds is not None else "(unknown)"
    )

    if mode == "stuck":
        header = "⚠️ Cortex stuck cycle"
        framing = (
            f"Status `{status}` past {STUCK_THRESHOLD_MINUTES}-min threshold; "
            "the runner likely crashed or a phase await hung."
        )
    elif mode == "archive_failed":
        header = "🚨 Cortex archive failure"
        framing = (
            "Phase 6 archive itself raised; reasoning + proposal artifacts "
            "may have landed but the cycle row was not finalised. Inspect "
            "the row + recent logs."
        )
    else:
        header = "Cortex sentinel alert"
        framing = f"Mode: {mode}"

    return (
        f"{header}\n\n"
        f"• cycle_id: `{cycle_id}`\n"
        f"• matter_slug: `{matter_slug}`\n"
        f"• status: `{status}`\n"
        f"• current_phase: `{current_phase}`\n"
        f"• age: {age_minutes}\n\n"
        f"{framing}"
    )


def _post_alert_to_director(text: str) -> bool:
    """Best-effort Slack DM. Returns True if post_to_channel succeeded."""
    try:
        from outputs.slack_notifier import post_to_channel
        return bool(post_to_channel(DIRECTOR_DM_CHANNEL, text))
    except Exception as e:
        logger.warning("sentinel: Slack post raised: %s", e)
        return False


def _record_alert(
    store, cycle_id: str, matter_slug: Optional[str], action_type: str
) -> bool:
    """Atomic dedup-aware INSERT into baker_actions.

    Mirrors the canonical pattern from `triggers/cortex_pre_review_gate.py`
    (PR #80): single INSERT…SELECT WHERE NOT EXISTS RETURNING id closes the
    TOCTOU window between read-then-write. Returns True if a new row was
    written (i.e. this cycle had not been alerted on this mode yet),
    False if the row was deduped or the INSERT itself failed.
    """
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        payload_json = json.dumps({
            "cycle_id": str(cycle_id),
            "matter_slug": str(matter_slug) if matter_slug else None,
            "mode": action_type,
        })
        cur.execute(
            "INSERT INTO baker_actions "
            "(action_type, target_task_id, payload, trigger_source, success) "
            "SELECT %s, %s, %s::jsonb, %s, %s "
            "WHERE NOT EXISTS ("
            "    SELECT 1 FROM baker_actions "
            "    WHERE target_task_id = %s AND action_type = %s"
            ") "
            "RETURNING id",
            (
                action_type,
                str(cycle_id),
                payload_json,
                "cortex_stuck_cycle_sentinel",
                True,
                str(cycle_id),
                action_type,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row is not None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(
            "sentinel: dedup INSERT failed",
            extra={
                "cycle_id": str(cycle_id),
                "phase": "sentinel",
                "error_class": type(e).__name__,
                "matter_slug": str(matter_slug) if matter_slug else None,
            },
        )
        return False
    finally:
        store._put_conn(conn)


def _detect(store, action_type: str, where_sql: str, params: tuple) -> List[Dict[str, Any]]:
    """Run a detector query and return rows that have NOT yet been alerted.

    `where_sql` is the per-detector predicate (e.g. status filter + threshold).
    Dedup is enforced inline via NOT IN against baker_actions for the given
    `action_type`. We project age_seconds in SQL so the alert text formatter
    has it without a second roundtrip.
    """
    conn = store._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT cycle_id::text, matter_slug, status, started_at, current_phase,
                   EXTRACT(EPOCH FROM (NOW() - started_at))::bigint AS age_seconds
              FROM cortex_cycles
             WHERE {where_sql}
               AND cycle_id::text NOT IN (
                   SELECT target_task_id FROM baker_actions
                    WHERE action_type = %s AND target_task_id IS NOT NULL
               )
             LIMIT 100
            """,
            (*params, action_type),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        cur.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("sentinel: detector query failed (action_type=%s): %s", action_type, e)
        return []
    finally:
        store._put_conn(conn)


# --- detectors ---------------------------------------------------------------


def _detect_stuck_cycles(store) -> List[Dict[str, Any]]:
    """Detector A — machine-transient stuck statuses past 15-min threshold."""
    return _detect(
        store,
        action_type=ACTION_TYPE_STUCK,
        where_sql=(
            "status = ANY(%s) "
            f"AND started_at < NOW() - INTERVAL '{STUCK_THRESHOLD_MINUTES} minutes'"
        ),
        params=(list(STUCK_STATUSES),),
    )


def _detect_archive_failed(store) -> List[Dict[str, Any]]:
    """Detector B — terminal status `archive_failed` from Phase 6 self-fail path."""
    return _detect(
        store,
        action_type=ACTION_TYPE_ARCHIVE_FAILED,
        where_sql="status = %s",
        params=("archive_failed",),
    )


# --- entry point -------------------------------------------------------------


def run_cortex_stuck_cycle_sentinel() -> Dict[str, Any]:
    """Entry point called by APScheduler every 5 minutes.

    Returns a summary dict for observability / tests:
        {
            "stuck_found": int,
            "archive_failed_found": int,
            "alerts_posted": int,
            "alerts_deduped": int,
            "errors": int,
        }

    Never raises — any exception inside is caught + logged + counted in
    `errors`. The scheduler thread continues.
    """
    summary: Dict[str, Any] = {
        "stuck_found": 0,
        "archive_failed_found": 0,
        "alerts_posted": 0,
        "alerts_deduped": 0,
        "errors": 0,
    }
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        # Detector A — stuck
        try:
            stuck_rows = _detect_stuck_cycles(store)
            summary["stuck_found"] = len(stuck_rows)
            for row in stuck_rows:
                cycle_id = row["cycle_id"]
                matter_slug = row.get("matter_slug")
                inserted = _record_alert(store, cycle_id, matter_slug, ACTION_TYPE_STUCK)
                if not inserted:
                    summary["alerts_deduped"] += 1
                    continue
                text = _format_alert_text(row, "stuck")
                if _post_alert_to_director(text):
                    summary["alerts_posted"] += 1
        except Exception as e:
            summary["errors"] += 1
            logger.error("sentinel: Detector A pipeline failed: %s", e)

        # Detector B — archive_failed
        try:
            archived_rows = _detect_archive_failed(store)
            summary["archive_failed_found"] = len(archived_rows)
            for row in archived_rows:
                cycle_id = row["cycle_id"]
                matter_slug = row.get("matter_slug")
                inserted = _record_alert(
                    store, cycle_id, matter_slug, ACTION_TYPE_ARCHIVE_FAILED
                )
                if not inserted:
                    summary["alerts_deduped"] += 1
                    continue
                text = _format_alert_text(row, "archive_failed")
                if _post_alert_to_director(text):
                    summary["alerts_posted"] += 1
        except Exception as e:
            summary["errors"] += 1
            logger.error("sentinel: Detector B pipeline failed: %s", e)

    except Exception as e:
        summary["errors"] += 1
        logger.error("sentinel: top-level pipeline failed: %s", e)

    logger.info(
        "cortex_stuck_cycle_sentinel: %s",
        json.dumps(summary, default=str),
    )
    return summary
