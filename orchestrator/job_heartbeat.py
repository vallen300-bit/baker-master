"""LONG_RUNNING_JOB_OWNERSHIP_1 — per-job cursor heartbeat store.

`beat(job_id, cursor, state)` UPSERTs a row into `job_heartbeats`; `read(job_id)`
returns the current row. Fault-tolerant by contract: a heartbeat failure must
NEVER crash the caller's real work — every DB call is wrapped in try/except with
conn.rollback() and logs-then-returns on error.

Used by:
  - scripts/backfill_graph.py + scripts/backfill_bluewin.py (real cursor beats)
  - triggers/cursor_stall_sentinel.py (its own meta-watchdog self-beat)
"""
from __future__ import annotations

import logging

logger = logging.getLogger("sentinel.job_heartbeat")

_VALID_STATES = ("RUNNING", "DONE", "FAILED", "PAUSED")


def _store():
    """Return the global SentinelStoreBack instance, or None if unavailable."""
    try:
        from memory.store_back import SentinelStoreBack
        return SentinelStoreBack._get_global_instance()
    except Exception as e:  # pragma: no cover - import/singleton failure
        logger.warning("job_heartbeat: store_back unreachable: %s", e)
        return None


def beat(job_id: str, cursor, state: str = "RUNNING") -> bool:
    """UPSERT a heartbeat for ``job_id``. Returns True on success, False on any
    failure (never raises — monitoring must not crash real work).

    ``cursor`` is coerced to text (the column is TEXT). ``state`` must be one of
    RUNNING / DONE / FAILED / PAUSED (defaults to RUNNING on an unknown value).
    """
    if state not in _VALID_STATES:
        logger.warning("job_heartbeat.beat: unknown state %r for %s -> RUNNING",
                       state, job_id)
        state = "RUNNING"

    store = _store()
    if store is None:
        return False
    conn = None
    try:
        conn = store._get_conn()
        if not conn:
            return False
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_heartbeats (job_id, cursor_text, state, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (job_id) DO UPDATE SET
                    cursor_text = EXCLUDED.cursor_text,
                    state       = EXCLUDED.state,
                    updated_at  = now()
                """,
                (job_id, None if cursor is None else str(cursor), state),
            )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("job_heartbeat.beat failed for %s: %s", job_id, e)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return False
    finally:
        if conn is not None:
            try:
                store._put_conn(conn)
            except Exception:
                pass


def read(job_id: str) -> dict | None:
    """Return {job_id, cursor_text, state, updated_at} or None (never raises)."""
    store = _store()
    if store is None:
        return None
    conn = None
    try:
        conn = store._get_conn()
        if not conn:
            return None
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute(
                "SELECT job_id, cursor_text, state, updated_at "
                "FROM job_heartbeats WHERE job_id = %s LIMIT 1",
                (job_id,),
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            return None
        return {
            "job_id": row[0],
            "cursor_text": row[1],
            "state": row[2],
            "updated_at": row[3],
        }
    except Exception as e:
        logger.warning("job_heartbeat.read failed for %s: %s", job_id, e)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return None
    finally:
        if conn is not None:
            try:
                store._put_conn(conn)
            except Exception:
                pass
