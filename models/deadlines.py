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
import psycopg2.extras
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

        # OBLIGATIONS-UNIFY-1: Add severity + assignment columns for commitment merger
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS severity VARCHAR(10) DEFAULT 'firm'")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS assigned_to TEXT")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS assigned_by TEXT")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS matter_slug TEXT")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS obligation_type VARCHAR(20) DEFAULT 'deadline'")
        # Make due_date nullable for soft commitments (no specific date)
        cur.execute("ALTER TABLE deadlines ALTER COLUMN due_date DROP NOT NULL")
        cur.execute("ALTER TABLE deadlines ALTER COLUMN confidence DROP NOT NULL")
        # CRITICAL-CARD-1: Critical flag for Director's must-do-today items
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS is_critical BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS critical_flagged_at TIMESTAMPTZ")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS vip_contacts (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                role VARCHAR(200),
                email VARCHAR(200),
                whatsapp_id VARCHAR(50),
                fireflies_speaker_label VARCHAR(200),
                role_context TEXT,
                communication_pref TEXT DEFAULT 'email',
                expertise TEXT,
                added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        # CONTACTS-RENAME-1: Create view so `contacts` and `vip_contacts` both work
        cur.execute("""
            CREATE OR REPLACE VIEW contacts AS SELECT * FROM vip_contacts
        """)

        conn.commit()
        cur.close()
        logger.info("deadlines: tables verified (deadlines, vip_contacts, contacts view)")
    except Exception as e:
        logger.error(f"deadlines: table creation failed: {e}")
    finally:
        put_conn(conn)


def seed_vip_contacts():
    """
    VIP-SEED-1: Seed the VIP contacts table with the full Director-confirmed list.
    Replaces old placeholder data. Runs on every startup — idempotent via row-count check.
    """
    conn = get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()

        # VIP-SEED-1: Full list with confirmed emails and WhatsApp IDs
        vips = [
            ("Balazs Csepregi", "Brisen Internal", "balazs.csepregi@brisengroup.com", "36303005919@c.us"),
            ("Caroline Schreiner", "Brisen Internal", "caroline.schreiner@brisengroup.com", "491735460427@c.us"),
            ("Conrad Weiss", "Brisen Internal", "conrad.weiss@brisengroup.com", "41794033419@c.us"),
            ("Constantinos Pohanis", "Brisen Internal", "cpohanis@brisengroup.com", "35799492642@c.us"),
            ("Edita Vallen", "COO / Brisen Internal", "edita.vallen@brisengroup.com", "41799439246@c.us"),
            ("Rolf Hübner", "Brisen Internal", "rolf.huebner@brisengroup.com", "35799484778@c.us"),
            ("Siegfried Brandner", "Brisen Internal", "siegfried.brandner@brisengroup.com", "436605206014@c.us"),
            ("Thomas Leitner", "Brisen Internal", "thomas.leitner@brisengroup.com", "436645244702@c.us"),
            ("Vladimir Moravcik", "Brisen Internal", "vladimir.moravcik@brisengroup.com", "436649676154@c.us"),
            ("Alric Ofenheimer", "External / Attorney-at-law", "A.Ofenheimer@eh.at", "4367683647246@c.us"),
            ("Christophe Buchwalder", "External / Attorney-at-law", "buchwalder@gantey.ch", "41794055384@c.us"),
        ]

        # Check if already migrated (11 rows = current version)
        cur.execute("SELECT COUNT(*) FROM vip_contacts")
        count = cur.fetchone()[0]
        if count == len(vips):
            logger.info(f"deadlines: vip_contacts already has {count} rows, skipping seed")
            cur.close()
            return

        # Clear old data and insert fresh
        cur.execute("DELETE FROM vip_contacts")
        for name, role, email, whatsapp_id in vips:
            cur.execute("""
                INSERT INTO vip_contacts (name, role, email, whatsapp_id)
                VALUES (%s, %s, %s, %s)
            """, (name, role, email, whatsapp_id))

        conn.commit()
        cur.close()
        logger.info(f"deadlines: seeded {len(vips)} VIP contacts (VIP-SEED-1)")
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
            ORDER BY due_date ASC NULLS LAST
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


