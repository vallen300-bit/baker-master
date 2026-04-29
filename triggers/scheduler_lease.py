"""SCHEDULER_SINGLETON_HARDEN_1 — process-singleton lock for the BackgroundScheduler.

Held on a DEDICATED non-pooled Neon connection. The lock auto-releases when
the process dies (SIGTERM closes the connection at the OS level), giving a
clean handoff during Render Pro zero-downtime deploys.

Usage:
    from triggers.scheduler_lease import acquire_singleton_lock, release_singleton_lock

    held_conn = acquire_singleton_lock()
    if held_conn is None:
        # Another process holds the lock. Caller MUST NOT call _register_jobs.
        return
    # Caller proceeds to start scheduler.
    # held_conn must be kept alive for the process lifetime.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import psycopg2

from config.settings import config

logger = logging.getLogger(__name__)

# Arbitrary fixed key — distinct from existing 900600 (bridge xact), 8005, 867531.
SCHEDULER_LOCK_KEY = 8800100

_held_conn: Optional[psycopg2.extensions.connection] = None
_lock = threading.Lock()


def acquire_singleton_lock() -> Optional[psycopg2.extensions.connection]:
    """Try to acquire the scheduler singleton advisory lock.

    Returns the held connection on success, ``None`` on:
      * Another process holds the lock.
      * DB unreachable.
      * ``POSTGRES_HOST_DIRECT`` unset — pooler endpoint is unsafe for
        session-level locks (pgbouncer transaction-mode releases on commit).

    Caller MUST keep the returned connection alive for the process lifetime
    and MUST NOT pass it back to a connection pool.
    """
    global _held_conn
    with _lock:
        if _held_conn is not None:
            return _held_conn

        if not config.postgres.host_direct:
            logger.error(
                "POSTGRES_HOST_DIRECT unset — scheduler singleton lock disabled "
                "(pooler endpoint cannot hold session-level advisory locks). "
                "Set POSTGRES_HOST_DIRECT on Render to enable. Continuing without "
                "lock; duplicate scheduler firing remains possible during deploy "
                "overlap."
            )
            return None

        try:
            conn = psycopg2.connect(**config.postgres.direct_dsn_params)
            # Advisory locks need a real session, not pgbouncer transaction-mode;
            # autocommit avoids accidental session-state drift on idle.
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(%s)", (SCHEDULER_LOCK_KEY,))
            row = cur.fetchone()
            cur.close()
            if not row or not row[0]:
                conn.close()
                logger.info(
                    "scheduler singleton lock NOT acquired (key=%s) — "
                    "another process holds it",
                    SCHEDULER_LOCK_KEY,
                )
                return None
            _held_conn = conn
            logger.info(
                "scheduler singleton lock ACQUIRED (key=%s) on direct host %s",
                SCHEDULER_LOCK_KEY,
                config.postgres.host_direct,
            )
            return conn
        except Exception as e:
            logger.error("scheduler singleton lock acquire failed: %s", e)
            return None


def release_singleton_lock() -> None:
    """Explicit release for graceful shutdown.

    SIGTERM-driven connection close also releases the lock naturally; this is
    belt-and-suspenders for FastAPI lifespan and watchdog-driven restart.
    """
    global _held_conn
    with _lock:
        if _held_conn is None:
            return
        try:
            cur = _held_conn.cursor()
            cur.execute("SELECT pg_advisory_unlock(%s)", (SCHEDULER_LOCK_KEY,))
            cur.close()
        except Exception:
            pass
        try:
            _held_conn.close()
        except Exception:
            pass
        _held_conn = None
        logger.info(
            "scheduler singleton lock RELEASED (key=%s)", SCHEDULER_LOCK_KEY
        )


def is_held() -> bool:
    """Probe for tests + observability."""
    with _lock:
        return _held_conn is not None
