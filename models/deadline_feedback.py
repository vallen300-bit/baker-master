"""DEADLINE_FEEDBACK_LOOP_1: persistence layer for Director-click corpus.

Single-purpose module — write-only from the dashboard, read-only from phase-3
classifier training jobs (SIGNAL_CLASSIFIER_TIER2_1, future).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2.extras

from models.deadlines import get_conn, put_conn

logger = logging.getLogger(__name__)

VALID_FEEDBACK_TYPES = frozenset({"confirm", "mute", "wrong_matter", "wrong_deadline"})

# Observability counter for corpus-write degradation (Fix B per AH1 fix request).
# Phase 3 classifier upgrade is gated on "2+ weeks of click corpus lands here" — a
# silent regression (schema drift, pool exhaustion, migration unapplied) would
# invalidate that window with zero visibility. Surfaced via /api/health.
_WRITE_FAILURES: int = 0
_LAST_FAILURE_AT: Optional[datetime] = None


def _record_write_failure() -> None:
    global _WRITE_FAILURES, _LAST_FAILURE_AT
    _WRITE_FAILURES += 1
    _LAST_FAILURE_AT = datetime.now(timezone.utc)


def get_write_failure_stats() -> dict:
    """Snapshot for /api/health. Non-fatal — health stays ok even if count > 0."""
    return {
        "count": _WRITE_FAILURES,
        "last_failure_at": _LAST_FAILURE_AT.isoformat() if _LAST_FAILURE_AT else None,
    }


def reset_write_failure_stats() -> None:
    """Test-only helper; not wired to any endpoint."""
    global _WRITE_FAILURES, _LAST_FAILURE_AT
    _WRITE_FAILURES = 0
    _LAST_FAILURE_AT = None


def insert_feedback(
    deadline_id: int,
    feedback_type: str,
    original_matter_slug: Optional[str],
    corrected_matter_slug: Optional[str],
    original_description: str,
    original_source_type: Optional[str],
    director_note: Optional[str] = None,
) -> Optional[int]:
    """Insert one feedback row. Returns the new id or None on failure.

    Fault-tolerant: callers do NOT see exceptions; failures log + return None.
    Status-flip endpoints (dismiss/complete) must succeed even if feedback
    logging is degraded.
    """
    if feedback_type not in VALID_FEEDBACK_TYPES:
        logger.error(f"deadline_feedback: invalid type {feedback_type!r}")
        _record_write_failure()
        return None

    conn = get_conn()
    if not conn:
        logger.warning("deadline_feedback: no DB connection")
        _record_write_failure()
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO deadline_feedback
                (deadline_id, feedback_type, original_matter_slug,
                 corrected_matter_slug, original_description,
                 original_source_type, director_note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (deadline_id, feedback_type, original_matter_slug,
             corrected_matter_slug, original_description,
             original_source_type, director_note),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"deadline_feedback insert failed: {e}")
        _record_write_failure()
        return None
    finally:
        put_conn(conn)


def get_recent_feedback(limit: int = 100) -> list:
    """Read recent feedback rows (DESC by clicked_at). LIMIT enforced per backend rule."""
    if not isinstance(limit, int) or limit <= 0:
        limit = 100
    if limit > 1000:
        limit = 1000
    conn = get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, deadline_id, feedback_type, original_matter_slug,
                   corrected_matter_slug, original_description,
                   original_source_type, director_note, clicked_at
            FROM deadline_feedback
            ORDER BY clicked_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        return list(rows)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"deadline_feedback read failed: {e}")
        return []
    finally:
        put_conn(conn)