def _deadline_dedup_check(cur, description: str, due_date) -> Optional[int]:
    """DEADLINE-DEDUP-1: Check for similar active deadline on same date.
    Returns existing deadline ID if duplicate found, None otherwise."""
    if not due_date or not description:
        return None
    import re
    # Extract key words: capitalized words + long words, minus common verbs
    _stopwords = {'should', 'could', 'would', 'provide', 'complete', 'confirm',
                  'arrange', 'ensure', 'follow', 'check', 'review', 'prepare',
                  'execute', 'submit', 'today', 'tomorrow', 'deadline'}
    key_words = [w for w in re.findall(r'[A-Z][a-z]+|[a-z]{5,}', description)
                 if w.lower() not in _stopwords]
    if not key_words:
        return None
    try:
        cur.execute("""
            SELECT id, description FROM deadlines
            WHERE status = 'active'
              AND due_date = %s
            ORDER BY created_at ASC
        """, (due_date,))
        for row in cur.fetchall():
            existing_desc = (row[1] or "").lower()
            matches = sum(1 for kw in key_words if kw.lower() in existing_desc)
            if matches >= 2:
                logger.info(f"Deadline dedup: '{description[:60]}' matches existing #{row[0]} ({matches} keyword overlaps) — skipping")
                return row[0]
    except Exception as e:
        logger.debug(f"Deadline dedup check failed (non-fatal): {e}")
    return None


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
    """Insert a new deadline. Returns the new ID or None on error.
    DEADLINE-DEDUP-1: Checks for similar active deadline on same date before inserting."""
    if status is None:
        status = "pending_confirm" if confidence == "soft" else "active"
    conn = get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        # DEADLINE-DEDUP-1: Check for existing similar deadline on same date
        existing_id = _deadline_dedup_check(cur, description, due_date)
        if existing_id:
            cur.close()
            return existing_id
        cur.execute("""
            INSERT INTO deadlines
                (description, due_date, source_type, source_id, source_snippet,
                 confidence, priority, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (description, due_date, source_type, source_id,
              source_snippet or "", confidence, priority, status))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        conn.rollback()
        logger.error(f"insert_deadline failed: {e}")
        return None
    finally:
        put_conn(conn)


def get_critical_items(limit: int = 5) -> list:
    """CRITICAL-CARD-1: Get active critical items for dashboard."""
    conn = get_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, description, due_date, priority, source_snippet, critical_flagged_at
            FROM deadlines
            WHERE is_critical = TRUE AND status = 'active'
            ORDER BY critical_flagged_at DESC
            LIMIT %s
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        logger.error(f"get_critical_items failed: {e}")
        return []
    finally:
        put_conn(conn)


def get_critical_count() -> int:
    """CRITICAL-CARD-1: Count active critical items."""
    conn = get_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM deadlines WHERE is_critical = TRUE AND status = 'active'")
        count = cur.fetchone()[0]
        cur.close()
        return count
    except Exception:
        return 0
    finally:
        put_conn(conn)


def set_critical(deadline_id: int, is_critical: bool = True) -> bool:
    """CRITICAL-CARD-1: Flag/unflag a deadline as critical."""
    conn = get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        if is_critical:
            cur.execute(
                "UPDATE deadlines SET is_critical = TRUE, critical_flagged_at = NOW() WHERE id = %s",
                (deadline_id,),
            )
        else:
            cur.execute(
                "UPDATE deadlines SET is_critical = FALSE, critical_flagged_at = NULL WHERE id = %s",
                (deadline_id,),
            )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"set_critical failed: {e}")
        return False
    finally:
        put_conn(conn)


def complete_critical(deadline_id: int) -> bool:
    """CRITICAL-CARD-1: Mark critical item as done."""
    conn = get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE deadlines SET is_critical = FALSE, status = 'completed', updated_at = NOW() WHERE id = %s",
            (deadline_id,),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"complete_critical failed: {e}")
        return False
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
