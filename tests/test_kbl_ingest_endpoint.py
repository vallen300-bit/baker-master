"""Tests for kbl/ingest_endpoint.py.

Hermetic where possible: in-memory sqlite3 mirrors wiki_pages +
baker_actions schemas. Qdrant and Voyage are stubbed. Gold mirror
writes to a tmp_path fixture dir.

Atomicity tests use the same monkeypatch-context-manager pattern as
test_ledger_atomic.py — swap the ledger helper with a fail-on-exit
variant to simulate transaction failure.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
import pytest

# Ensure BAKER_VAULT_PATH is set before slug_registry import path is exercised.
# test_validate_slug_in_registry_rejects_unknown_matter triggers is_canonical
# which loads slugs.yml from the vault. Set a reasonable default so the test
# works both locally and in CI.
os.environ.setdefault("BAKER_VAULT_PATH", "/Users/dimitry/baker-vault")

import kbl.ingest_endpoint as mod
from kbl.ingest_endpoint import (
    IngestResult,
    KBLIngestError,
    ingest,
    validate_frontmatter,
    validate_slug_in_registry,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def sqlite_conn():
    """In-memory sqlite3 with wiki_pages + baker_actions tables."""
    c = sqlite3.connect(":memory:")
    c.isolation_level = ""  # explicit txn — mirrors psycopg2 default
    cur = c.cursor()
    cur.execute("""
        CREATE TABLE wiki_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            agent_owner TEXT,
            page_type TEXT NOT NULL,
            matter_slugs TEXT,
            backlinks TEXT,
            generation INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    """)
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
    c.commit()
    cur.close()
    yield c
    c.close()


@pytest.fixture
def fake_store(sqlite_conn, monkeypatch):
    """SentinelStoreBack stand-in exposing _get_conn / _put_conn."""
    class _FakeStore:
        def _get_conn(self):
            return sqlite_conn
        def _put_conn(self, _):
            pass
    fake = _FakeStore()

    # Stub SentinelStoreBack._get_global_instance for modules that look it up.
    import memory.store_back as sb_mod
    monkeypatch.setattr(sb_mod.SentinelStoreBack, "_get_global_instance",
                        classmethod(lambda cls: fake), raising=False)
    return fake


def _pg_to_sqlite(sql: str) -> str:
    """Translate Postgres dialect snippets to sqlite equivalents.

    Scoped to what `ingest()`'s wiki_pages UPSERT actually emits — not
    a general translator.
    """
    return sql.replace("%s", "?").replace("NOW()", "CURRENT_TIMESTAMP")


def _serialize_params(params):
    """Postgres psycopg2 accepts Python lists for TEXT[] columns; sqlite
    wants scalars. JSON-encode list/dict values for sqlite fidelity."""
    if params is None:
        return params
    out = []
    for p in params:
        if isinstance(p, (list, dict)):
            out.append(json.dumps(p))
        else:
            out.append(p)
    return tuple(out) if isinstance(params, tuple) else out


class _TranslatingCursor:
    """Wraps a real sqlite3.Cursor and translates Postgres→sqlite on execute.

    Python 3.12 makes sqlite3.Cursor immutable — we can't monkeypatch its
    execute method directly (TypeError: cannot set 'execute' attribute of
    immutable type 'sqlite3.Cursor'). So we wrap and delegate instead.
    """
    def __init__(self, real):
        self._real = real

    def execute(self, sql, params=()):
        return self._real.execute(_pg_to_sqlite(sql), _serialize_params(params))

    def executemany(self, sql, seq):
        return self._real.executemany(
            _pg_to_sqlite(sql), [_serialize_params(p) for p in seq]
        )

    def fetchone(self):
        return self._real.fetchone()

    def fetchall(self):
        return self._real.fetchall()

    def close(self):
        return self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def patch_ledger(monkeypatch):
    """Swap invariant_checks.ledger_atomic.atomic_director_action for a
    sqlite-compatible variant. Yields a translating cursor wrapper so the
    wiki_pages INSERT (psycopg2-style `%s` placeholders) lands correctly."""
    @contextmanager
    def _sqlite_cm(conn, action_type, payload=None, trigger_source=None,
                    target_task_id=None, target_space_id=None):
        cur = conn.cursor()
        wrapped = _TranslatingCursor(cur)
        try:
            yield wrapped
            cur.execute(
                "INSERT INTO baker_actions "
                "(action_type, target_task_id, target_space_id, payload, "
                " trigger_source, success, error_message) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL)",
                (
                    action_type,
                    target_task_id,
                    target_space_id,
                    json.dumps(payload) if payload else None,
                    trigger_source,
                ),
            )
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            try: cur.close()
            except Exception: pass

    import invariant_checks.ledger_atomic as la
    monkeypatch.setattr(la, "atomic_director_action", _sqlite_cm)
    yield _sqlite_cm


@pytest.fixture
def patch_vector(monkeypatch):
    """No-op _upsert_vector to avoid Qdrant + Voyage dependencies."""
    monkeypatch.setattr(mod, "_upsert_vector", lambda *a, **kw: None)


@pytest.fixture
def valid_matter_fm():
    return {
        "type": "matter",
        "slug": "hagenauer-rg7",  # Real slug from slugs.yml v9
        "name": "Hagenauer RG7",
        "updated": "2026-04-23",
        "author": "agent",
        "tags": [],
        "related": [],
    }


# ─── Validation tests ─────────────────────────────────────────────────────

def test_validate_frontmatter_happy(valid_matter_fm):
    validate_frontmatter(valid_matter_fm)  # no raise


@pytest.mark.parametrize("mutate,key", [
    (lambda fm: fm.pop("type"), "type"),
    (lambda fm: fm.pop("slug"), "slug"),
    (lambda fm: fm.pop("tags"), "tags"),
])
def test_validate_frontmatter_missing_required_key(valid_matter_fm, mutate, key):
    mutate(valid_matter_fm)
    with pytest.raises(KBLIngestError, match="missing required keys"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_bad_type(valid_matter_fm):
    valid_matter_fm["type"] = "thing"
    with pytest.raises(KBLIngestError, match="type must be"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_bad_slug_format(valid_matter_fm):
    valid_matter_fm["slug"] = "Hagenauer_RG7"  # underscore + caps = bad
    with pytest.raises(KBLIngestError, match="kebab-case"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_person_slug_must_be_firstname_lastname(valid_matter_fm):
    valid_matter_fm["type"] = "person"
    valid_matter_fm["slug"] = "ao"  # single-token fails person rule
    with pytest.raises(KBLIngestError, match="firstname-lastname"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_bad_date(valid_matter_fm):
    valid_matter_fm["updated"] = "23 April 2026"
    with pytest.raises(KBLIngestError, match="updated must be YYYY-MM-DD"):
        validate_frontmatter(valid_matter_fm)


def test_validate_slug_in_registry_rejects_unknown_matter(valid_matter_fm):
    valid_matter_fm["slug"] = "nonexistent-matter"
    # validate_frontmatter passes format checks; registry check rejects.
    validate_frontmatter(valid_matter_fm)
    with pytest.raises(KBLIngestError, match="not in slugs.yml registry"):
        validate_slug_in_registry(valid_matter_fm)


# ─── Ingest-flow tests ────────────────────────────────────────────────────

def test_ingest_happy_path(
    fake_store, sqlite_conn, patch_ledger, patch_vector,
    valid_matter_fm,
):
    result = ingest(
        frontmatter=valid_matter_fm,
        body="Body content.",
        trigger_source="test",
        store=fake_store,
    )
    assert isinstance(result, IngestResult)
    assert result.slug == "hagenauer-rg7"
    assert result.wiki_page_id > 0
    assert result.gold_mirrored is False

    cur = sqlite_conn.cursor()
    cur.execute("SELECT slug, title, agent_owner, page_type FROM wiki_pages")
    row = cur.fetchone()
    assert row == ("hagenauer-rg7", "Hagenauer RG7", "agent", "kbl_matter")
    cur.execute("SELECT COUNT(*) FROM baker_actions")
    assert cur.fetchone()[0] == 1


def test_ingest_validation_failure_no_writes(
    fake_store, sqlite_conn, patch_ledger, patch_vector, valid_matter_fm,
):
    valid_matter_fm["type"] = "bogus"
    with pytest.raises(KBLIngestError):
        ingest(valid_matter_fm, "body", store=fake_store)
    cur = sqlite_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM wiki_pages")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM baker_actions")
    assert cur.fetchone()[0] == 0


def test_ingest_upsert_bumps_generation(
    fake_store, sqlite_conn, patch_ledger, patch_vector,
    valid_matter_fm,
):
    ingest(valid_matter_fm, "first", store=fake_store)
    ingest(valid_matter_fm, "second", store=fake_store)
    cur = sqlite_conn.cursor()
    cur.execute("SELECT generation, content FROM wiki_pages WHERE slug = 'hagenauer-rg7'")
    row = cur.fetchone()
    assert row[0] == 2
    assert "second" in row[1]


def test_ingest_gold_voice_writes_mirror(
    fake_store, sqlite_conn, patch_ledger, patch_vector,
    valid_matter_fm, tmp_path,
):
    valid_matter_fm["voice"] = "gold"
    result = ingest(
        valid_matter_fm, "gold body", store=fake_store,
        mirror_root=tmp_path,
    )
    assert result.gold_mirrored is True
    target = tmp_path / "hagenauer-rg7.md"
    assert target.exists()
    content = target.read_text()
    assert "gold body" in content
    assert "voice: gold" in content


def test_ingest_silver_voice_no_mirror(
    fake_store, sqlite_conn, patch_ledger, patch_vector,
    valid_matter_fm, tmp_path,
):
    result = ingest(
        valid_matter_fm, "silver body", store=fake_store,
        mirror_root=tmp_path,
    )
    assert result.gold_mirrored is False
    assert list(tmp_path.iterdir()) == []


def test_ingest_atomic_rollback_on_ledger_failure(
    fake_store, sqlite_conn, patch_vector,
    valid_matter_fm, monkeypatch,
):
    """Simulate ledger-write failure inside the atomic block → wiki_pages rolls back too."""

    @contextmanager
    def _failing_cm(conn, *a, **kw):
        cur = conn.cursor()
        wrapped = _TranslatingCursor(cur)
        try:
            yield wrapped
            raise sqlite3.OperationalError("simulated ledger failure")
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            cur.close()

    import invariant_checks.ledger_atomic as la
    monkeypatch.setattr(la, "atomic_director_action", _failing_cm)

    with pytest.raises(RuntimeError, match="atomic write failed"):
        ingest(valid_matter_fm, "doomed", store=fake_store)

    cur = sqlite_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM wiki_pages")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM baker_actions")
    assert cur.fetchone()[0] == 0
