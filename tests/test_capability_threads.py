"""BRIEF_CAPABILITY_THREADS_1 tests — unit + integration.

Unit tests (no DB):
  * entity extractor — PM_REGISTRY pattern match behaviour
  * scoring helpers — Jaccard, recency half-life, combined scorer
  * topic_summary — truncation + newline handling
  * SQL-assertion — stitcher creates threads with Python uuid4 (not pgcrypto)

Integration tests (require live PG via ``needs_live_pg`` fixture, per
``tests/conftest.py`` convention — skip cleanly when TEST_DATABASE_URL +
NEON_API_KEY both absent):
  * DDL smoke — capability_threads + capability_turns tables exist;
    pm_state_history.thread_id column present.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


# ─── Unit: entity extractor ───

def test_extract_entity_cluster_ao_pm_patterns():
    from orchestrator.capability_threads import extract_entity_cluster
    entities = extract_entity_cluster(
        question="What's the latest on Aukera and Patrick Zuchner?",
        answer="Patrick is escalating the release request to the AIFM trust body.",
        pm_slug="ao_pm",
    )
    # At least one pattern must match; the specific pattern key is opaque
    # (matches live PM_REGISTRY) so we only assert non-empty.
    assert isinstance(entities, dict)
    assert len(entities) >= 1


def test_extract_entity_cluster_unknown_pm_returns_empty():
    from orchestrator.capability_threads import extract_entity_cluster
    entities = extract_entity_cluster(
        question="Any Q at all",
        answer="Any A at all",
        pm_slug="__not_a_real_pm__",
    )
    assert entities == {}


# ─── Unit: scoring helpers ───

def test_score_candidate_weights():
    from orchestrator.capability_threads import _score_candidate
    # Entity overlap adds positive weight
    assert _score_candidate(0.8, 1.0, 1.0) > _score_candidate(0.8, 0.0, 1.0)
    # Recency multiplier — decaying recency lowers score
    assert _score_candidate(0.5, 1.0, 0.5) < _score_candidate(0.8, 1.0, 1.0)


def test_jaccard_overlap():
    from orchestrator.capability_threads import _jaccard_overlap
    assert _jaccard_overlap({"a": 1, "b": 2}, {"a": 1, "c": 3}) == pytest.approx(1 / 3)
    assert _jaccard_overlap({}, {}) == 0.0
    assert _jaccard_overlap({"x": 1}, {}) == 0.0


def test_recency_weight_now_is_one():
    from orchestrator.capability_threads import _recency_weight
    assert _recency_weight(datetime.now(timezone.utc)) == pytest.approx(1.0, rel=1e-3)


def test_recency_weight_half_life():
    from orchestrator.capability_threads import (
        _recency_weight,
        STITCH_RECENCY_DECAY_HOURS,
    )
    past = datetime.now(timezone.utc) - timedelta(hours=STITCH_RECENCY_DECAY_HOURS)
    assert _recency_weight(past) == pytest.approx(0.5, rel=0.05)


# ─── Unit: topic summary ───

def test_topic_summary_truncates():
    from orchestrator.capability_threads import _topic_summary
    s = _topic_summary("q" * 500, "a" * 500)
    assert len(s) <= 500


def test_topic_summary_strips_newlines():
    from orchestrator.capability_threads import _topic_summary
    s = _topic_summary("line1\nline2", "answer\n")
    assert "\n" not in s


# ─── Unit: surface-from-mutation-source mapping ───

def test_surface_from_mutation_source_known_sources():
    from orchestrator.capability_threads import surface_from_mutation_source
    assert surface_from_mutation_source("sidebar") == "sidebar"
    assert surface_from_mutation_source("decomposer") == "decomposer"
    assert surface_from_mutation_source("opus_auto") == "opus_auto"
    assert surface_from_mutation_source("pm_signal_whatsapp") == "signal"
    assert surface_from_mutation_source("pm_signal_email") == "signal"
    assert surface_from_mutation_source("agent_tool") == "agent_tool"
    assert surface_from_mutation_source("backfill_2026-04-24") == "backfill"
    assert surface_from_mutation_source("auto") == "other"
    assert surface_from_mutation_source("") == "other"


# ─── SQL-assertion: stitcher creates threads with Python uuid4 (not pgcrypto) ───

class _FakeCursor:
    def __init__(self):
        self.queries: list = []
        self._rows = [None]
        self.rowcount = 1

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchone(self):
        return self._rows[0]

    def close(self):
        pass


class _FakeConn:
    def cursor(self):
        return _FakeCursor()

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeStore:
    def _get_conn(self):
        return _FakeConn()

    def _put_conn(self, c):
        pass


def test_create_new_thread_uses_python_uuid_not_pgcrypto():
    """Guardrail: stitcher generates UUIDs in Python (uuid.uuid4) — never calls
    ``gen_random_uuid()`` which would require the pgcrypto extension (NOT
    installed on Neon per the design premise verified 2026-04-24)."""
    from orchestrator.capability_threads import _create_new_thread
    tid, dec = _create_new_thread(
        _FakeStore(), "ao_pm", "summary", {}, reason="test"
    )
    assert isinstance(tid, str)
    uuid.UUID(tid)  # raises if not a valid UUID
    assert dec["matched_on"] == "new_thread"
    assert dec["reason"] == "test"


# ─── Integration: DDL smoke (per lesson #42 — fixture-only can miss schema drift) ───

def test_capability_threads_ddl_applied(needs_live_pg):
    """Schema-smoke: confirms migration ran and additive column is present."""
    import psycopg2
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_name IN ('capability_threads', 'capability_turns')
            ORDER BY table_name
            """
        )
        tables = [r[0] for r in cur.fetchall()]
        assert tables == ["capability_threads", "capability_turns"]
        cur.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'pm_state_history' AND column_name = 'thread_id'
            """
        )
        row = cur.fetchone()
        assert row is not None
        assert row[1] == "uuid"
    finally:
        conn.close()
