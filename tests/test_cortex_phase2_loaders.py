"""Tests for orchestrator/cortex_phase2_loaders.py — vault readers + recent-
activity SQL coverage for sub-brief CORTEX_3T_FORMALIZE_1A.

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1A.md``.

Test strategy: tmp_path for the vault tree, captured-SQL stubs for the
DB. Includes Lesson #42 SQL-assertion tests verifying the EXPLORE-
corrected canonical column references (sent_emails.body_preview, NOT
body; signal_queue.primary_matter JOIN, NOT email_messages.primary_matter).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from orchestrator import cortex_phase2_loaders as loaders


# --------------------------------------------------------------------------
# Vault fixture — full tree under tmp_path
# --------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Build a baker-vault skeleton at tmp_path with seed cortex content."""
    root = tmp_path / "baker-vault"
    matter = root / "wiki" / "matters" / "oskolkov"
    matter.mkdir(parents=True)
    cortex = root / "wiki" / "_cortex"
    cortex.mkdir(parents=True)

    (matter / "cortex-config.md").write_text("# Oskolkov system prompt\n")
    (matter / "state.md").write_text("# Current state\n")
    (matter / "proposed-gold.md").write_text("# Proposed Gold\n")

    curated = matter / "curated"
    curated.mkdir()
    (curated / "a-finance.md").write_text("# Finance notes\n")
    (curated / "b-legal.md").write_text("# Legal notes\n")

    (cortex / "director-gold-global.md").write_text("# Director gold\n")
    (cortex / "cross-matter-patterns.md").write_text("# Cross-matter\n")
    (cortex / "brisen-style.md").write_text("# Style\n")

    monkeypatch.setenv("BAKER_VAULT_PATH", str(root))
    return root


# --------------------------------------------------------------------------
# DB stubs (mirrors tests/test_capability_threads.py shape)
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows_by_substring: dict[str, list] | None = None):
        self.queries: list[tuple] = []
        self._rows_by_substring = rows_by_substring or {}
        self._last_rows: list = []
        self.rowcount = 0

    def execute(self, q, params=None):
        self.queries.append((q, params))
        # Return rows when SQL contains a configured substring
        self._last_rows = []
        for sub, rows in self._rows_by_substring.items():
            if sub in q:
                self._last_rows = rows
                break

    def fetchone(self):
        return self._last_rows[0] if self._last_rows else None

    def fetchall(self):
        return list(self._last_rows)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur=None):
        self.cur = cur or _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakeStore:
    def __init__(self, conn=None):
        self.conn = conn
        self.put_count = 0
        self.last_returned = None

    def _get_conn(self):
        self.last_returned = self.conn
        return self.conn

    def _put_conn(self, c):
        self.put_count += 1


@pytest.fixture
def patch_store(monkeypatch):
    """Replace ``loaders._get_store`` with a configurable fake.

    Patching the loaders module's own helper avoids the whole
    ``memory.store_back`` attribute-pollution class of issues that bites
    when earlier tests in the suite have already imported the real class
    (full-suite test ordering can vary; the loader-level patch is stable).
    """
    holder = {"store": _FakeStore(_FakeConn())}
    monkeypatch.setattr(loaders, "_get_store", lambda: holder["store"])

    def _set(store):
        holder["store"] = store

    return _set, holder


# ==========================================================================
# 1. Vault readers
# ==========================================================================


