"""DASHBOARD_ALERT_NOISE_FIX_1 — Slice A acceptance tests.

Slice A scope (proactive_pm_sentinel.py + last_turn_direction migration):
  - Fix 1: quiet-thread upsert (<=1 pending card per source_id) + auto-resolve
           when the thread becomes active again. Acknowledged/snoozed immune.
  - Fix 2: Director-outbound threads demote to tier 3 'awaiting_counterparty'.
           Direction prefers the durable last_turn_direction column; falls back
           to the topic_summary marker when the column is NULL.

Live-PG gated via the shared ``needs_live_pg`` fixture (skips cleanly with no DB).
"""
from __future__ import annotations

import uuid

import psycopg2
import psycopg2.extras
import pytest


def _bootstrap_schema(dsn: str) -> None:
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                source TEXT,
                source_id TEXT,
                tier INTEGER,
                title TEXT,
                body TEXT,
                matter_slug TEXT,
                status TEXT DEFAULT 'pending',
                structured_actions JSONB,
                exit_reason TEXT,
                acknowledged_at TIMESTAMPTZ,
                snoozed_until TIMESTAMPTZ,
                resolved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS capability_threads (
                thread_id UUID PRIMARY KEY,
                pm_slug TEXT,
                topic_summary TEXT,
                last_turn_at TIMESTAMPTZ DEFAULT NOW(),
                status TEXT DEFAULT 'active',
                sla_hours INTEGER,
                last_turn_direction TEXT
            );
            """
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


class _Shim:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def _get_conn(self):
        return psycopg2.connect(self._dsn)

    def _put_conn(self, conn) -> None:
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


@pytest.fixture
def sentinel_store(needs_live_pg, monkeypatch):
    _bootstrap_schema(needs_live_pg)
    import memory.store_back as sb

    shim = _Shim(needs_live_pg)
    conn = shim._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE alerts, capability_threads RESTART IDENTITY")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    monkeypatch.setattr(
        sb.SentinelStoreBack, "_get_global_instance",
        classmethod(lambda cls: shim),
    )
    return shim


def _seed_thread(dsn, topic, hours_silent=72.0, status="active", sla_hours=None,
                 pm_slug="ao_pm", direction=None):
    tid = str(uuid.uuid4())
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO capability_threads
                (thread_id, pm_slug, topic_summary, last_turn_at, status,
                 sla_hours, last_turn_direction)
            VALUES (%s, %s, %s, NOW() - (%s || ' hours')::interval, %s, %s, %s)
            """,
            (tid, pm_slug, topic, str(hours_silent), status, sla_hours, direction),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return tid


def _pending_for(dsn, source_id):
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT id, tier, status, structured_actions FROM alerts "
            "WHERE source_id = %s AND status = 'pending'",
            (source_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def _status_of(dsn, alert_id):
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute("SELECT status, exit_reason FROM alerts WHERE id = %s", (alert_id,))
        row = cur.fetchone()
        cur.close()
        return row
    finally:
        conn.close()


# ─── Fix 1 ───

def test_upsert_one_card_per_thread(sentinel_store, needs_live_pg):
    """Run detect_quiet_threads twice → exactly 1 pending card (no duplicate)."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(needs_live_pg, "email: Counterparty — please advise")
    detect_quiet_threads()
    detect_quiet_threads()
    rows = _pending_for(needs_live_pg, tid)
    assert len(rows) == 1
    assert rows[0]["tier"] == 2
    assert rows[0]["structured_actions"]["trigger"] == "quiet_thread"


def test_auto_resolve_when_thread_active_again(sentinel_store, needs_live_pg):
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = str(uuid.uuid4())
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO capability_threads (thread_id, pm_slug, topic_summary, "
            "last_turn_at, status) VALUES (%s,'ao_pm','email: X — hi', NOW() - INTERVAL '1 hour','active')",
            (tid,),
        )
        cur.execute(
            "INSERT INTO alerts (source, source_id, tier, title, body, status, "
            "structured_actions, created_at) VALUES ('proactive_pm_sentinel',%s,2,'q','b','pending',"
            "'{\"trigger\":\"quiet_thread\"}'::jsonb, NOW() - INTERVAL '2 hours') RETURNING id",
            (tid,),
        )
        aid = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        conn.close()
    detect_quiet_threads()
    status, exit_reason = _status_of(needs_live_pg, aid)
    assert status == "resolved"
    assert exit_reason == "thread_active_again"


def test_acknowledged_thread_not_re_noised(sentinel_store, needs_live_pg):
    """An acknowledged quiet card blocks a fresh pending card for the same thread."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(needs_live_pg, "email: Counterparty — advise")
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO alerts (source, source_id, tier, title, body, status, "
            "acknowledged_at, structured_actions, created_at) VALUES "
            "('proactive_pm_sentinel',%s,2,'q','b','acknowledged', NOW(),"
            "'{\"trigger\":\"quiet_thread\"}'::jsonb, NOW())",
            (tid,),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    detect_quiet_threads()
    assert len(_pending_for(needs_live_pg, tid)) == 0, "acknowledged thread must not re-noise"


# ─── Fix 2 ───

def test_director_outbound_demoted_via_marker(sentinel_store, needs_live_pg):
    """topic_summary marker (column NULL) → tier 3 awaiting_counterparty."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(
        needs_live_pg, "whatsapp_outbound: Director outbound — Noted, locked in.",
        direction=None,
    )
    detect_quiet_threads()
    rows = _pending_for(needs_live_pg, tid)
    assert len(rows) == 1
    assert rows[0]["tier"] == 3
    assert rows[0]["structured_actions"]["trigger"] == "awaiting_counterparty"


def test_direction_column_takes_precedence(sentinel_store, needs_live_pg):
    """Durable column wins over the marker: column='inbound' on a thread whose
    topic still says 'outbound' → tier 2 (column is authoritative)."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(
        needs_live_pg,
        "whatsapp_outbound: Director outbound — stale text marker",
        direction="inbound",
    )
    detect_quiet_threads()
    rows = _pending_for(needs_live_pg, tid)
    assert len(rows) == 1
    assert rows[0]["tier"] == 2, "explicit inbound column must override the text marker"
    assert rows[0]["structured_actions"]["trigger"] == "quiet_thread"


def test_direction_column_outbound_demotes(sentinel_store, needs_live_pg):
    """Column='outbound' (no marker in topic) → tier 3 awaiting_counterparty."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(
        needs_live_pg, "email: Counterparty — plain inbound-looking text",
        direction="outbound",
    )
    detect_quiet_threads()
    rows = _pending_for(needs_live_pg, tid)
    assert len(rows) == 1
    assert rows[0]["tier"] == 3
    assert rows[0]["structured_actions"]["trigger"] == "awaiting_counterparty"
