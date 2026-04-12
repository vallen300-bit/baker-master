"""
Baker Cortex v2 — Event Bus
CORTEX-PHASE-2A: publish_event() + audit + decisions→insights pipeline.
Behind tool_router_enabled feature flag.
"""
import json
import logging
from typing import Optional

logger = logging.getLogger("baker.cortex")


def _get_store():
    """Get SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _get_conn():
    store = _get_store()
    return store._get_conn()


def _put_conn(conn):
    store = _get_store()
    store._put_conn(conn)


def publish_event(
    event_type: str,
    category: str,
    source_agent: str,
    source_type: str,
    payload: dict,
    source_ref: str = None,
    canonical_id: int = None,
) -> Optional[int]:
    """
    Publish an event to the Cortex event bus.
    This is the SINGLE entry point for all coordinated writes.

    Returns: event ID or None on failure.
    """
    conn = _get_conn()
    if not conn:
        logger.error("cortex.publish_event: no DB connection")
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cortex_events
                (event_type, category, source_agent, source_type,
                 source_ref, payload, canonical_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            event_type, category, source_agent, source_type,
            source_ref, json.dumps(payload), canonical_id,
        ))
        event_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        logger.info(
            "cortex event #%d: %s/%s by %s (canonical=%s)",
            event_id, event_type, category, source_agent, canonical_id
        )

        # Post-write hooks (non-blocking — failures logged, not raised)
        try:
            _audit_to_baker_actions(event_type, category, source_agent, payload, event_id)
        except Exception as e:
            logger.warning("cortex audit failed (non-fatal): %s", e)

        try:
            _auto_queue_insights(category, source_agent, payload, canonical_id)
        except Exception as e:
            logger.warning("cortex insights queue failed (non-fatal): %s", e)

        return event_id
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("cortex.publish_event failed: %s", e)
        return None
    finally:
        _put_conn(conn)


def _audit_to_baker_actions(
    event_type: str, category: str, source_agent: str,
    payload: dict, event_id: int,
):
    """Log every Cortex event to baker_actions for audit trail."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO baker_actions
                (action_type, payload, trigger_source, success)
            VALUES (%s, %s, %s, TRUE)
        """, (
            f"cortex:{event_type}:{category}",
            json.dumps({
                "event_id": event_id,
                "source_agent": source_agent,
                "summary": str(payload.get("description", payload.get("decision", "")))[:200],
            }),
            source_agent,
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("_audit_to_baker_actions failed: %s", e)
    finally:
        _put_conn(conn)


# ─── Decisions → PM Pending Insights Pipeline ───

# Map: keyword patterns → PM slugs that should receive the insight
PM_MATTER_KEYWORDS = {
    "ao_pm": [
        "oskolkov", "andrey", "aelio", "aukera", "capital call",
        "hagenauer", "lilienmatt", "balgerstrasse", "rg7", "riemergasse",
        "participation agreement", "rosfinmonitoring",
    ],
    "movie_am": [
        "movie", "mandarin oriental", "mohg", "mario habicher",
        "francesco", "robin", "rolf", "operator", "occupancy",
        "revpar", "ff&e", "warranty",
    ],
}

# Map: keyword → target view file for the insight
INSIGHT_TARGET_FILES = {
    "capital call": "agenda.md",
    "hagenauer": "agenda.md",
    "lilienmatt": "agenda.md",
    "balgerstrasse": "agenda.md",
    "aukera": "agenda.md",
    "rosfinmonitoring": "psychology.md",
    "co-ownership": "psychology.md",
    "udmurtia": "psychology.md",
    "oskolkov": "agenda.md",
    "movie": "agenda.md",
    "mandarin": "agenda.md",
    "occupancy": "kpi_framework.md",
    "revpar": "kpi_framework.md",
    "warranty": "owner_obligations.md",
    "operator": "operator_dynamics.md",
}


def _auto_queue_insights(
    category: str, source_agent: str, payload: dict,
    canonical_id: int = None,
):
    """
    When a decision is stored, check if it matches any PM's matters.
    If yes, auto-queue as pm_pending_insight targeting the right view file.
    """
    if category != "decision":
        return  # Only decisions trigger insight queueing for now

    decision_text = payload.get("decision", "")
    if not decision_text:
        return

    decision_lower = decision_text.lower()

    for pm_slug, keywords in PM_MATTER_KEYWORDS.items():
        matched_keywords = [kw for kw in keywords if kw in decision_lower]
        if not matched_keywords:
            continue

        # Find best target file
        target_file = "agenda.md"  # default
        for kw, tf in INSIGHT_TARGET_FILES.items():
            if kw in decision_lower:
                target_file = tf
                break

        # Queue the insight
        conn = _get_conn()
        if not conn:
            continue
        try:
            cur = conn.cursor()
            # Check for duplicate (same pm_slug + same text in last 24h)
            cur.execute("""
                SELECT id FROM pm_pending_insights
                WHERE pm_slug = %s AND status = 'pending'
                  AND insight = %s
                  AND created_at > NOW() - INTERVAL '24 hours'
                LIMIT 1
            """, (pm_slug, decision_text))
            if cur.fetchone():
                cur.close()
                _put_conn(conn)
                continue  # Already queued

            cur.execute("""
                INSERT INTO pm_pending_insights
                    (pm_slug, insight, target_file, target_section,
                     source_question, confidence, status)
                VALUES (%s, %s, %s, %s, %s, 'medium', 'pending')
            """, (
                pm_slug,
                decision_text,
                target_file,
                f"Auto-queued from decision (matched: {', '.join(matched_keywords[:3])})",
                f"cortex:{source_agent}:decision#{canonical_id}",
            ))
            conn.commit()
            cur.close()
            logger.info(
                "cortex: auto-queued insight for %s from decision (matched: %s, target: %s)",
                pm_slug, matched_keywords[:3], target_file,
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("_auto_queue_insights failed for %s: %s", pm_slug, e)
        finally:
            _put_conn(conn)
