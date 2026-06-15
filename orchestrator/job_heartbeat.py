"""LONG_RUNNING_JOB_OWNERSHIP_1 — per-job cursor heartbeat store.

`beat(job_id, cursor, state)` UPSERTs a row into `job_heartbeats`; `read(job_id)`
returns the current row. Fault-tolerant by contract: a heartbeat failure must
NEVER crash the caller's real work — every DB call is wrapped in try/except with
conn.rollback() and logs-then-returns on error.

Used by:
  - scripts/backfill_graph.py + scripts/backfill_bluewin.py (real cursor beats)
  - triggers/cursor_stall_sentinel.py (its own meta-watchdog self-beat)

Connection: a DIRECT db connection via kbl.db.get_conn — the same Voyage-free
path the backfills use. It deliberately does NOT route through SentinelStoreBack:
that singleton's __init__ requires VOYAGE_API_KEY (the embedding stack), so a
local backfill with no Voyage key could not write a heartbeat at all — beat()
silently no-op'd and job_heartbeats stayed empty (HEARTBEAT_DECOUPLE_FROM_EMBEDDING_1).
A liveness heartbeat must never depend on an embedding key.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("sentinel.job_heartbeat")

_VALID_STATES = ("RUNNING", "DONE", "FAILED", "PAUSED")


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

    try:
        from kbl.db import get_conn  # noqa: PLC0415 — Voyage-free pool, kbl pattern
        with get_conn() as conn:
            try:
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
            except Exception:
                conn.rollback()
                raise
        return True
    except Exception as e:
        logger.warning("job_heartbeat.beat failed for %s: %s", job_id, e)
        return False


def read(job_id: str) -> dict | None:
    """Return {job_id, cursor_text, state, updated_at} or None (never raises)."""
    try:
        from kbl.db import get_conn  # noqa: PLC0415 — Voyage-free pool, kbl pattern
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '10s'")
                    cur.execute(
                        "SELECT job_id, cursor_text, state, updated_at "
                        "FROM job_heartbeats WHERE job_id = %s LIMIT 1",
                        (job_id,),
                    )
                    row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
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
        return None
