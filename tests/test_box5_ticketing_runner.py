"""BOX5_TICKETING_RUNNER_1 — reliability matrix for the extended run_tick.

Asserts the real crash / concurrency / error / idempotency paths, not happy-path
only (codex caught 2 P1 crash-path bugs on the prior Box-5 job; this matrix exists
to catch that class before the gate).

Live-PG via ``tier_b_test_store`` (points SentinelStoreBack._get_global_instance —
which both run_tick AND trigger_state use — at the test DB + bootstraps
baker_actions) and ``needs_live_pg`` (auto-skip without TEST_DATABASE_URL /
NEON_*; CI runs live).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from orchestrator import airport_ticketing_bridge as bridge


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def runner(tier_b_test_store, needs_live_pg, monkeypatch):
    """Live runner harness: source tables + clean airport_tickets/watermark, master
    gate ON, fast lane unset, bus post stubbed (no network)."""
    admin = psycopg2.connect(needs_live_pg)
    # Autocommit so admin reads never sit idle-in-transaction holding ACCESS SHARE
    # on airport_tickets — otherwise the next run_tick's ensure (DROP/ADD CONSTRAINT,
    # ACCESS EXCLUSIVE) would block on this connection and the tick would hang.
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS email_messages (
                message_id TEXT PRIMARY KEY, thread_id TEXT, sender_name TEXT,
                sender_email TEXT, subject TEXT, full_body TEXT,
                received_date TIMESTAMPTZ, source TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS email_attachments (
                message_id TEXT, filename TEXT, mime_type TEXT, size_bytes BIGINT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trigger_watermarks (
                source TEXT PRIMARY KEY, last_seen TIMESTAMPTZ,
                updated_at TIMESTAMPTZ, cursor_data TEXT
            )
            """
        )
    admin.commit()
    bridge.ensure_airport_ticket_table(admin)  # airport_tickets + BRIEF-B terminal cols
    admin.commit()
    with admin.cursor() as cur:
        cur.execute("DELETE FROM airport_tickets")
        cur.execute("DELETE FROM email_messages")
        cur.execute("DELETE FROM email_attachments")
        cur.execute("DELETE FROM trigger_watermarks WHERE source = %s", (bridge._WATERMARK_SOURCE,))
        cur.execute("DELETE FROM baker_actions WHERE trigger_source = 'airport_ticketing_bridge'")
    admin.commit()

    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "true")
    monkeypatch.delenv("BOX5_FAST_LANE_ENABLED", raising=False)
    monkeypatch.setenv("AIRPORT_TICKETING_KEYWORDS", "aukera,annaberg,lilienmatt")
    monkeypatch.setenv("AIRPORT_TICKETING_MAX_POSTS_PER_TICK", "25")
    # Neutralize the real bus POST — no network; pretend it succeeded.
    monkeypatch.setattr(
        bridge, "post_ticket_to_bus",
        lambda ticket: {"ok": True, "message_id": 555, "thread_id": "t-555"},
    )
    yield admin
    admin.close()


def _seed_email(conn, message_id, *, subject="annaberg status",
                sender_email="balazs@brisengroup.com", body="annaberg update",
                received=None):
    received = received or (_now() - timedelta(hours=1))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_messages
                (message_id, thread_id, sender_name, sender_email, subject,
                 full_body, received_date, source)
            VALUES (%s, %s, 'Sender', %s, %s, %s, %s, 'graph')
            ON CONFLICT (message_id) DO NOTHING
            """,
            (message_id, message_id, sender_email, subject, body, received),
        )
    conn.commit()
    return received


def _terminal(conn, message_id):
    """(terminal_status, terminal_outcome_written_at) for a row by raw_source_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT terminal_status, terminal_outcome_written_at FROM airport_tickets "
            "WHERE raw_source_id = %s LIMIT 1",
            (message_id,),
        )
        row = cur.fetchone()
    return row if row else (None, None)


# 1 — IDEMPOTENCY (highest value): run twice, the terminal write happens once.
def test_idempotent_terminal_write(runner):
    _seed_email(runner, "m1")
    s1 = bridge.run_tick()
    assert s1["ok"] and s1["terminal_written"] == 1
    ts_status, ts_written = _terminal(runner, "m1")
    assert ts_status == "TICKET" and ts_written is not None

    s2 = bridge.run_tick()
    assert s2["terminal_written"] == 0          # status-guard: second pass writes nothing
    ts_status2, ts_written2 = _terminal(runner, "m1")
    assert ts_status2 == "TICKET"
    assert ts_written2 == ts_written            # timestamp UNCHANGED -> no double-write


# 2 — SKIP-LOCKED concurrency: a row another tx holds is skipped, not blocked.
def test_claim_for_terminal_skips_locked_row(runner, needs_live_pg):
    with runner.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, source_channel, source_id, proposed_desk_slug) "
            "VALUES ('lk','lk','email','lk','baden-baden-desk') RETURNING id"
        )
        row_id = cur.fetchone()[0]
    runner.commit()

    holder = psycopg2.connect(needs_live_pg)
    other = psycopg2.connect(needs_live_pg)
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT id FROM airport_tickets WHERE id=%s FOR UPDATE", (row_id,))
            cur.fetchone()  # holder now locks the row (no commit)
        # The claim must return None (skipped), NOT hang/block.
        assert bridge._claim_for_terminal(other, row_id) is None
    finally:
        holder.rollback(); holder.close()
        other.rollback(); other.close()