def test_vault_unavailable_returns_warning_and_empty_vault_keys(monkeypatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", "/nonexistent/path")
    # Need a fake store so recent_activity doesn't hit a real connection
    holder_store = _FakeStore(None)
    monkeypatch.setattr(loaders, "_get_store", lambda: holder_store)

    out = asyncio.run(loaders.load_phase2_context("oskolkov"))
    assert out["vault_available"] is False
    assert out["matter_config"] == ""
    assert out["state"] == ""
    assert out["curated"] == {}
    assert out["cortex_meta"] == {}
    # recent_activity is still attempted (even if empty)
    assert "recent_activity" in out


def test_vault_present_but_matter_dir_missing(vault, monkeypatch, patch_store):
    """Vault exists, _cortex/ has files, but matter dir absent → matter keys
    empty but cortex_meta still loads."""
    set_store, holder = patch_store
    set_store(_FakeStore(_FakeConn()))

    out = asyncio.run(loaders.load_phase2_context("missing-matter"))
    assert out["vault_available"] is True
    assert out["matter_config"] == ""
    assert out["state"] == ""
    assert out["curated"] == {}
    # _cortex meta IS loaded even when matter dir missing
    assert "Director gold" in out["cortex_meta"]["director_gold_global"]


def test_load_phase2_context_happy_path(vault, monkeypatch, patch_store):
    set_store, holder = patch_store
    set_store(_FakeStore(_FakeConn()))

    out = asyncio.run(loaders.load_phase2_context("oskolkov"))
    assert out["vault_available"] is True
    assert "Oskolkov system prompt" in out["matter_config"]
    assert "Current state" in out["state"]
    assert "Proposed Gold" in out["proposed_gold"]
    assert set(out["curated"].keys()) == {"a-finance.md", "b-legal.md"}
    assert "Director gold" in out["cortex_meta"]["director_gold_global"]


def test_read_or_empty_caps_at_max_bytes(tmp_path):
    big = tmp_path / "big.md"
    big.write_text("x" * 250_000)
    out = loaders._read_or_empty(big, max_bytes=200_000)
    assert len(out) == 200_000


def test_read_or_empty_returns_empty_for_missing(tmp_path):
    assert loaders._read_or_empty(tmp_path / "nope.md") == ""


def test_load_curated_dir_alphabetical(tmp_path):
    cur = tmp_path / "curated"
    cur.mkdir()
    (cur / "z.md").write_text("zee")
    (cur / "a.md").write_text("ay")
    (cur / "m.md").write_text("em")
    out = loaders._load_curated_dir(cur)
    assert list(out.keys()) == ["a.md", "m.md", "z.md"]


def test_load_curated_dir_empty_when_missing(tmp_path):
    assert loaders._load_curated_dir(tmp_path / "nope") == {}


def test_load_cortex_meta_returns_three_keys(tmp_path):
    cortex_dir = tmp_path / "wiki" / "_cortex"
    cortex_dir.mkdir(parents=True)
    (cortex_dir / "director-gold-global.md").write_text("g")
    (cortex_dir / "cross-matter-patterns.md").write_text("c")
    (cortex_dir / "brisen-style.md").write_text("s")
    out = loaders._load_cortex_meta(tmp_path)
    assert set(out.keys()) == {"director_gold_global", "cross_matter_patterns", "brisen_style"}


# ==========================================================================
# 2. Recent-activity SQL (Lesson #42 SQL-assertion coverage)
# ==========================================================================


def test_recent_activity_uses_body_preview_not_body(vault, patch_store):
    """SQL-assertion: sent_emails query references body_preview (the canonical
    column verified by EXPLORE), NOT body or full_body."""
    set_store, holder = patch_store
    cur = _FakeCursor()
    set_store(_FakeStore(_FakeConn(cur)))

    asyncio.run(loaders._load_recent_activity("oskolkov", 14))

    sent_email_sql = next(
        (q[0] for q in cur.queries if "FROM sent_emails" in q[0]),
        None,
    )
    assert sent_email_sql is not None
    assert "body_preview" in sent_email_sql
    # Must NOT reference the columns the brief snippet (incorrectly) had
    assert "WHERE created_at" in sent_email_sql
    assert " body " not in sent_email_sql  # bare 'body' column reference would fail


def test_recent_activity_joins_signal_queue_for_email_messages(vault, patch_store):
    """SQL-assertion: email_messages has no primary_matter — Phase 2 must JOIN
    through signal_queue (which carries the column per migration 20260418)."""
    set_store, holder = patch_store
    cur = _FakeCursor()
    set_store(_FakeStore(_FakeConn(cur)))

    asyncio.run(loaders._load_recent_activity("oskolkov", 14))

    em_sql = next(
        (q[0] for q in cur.queries if "FROM email_messages" in q[0]),
        None,
    )
    assert em_sql is not None
    assert "JOIN signal_queue" in em_sql
    assert "sq.primary_matter" in em_sql


def test_recent_activity_baker_actions_query_present(vault, patch_store):
    set_store, holder = patch_store
    cur = _FakeCursor()
    set_store(_FakeStore(_FakeConn(cur)))

    asyncio.run(loaders._load_recent_activity("oskolkov", 14))

    ba_sql = next(
        (q[0] for q in cur.queries if "FROM baker_actions" in q[0]),
        None,
    )
    assert ba_sql is not None
    assert "target_task_id" in ba_sql
    assert "payload::text" in ba_sql


def test_all_recent_activity_queries_have_limit(vault, patch_store):
    """Lesson #1: every SELECT must have a LIMIT clause."""
    set_store, holder = patch_store
    cur = _FakeCursor()
    set_store(_FakeStore(_FakeConn(cur)))

    asyncio.run(loaders._load_recent_activity("oskolkov", 14))
    for sql, _ in cur.queries:
        if sql.strip().upper().startswith("SELECT"):
            assert "LIMIT" in sql.upper(), f"unbounded SELECT: {sql[:120]}..."


def test_recent_activity_no_db_returns_empty_lists(vault, patch_store):
    """Graceful: if _get_conn returns None, function returns empty lists."""
    set_store, holder = patch_store
    set_store(_FakeStore(None))  # _get_conn returns None

    out = asyncio.run(loaders._load_recent_activity("oskolkov", 14))
    assert out == {"director_outbound": [], "entity_inbound": [], "baker_actions": []}


def test_recent_activity_handles_db_exception_gracefully(vault, patch_store):
    """Graceful: cursor.execute raising → empty lists, rollback called."""
    set_store, holder = patch_store

    class _Raising(_FakeCursor):
        def execute(self, q, params=None):
            super().execute(q, params)
            raise RuntimeError("db connection dropped")

    cur = _Raising()
    conn = _FakeConn(cur)
    set_store(_FakeStore(conn))

    out = asyncio.run(loaders._load_recent_activity("oskolkov", 14))
    assert out == {"director_outbound": [], "entity_inbound": [], "baker_actions": []}
    assert conn.rolled_back is True


def test_recent_activity_serializes_datetimes_to_isoformat(vault, patch_store):
    """Datetime column values must be ISO-8601 strings in the output dicts
    (so they round-trip through json.dumps for the cortex_phase_outputs payload)."""
    from datetime import datetime, timezone

    sample_dt = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    set_store, holder = patch_store
    cur = _FakeCursor(rows_by_substring={
        "FROM sent_emails": [("subj", "to@x.com", sample_dt)],
        "FROM email_messages": [("inbound", "from@x.com", sample_dt)],
        "FROM baker_actions": [("act", "task-1", sample_dt)],
    })
    set_store(_FakeStore(_FakeConn(cur)))

    out = asyncio.run(loaders._load_recent_activity("oskolkov", 14))
    assert out["director_outbound"][0]["created_at"] == "2026-04-28T12:00:00+00:00"
    assert out["entity_inbound"][0]["received_at"] == "2026-04-28T12:00:00+00:00"
    assert out["baker_actions"][0]["created_at"] == "2026-04-28T12:00:00+00:00"
