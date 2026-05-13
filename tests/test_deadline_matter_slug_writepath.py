"""DEADLINE_MATTER_SLUG_BACKFILL_1 — Scope A write-path closure tests.

Verifies that the 3 previously-bypassed write-paths now propagate matter_slug
into the deadlines row:

  A1. models.deadlines.insert_deadline(matter_slug=...)        — round-trip
  A2. models.cortex.cortex_create_deadline(matter_slug=...)    — pass-through
  A3. orchestrator.pipeline._match_matter_slug + slug_registry — integration shape

Backward-compat (no matter_slug arg) leaves the column NULL — that path is
exercised separately.

Live-PG tests gate on the standard conftest ``needs_live_pg`` fixture; with no
TEST_DATABASE_URL and no Neon CI vars they skip cleanly. Test 4 (classifier
shape) is pure-unit and always runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import psycopg2
import psycopg2.pool
import pytest


# ---------------------------------------------------------------------------
# Live-PG fixture: redirect models.deadlines._pool to the test DSN and
# bootstrap the deadlines table schema.
# ---------------------------------------------------------------------------


@pytest.fixture
def deadlines_pg(needs_live_pg, monkeypatch):
    """Point ``models.deadlines`` at the live test DB + create the table."""
    import models.deadlines as md

    test_pool = psycopg2.pool.SimpleConnectionPool(
        minconn=1, maxconn=3, dsn=needs_live_pg
    )
    monkeypatch.setattr(md, "_pool", test_pool)

    md.ensure_tables()

    # Clean any pre-existing deadlines row that would collide with our inserts.
    conn = test_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM deadlines WHERE source_id LIKE 'matter-slug-writepath-test:%%'"
        )
        conn.commit()
        cur.close()
    finally:
        test_pool.putconn(conn)

    yield test_pool

    # Best-effort teardown — drop the test rows + close the pool.
    try:
        conn = test_pool.getconn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM deadlines WHERE source_id LIKE 'matter-slug-writepath-test:%%'"
        )
        conn.commit()
        cur.close()
        test_pool.putconn(conn)
    finally:
        try:
            test_pool.closeall()
        except Exception:
            pass


def _due_date() -> datetime:
    return datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc)


def _select_matter_slug(test_pool, deadline_id: int):
    conn = test_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT matter_slug FROM deadlines WHERE id = %s", (deadline_id,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    finally:
        test_pool.putconn(conn)


# ---------------------------------------------------------------------------
# T1 — insert_deadline(matter_slug=...) round-trip
# ---------------------------------------------------------------------------


def test_insert_deadline_matter_slug_roundtrip(deadlines_pg):
    from models.deadlines import insert_deadline

    dl_id = insert_deadline(
        description="round-trip test deadline (cupial)",
        due_date=_due_date(),
        source_type="test",
        confidence="high",
        source_id="matter-slug-writepath-test:t1",
        source_snippet="t1",
        matter_slug="cupial",
    )
    assert dl_id is not None, "insert_deadline should return an id"
    assert _select_matter_slug(deadlines_pg, dl_id) == "cupial"


# ---------------------------------------------------------------------------
# T2 — insert_deadline() backward-compat: no matter_slug → NULL
# ---------------------------------------------------------------------------


def test_insert_deadline_without_matter_slug_is_null(deadlines_pg):
    from models.deadlines import insert_deadline

    dl_id = insert_deadline(
        description="backward-compat test deadline (no slug)",
        due_date=_due_date(),
        source_type="test",
        confidence="high",
        source_id="matter-slug-writepath-test:t2",
        source_snippet="t2",
        # matter_slug intentionally omitted
    )
    assert dl_id is not None
    assert _select_matter_slug(deadlines_pg, dl_id) is None


# ---------------------------------------------------------------------------
# T3 — cortex_create_deadline propagates matter_slug through to the row
# ---------------------------------------------------------------------------


def test_cortex_create_deadline_propagates_matter_slug(deadlines_pg):
    from models.cortex import cortex_create_deadline

    dl_id = cortex_create_deadline(
        description="cortex pass-through test (hagenauer)",
        due_date=_due_date(),
        source_type="test",
        source_agent="test-agent",
        confidence="medium",
        source_id="matter-slug-writepath-test:t3",
        source_snippet="t3",
        matter_slug="hagenauer-rg7",
    )
    assert dl_id is not None
    assert _select_matter_slug(deadlines_pg, dl_id) == "hagenauer-rg7"


# ---------------------------------------------------------------------------
# T4 — classifier → slug_registry.normalize integration shape (pure unit)
# ---------------------------------------------------------------------------


def test_match_matter_slug_then_normalize_resolves_to_canonical():
    """Mirrors the call pattern wired into baker_mcp + clickup_trigger.

    _match_matter_slug returns the matter_name (which may be a free-form
    label like 'Cupial'); slug_registry.normalize() resolves that label to
    a canonical slug or None.
    """
    from orchestrator.pipeline import _match_matter_slug
    from kbl import slug_registry

    store = MagicMock()
    # Shape returned by SentinelStoreBack.get_matters(status='active').
    store.get_matters.return_value = [
        {
            "matter_name": "Cupial",
            "keywords": ["cupial", "handover"],
            "people": [],
        }
    ]

    matter_name = _match_matter_slug(
        "Cupial handover top 4 schlussabrechnung",
        "",
        store,
    )
    assert matter_name == "Cupial"
    assert slug_registry.normalize(matter_name) == "cupial"

    # None pass-through: no match → None → normalize(None) → None.
    store.get_matters.return_value = []
    assert _match_matter_slug("anything", "anything", store) is None
    assert slug_registry.normalize(None) is None