# 3 — SAFE DEFAULT TICKET: a relevant, non-dup, non-noise arrival -> TICKET + bus post.
def test_safe_default_ticket(runner):
    _seed_email(runner, "m3", subject="annaberg closing")
    s = bridge.run_tick()
    assert s["defaulted_ticket"] == 1
    assert s["issued"] == 1               # bus post happened (stubbed ok)
    status, _ = _terminal(runner, "m3")
    assert status == "TICKET"
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason, status FROM airport_tickets WHERE raw_source_id='m3'")
        reason, live_status = cur.fetchone()
    assert reason == "safe_default_desk_review"
    assert live_status == "sent"          # issue path unchanged (live status axis)


# 4a — DUPLICATE deterministic clear via dedup_key collision.
def test_duplicate_deterministic_clear(runner):
    received = _seed_email(runner, "mdup", subject="annaberg dup")
    # Pre-seed the colliding row (status='sent' + bus_message_id so reserve_ticket
    # treats it as an existing duplicate, not a failed-retry), terminal_status NULL.
    dedup = bridge._dedup_key("email", "mdup", "baden-baden-desk")
    with runner.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, status, source_channel, source_id, "
            "source_received_at, proposed_desk_slug, bus_message_id) "
            "VALUES ('pre-mdup',%s,'sent','email','mdup',%s,'baden-baden-desk',999) RETURNING id",
            (dedup, received),
        )
        pre_id = cur.fetchone()[0]
    runner.commit()

    s = bridge.run_tick()
    assert s["deterministic_cleared"] >= 1
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_status, terminal_reason FROM airport_tickets WHERE id=%s", (pre_id,))
        status, reason = cur.fetchone()
    assert status == "DUPLICATE"
    assert reason == "dedup_key_collision"


# 4b — REJECT_NOISE deterministic clear (automated sender).
def test_reject_noise_deterministic_clear(runner):
    _seed_email(runner, "mnoise", subject="aukera newsletter",
                sender_email="noreply@example.com")
    s = bridge.run_tick()
    assert s["deterministic_cleared"] >= 1
    status, _ = _terminal(runner, "mnoise")
    assert status == "REJECT_NOISE"


# 4c — None-id reserve race: id=None must be a no-op, never a crash.
def test_none_id_reserve_race_is_noop(runner, monkeypatch):
    _seed_email(runner, "mrace", subject="annaberg race")
    monkeypatch.setattr(
        bridge, "issue_ticket",
        lambda ticket, conn: {"skipped": True, "reason": "duplicate", "id": None},
    )
    s = bridge.run_tick()
    assert s["ok"]                       # no crash
    assert s["lease_skipped"] >= 1
    assert s["terminal_written"] == 0
    status, _ = _terminal(runner, "mrace")
    assert status is None                # nothing written


# 5 — ERROR NEVER AUTO-CLEARS + one bad row doesn't stop the batch.
def test_error_never_auto_clears(runner, monkeypatch):
    _seed_email(runner, "mbad", subject="annaberg bad", received=_now() - timedelta(hours=2))
    _seed_email(runner, "mgood", subject="annaberg good", received=_now() - timedelta(hours=1))

    real_build = bridge.build_email_ticket

    def _boom(arrival, **kw):
        if arrival.message_id == "mbad":
            raise RuntimeError("classify exploded")
        return real_build(arrival, **kw)

    monkeypatch.setattr(bridge, "build_email_ticket", _boom)

    s = bridge.run_tick()
    assert s["failed"] >= 1
    assert s["deterministic_cleared"] == 0      # an error is NEVER a clear
    bad_status, _ = _terminal(runner, "mbad")
    assert bad_status is None                    # errored row left NULL, not cleared
    good_status, _ = _terminal(runner, "mgood")
    assert good_status == "TICKET"               # batch continued past the bad row


# 6 — CURSOR advances to max processed received_date on the DISTINCT key.
def test_cursor_advances_on_distinct_key(runner):
    r_old = _now() - timedelta(hours=3)
    r_new = _now() - timedelta(hours=1)
    _seed_email(runner, "mc1", subject="annaberg old", received=r_old)
    _seed_email(runner, "mc2", subject="annaberg new", received=r_new)

    bridge.run_tick()
    wm = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm - r_new).total_seconds()) < 1.0   # advanced to the max processed
    assert bridge._WATERMARK_SOURCE == "airport_ticketing:email"  # never the live email_poll


# 7 — KILL SWITCH: master gate off -> skip, nothing written.
def test_master_gate_off_writes_nothing(runner, monkeypatch):
    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "false")
    _seed_email(runner, "mk", subject="annaberg gated")
    s = bridge.run_tick()
    assert s.get("skipped") is True
    status, _ = _terminal(runner, "mk")
    assert status is None


# 8 — STUCK gauge counts un-terminal aged arrivals; flag default false.
def test_stuck_gauge_and_flag_default(runner):
    assert bridge.fast_lane_enabled() is False   # default closed
    # an aged row with no terminal_status is "stuck"
    with runner.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, source_channel, source_id, "
            "source_received_at, proposed_desk_slug) "
            "VALUES ('stuck','stuck','email','stuck', NOW() - INTERVAL '90 minutes', 'baden-baden-desk')"
        )
    runner.commit()
    assert bridge._count_stuck_arrivals(runner) >= 1
