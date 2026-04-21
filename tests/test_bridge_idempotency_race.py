"""Advisory-lock serialization — BRIDGE_HOT_MD_AND_TUNING_1.

Simulates two ticks racing: the first acquires
``pg_try_advisory_xact_lock``; the second receives ``False`` and must
no-op cleanly (empty counts, rolled back, no inserts, no watermark
advance). This is the Batch #1 duplicate's fix.

Pure mocks. The live-PG concurrency shape (two processes, one blocking
the other) is the test #8 pattern in ``test_migration_runner.py`` —
out of scope here to keep the bridge test suite hermetic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kbl.bridge import alerts_to_signal as bridge


class _LockCursor:
    """Minimal cursor that routes ``pg_try_advisory_xact_lock`` to a canned value."""

    def __init__(self, acquire: bool):
        self._acquire = acquire
        self._last = None
        self.executes = []

    def execute(self, sql, params=None):
        self.executes.append((sql, params))
        if "pg_try_advisory_xact_lock" in sql:
            self._last = (self._acquire,)
        else:
            self._last = None

    def fetchone(self):
        return self._last

    def fetchall(self):
        return [self._last] if self._last else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _NeverCalledCursor:
    """Cursor that fails loudly if used — proves the lock path short-circuited."""

    def execute(self, sql, params=None):
        raise AssertionError(
            f"_NeverCalledCursor unexpectedly used; sql={sql[:80]!r}"
        )

    def fetchone(self):
        raise AssertionError("_NeverCalledCursor.fetchone called")

    def fetchall(self):
        raise AssertionError("_NeverCalledCursor.fetchall called")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, cursors):
        self._cursors = list(cursors)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursors.pop(0)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _patch_conn(monkeypatch, conn):
    from contextlib import contextmanager

    @contextmanager
    def fake_get_conn():
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(bridge, "get_conn", fake_get_conn)


def test_tick_skips_cleanly_when_lock_not_acquired(monkeypatch):
    """Second concurrent tick: lock=False → no reads, no writes, rolled back."""
    # Only one cursor ever opens — the lock check. The setup + write
    # cursors are _NeverCalledCursor to fail loudly if the short-circuit
    # is broken.
    conn = _FakeConn(
        [
            _LockCursor(acquire=False),
            _NeverCalledCursor(),
            _NeverCalledCursor(),
        ]
    )
    _patch_conn(monkeypatch, conn)

    counts = bridge.run_bridge_tick()

    assert counts["skipped_locked"] == 1
    assert counts["read"] == 0
    assert counts["bridged"] == 0
    assert counts["errors"] == 0
    assert conn.committed is False
    assert conn.rolled_back is True, (
        "empty txn from the failed lock attempt must be rolled back"
    )


def test_tick_proceeds_when_lock_acquired(monkeypatch):
    """First concurrent tick: lock=True → full tick body runs, commit fires."""
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    # Re-use the _FakeCursor from the existing bridge test module would
    # force a coupling; instead hand-roll the minimum surface needed here.
    class _Cur:
        def __init__(self, plan):
            self._plan = plan
            self._last = None
            self.executes = []

        def execute(self, sql, params=None):
            self.executes.append((sql, params))
            if "pg_try_advisory_xact_lock" in sql:
                self._last = (True,)
                return
            for needle, response in self._plan:
                if needle in sql:
                    self._last = response
                    return
            self._last = None

        def fetchone(self):
            return self._last[0] if isinstance(self._last, list) else self._last

        def fetchall(self):
            return list(self._last) if isinstance(self._last, list) else ([self._last] if self._last else [])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    lock_cursor = _Cur([])
    setup_cursor = _Cur(
        [
            ("FROM trigger_watermarks", (now - timedelta(hours=1),)),
            ("FROM vip_contacts", []),
            (
                "FROM alerts",
                [
                    (
                        100, 1, "Court filing today", None, "movie",
                        "email", "msg-100", None, None, None, now,
                    )
                ],
            ),
        ]
    )
    write_cursor = _Cur(
        [
            ("INSERT INTO signal_queue", (500,)),
            ("INSERT INTO trigger_watermarks", None),
        ]
    )

    conn = _FakeConn([lock_cursor, setup_cursor, write_cursor])
    _patch_conn(monkeypatch, conn)

    counts = bridge.run_bridge_tick()

    assert counts["skipped_locked"] == 0
    assert counts["read"] == 1
    assert counts["bridged"] == 1
    assert conn.committed is True


def test_lock_acquired_empty_alerts_still_commits_to_release_lock(monkeypatch):
    """Empty-alert path must still commit — the xact-scoped lock holds until COMMIT/ROLLBACK.

    Prevents a dead-tick from starving sibling ticks on a lingering lock.
    """
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    class _Cur:
        def __init__(self, plan):
            self._plan = plan
            self._last = None
            self.executes = []

        def execute(self, sql, params=None):
            self.executes.append((sql, params))
            if "pg_try_advisory_xact_lock" in sql:
                self._last = (True,)
                return
            for needle, response in self._plan:
                if needle in sql:
                    self._last = response
                    return
            self._last = None

        def fetchone(self):
            return self._last

        def fetchall(self):
            return [self._last] if self._last else []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    lock_cursor = _Cur([])
    setup_cursor = _Cur(
        [
            ("FROM trigger_watermarks", (now - timedelta(hours=1),)),
            ("FROM vip_contacts", []),
            ("FROM alerts", []),
        ]
    )
    conn = _FakeConn([lock_cursor, setup_cursor])
    _patch_conn(monkeypatch, conn)

    counts = bridge.run_bridge_tick()

    assert counts["read"] == 0
    assert counts["skipped_locked"] == 0
    assert conn.committed is True, (
        "empty-alert branch must commit to release xact-scoped advisory lock"
    )
    assert conn.rolled_back is False


def test_lock_key_is_stable_integer_constant():
    """Brief constraint: advisory lock key must be stable (not a mutable string).

    Specifically: not runtime-hashed from a string that could change.
    """
    assert isinstance(bridge._BRIDGE_ADVISORY_LOCK_KEY, int)
    # Distinct from the migration runner's key to avoid cross-lock contention.
    from config.migration_runner import _MIGRATION_LOCK_KEY
    assert bridge._BRIDGE_ADVISORY_LOCK_KEY != _MIGRATION_LOCK_KEY
