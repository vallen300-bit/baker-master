"""Tests for ``config.migration_runner``.

Covers (per B2-APPROVED brief v2 at ``briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md``):

#1 ``test_apply_all_applies_new_file``         — pure mock, psycopg2.connect patched.
#2 ``test_apply_all_skips_already_applied``     — pure mock.
#3 ``test_apply_all_aborts_on_sha_mismatch``    — pure mock.
#4 ``test_apply_all_aborts_on_sql_error_no_partial`` — pure mock.
#5 ``test_startup_call_order``                  — runtime Mock manager (N1 — NOT AST).
#6 ``test_first_deploy_idempotency_dry_run``    — live-PG via ``needs_live_pg``.
#7 ``test_migration_file_has_up_marker``        — pure file scan.
#8 ``test_second_instance_blocks_on_advisory_lock`` — live-PG via ``needs_live_pg``.

Tests #1-5, #7 run unconditionally. Tests #6, #8 use the shared
``needs_live_pg`` fixture (see ``tests/conftest.py``) which resolves a live
PG URL from ``TEST_DATABASE_URL`` or an ephemeral Neon branch; skips
otherwise. Brief N2 + CONFTEST_NEON_EPHEMERAL_FIXTURE.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Fake psycopg2 plumbing for pure-mock tests (#1-4)
# ---------------------------------------------------------------------------
#
# Simulates the subset of psycopg2 the runner touches:
#   * ``pg_try_advisory_lock`` / ``pg_advisory_unlock`` — always succeed.
#   * ``CREATE TABLE IF NOT EXISTS schema_migrations`` — no-op.
#   * ``SELECT column_name FROM information_schema.columns`` — return
#     expected column set unless ``col_drift`` arg says otherwise.
#   * ``SELECT filename, sha256 FROM schema_migrations`` — return pre-seeded
#     applied set.
#   * ``INSERT INTO schema_migrations`` — append to a list.
#   * Arbitrary migration SQL — record it, optionally raise via ``bad_sqls``.


class _FakeCursor:
    def __init__(self, conn: "_FakeConn"):
        self._conn = conn
        self._last_result: list = []

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        s = sql.strip()
        s_lower = s.lower()

        if "pg_try_advisory_lock" in s_lower:
            self._last_result = [(self._conn.lock_acquires.pop(0) if self._conn.lock_acquires else True,)]
            return
        if "pg_advisory_unlock" in s_lower:
            self._last_result = [(True,)]
            return
        if "create table if not exists schema_migrations" in s_lower:
            self._last_result = []
            return
        if "information_schema.columns" in s_lower:
            if self._conn.col_drift_missing:
                self._last_result = [(c,) for c in ("filename", "sha256")]  # applied_at missing
            else:
                self._last_result = [(c,) for c in ("filename", "applied_at", "sha256")]
            return
        if "select filename, sha256 from schema_migrations" in s_lower:
            self._last_result = list(self._conn.applied.items())
            return
        if "insert into schema_migrations" in s_lower:
            # params = (filename, sha256)
            self._conn.inserts.append(params)
            return
        # Any other SQL is a migration body.
        for marker, exc in self._conn.bad_sqls.items():
            if marker in sql:
                raise exc
        self._conn.migrations_executed.append(sql)

    def fetchall(self):
        return list(self._last_result)

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(
        self,
        applied: dict[str, str] | None = None,
        col_drift_missing: bool = False,
        lock_acquires: list[bool] | None = None,
        bad_sqls: dict[str, Exception] | None = None,
    ):
        self.applied = dict(applied or {})
        self.col_drift_missing = col_drift_missing
        self.lock_acquires = list(lock_acquires) if lock_acquires is not None else []
        self.bad_sqls = dict(bad_sqls or {})
        self.executed: list[tuple] = []
        self.inserts: list[tuple] = []
        self.migrations_executed: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@contextmanager
def _fixture_migrations(*files: tuple[str, str]):
    """Yield a tempdir path with the given (filename, content) tuples written."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for name, content in files:
            (tdp / name).write_text(content)
        yield str(tdp)


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ===========================================================================
# Tests #1-4: pure mock (no real PG)
# ===========================================================================


