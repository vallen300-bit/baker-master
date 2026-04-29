"""SCHEDULER_SINGLETON_HARDEN_1 — singleton-lock enforcement tests.

Live-PG via the ``needs_live_pg`` fixture (``tests/conftest.py``): resolves
``TEST_DATABASE_URL`` or auto-provisions an ephemeral Neon branch when
``NEON_API_KEY`` + ``NEON_PROJECT_ID`` are set; skips otherwise.

The lock module reads ``config.postgres.direct_dsn_params``. Tests parse the
``needs_live_pg`` URL and monkeypatch ``config.postgres`` fields so the lock
runs against the test DB, not production.
"""
from __future__ import annotations

import urllib.parse

import psycopg2
import pytest


def _patch_postgres_config_to_url(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Point ``config.postgres`` at the live-PG URL for this test.

    Sets both ``host_direct`` (so the gating check in ``acquire_singleton_lock``
    passes) and the rest of the connection params so ``direct_dsn_params``
    reaches the test DB.
    """
    parsed = urllib.parse.urlparse(url)
    from config.settings import config as _cfg

    monkeypatch.setattr(_cfg.postgres, "host", parsed.hostname or "localhost")
    monkeypatch.setattr(_cfg.postgres, "host_direct", parsed.hostname or "localhost")
    monkeypatch.setattr(_cfg.postgres, "port", int(parsed.port or 5432))
    monkeypatch.setattr(_cfg.postgres, "database", (parsed.path or "/").lstrip("/"))
    if parsed.username:
        monkeypatch.setattr(_cfg.postgres, "user", urllib.parse.unquote(parsed.username))
    if parsed.password:
        monkeypatch.setattr(_cfg.postgres, "password", urllib.parse.unquote(parsed.password))
    qs = urllib.parse.parse_qs(parsed.query)
    if "sslmode" in qs:
        monkeypatch.setattr(_cfg.postgres, "sslmode", qs["sslmode"][0])


def test_first_acquire_succeeds(needs_live_pg, monkeypatch):
    _patch_postgres_config_to_url(monkeypatch, needs_live_pg)
    from triggers.scheduler_lease import (
        acquire_singleton_lock,
        is_held,
        release_singleton_lock,
    )
    release_singleton_lock()  # clean state
    held = acquire_singleton_lock()
    try:
        assert held is not None, "first acquire on clean key should succeed"
        assert is_held() is True
    finally:
        release_singleton_lock()


def test_second_acquire_from_separate_connection_blocks(needs_live_pg, monkeypatch):
    """Two-process race: first conn holds lock, second conn must NOT acquire."""
    _patch_postgres_config_to_url(monkeypatch, needs_live_pg)
    from config.settings import config
    from triggers.scheduler_lease import (
        SCHEDULER_LOCK_KEY,
        acquire_singleton_lock,
        release_singleton_lock,
    )
    release_singleton_lock()
    held = acquire_singleton_lock()
    try:
        assert held is not None

        other = psycopg2.connect(**config.postgres.direct_dsn_params)
        other.autocommit = True
        try:
            cur = other.cursor()
            cur.execute("SELECT pg_try_advisory_lock(%s)", (SCHEDULER_LOCK_KEY,))
            got = cur.fetchone()[0]
            cur.close()
        finally:
            other.close()

        assert got is False, "second connection acquired despite first holding"
    finally:
        release_singleton_lock()


def test_release_then_reacquire(needs_live_pg, monkeypatch):
    _patch_postgres_config_to_url(monkeypatch, needs_live_pg)
    from triggers.scheduler_lease import (
        acquire_singleton_lock,
        release_singleton_lock,
    )
    release_singleton_lock()
    h1 = acquire_singleton_lock()
    assert h1 is not None
    release_singleton_lock()

    h2 = acquire_singleton_lock()
    try:
        assert h2 is not None, "re-acquire after release should succeed"
    finally:
        release_singleton_lock()


def test_acquire_returns_none_when_host_direct_unset(monkeypatch):
    """Pure-unit guard: with ``host_direct`` empty, acquire MUST return None
    (refuse pooler-fallback, per brief — pgbouncer transaction-mode releases
    session locks on commit).

    Skips the live-PG fixture by clearing ``host_direct`` to '' before any
    psycopg2 call. No DB roundtrip — gate fires first.
    """
    from config.settings import config as _cfg
    monkeypatch.setattr(_cfg.postgres, "host_direct", "")
    # also reset any lingering held state from prior tests
    import triggers.scheduler_lease as _lease
    _lease._held_conn = None
    held = _lease.acquire_singleton_lock()
    assert held is None
    assert _lease.is_held() is False
