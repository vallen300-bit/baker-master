"""
DEADLINE-SYSTEM-1: Database schema for deadlines and VIP contacts.

Tables:
  - deadlines: tracks all extracted deadlines with escalation state
  - vip_contacts: Director's key contacts (drives priority classification)

Uses raw psycopg2 with CREATE TABLE IF NOT EXISTS (same pattern as store_back.py).
Called once at import time to ensure tables exist.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.pool

from config.settings import config

logger = logging.getLogger("baker.models.deadlines")

# ---------------------------------------------------------------------------
# Connection pool (lightweight, shared with deadline_manager)
# ---------------------------------------------------------------------------

_pool: Optional[psycopg2.pool.SimpleConnectionPool] = None


def _get_pool():
    global _pool
    if _pool is None:
        try:
            _pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1, maxconn=3, **config.postgres.dsn_params,
            )
            logger.info("deadlines: PostgreSQL pool initialised")
        except Exception as e:
            logger.warning(f"deadlines: PostgreSQL pool init failed: {e}")
    return _pool


def get_conn():
    pool = _get_pool()
    if pool is None:
        return None
    try:
        return pool.getconn()
    except Exception as e:
        logger.warning(f"deadlines: could not get connection: {e}")
        return None


def put_conn(conn):
    pool = _get_pool()
    if pool and conn:
        try:
            pool.putconn(conn)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def ensure_tables():
    """Create deadlines and vip_contacts tables if they don't exist."""
    conn = get_conn()
    if not conn:
        logger.warning("deadlines: no DB connection — tables not verified")
        return
    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS deadlines (
                id SERIAL PRIMARY KEY,
                description TEXT NOT NULL,
                due_date TIMESTAMP WITH TIME ZONE NOT NULL,
                source_type VARCHAR(50) NOT NULL,
                source_id TEXT,
                source_snippet TEXT,
                confidence VARCHAR(10) NOT NULL,
                priority VARCHAR(10) NOT NULL DEFAULT 'normal',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                dismissed_reason TEXT,
                last_reminded_at TIMESTAMP WITH TIME ZONE,
                reminder_stage VARCHAR(20),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS vip_contacts (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                role VARCHAR(200),
                email VARCHAR(200),
                whatsapp_id VARCHAR(50),
                fireflies_speaker_label VARCHAR(200),
                added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        conn.commit()
        cur.close()
        logger.info("deadlines: tables verified (deadlines, vip_contacts)")
    except Exception as e:
        logger.error(f"deadlines: table creation failed: {e}")
    finally:
        put_conn(conn)


def seed_vip_contacts():
    """
    Seed the VIP contacts table with initial contacts if empty.
    Emails/WhatsApp IDs resolved from known data; NULL where unknown.
    """
    conn = get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()

        # Only seed if table is empty
        cur.execute("SELECT COUNT(*) FROM vip_contacts")
        count = cur.fetchone()[0]
        if count > 0:
            logger.info(f"deadlines: vip_contacts already has {count} rows, skipping seed")
            cur.close()
            return

        vips = [
            {
                "name": "Edita Vallen",
                "role": "COO, Brisen Group",
                "email": None,  # not in known data
                "whatsapp_id": None,
                "fireflies_speaker_label": "Edita",
            },
            {
                "name": "Thomas Leitner",
                "role": "CFO, Brisen Development",
                "email": None,  # not in known data
                "whatsapp_id": None,
                "fireflies_speaker_label": "Thomas",
            },
            {
                "name": "Christophe Buchwalder",
                "role": "Legal advisor",
                "email": None,
                "whatsapp_id": None,
                "fireflies_speaker_label": "Christophe",
            },
            {
                "name": "Alric Ofenheimer",
                "role": "E+H lawyer",
                "email": None,
                "whatsapp_id": None,
                "fireflies_speaker_label": "Alric",
            },
            {
                "name": "Balazs Csepregi",
                "role": "Financial modeling, Brisengroup",
                "email": None,
                "whatsapp_id": None,
                "fireflies_speaker_label": "Balazs",
            },
            {
                "name": "Constantinos Pohanis",
                "role": "Finance/Legal",
                "email": None,
                "whatsapp_id": None,
                "fireflies_speaker_label": "Constantinos",
            },
        ]

        for v in vips:
            cur.execute("""
                INSERT INTO vip_contacts (name, role, email, whatsapp_id, fireflies_speaker_label)
                VALUES (%s, %s, %s, %s, %s)
            """, (v["name"], v["role"], v["email"], v["whatsapp_id"], v["fireflies_speaker_label"]))

        conn.commit()
        cur.close()
        logger.info(f"deadlines: seeded {len(vips)} VIP contacts")
    except Exception as e:
        logger.error(f"deadlines: VIP seed failed: {e}")
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Query helpers (used by deadline_manager and dashboard)
# ---------------------------------------------------------------------------

def get_active_deadlines(limit: int = 50) -> list:
    """Return active and pending_confirm deadlines, ordered by due_date."""
    conn = get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM deadlines
            WHERE status IN ('active', 'pending_confirm')
            ORDER BY due_date ASC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_active_deadlines failed: {e}")
        return []
    finally:
        put_conn(conn)


def get_deadline_by_id(deadline_id: int) -> Optional[dict]:
    """Return a single deadline by ID."""
    conn = get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM deadlines WHERE id = %s", (deadline_id,))
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_deadline_by_id failed: {e}")
        return None
    finally:
        put_conn(conn)


def insert_deadline(
    description: str,
    due_date: datetime,
    source_type: str,
    confidence: str,
    priority: str = "normal",
    source_id: str = None,
    source_snippet: str = None,
    status: str = None,
) -> Optional[int]:
    """Insert a new deadline. Returns the new ID or None on error."""
    if status is None:
        status = "pending_confirm" if confidence == "soft" else "active"
    conn = get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO deadlines
                (description, due_date, source_type, source_id, source_snippet,
                 confidence, priority, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (description, due_date, source_type, source_id,
              (source_snippet or "")[:500], confidence, priority, status))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"insert_deadline failed: {e}")
        return None
    finally:
        put_conn(conn)


def update_deadline(deadline_id: int, **kwargs) -> bool:
    """Update fields on a deadline. Returns True on success."""
    if not kwargs:
        return False
    allowed = {
        "description", "due_date", "confidence", "priority", "status",
        "dismissed_reason", "last_reminded_at", "reminder_stage", "source_snippet",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False

    fields["updated_at"] = datetime.now(timezone.utc)

    conn = get_conn()
    if not conn:
        return False
    try:
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [deadline_id]
        cur = conn.cursor()
        cur.execute(
            f"UPDATE deadlines SET {set_clause} WHERE id = %s",
            values,
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        logger.error(f"update_deadline failed: {e}")
        return False
    finally:
        put_conn(conn)


def find_duplicate_deadline(description: str, due_date: datetime) -> Optional[dict]:
    """
    Check if a similar deadline exists (same due_date +-1 day).
    Returns the existing deadline or None.
    """
    conn = get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM deadlines
            WHERE status IN ('active', 'pending_confirm')
              AND due_date BETWEEN %s - INTERVAL '1 day' AND %s + INTERVAL '1 day'
            ORDER BY due_date ASC
            LIMIT 10
        """, (due_date, due_date))
        rows = cur.fetchall()
        cur.close()

        if not rows:
            return None

        # Simple string similarity: check if description words overlap significantly
        desc_words = set(description.lower().split())
        for row in rows:
            existing_words = set((row.get("description") or "").lower().split())
            if len(desc_words & existing_words) >= max(2, len(desc_words) // 2):
                return dict(row)

        return None
    except Exception as e:
        logger.error(f"find_duplicate_deadline failed: {e}")
        return None
    finally:
        put_conn(conn)


def get_vip_contacts() -> list:
    """Return all VIP contacts."""
    conn = get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM vip_contacts ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_vip_contacts failed: {e}")
        return []
    finally:
        put_conn(conn)


def add_vip_contact(name: str, role: str = None, email: str = None,
                    whatsapp_id: str = None) -> Optional[int]:
    """Add a new VIP contact. Returns ID or None."""
    conn = get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO vip_contacts (name, role, email, whatsapp_id)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (name, role, email, whatsapp_id))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"add_vip_contact failed: {e}")
        return None
    finally:
        put_conn(conn)


def remove_vip_contact(name: str) -> bool:
    """Remove a VIP contact by name (case-insensitive match). Returns True if found."""
    conn = get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM vip_contacts WHERE LOWER(name) LIKE %s", (f"%{name.lower()}%",))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        return deleted > 0
    except Exception as e:
        logger.error(f"remove_vip_contact failed: {e}")
        return False
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Auto-bootstrap on import
# ---------------------------------------------------------------------------
ensure_tables()
seed_vip_contacts()
