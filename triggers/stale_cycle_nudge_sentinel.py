"""Stale tier_b_pending cycle nudge sentinel — STALE_CYCLE_NUDGE_SENTINEL_1.

Runs daily at 07:00 UTC via APScheduler (`triggers/embedded_scheduler.py`).
Catches Cortex cycles that reached terminal status `tier_b_pending` more than
3 days ago and still await Director ratification — emits one ClickUp task per
stale cycle into BAKER space list 901521426367 (Handoff Notes), then re-nudges
every 7 days if still stale.

  Scar anchor: Oskolkov cycle c4242a20 sat tier_b_pending 10 days
  (2026-05-05 → 2026-05-15) before a fresh cycle accidentally resurfaced the
  proposals. russo_fr specialist on the second cycle named the gap.

Disjoint from `cortex_stuck_cycle_sentinel.py` — that one watches MACHINE-
transient statuses (in_flight / awaiting_reason / proposed past 15 minutes)
and the terminal archive_failed status; it EXPLICITLY excludes tier_b_pending
because that's Director-blocked by design. This sentinel fills the gap with a
slower cadence (daily, 3-day threshold) and a different surface (ClickUp,
not Slack DM) — ClickUp is the chosen Director-eyeball board for stale work.

Anti-spam state lives in `cortex_cycles.last_nudge_at` (added by
migrations/20260518_cortex_cycles_add_last_nudge_at.sql). A row is re-nudged
only when last_nudge_at IS NULL or older than 7 days.

Never raises. The scheduler thread continues regardless of DB, ClickUp, or
import failures — per-row try/except so one bad row doesn't block the rest.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("sentinel.stale_cycle_nudge_sentinel")

BAKER_HANDOFF_LIST_ID = "901521426367"

STALE_THRESHOLD_DAYS = 3
RENUDGE_INTERVAL_DAYS = 7
PER_RUN_LIMIT = 10

SENTINEL_HEALTH_SOURCE = "stale_cycle_nudge"


def _clickup_readonly() -> bool:
    return os.getenv("BAKER_CLICKUP_READONLY", "").lower() == "true"


def _fetch_stale_cycles(store) -> List[Dict[str, Any]]:
    """SELECT stale tier_b_pending cycles past the nudge threshold.

    Returns rows ordered oldest-first, capped at PER_RUN_LIMIT so a single
    run can never exceed the 10-writes-per-cycle BAKER-space rule even if
    the backlog explodes.

    Empty list on DB unreachable or any query failure — callers see "no
    work to do" rather than a raised exception.
    """
    conn = store._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT cycle_id::text,
                   matter_slug,
                   created_at,
                   EXTRACT(DAY FROM (NOW() - created_at))::int AS days_stale
              FROM cortex_cycles
             WHERE status = 'tier_b_pending'
               AND created_at < NOW() - INTERVAL '{STALE_THRESHOLD_DAYS} days'
               AND (
                   last_nudge_at IS NULL
                   OR last_nudge_at < NOW() - INTERVAL '{RENUDGE_INTERVAL_DAYS} days'
               )
             ORDER BY created_at ASC
             LIMIT {PER_RUN_LIMIT}
            """
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
        logger.warning("sentinel: stale-cycle SELECT failed: %s", e)
        return []
    finally:
        store._put_conn(conn)


def _mark_nudged(store, cycle_id: str) -> bool:
    """UPDATE cortex_cycles.last_nudge_at = NOW() for the given cycle.

    Bounded query (PK lookup, single-row update). Rollback in except per
    `.claude/rules/python-backend.md`. Returns True on success.
    """
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cortex_cycles SET last_nudge_at = NOW() WHERE cycle_id::text = %s",
            (cycle_id,),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(
            "sentinel: last_nudge_at UPDATE failed",
            extra={"cycle_id": cycle_id, "error_class": type(e).__name__},
        )
        return False
    finally:
        store._put_conn(conn)


