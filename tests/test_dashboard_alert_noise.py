"""DASHBOARD_ALERT_NOISE_FIX_1 — acceptance tests.

Covers the done-rubric for the alert-noise fix:
  - Fix 1: quiet-thread upsert (≤1 pending card per source_id) + auto-resolve
           when the thread becomes active again.
  - Fix 2: Director-outbound threads demote to tier 3 'awaiting_counterparty'.
  - Fix 3: expire_stale_alerts flat-30d TTL; acknowledged/snoozed never expire.
  - Fix 4/5: business feed excludes infra sources + normalizes NULL matter to
             'unsorted'; system feed returns only infra.
  - Sweep: collapses the quiet flood + stale backlog, logs baker_actions,
           idempotent, never touches acknowledged/snoozed.

Live-PG gated via the shared ``needs_live_pg`` fixture (skips cleanly with no DB).
"""
from __future__ import annotations

import json
import uuid

import psycopg2
import psycopg2.extras
import pytest


# ─── schema bootstrap (minimal superset the fixed code touches) ───

def _bootstrap_alert_schema(dsn: str) -> None:
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
                tags JSONB DEFAULT '[]'::jsonb,
                exit_reason TEXT,
                dismiss_reason TEXT,
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
                entity_cluster JSONB DEFAULT '{}'::jsonb,
                last_turn_at TIMESTAMPTZ DEFAULT NOW(),
                status TEXT DEFAULT 'active',
                sla_hours INTEGER,
                turn_count INTEGER DEFAULT 0,
                started_at TIMESTAMPTZ DEFAULT NOW(),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS baker_actions (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                payload JSONB,
                trigger_source TEXT,
                success BOOLEAN,
                tier TEXT,
                committer_agent TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


class _Shim:
    """Connection shim bound to the test DSN (mirrors conftest._TestStore)."""

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
def alert_store(needs_live_pg, monkeypatch):
    """Bootstrap schema + redirect SentinelStoreBack._get_global_instance to a
    test-DSN shim. Truncates the three tables for isolation."""
    _bootstrap_alert_schema(needs_live_pg)
    import memory.store_back as sb

    shim = _Shim(needs_live_pg)
    conn = shim._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE alerts, capability_threads, baker_actions RESTART IDENTITY")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    # Bind the real store methods under test onto the shim (they only use
    # self._get_conn/_put_conn + module globals, so they work against the shim).
    for _m in ("get_pending_alerts", "sweep_alert_noise"):
        setattr(shim, _m, getattr(sb.SentinelStoreBack, _m).__get__(shim))
    monkeypatch.setattr(
        sb.SentinelStoreBack, "_get_global_instance",
        classmethod(lambda cls: shim),
    )
    return shim


# ─── seed helpers ───

def _seed_thread(dsn, topic, hours_silent=72.0, status="active", sla_hours=None,
                 pm_slug="ao_pm"):
    tid = str(uuid.uuid4())
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO capability_threads
                (thread_id, pm_slug, topic_summary, last_turn_at, status, sla_hours)
            VALUES (%s, %s, %s, NOW() - (%s || ' hours')::interval, %s, %s)
            """,
            (tid, pm_slug, topic, str(hours_silent), status, sla_hours),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return tid


def _seed_alert(dsn, **kw):
    cols = {
        "source": "proactive_pm_sentinel", "source_id": None, "tier": 2,
        "title": "t", "body": "b", "matter_slug": "ao_pm", "status": "pending",
        "structured_actions": json.dumps({"trigger": "quiet_thread"}),
        "age_days": 0, "acknowledged": False, "snoozed_hours": None,
    }
    cols.update(kw)
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alerts (source, source_id, tier, title, body, matter_slug,
                                status, structured_actions, created_at,
                                acknowledged_at, snoozed_until)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,
                    NOW() - (%s || ' days')::interval,
                    CASE WHEN %s THEN NOW() ELSE NULL END,
                    CASE WHEN %s IS NULL THEN NULL
                         ELSE NOW() + (%s || ' hours')::interval END)
            RETURNING id
            """,
            (cols["source"], cols["source_id"], cols["tier"], cols["title"],
             cols["body"], cols["matter_slug"], cols["status"],
             cols["structured_actions"], str(cols["age_days"]),
             cols["acknowledged"], cols["snoozed_hours"],
             str(cols["snoozed_hours"]) if cols["snoozed_hours"] is not None else None),
        )
        aid = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return aid


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


# ─── Fix 1: upsert ≤1 pending per thread + auto-resolve ───

def test_quiet_thread_upsert_one_card_per_thread(alert_store, needs_live_pg):
    """Rubric 1: run detect_quiet_threads twice → exactly 1 pending card."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(needs_live_pg, "email: Counterparty — please advise", hours_silent=72)

    detect_quiet_threads()
    detect_quiet_threads()

    rows = _pending_for(needs_live_pg, tid)
    assert len(rows) == 1, f"expected exactly 1 pending card, got {len(rows)}"
    assert rows[0]["tier"] == 2
    assert rows[0]["structured_actions"]["trigger"] == "quiet_thread"


def test_auto_resolve_when_thread_active_again(alert_store, needs_live_pg):
    """Rubric 2: a pending quiet card resolves once the thread gets a new turn."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = str(uuid.uuid4())
    # Thread is currently ACTIVE (last turn 1h ago) but had a pending quiet alert
    # created 2h ago — i.e. the thread revived after we alerted.
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
    assert status == "resolved", f"expected resolved, got {status}"
    assert exit_reason == "thread_active_again"


