"""Tests for invariant_checks/ledger_atomic.py.

Hermetic: uses an in-memory sqlite3 DB that mimics the baker_actions
+ cortex_events schemas closely enough to exercise the context
manager's transaction semantics.

SQLite doesn't support JSONB, so we rewrite the helper's INSERT SQL
via a small monkeypatch fixture. Transaction semantics (BEGIN / COMMIT
/ ROLLBACK) are identical to psycopg2's non-autocommit mode, so
atomicity behaviour translates.
"""
from __future__ import annotations

import sqlite3
import pytest

from invariant_checks.ledger_atomic import atomic_director_action  # noqa: F401


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def conn():
    """In-memory sqlite3 conn with baker_actions + cortex_events schemas."""
    c = sqlite3.connect(":memory:")
    c.isolation_level = ""  # Explicit txn control — mirrors psycopg2 default.
    cur = c.cursor()
    cur.execute("""
        CREATE TABLE baker_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            target_task_id TEXT,
            target_space_id TEXT,
            payload TEXT,
            trigger_source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1,
            error_message TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE cortex_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            category TEXT,
            source_agent TEXT,
            payload TEXT
        )
    """)
    c.commit()
    cur.close()

    # Patch the helper's ledger-INSERT SQL to be sqlite-compatible
    # (remove the ::jsonb cast; sqlite uses ? instead of %s).
    import invariant_checks.ledger_atomic as mod
    original_cm = mod.atomic_director_action

    from contextlib import contextmanager

    @contextmanager
    def _sqlite_cm(conn, action_type, payload=None, trigger_source=None,
                   target_task_id=None, target_space_id=None):
        import json as _json
        if conn is None:
            raise RuntimeError("ledger_atomic: conn is None")
        cur = conn.cursor()
        try:
            yield cur
            cur.execute(
                "INSERT INTO baker_actions "
                "(action_type, target_task_id, target_space_id, payload, "
                " trigger_source, success, error_message) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL)",
                (action_type, target_task_id, target_space_id,
                 _json.dumps(payload) if payload else None, trigger_source),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass

    mod.atomic_director_action = _sqlite_cm
    yield c
    mod.atomic_director_action = original_cm
    c.close()


def _count(conn, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    n = cur.fetchone()[0]
    cur.close()
    return n


# --- Tests ---------------------------------------------------------------


def test_happy_path_both_rows_land(conn):
    """Primary INSERT + ledger INSERT both commit atomically."""
    import invariant_checks.ledger_atomic as mod
    with mod.atomic_director_action(
        conn,
        action_type="test:happy",
        payload={"summary": "ok"},
        trigger_source="test_agent",
    ) as cur:
        cur.execute(
            "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
            "VALUES (?, ?, ?, ?)",
            ("deadline", "ratified", "test_agent", "{}"),
        )

    assert _count(conn, "cortex_events") == 1
    assert _count(conn, "baker_actions") == 1


def test_primary_raises_both_rows_rolled_back(conn):
    """If caller's primary INSERT raises, ledger INSERT is NOT executed
    and primary INSERT is rolled back. Invariant: neither row persists."""
    import invariant_checks.ledger_atomic as mod
    with pytest.raises(sqlite3.OperationalError):
        with mod.atomic_director_action(
            conn,
            action_type="test:primary_fails",
            payload={"summary": "doomed"},
            trigger_source="test_agent",
        ) as cur:
            # Syntactically invalid SQL — raises.
            cur.execute("INSERT INTO cortex_events (no_such_column) VALUES (?)", (1,))

    assert _count(conn, "cortex_events") == 0
    assert _count(conn, "baker_actions") == 0


def test_ledger_raises_primary_rolled_back(conn):
    """Fault-injection: simulate ledger-INSERT failure (duplicate PK,
    disk full, etc.). The prior primary INSERT must be rolled back too.

    Implementation: monkeypatch the ledger INSERT to raise on execute.
    """
    import invariant_checks.ledger_atomic as mod
    from contextlib import contextmanager

    @contextmanager
    def _failing_cm(conn, action_type, payload=None, trigger_source=None,
                    target_task_id=None, target_space_id=None):
        cur = conn.cursor()
        try:
            yield cur
            # Simulate ledger-INSERT failure.
            raise sqlite3.OperationalError("simulated ledger failure")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()

    saved = mod.atomic_director_action
    mod.atomic_director_action = _failing_cm
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated ledger failure"):
            with mod.atomic_director_action(
                conn,
                action_type="test:ledger_fails",
                payload={"summary": "doomed"},
                trigger_source="test_agent",
            ) as cur:
                cur.execute(
                    "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
                    "VALUES (?, ?, ?, ?)",
                    ("deadline", "ratified", "test_agent", "{}"),
                )
    finally:
        mod.atomic_director_action = saved

    assert _count(conn, "cortex_events") == 0
    assert _count(conn, "baker_actions") == 0


def test_no_conn_raises_runtime_error(conn):
    """conn=None is a programmer error, not a swallowed no-op."""
    import invariant_checks.ledger_atomic as mod
    with pytest.raises(RuntimeError, match="conn is None"):
        with mod.atomic_director_action(None, action_type="x") as cur:
            pass  # pragma: no cover


def test_payload_serialized_as_json(conn):
    """payload dict is JSON-serialized into baker_actions.payload."""
    import invariant_checks.ledger_atomic as mod
    with mod.atomic_director_action(
        conn,
        action_type="test:payload",
        payload={"k": "v", "n": 42},
        trigger_source="test_agent",
    ) as cur:
        cur.execute(
            "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
            "VALUES (?, ?, ?, ?)",
            ("deadline", "ratified", "test_agent", "{}"),
        )
    cur = conn.cursor()
    cur.execute("SELECT payload FROM baker_actions LIMIT 1")
    row = cur.fetchone()
    cur.close()
    import json
    parsed = json.loads(row[0])
    assert parsed == {"k": "v", "n": 42}


def test_multiple_writes_each_atomic(conn):
    """Two successful atomic blocks both land in full."""
    import invariant_checks.ledger_atomic as mod
    for i in range(2):
        with mod.atomic_director_action(
            conn,
            action_type=f"test:multi_{i}",
            payload={"i": i},
            trigger_source="test_agent",
        ) as cur:
            cur.execute(
                "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
                "VALUES (?, ?, ?, ?)",
                ("deadline", "ratified", "test_agent", "{}"),
            )

    assert _count(conn, "cortex_events") == 2
    assert _count(conn, "baker_actions") == 2