def test_apply_all_applies_new_file():
    """Empty DB, one file: apply_all runs migration SQL, commits twice (once
    for schema_migrations CREATE, once for the per-file transaction),
    inserts one tracking row with correct sha256, returns the filename."""
    sql_body = "CREATE TABLE test_noop (id INT);"
    files = (("001_noop.sql", sql_body),)
    fake = _FakeConn(applied={})

    with _fixture_migrations(*files) as mig_dir, \
         patch("config.migration_runner.psycopg2.connect", return_value=fake):
        from config.migration_runner import run_pending_migrations
        applied = run_pending_migrations("postgres://fake", migrations_dir=mig_dir)

    assert applied == ["001_noop.sql"]
    # Migration body ran.
    assert any(sql_body in s for s in fake.migrations_executed)
    # One tracking row inserted with correct sha256.
    assert fake.inserts == [("001_noop.sql", _sha256_of(sql_body))]
    assert fake.rollbacks == 0
    assert fake.closed is True


def test_apply_all_skips_already_applied():
    """Pre-populated applied set: runner reads sha, matches, skips. No
    migration SQL runs; no tracking row inserted."""
    sql_body = "CREATE TABLE test_noop (id INT);"
    files = (("001_noop.sql", sql_body),)
    fake = _FakeConn(applied={"001_noop.sql": _sha256_of(sql_body)})

    with _fixture_migrations(*files) as mig_dir, \
         patch("config.migration_runner.psycopg2.connect", return_value=fake):
        from config.migration_runner import run_pending_migrations
        applied = run_pending_migrations("postgres://fake", migrations_dir=mig_dir)

    assert applied == []
    assert fake.migrations_executed == []  # migration body never ran
    assert fake.inserts == []              # no new tracking row
    assert fake.rollbacks == 0


def test_apply_all_aborts_on_sha_mismatch():
    """Stored sha != current sha → MigrationError. Error message contains
    filename + both shas + force-re-apply hint."""
    sql_body = "CREATE TABLE test_noop (id INT);"
    files = (("001_noop.sql", sql_body),)
    stored_sha = "deadbeef" * 8
    fake = _FakeConn(applied={"001_noop.sql": stored_sha})

    with _fixture_migrations(*files) as mig_dir, \
         patch("config.migration_runner.psycopg2.connect", return_value=fake):
        from config.migration_runner import run_pending_migrations, MigrationError

        with pytest.raises(MigrationError) as exc_info:
            run_pending_migrations("postgres://fake", migrations_dir=mig_dir)

    msg = str(exc_info.value)
    assert "001_noop.sql" in msg
    assert stored_sha in msg
    assert _sha256_of(sql_body) in msg
    assert "DELETE FROM schema_migrations" in msg
    # No migration body ran, no new tracking row inserted.
    assert fake.migrations_executed == []
    assert fake.inserts == []


def test_apply_all_aborts_on_sql_error_no_partial():
    """First file applies fine, second file has bad SQL: MigrationError
    raised, second file's tracking row NOT inserted, rollback fired."""
    good_sql = "CREATE TABLE test_good (id INT);"
    bad_sql = "CREATE TABLE test_bad (id INT); SELECT nonexistent();"

    pg_error = Exception("function nonexistent() does not exist")
    fake = _FakeConn(applied={}, bad_sqls={"nonexistent": pg_error})

    files = (
        ("001_good.sql", good_sql),
        ("002_bad.sql", bad_sql),
    )

    with _fixture_migrations(*files) as mig_dir, \
         patch("config.migration_runner.psycopg2.connect", return_value=fake):
        from config.migration_runner import run_pending_migrations, MigrationError

        with pytest.raises(MigrationError) as exc_info:
            run_pending_migrations("postgres://fake", migrations_dir=mig_dir)

    assert "002_bad.sql" in str(exc_info.value)
    # Good file's tracking row DID land (committed before the bad file failed).
    assert ("001_good.sql", _sha256_of(good_sql)) in fake.inserts
    # Bad file's tracking row did NOT.
    assert not any(name == "002_bad.sql" for (name, _) in fake.inserts)
    assert fake.rollbacks >= 1


# ===========================================================================
# Test #5: startup ordering (N1 — Mock manager, NOT AST)
# ===========================================================================


def test_startup_call_order():
    """``outputs.dashboard.startup`` must call ``_init_store`` before
    ``_run_migrations`` before ``_start_scheduler``. Asserted via a Mock
    manager's ``mock_calls`` list — survives whitespace reformats and
    async-body restructuring (brief §N1)."""
    import asyncio

    manager = Mock()
    with patch("outputs.dashboard._init_store") as m_init, \
         patch("outputs.dashboard._run_migrations") as m_migrate, \
         patch("outputs.dashboard._ensure_vault_mirror") as m_vault, \
         patch("outputs.dashboard._start_scheduler") as m_start:
        manager.attach_mock(m_init, "init")
        manager.attach_mock(m_migrate, "migrate")
        manager.attach_mock(m_vault, "vault")
        manager.attach_mock(m_start, "start")

        from outputs.dashboard import startup
        asyncio.run(startup())

    assert manager.mock_calls == [
        call.init(), call.migrate(), call.vault(), call.start(),
    ]