def test_acknowledged_at_set_blocks_renoise_even_if_pending(alert_store, needs_live_pg):
    """Codex gate fix #1: an alert with acknowledged_at set but status still
    'pending' must NOT be duplicated by a fresh card (guard keys on
    acknowledged_at, not status)."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(needs_live_pg, "email: Counterparty — advise", hours_silent=72)
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor()
        # Inconsistent state: acknowledged_at set but status left 'pending'.
        cur.execute(
            "INSERT INTO alerts (source, source_id, tier, title, body, status, "
            "acknowledged_at, structured_actions, created_at) VALUES "
            "('proactive_pm_sentinel',%s,2,'q','b','pending', NOW(),"
            "'{\"trigger\":\"quiet_thread\"}'::jsonb, NOW() - INTERVAL '2 hours')",
            (tid,),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    detect_quiet_threads()

    # The existing acknowledged_at row is the only pending card — no duplicate.
    rows = _pending_for(needs_live_pg, tid)
    assert len(rows) == 1, f"acknowledged_at row must not be duplicated, got {len(rows)}"


# ─── Fix 2: demote Director-outbound to tier 3 ───

def test_director_outbound_demoted_to_tier3(alert_store, needs_live_pg):
    """Rubric 7: Director-outbound thread → tier 3 awaiting_counterparty, not tier 2."""
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads
    tid = _seed_thread(
        needs_live_pg,
        "whatsapp_outbound: Director outbound — Noted, locked in.",
        hours_silent=72,
    )
    detect_quiet_threads()

    rows = _pending_for(needs_live_pg, tid)
    assert len(rows) == 1
    assert rows[0]["tier"] == 3, f"expected tier 3, got {rows[0]['tier']}"
    assert rows[0]["structured_actions"]["trigger"] == "awaiting_counterparty"


# ─── Fix 3: TTL expiry; ack/snooze immune ───

def test_expire_stale_alerts_ttl_and_immunity(alert_store, needs_live_pg):
    """Rubric 3 + 6: >30d pending expires; <30d, acknowledged, snoozed are immune."""
    from orchestrator.alert_expiry import expire_stale_alerts
    old_id = _seed_alert(needs_live_pg, source_id="old", age_days=40)
    recent_id = _seed_alert(needs_live_pg, source_id="recent", age_days=10)
    ack_id = _seed_alert(needs_live_pg, source_id="ack", age_days=40, acknowledged=True,
                         status="pending")
    snoozed_id = _seed_alert(needs_live_pg, source_id="snz", age_days=40, snoozed_hours=48)

    res = expire_stale_alerts()
    assert res["expired"] == 1, f"only the un-protected 40d alert should expire: {res}"

    assert _status_of(needs_live_pg, old_id)[0] == "expired"
    assert _status_of(needs_live_pg, recent_id)[0] == "pending"
    assert _status_of(needs_live_pg, ack_id)[0] == "pending"
    assert _status_of(needs_live_pg, snoozed_id)[0] == "pending"


# ─── Fix 4 + 5: business vs system feed ───

def test_business_feed_excludes_infra_and_normalizes_null_matter(alert_store, needs_live_pg):
    """Rubric 4 + 5: infra sources off the business feed; NULL matter → 'unsorted'."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    _seed_alert(needs_live_pg, source="pipeline", source_id="biz1", matter_slug=None)
    _seed_alert(needs_live_pg, source="scheduler_job_liveness", source_id="infra1",
                matter_slug=None)
    _seed_alert(needs_live_pg, source="sentinel_health", source_id="infra2", matter_slug=None)

    business = store.get_pending_alerts(category="business")
    biz_sources = {a["source"] for a in business}
    assert "scheduler_job_liveness" not in biz_sources
    assert "sentinel_health" not in biz_sources
    assert "pipeline" in biz_sources
    assert all(a.get("matter_slug") for a in business), "no bare-NULL matter on business feed"
    assert any(a["matter_slug"] == "unsorted" for a in business)

    system = store.get_pending_alerts(category="system")
    sys_sources = {a["source"] for a in system}
    assert sys_sources <= {"scheduler_job_liveness", "sentinel_health", "waha_session"}
    assert "scheduler_job_liveness" in sys_sources


# ─── Sweep: collapse backlog, audit, idempotent, ack/snooze immune ───

def test_sweep_collapses_backlog_and_logs(alert_store, needs_live_pg):
    """Rubric 5/6 + sweep: flood + stale collapse; ack/snooze immune; baker_actions logged."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    # quiet flood (5 pending quiet cards), 1 stale pipeline (>30d), protected rows
    for i in range(5):
        _seed_alert(needs_live_pg, source="proactive_pm_sentinel", source_id=f"q{i}")
    stale_id = _seed_alert(needs_live_pg, source="pipeline", source_id="stale", age_days=60)
    ack_id = _seed_alert(needs_live_pg, source="proactive_pm_sentinel", source_id="ackq",
                         acknowledged=True)
    snz_id = _seed_alert(needs_live_pg, source="proactive_pm_sentinel", source_id="snzq",
                         snoozed_hours=24)

    counts = store.sweep_alert_noise()
    assert counts["quiet_flood_expired"] == 5
    assert counts["stale_expired"] == 1
    assert counts["audit_logged"] is True  # atomic audit committed with the sweep

    assert _status_of(needs_live_pg, stale_id)[0] == "expired"
    assert _status_of(needs_live_pg, ack_id)[0] == "pending", "acknowledged must survive"
    assert _status_of(needs_live_pg, snz_id)[0] == "pending", "snoozed must survive"

    # audit row written
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM baker_actions WHERE action_type='alert_noise_sweep'")
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.close()

    # idempotent: second run expires ~0 (flood + stale already cleared)
    counts2 = store.sweep_alert_noise()
    assert counts2["quiet_flood_expired"] == 0
    assert counts2["stale_expired"] == 0
