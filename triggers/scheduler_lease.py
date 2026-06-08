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
# SCHEDULER_STALL_CODEFIX_1 — the server-side backend PID of the session that
# holds the advisory lock. Tracked SEPARATELY from _held_conn and kept STICKY:
# when a transient probe false-positive (or Neon idle-drop) nulls _held_conn while
# the server session stays alive holding the lock (the #2508 permanent-stall class),
# _held_pid survives so a later reacquire/release can evict that orphan by PID via
# pg_terminate_backend. Cleared only after a confirmed unlock or a confirmed
# terminate. None when we have never held the lock.
_held_pid: Optional[int] = None
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


def _query_backend_pid(conn: psycopg2.extensions.connection) -> Optional[int]:
    """Return the server-side backend PID for ``conn`` (``pg_backend_pid()``).

    Best-effort: returns None on any failure. Used to record the holder PID so an
    orphaned-but-alive lock session can be terminated later even if the client-side
    connection reference is lost.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_backend_pid()")
        row = cur.fetchone()
        cur.close()
        return int(row[0]) if row and row[0] is not None else None
    except Exception as e:  # noqa: BLE001 — best-effort, never fatal
        logger.warning("scheduler singleton lock: pg_backend_pid() failed: %s", e)
        return None


def _terminate_lock_holder(cur, pid: int) -> bool:
    """Terminate ``pid`` ONLY if it still holds advisory lock ``SCHEDULER_LOCK_KEY``.

    The join-guard against pg_locks is load-bearing: PG can recycle a backend PID
    after a session exits, so an unconditional ``pg_terminate_backend(pid)`` could
    kill an innocent reused backend. Gating on "this exact PID still holds OUR lock"
    makes the terminate safe against PID reuse. Returns True iff a backend was
    actually terminated (i.e. ``pid`` still held the lock).
    """
    cur.execute(
        """
        SELECT pg_terminate_backend(a.pid)
        FROM pg_locks l
        JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.locktype = 'advisory' AND l.objid = %s AND l.pid = %s AND l.granted
        """,
        (SCHEDULER_LOCK_KEY, pid),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def _evict_orphan_holder(pid: int) -> bool:
    """Open a fresh bounded session and terminate orphaned holder ``pid`` if alive.

    Used by ``release_singleton_lock`` when the client-side ``_held_conn`` reference
    was already lost (the #2508 stall) but the server session may still hold the
    lock. Best-effort: returns True iff a holder was terminated.
    """
    try:
        conn = _open_lock_session()
    except Exception as e:
        logger.warning(
            "scheduler singleton lock: evict-orphan connect failed (%s) — "
            "lock may stay held until the dyno restarts", e,
        )
        return False
    try:
        cur = conn.cursor()
        killed = _terminate_lock_holder(cur, pid)
        cur.close()
        if killed:
            logger.warning(
                "scheduler singleton lock: terminated orphaned holder pid=%s "
                "(key=%s) — lock freed for reacquire", pid, SCHEDULER_LOCK_KEY,
            )
        return killed
    except Exception as e:
        logger.warning(
            "scheduler singleton lock: evict-orphan terminate pid=%s failed "
            "(non-fatal): %s", pid, e,
        )
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
    global _held_conn, _held_pid
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

        # Split connect from the lock-probe block so EVERY failure path after the
        # connection is open closes it (codex G3 v2 #1888: the old single try/except
        # returned None on a cursor-block raise WITHOUT closing conn → the 30s
        # acquire-retry loop leaked a direct Neon session per cycle). Mirrors
        # reacquire_singleton_lock's structure exactly.
        try:
            conn = _open_lock_session()
        except Exception as e:
            logger.error("scheduler singleton lock acquire connect failed: %s", e)
            return None

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
            logger.error("scheduler singleton lock acquire probe failed: %s", e)
            return None

        if not row or not row[0]:
            conn.close()
            logger.info(
                "scheduler singleton lock NOT acquired (key=%s) — "
                "another process holds it",
                SCHEDULER_LOCK_KEY,
            )
            return None
        _held_conn = conn
        _held_pid = _query_backend_pid(conn)
        logger.info(
            "scheduler singleton lock ACQUIRED (key=%s, pid=%s) on direct host %s",
            SCHEDULER_LOCK_KEY,
            _held_pid,
            config.postgres.host_direct,
        )
        return conn


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
    global _held_conn, _held_pid
    with _lock:
        # SCHEDULER_STALL_CODEFIX_1 — false-positive guard. reacquire is called when
        # the heartbeat THINKS its lock conn is dead, but the #2508 stall began with a
        # transient probe blip on a STILL-ALIVE session: dropping it abandons a live
        # lock holder that nothing can later evict. Probe SELECT 1 once; if it answers,
        # the conn is alive and we still own the lock — keep it, do NOT reconnect.
        if _held_conn is not None:
            try:
                _cur = _held_conn.cursor()
                _cur.execute("SELECT 1")
                _cur.fetchone()
                _cur.close()
                logger.info(
                    "scheduler singleton lock reacquire: existing conn still alive "
                    "(SELECT 1 ok, pid=%s) — keeping, no reconnect", _held_pid,
                )
                return REACQUIRE_REOWNED
            except Exception:
                # Genuinely dead — close it. Keep _held_pid STICKY so we can terminate
                # the orphaned-but-alive server session below before re-probing.
                try:
                    _held_conn.close()
                except Exception:
                    pass
                _held_conn = None

        # The PID we last held the lock on (may be an orphaned-but-alive Neon session).
        old_pid = _held_pid

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

        # SCHEDULER_STALL_CODEFIX_1 — evict our prior holder BEFORE re-probing. If the
        # old session is orphaned-but-alive on Neon's pooler, it still holds the lock
        # and pg_try_advisory_lock would return FALSE forever (the permanent stall).
        # The terminate is PID-reuse-safe (only fires if old_pid still holds OUR lock).
        if old_pid is not None:
            try:
                _cur = conn.cursor()
                if _terminate_lock_holder(_cur, old_pid):
                    logger.warning(
                        "scheduler singleton lock reacquire: terminated orphaned prior "
                        "holder pid=%s before re-probe (key=%s)",
                        old_pid, SCHEDULER_LOCK_KEY,
                    )
                _cur.close()
            except Exception as e:
                logger.warning(
                    "scheduler singleton lock reacquire: terminate prior holder pid=%s "
                    "failed (non-fatal, continuing to re-probe): %s", old_pid, e,
                )

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
            # Another container owns the lock now — we are a zombie duplicate. (Our own
            # orphan, if any, was terminated above, so a FALSE here means a legitimate
            # other holder.) Drop our PID tracking — the live holder is not ours.
            try:
                conn.close()
            except Exception:
                pass
            _held_pid = None
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
        _held_pid = _query_backend_pid(conn)
        logger.info(
            "scheduler singleton lock RE-ACQUIRED (key=%s, pid=%s) after connection drop "
            "— no teardown needed",
            SCHEDULER_LOCK_KEY,
            _held_pid,
        )
        return REACQUIRE_REOWNED


def release_singleton_lock() -> None:
    """Explicit release for graceful shutdown.

    SIGTERM-driven connection close also releases the lock naturally; this is
    belt-and-suspenders for FastAPI lifespan and watchdog-driven restart.
    """
    global _held_conn, _held_pid
    with _lock:
        if _held_conn is None:
            # SCHEDULER_STALL_CODEFIX_1 — the #2508 stall path: a prior transient
            # false-positive already nulled _held_conn while the server session stayed
            # alive holding the lock. The OLD release was a pure no-op here, so the
            # subsequent acquire (via restart_scheduler) could never win and the
            # scheduler stalled permanently. Now: evict the orphaned holder by its
            # tracked PID so the immediately-following acquire starts clean.
            if _held_pid is not None:
                _evict_orphan_holder(_held_pid)
                _held_pid = None
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
        _held_pid = None
        logger.info(
            "scheduler singleton lock RELEASED (key=%s)", SCHEDULER_LOCK_KEY
        )


def is_held() -> bool:
    """Probe for tests + observability."""
    with _lock:
        return _held_conn is not None


def held_pid() -> Optional[int]:
    """Return the tracked server-side PID of the lock holder (tests + observability).

    May be non-None even when ``is_held()`` is False: that is the orphaned-but-alive
    case (#2508) where the client conn ref was lost but the server session — and the
    advisory lock — survive, pending eviction by PID.
    """
    with _lock:
        return _held_pid
