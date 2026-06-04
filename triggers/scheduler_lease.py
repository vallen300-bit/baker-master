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

# SCHEDULER_NEON_IDLE_HARDEN_1 — bounds on the lock connection so a dead/idle
# socket or a server-side stall fails fast instead of hanging the heartbeat
# job thread (which would skip the next 5-min fire and trip the watchdog).
_CONNECT_TIMEOUT_S = 5          # initial TCP connect bound (keepalives don't cover connect)
_STATEMENT_TIMEOUT = "10s"      # per-session server-stall bound on the lock session

# SCHEDULER_NEON_IDLE_HARDEN_1 — 3-state outcome of reacquire_singleton_lock().
REACQUIRE_REOWNED = "reowned"      # reconnect OK + advisory lock TRUE → we re-own; keep firing
REACQUIRE_LOST = "lost"            # reconnect OK + advisory lock FALSE → another holder; stand down
REACQUIRE_TRANSIENT = "transient"  # reconnect failed → indeterminate; retry next heartbeat

_held_conn: Optional[psycopg2.extensions.connection] = None
_lock = threading.Lock()

# SCHEDULER_NEON_IDLE_HARDEN_1 — non-self-join stand-down request. The heartbeat
# job thread MUST NOT call restart_scheduler()/shutdown(wait=True) (a thread cannot
# join itself). Instead it sets this flag; the request-thread watchdog consumes it.
_standdown_requested = False
_standdown_lock = threading.Lock()


def request_standdown() -> None:
    """Mark that this process must stop firing (it lost the singleton lock).

    Called from the heartbeat job thread. The request-thread watchdog
    (outputs/dashboard.py `_check_scheduler_heartbeat`) consumes it and runs the
    actual restart off the job thread — avoiding a self-join.
    """
    global _standdown_requested
    with _standdown_lock:
        _standdown_requested = True


def consume_standdown() -> bool:
    """Test-and-clear the stand-down request. Returns True at most once per request.

    Idempotent: a second call after a consumed request returns False, so the
    watchdog does not re-restart on the next tick.
    """
    global _standdown_requested
    with _standdown_lock:
        if _standdown_requested:
            _standdown_requested = False
            return True
        return False


def _open_lock_session() -> psycopg2.extensions.connection:
    """Open a fresh direct (non-pooled) autocommit connection for the singleton lock.

    Bounds layered so the lock path can never block the heartbeat job thread:
      * ``connect_timeout`` bounds the initial TCP connect (keepalives don't);
      * keepalives (from ``direct_dsn_params``) bound a half-open socket;
      * a per-session ``statement_timeout`` bounds a server-side stall.
    Raises on connect failure — callers handle the transient case.
    """
    # statement_timeout is applied at CONNECT time via libpq options (codex G3
    # #1884): a post-connect `SET` has an unprotected failure/hang window and, if
    # it raised, the half-opened connection leaked (acquire->None / reacquire->
    # TRANSIENT never closed it → the 30s retry loop leaks a direct Neon session
    # each cycle). _STATEMENT_TIMEOUT is a fixed module constant (never user input);
    # direct_dsn_params carries no conflicting 'options' key.
    conn = psycopg2.connect(
        connect_timeout=_CONNECT_TIMEOUT_S,
        options="-c statement_timeout=%s" % _STATEMENT_TIMEOUT,
        **config.postgres.direct_dsn_params,
    )
    try:
        # Advisory locks need a real session, not pgbouncer transaction-mode;
        # autocommit avoids accidental session-state drift on idle. Guard EVERY
        # post-connect step so ANY failure closes the conn instead of leaking it.
        conn.autocommit = True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise
    return conn


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
            conn = _open_lock_session()
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


def reacquire_singleton_lock() -> str:
    """SCHEDULER_NEON_IDLE_HARDEN_1 — self-heal a dropped lock connection.

    Called by the heartbeat when its lock connection is dead/None (Neon idle-drop
    between probes). Closes the stale ``_held_conn``, opens a fresh bounded session,
    and re-attempts the advisory lock. Returns a 3-state result the caller acts on,
    because the singleton contract is *no jobs may run without the lock*:

      * ``REACQUIRE_REOWNED``   — we re-own the same lock; ``_held_conn`` set; keep firing.
      * ``REACQUIRE_LOST``      — another process now holds it (deploy overlap); ``_held_conn``
                                  cleared; caller MUST stand down (stop firing).
      * ``REACQUIRE_TRANSIENT`` — reconnect failed; ownership indeterminate; ``_held_conn``
                                  cleared; caller retries next heartbeat (do NOT stand down —
                                  if the DB is unreachable to us it is to all, so no one else
                                  can grab the lock; the watchdog is the backstop).
    """
    global _held_conn
    with _lock:
        # Close the stale held connection first (it is presumed dead).
        if _held_conn is not None:
            try:
                _held_conn.close()
            except Exception:
                pass
            _held_conn = None

        if not config.postgres.host_direct:
            # No direct endpoint → cannot hold a session lock. Treat as transient
            # (matches acquire's refusal) so the watchdog stays the backstop.
            logger.warning(
                "scheduler singleton lock reacquire skipped — POSTGRES_HOST_DIRECT unset"
            )
            return REACQUIRE_TRANSIENT

        try:
            conn = _open_lock_session()
        except Exception as e:
            logger.warning(
                "scheduler singleton lock reacquire connect failed (%s) — "
                "transient, retrying next heartbeat (watchdog backstop active)",
                e,
            )
            return REACQUIRE_TRANSIENT

        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(%s)", (SCHEDULER_LOCK_KEY,))
            row = cur.fetchone()
            cur.close()
        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            logger.warning(
                "scheduler singleton lock reacquire probe failed (%s) — transient",
                e,
            )
            return REACQUIRE_TRANSIENT

        if not row or not row[0]:
            # Another container owns the lock now — we are a zombie duplicate.
            try:
                conn.close()
            except Exception:
                pass
            logger.error(
                "scheduler singleton lock reacquire: ANOTHER process holds key=%s "
                "now — standing down to avoid a duplicate scheduler",
                SCHEDULER_LOCK_KEY,
            )
            # Request stand-down here (idempotent with the heartbeat's own call) so
            # a direct reacquire caller also stops firing without the heartbeat.
            request_standdown()
            return REACQUIRE_LOST

        _held_conn = conn
        logger.info(
            "scheduler singleton lock RE-ACQUIRED (key=%s) after connection drop "
            "— no teardown needed",
            SCHEDULER_LOCK_KEY,
        )
        return REACQUIRE_REOWNED


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
