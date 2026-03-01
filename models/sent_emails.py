"""
REPLY-TRACK-1: Database schema for tracking Baker-sent emails and reply detection.

Table:
  - sent_emails: logs every email Baker sends on the Director's behalf,
    with Gmail thread_id for reply matching during email polling.

Uses raw psycopg2 with CREATE TABLE IF NOT EXISTS (same pattern as models/deadlines.py).
Called once at import time to ensure table exists.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

from config.settings import config

logger = logging.getLogger("baker.models.sent_emails")

# Reuse the connection pool from models.deadlines
from models.deadlines import get_conn, put_conn


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def ensure_table():
    """Create sent_emails table if it doesn't exist."""
    conn = get_conn()
    if not conn:
        logger.warning("sent_emails: no DB connection — table not verified")
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_emails (
                id SERIAL PRIMARY KEY,
                to_address VARCHAR(200) NOT NULL,
                subject TEXT NOT NULL,
                body_preview TEXT,
                gmail_message_id VARCHAR(200),
                gmail_thread_id VARCHAR(200),
                channel VARCHAR(20) NOT NULL,
                reply_received BOOLEAN DEFAULT FALSE,
                reply_received_at TIMESTAMP WITH TIME ZONE,
                reply_snippet TEXT,
                reply_from VARCHAR(200),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        logger.info("sent_emails: table verified")
    except Exception as e:
        logger.error(f"sent_emails: table creation failed: {e}")
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def log_sent_email(
    to_address: str,
    subject: str,
    body_preview: str = "",
    gmail_message_id: str = None,
    gmail_thread_id: str = None,
    channel: str = "scan",
) -> Optional[int]:
    """
    Log a Baker-sent email for reply tracking.
    Returns the new row ID or None on error.
    """
    conn = get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sent_emails
                (to_address, subject, body_preview, gmail_message_id, gmail_thread_id, channel)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (to_address, subject, (body_preview or "")[:200],
              gmail_message_id, gmail_thread_id, channel))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if row:
            logger.info(
                f"Sent email logged: to={to_address}, thread={gmail_thread_id}, "
                f"channel={channel} (id={row[0]})"
            )
            return row[0]
        return None
    except Exception as e:
        logger.error(f"log_sent_email failed: {e}")
        return None
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def find_awaiting_reply(gmail_thread_id: str) -> Optional[dict]:
    """
    Check if a thread_id matches any sent email awaiting a reply.
    Returns the sent_email row dict or None.
    """
    if not gmail_thread_id:
        return None
    conn = get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM sent_emails
            WHERE gmail_thread_id = %s AND reply_received = FALSE
            ORDER BY created_at DESC
            LIMIT 1
        """, (gmail_thread_id,))
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"find_awaiting_reply failed: {e}")
        return None
    finally:
        put_conn(conn)


def mark_reply_received(
    sent_email_id: int,
    reply_snippet: str = "",
    reply_from: str = "",
) -> bool:
    """Mark a sent email as having received a reply."""
    conn = get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE sent_emails
            SET reply_received = TRUE,
                reply_received_at = %s,
                reply_snippet = %s,
                reply_from = %s
            WHERE id = %s
        """, (datetime.now(timezone.utc), (reply_snippet or "")[:300],
              reply_from, sent_email_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        logger.error(f"mark_reply_received failed: {e}")
        return False
    finally:
        put_conn(conn)


def get_recent_sent_emails(limit: int = 20) -> list:
    """Return recent sent emails with reply status."""
    conn = get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM sent_emails
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_recent_sent_emails failed: {e}")
        return []
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Auto-bootstrap on import
# ---------------------------------------------------------------------------
ensure_table()
