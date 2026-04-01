"""
Weekly Priority Alignment — Baker knows what matters THIS WEEK.

Director sets 3-5 priorities each week. Baker uses them to:
1. Weight alert scoring (priority-related alerts score higher)
2. Focus morning briefs (lead with priority matters)
3. Guide chain planning (chains for priority matters get richer plans)
4. Filter noise (low-relevance items suppressed)

Table: weekly_priorities
API: POST /api/priorities, GET /api/priorities, DELETE /api/priorities/{id}
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("baker.priority_manager")


def _ensure_table():
    """Create weekly_priorities table if not exists."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS weekly_priorities (
                    id SERIAL PRIMARY KEY,
                    priority_text TEXT NOT NULL,
                    matter_slug VARCHAR(100),
                    rank INTEGER DEFAULT 1,
                    week_start DATE NOT NULL DEFAULT (date_trunc('week', CURRENT_DATE))::date,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_weekly_priorities_active ON weekly_priorities(active) WHERE active = TRUE")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_weekly_priorities_week ON weekly_priorities(week_start)")
            conn.commit()
            cur.close()
            logger.info("weekly_priorities table verified")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Could not ensure weekly_priorities table: {e}")


def get_current_priorities() -> list:
    """Get active priorities for this week."""
    _ensure_table()
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, priority_text, matter_slug, rank, week_start, created_at
                FROM weekly_priorities
                WHERE active = TRUE
                ORDER BY rank ASC, created_at ASC
                LIMIT 10
            """)
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"get_current_priorities failed: {e}")
        return []


def set_priorities(priorities: list) -> list:
    """
    Set this week's priorities. Deactivates previous priorities.
    Input: [{"text": "Close Kempinski LOI", "matter": "Kitzbühel"}, ...]
    Returns: created priority records.
    """
    _ensure_table()
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Deactivate old priorities
            cur.execute("UPDATE weekly_priorities SET active = FALSE WHERE active = TRUE")

            # Insert new priorities
            created = []
            for i, p in enumerate(priorities[:5]):  # Max 5
                text = p.get("text", p) if isinstance(p, dict) else str(p)
                matter = p.get("matter", p.get("matter_slug")) if isinstance(p, dict) else None
                cur.execute("""
                    INSERT INTO weekly_priorities (priority_text, matter_slug, rank)
                    VALUES (%s, %s, %s)
                    RETURNING id, priority_text, matter_slug, rank, week_start
                """, (text, matter, i + 1))
                created.append(dict(cur.fetchone()))

            conn.commit()
            cur.close()
            logger.info(f"Set {len(created)} weekly priorities")
            return created
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"set_priorities failed: {e}")
        return []


def complete_priority(priority_id: int) -> bool:
    """Mark a priority as completed."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE weekly_priorities
                SET active = FALSE, completed_at = NOW()
                WHERE id = %s
            """, (priority_id,))
            conn.commit()
            cur.close()
            return True
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"complete_priority failed: {e}")
        return False


def format_priorities_for_prompt() -> str:
    """Format current priorities for injection into prompts."""
    priorities = get_current_priorities()
    if not priorities:
        return ""

    lines = ["## DIRECTOR'S PRIORITIES THIS WEEK"]
    for p in priorities:
        matter = f" [{p['matter_slug']}]" if p.get("matter_slug") else ""
        lines.append(f"{p['rank']}. {p['priority_text']}{matter}")
    lines.append(
        "\nPrioritize information and actions related to these priorities. "
        "Flag anything that helps or hinders these goals."
    )
    return "\n".join(lines)


def is_priority_related(text: str) -> tuple:
    """Check if text relates to a current priority. Returns (is_related, matching_priority)."""
    priorities = get_current_priorities()
    if not priorities:
        return False, None

    text_lower = text.lower()
    for p in priorities:
        # Check priority text keywords
        priority_words = set(p["priority_text"].lower().split())
        # Remove common words
        priority_words -= {"the", "a", "an", "and", "or", "for", "to", "with", "on", "in", "of"}
        matches = sum(1 for w in priority_words if len(w) >= 4 and w in text_lower)
        if matches >= 2:
            return True, p

        # Check matter slug
        if p.get("matter_slug") and p["matter_slug"].lower() in text_lower:
            return True, p

    return False, None