def _format_task_body(row: Dict[str, Any]) -> Dict[str, str]:
    """Build the ClickUp task name + description for one stale cycle."""
    cycle_id = str(row.get("cycle_id") or "")
    matter_slug = row.get("matter_slug") or "(unknown)"
    days_stale = row.get("days_stale")
    short_id = cycle_id[:8] if cycle_id else "(unknown)"
    days_str = f"{days_stale}d" if days_stale is not None else "(unknown)"

    name = f"Stale tier_b_pending: {matter_slug} / {short_id} — {days_str}"
    description = (
        f"Cortex cycle awaiting Director Tier-B ratification.\n\n"
        f"- cycle_id: {cycle_id}\n"
        f"- matter_slug: {matter_slug}\n"
        f"- age: {days_str}\n"
        f"- dashboard: https://baker-master.onrender.com/cortex/cycle/{cycle_id}\n\n"
        f"Action: ratify in dashboard or close cycle if abandoned."
    )
    return {"name": name, "description": description}


def _nudge_one(client, store, row: Dict[str, Any]) -> bool:
    """Post one ClickUp task + mark the row nudged.

    Each row is isolated in its own try/except at the entry-point loop so
    one row's failure does not block the others. Returns True if the
    ClickUp create succeeded AND the UPDATE landed.
    """
    body = _format_task_body(row)
    matter_slug = row.get("matter_slug") or "unknown"
    tags = ["stale-cycle", "tier-b-pending", str(matter_slug)]
    result = client.create_task(
        list_id=BAKER_HANDOFF_LIST_ID,
        name=body["name"],
        description=body["description"],
        tags=tags,
    )
    if not result:
        return False
    return _mark_nudged(store, str(row.get("cycle_id")))


def run_stale_cycle_nudge_sentinel() -> Dict[str, Any]:
    """Entry point called by APScheduler daily at 07:00 UTC.

    Returns a summary dict for observability / tests:
        {
            "checked": int,                  # rows the SELECT returned
            "nudged": int,                   # ClickUp tasks created
            "skipped_readonly": bool,        # BAKER_CLICKUP_READONLY honored
            "errors": int,                   # per-row exception count
        }

    Never raises. Top-level try/except catches any unexpected import or
    pipeline failure and reports it via sentinel_health.report_failure.
    """
    summary: Dict[str, Any] = {
        "checked": 0,
        "nudged": 0,
        "skipped_readonly": False,
        "errors": 0,
    }

    if _clickup_readonly():
        summary["skipped_readonly"] = True
        logger.info("stale_cycle_nudge_sentinel: skipped (BAKER_CLICKUP_READONLY=true)")
        # Don't report success/failure to sentinel_health — kill-switch is
        # an operator state, not a sentinel outcome. Re-reporting would
        # noise up the health board with "healthy" lines while we're
        # deliberately disabled.
        return summary

    try:
        from memory.store_back import SentinelStoreBack
        from clickup_client import ClickUpClient
        from triggers import sentinel_health

        store = SentinelStoreBack._get_global_instance()
        client = ClickUpClient._get_global_instance()

        rows = _fetch_stale_cycles(store)
        summary["checked"] = len(rows)

        for row in rows:
            cycle_id = row.get("cycle_id")
            try:
                if _nudge_one(client, store, row):
                    summary["nudged"] += 1
            except Exception as e:
                summary["errors"] += 1
                logger.error(
                    "sentinel: per-row nudge failed",
                    extra={
                        "cycle_id": str(cycle_id) if cycle_id else None,
                        "error_class": type(e).__name__,
                        "error": str(e)[:200],
                    },
                )

        sentinel_health.report_success(SENTINEL_HEALTH_SOURCE)

    except Exception as e:
        summary["errors"] += 1
        logger.error("stale_cycle_nudge_sentinel: top-level pipeline failed: %s", e)
        try:
            from triggers import sentinel_health
            sentinel_health.report_failure(SENTINEL_HEALTH_SOURCE, str(e)[:500])
        except Exception:
            pass

    logger.info(
        "stale_cycle_nudge_sentinel: checked=%d nudged=%d skipped_readonly=%s errors=%d",
        summary["checked"], summary["nudged"],
        summary["skipped_readonly"], summary["errors"],
    )
    return summary