# ===========================================================================
# Test #7: migration file has UP marker (pure, unconditional)
# ===========================================================================


def test_migration_file_has_up_marker():
    """Every ``migrations/*.sql`` file outside ``_GRANDFATHERED`` must begin
    with the ``-- == migrate:up ==`` marker on some line. Enforced as CI
    gate per brief §R3. Grandfather list retires in the follow-up PR that
    rewrites those two files with markers."""
    from config.migration_runner import _GRANDFATHERED

    up_marker = re.compile(r"^\s*--\s*==\s*migrate:up\s*==\s*$", re.MULTILINE)
    mig_dir = pathlib.Path(__file__).resolve().parents[1] / "migrations"
    assert mig_dir.is_dir(), f"migrations dir not found at {mig_dir}"

    missing: list[str] = []
    for p in sorted(mig_dir.glob("*.sql")):
        if p.name in _GRANDFATHERED:
            continue
        if not up_marker.search(p.read_text()):
            missing.append(p.name)

    assert not missing, (
        f"migration files missing '-- == migrate:up ==' marker: {missing}. "
        f"All NEW migrations must include UP/DOWN section markers."
    )


# ===========================================================================
# Tests #6, #8: live-PG tests via ``needs_live_pg`` fixture
# (see ``tests/conftest.py`` — TEST_DATABASE_URL or ephemeral Neon branch)
# ===========================================================================


def test_first_deploy_idempotency_dry_run(needs_live_pg):
    """R2 dry-run: seeded-to-current-prod Neon branch + empty
    ``schema_migrations`` must re-apply all 11 files cleanly with zero
    errors. Each file's ``IF NOT EXISTS`` / ``IF EXISTS`` / ``ON CONFLICT
    DO NOTHING`` semantics turn a retroactive re-apply into a no-op DDL
    sequence; the only actual writes are the 11 tracking-table inserts."""
    import psycopg2

    from config.migration_runner import run_pending_migrations

    repo_mig_dir = str(pathlib.Path(__file__).resolve().parents[1] / "migrations")
    expected_files = sorted(
        p.name for p in pathlib.Path(repo_mig_dir).glob("*.sql")
    )
    assert len(expected_files) >= 11, (
        f"expected ≥11 migrations on-disk, got {len(expected_files)}"
    )

    # Pre-clean: drop schema_migrations so we exercise the first-deploy path.
    with psycopg2.connect(needs_live_pg) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS schema_migrations")
        conn.commit()

    applied = run_pending_migrations(needs_live_pg, migrations_dir=repo_mig_dir)
    assert sorted(applied) == expected_files, (
        f"retroactive claim drift: applied={sorted(applied)} vs "
        f"expected={expected_files}"
    )

    # Verify tracking table now has exactly those rows.
    with psycopg2.connect(needs_live_pg) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM schema_migrations ORDER BY filename")
            rows = [r[0] for r in cur.fetchall()]
    assert rows == expected_files


def test_second_instance_blocks_on_advisory_lock(needs_live_pg):
    """R1 concurrency contract: sidecar connection holds the advisory lock,
    runner's ``pg_try_advisory_lock`` path times out, graceful
    ``return []`` fires, no DDL runs, no tracking-table writes."""
    import psycopg2

    from config.migration_runner import (
        _MIGRATION_LOCK_KEY,
        run_pending_migrations,
    )

    sql_body = "CREATE TABLE IF NOT EXISTS test_advisory_noop (id INT);"
    files = (("001_advisory.sql", sql_body),)

    # Pre-clean tracking table row for this test fixture.
    with psycopg2.connect(needs_live_pg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM schema_migrations WHERE filename = %s",
                ("001_advisory.sql",),
            )
        conn.commit()

    blocker = psycopg2.connect(needs_live_pg)
    blocker.autocommit = True
    try:
        with blocker.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,))

        with _fixture_migrations(*files) as mig_dir, \
             patch("config.migration_runner._LOCK_TIMEOUT_SECONDS", 2.0):
            result = run_pending_migrations(needs_live_pg, migrations_dir=mig_dir)

        assert result == [], f"expected graceful empty result, got {result}"

        # Verify no tracking row landed for the fixture file.
        with psycopg2.connect(needs_live_pg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE filename = %s",
                    ("001_advisory.sql",),
                )
                assert cur.fetchone() is None
    finally:
        with blocker.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
        blocker.close()
