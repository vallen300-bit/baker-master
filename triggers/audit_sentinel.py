"""AI Head weekly audit sentinel — BRIEF_AUDIT_SENTINEL_1.

Runs Mon 10:00 UTC (1h after ai_head_weekly_audit). Verifies both:
  (a) a row landed in ai_head_audits today
  (b) a row landed in scheduler_executions for
      job_id='ai_head_weekly_audit' with status='executed' today

Either missing → Slack DM to D0AFY28N030 (Director substrate channel).

Dedupe: before alerting, checks scheduler_executions for an 'alerted'
row from this sentinel in the last 24h. If present, no double-alert.
Otherwise, alert + write own 'alerted' row for dedupe anchor.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger("sentinel.audit_sentinel")

DIRECTOR_DM_CHANNEL = "D0AFY28N030"


def run_sentinel_check() -> Dict[str, Any]:
    """Return {'audit_found': bool, 'execution_found': bool, 'alerted': bool}."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.warning("sentinel: DB unavailable — skipping check")
        return {"audit_found": None, "execution_found": None, "alerted": False,
                "reason": "db_unavailable"}

    try:
        cur = conn.cursor()

        # (a) Did the audit actually write a row?
        cur.execute(
            "SELECT COUNT(*) FROM ai_head_audits "
            "WHERE ran_at >= NOW() - INTERVAL '24 hours' LIMIT 1"
        )
        audit_count = cur.fetchone()[0]
        audit_found = audit_count > 0

        # (b) Did APScheduler record the execution?
        cur.execute(
            "SELECT COUNT(*) FROM scheduler_executions "
            "WHERE job_id = 'ai_head_weekly_audit' "
            "  AND status = 'executed' "
            "  AND fired_at >= NOW() - INTERVAL '24 hours' LIMIT 1"
        )
        exec_count = cur.fetchone()[0]
        execution_found = exec_count > 0

        if audit_found and execution_found:
            cur.close()
            return {"audit_found": True, "execution_found": True,
                    "alerted": False, "reason": "clean"}

        # (c) Dedupe check — prior alert in last 24h?
        cur.execute(
            "SELECT COUNT(*) FROM scheduler_executions "
            "WHERE job_id = 'ai_head_audit_sentinel' "
            "  AND status = 'alerted' "
            "  AND fired_at >= NOW() - INTERVAL '24 hours' LIMIT 1"
        )
        prior_alert_count = cur.fetchone()[0]
        if prior_alert_count > 0:
            cur.close()
            logger.info("sentinel: miss detected but deduped (prior alert in 24h)")
            return {"audit_found": audit_found, "execution_found": execution_found,
                    "alerted": False, "reason": "deduped"}

        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"sentinel: DB read failed: {e}")
        return {"audit_found": None, "execution_found": None, "alerted": False,
                "reason": f"db_error: {e}"}
    finally:
        store._put_conn(conn)

    # (d) Miss detected + not deduped → Slack alert + dedupe-anchor write
    missing_parts = []
    if not audit_found:
        missing_parts.append("ai_head_audits row")
    if not execution_found:
        missing_parts.append("scheduler_executions row for ai_head_weekly_audit")
    alert_text = (
        "⚠️ AI Head weekly audit sentinel — MISS\n\n"
        f"Missing: {', '.join(missing_parts)}\n\n"
        "Expected both to appear within 24h of Mon 09:00 UTC audit cron. "
        "Check Render logs for scheduler errors or ai_head_audit.run_weekly_audit failures."
    )
    slack_ok = False
    try:
        from outputs.slack_notifier import post_to_channel
        slack_ok = post_to_channel(DIRECTOR_DM_CHANNEL, alert_text)
    except Exception as e:
        logger.warning(f"sentinel: Slack post raised: {e}")

    # (e) Write dedupe anchor regardless of Slack success
    conn2 = store._get_conn()
    if conn2:
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                """
                INSERT INTO scheduler_executions
                    (job_id, fired_at, completed_at, status, error_msg, outputs_summary)
                VALUES (%s, NOW(), NOW(), 'alerted', %s, %s::jsonb)
                """,
                (
                    "ai_head_audit_sentinel",
                    f"missing: {', '.join(missing_parts)}",
                    f'{{"slack_ok": {str(slack_ok).lower()}, "missing": "{", ".join(missing_parts)}"}}',
                ),
            )
            conn2.commit()
            cur2.close()
        except Exception as e:
            try:
                conn2.rollback()
            except Exception:
                pass
            logger.warning(f"sentinel: dedupe-anchor write failed: {e}")
        finally:
            store._put_conn(conn2)

    return {"audit_found": audit_found, "execution_found": execution_found,
            "alerted": True, "slack_ok": slack_ok,
            "reason": f"miss: {', '.join(missing_parts)}"}
