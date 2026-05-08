"""Verify SentinelStoreBack uses a thread-safe pool (ThreadedConnectionPool).

Anchor: 2026-05-08 finding F2 — SimpleConnectionPool is single-thread-only
per psycopg2 docs, but the dashboard runs the pool from FastAPI thread +
APScheduler workers + boot-time daemon backfill threads.
"""
import psycopg2.pool
import pytest


def test_store_back_uses_threaded_pool():
    """Pool class must be ThreadedConnectionPool (not SimpleConnectionPool).

    The singleton's `__init__` touches voyage / Qdrant / Postgres; if any of
    those upstream deps is unavailable in the local env (no `VOYAGE_API_KEY`,
    no `DATABASE_URL`, etc.), construction raises before the pool is built.
    Skip in that case — the regression-pin still holds in any environment
    that can actually instantiate the singleton (CI / Render).
    """
    from memory.store_back import SentinelStoreBack
    try:
        store = SentinelStoreBack._get_global_instance()
    except Exception as e:
        pytest.skip(f"SentinelStoreBack singleton cannot be constructed in this env: {e!r}")
    if store._pool is None:
        # Local dev w/o DATABASE_URL — pool is None; nothing to type-check.
        pytest.skip("No PostgreSQL pool initialized (DATABASE_URL unset)")
    assert isinstance(store._pool, psycopg2.pool.ThreadedConnectionPool), (
        f"Pool must be ThreadedConnectionPool for thread safety; "
        f"got {type(store._pool).__name__}"
    )


def test_init_pool_uses_threaded_constructor():
    """Static guard: `_init_pool` source must reference ThreadedConnectionPool, not Simple.

    Belt-and-suspenders for environments where the singleton can't be
    constructed (above test would skip). Source-text inspection guarantees
    the regression-pin holds even when the runtime check is skipped.
    """
    import inspect
    from memory.store_back import SentinelStoreBack
    source = inspect.getsource(SentinelStoreBack._init_pool)
    assert "ThreadedConnectionPool" in source, (
        "_init_pool must construct psycopg2.pool.ThreadedConnectionPool"
    )
    # SimpleConnectionPool may appear only inside docstrings/comments referencing
    # the historical class; the executable line must NOT use it.
    assert "psycopg2.pool.SimpleConnectionPool(" not in source, (
        "_init_pool must NOT call psycopg2.pool.SimpleConnectionPool — "
        "it is single-thread-only per psycopg2 docs."
    )
