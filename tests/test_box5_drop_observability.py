"""BOX5_DROP_OBSERVABILITY_1 — per-gate drop-log acceptance matrix.

Proves the observability instrumentation does NOT change what tickets (parity), that
keyword-miss + routing UNROUTED/CONFLICT produce structured drop rows, and that a
drop-log write failure never aborts the tick (fault-tolerant).

Live-PG via ``tier_b_test_store`` (points SentinelStoreBack._get_global_instance —
which run_tick uses — at the test DB) + ``needs_live_pg`` (auto-skip without
TEST_DATABASE_URL / NEON_*; CI runs live). Mirrors tests/test_box5_ticketing_runner.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from orchestrator import airport_ticketing_bridge as bridge

# Non-Brisen counterparty sender: inbound, and NOT an automated pattern, so matched
# arrivals reach build_email_ticket (BOX5_OUTBOUND_INGEST short-circuits Brisen senders
# before the lanes; automated patterns clear as REJECT_NOISE).
_SENDER = "counterparty@aukera.lu"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def dropenv(tier_b_test_store, needs_live_pg, monkeypatch):
    """Live harness: source tables + a clean airport_tickets / drop-log / watermark,
    master gate ON, fast lane unset, bus post stubbed (no network)."""
    admin = psycopg2.connect(needs_live_pg)
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
    bridge.ensure_airport_ticket_table(admin)
    # Drop first so a prior test that deliberately corrupted the schema (the
    # fault-tolerance case installs a `note`-only table) can't survive via
    # CREATE TABLE IF NOT EXISTS no-op — each test starts on the correct schema.
    with admin.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS box5_dropped_signals")
    bridge.ensure_box5_dropped_signals_table(admin)
    with admin.cursor() as cur:
        cur.execute("DELETE FROM airport_tickets")
        cur.execute("DELETE FROM email_messages")
        cur.execute("DELETE FROM email_attachments")
        cur.execute("DELETE FROM box5_dropped_signals")
        cur.execute(
            "DELETE FROM trigger_watermarks WHERE source = %s",
            (bridge._WATERMARK_SOURCE,),
        )
        cur.execute(
            "DELETE FROM baker_actions WHERE trigger_source = 'airport_ticketing_bridge'"
        )

    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "true")
    monkeypatch.delenv("BOX5_FAST_LANE_ENABLED", raising=False)
    monkeypatch.delenv("AIRPORT_OUTBOUND_INGEST_ENABLED", raising=False)
    monkeypatch.setenv("AIRPORT_TICKETING_KEYWORDS", "aukera,annaberg,lilienmatt")
    monkeypatch.setenv("AIRPORT_TICKETING_MAX_POSTS_PER_TICK", "25")
    monkeypatch.setattr(
        bridge, "post_ticket_to_bus",
        lambda ticket: {"ok": True, "message_id": 555, "thread_id": "t-555"},
    )
    yield admin
    admin.close()


def _seed(conn, message_id, *, subject, body, sender=_SENDER, received=None,
          thread_id=None):
    received = received or (_now() - timedelta(hours=1))
    thread_id = thread_id or message_id
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_messages
                (message_id, thread_id, sender_name, sender_email, subject,
                 full_body, received_date, source)
            VALUES (%s, %s, 'Sender', %s, %s, %s, %s, 'graph')
            ON CONFLICT (message_id) DO NOTHING
            """,
            (message_id, thread_id, sender, subject, body, received),
        )
    conn.commit()
    return received


def _ticketed_ids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_source_id FROM airport_tickets WHERE raw_source_id IS NOT NULL"
        )
        return {r[0] for r in cur.fetchall()}


def _drops(conn, message_id) -> list[tuple]:
    """[(gate, reason, matched_keywords_list)] for a message_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT gate, reason, matched_keywords FROM box5_dropped_signals "
            "WHERE message_id = %s ORDER BY gate",
            (message_id,),
        )
        out = []
        for gate, reason, mk in cur.fetchall():
            mk = json.loads(mk) if isinstance(mk, str) else mk
            out.append((gate, reason, mk))
        return out


# ── AC1 / TDD1 — PARITY: what tickets is unchanged by the observability rewrite ─────
def test_parity_only_keyword_matches_ticket(dropenv):
    # 3 keyword-matched arrivals + 2 keyword-misses.
    _seed(dropenv, "hit_auk", subject="Aukera data room", body="please review")
    _seed(dropenv, "hit_ann", subject="Annaberg status", body="update inside")
    _seed(dropenv, "hit_lil", subject="ping", body="Lilienmatt financing note")
    _seed(dropenv, "miss_news", subject="Weekly newsletter", body="nothing relevant")
    _seed(dropenv, "miss_cal", subject="Lunch invite", body="see you at noon")

    s = bridge.run_tick()
    assert s["ok"] is True

    # Exactly the keyword-matched set tickets — identical to the pre-change SQL filter.
    assert _ticketed_ids(dropenv) == {"hit_auk", "hit_ann", "hit_lil"}


# ── AC1 / TDD2 — keyword-miss -> keyword_prefilter drop row, matched_keywords empty ─
def test_keyword_miss_writes_drop_row_and_matches_do_not(dropenv):
    _seed(dropenv, "hit_auk", subject="Aukera data room", body="please review")
    _seed(dropenv, "miss_news", subject="Weekly newsletter", body="nothing relevant")

    bridge.run_tick()

    miss = _drops(dropenv, "miss_news")
    assert len(miss) == 1
    gate, reason, mk = miss[0]
    assert gate == "keyword_prefilter"
    assert reason == "no_active_keyword_match"
    assert mk == []                                   # empty for a keyword miss (AC1)

    # A keyword MATCH is never logged as a keyword_prefilter drop.
    assert _drops(dropenv, "hit_auk") == []


def test_keyword_miss_drop_is_idempotent_across_ticks(dropenv):
    # A boundary re-fetch must not duplicate the drop row (UNIQUE message_id,gate).
    _seed(dropenv, "miss_news", subject="Weekly newsletter", body="nothing relevant")
    bridge.run_tick()
    bridge.run_tick()
    assert len(_drops(dropenv, "miss_news")) == 1


# ── AC2 / TDD3 — routing UNROUTED (no code, nothing to route on) -> drop row ─────────
def test_routing_unrouted_writes_drop_row(dropenv, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    # No confident route available: no code in text, thread/participant resolve to none.
    monkeypatch.setattr(bridge, "resolve_by_thread", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "resolve_by_participant", lambda *a, **k: [])
    monkeypatch.setattr(bridge, "resolve_project_number", lambda *a, **k: None)

    _seed(dropenv, "unr1", subject="Annaberg update", body="no project code here")
    s = bridge.run_tick()
    assert s["ok"] is True

    # Still tickets (safe-default desk review) — parity preserved.
    assert "unr1" in _ticketed_ids(dropenv)
    drops = _drops(dropenv, "unr1")
    assert len(drops) == 1
    gate, reason, mk = drops[0]
    assert gate == "routing_unrouted"
    assert reason == "no_confident_route"
    assert "annaberg" in mk                            # it DID pass the keyword gate


# ── AC2 / TDD3 — routing CONFLICT (>1 distinct project code) -> drop row ─────────────
def test_routing_conflict_writes_drop_row(dropenv, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    monkeypatch.setattr(bridge, "resolve_by_thread", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "resolve_by_participant", lambda *a, **k: [])
    monkeypatch.setattr(bridge, "resolve_project_number", lambda *a, **k: None)

    # Two distinct valid-shaped codes -> cross-matter conflict; keyword present so it
    # tickets. (D/E lanes only proceed on exactly-1 code, so this falls to (f).)
    _seed(
        dropenv, "conf1",
        subject="Annaberg cross ref BB-AUK-001 and BB-LIL-002",
        body="both matters referenced",
    )
    s = bridge.run_tick()
    assert s["ok"] is True

    assert "conf1" in _ticketed_ids(dropenv)
    drops = _drops(dropenv, "conf1")
    assert len(drops) == 1
    gate, reason, _mk = drops[0]
    assert gate == "routing_conflict"
    assert reason.startswith("cross_matter_conflict:")
    assert "BB-AUK-001" in reason and "BB-LIL-002" in reason


# ── AC3 / TDD4 — drop-log write failure must NOT abort the tick ──────────────────────
def test_drop_log_write_failure_does_not_abort_tick(dropenv, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    monkeypatch.setattr(bridge, "resolve_by_thread", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "resolve_by_participant", lambda *a, **k: [])
    monkeypatch.setattr(bridge, "resolve_project_number", lambda *a, **k: None)

    # Bootstrap a SCHEMA-INCOMPATIBLE drop-log table (no `gate` column) so EVERY
    # drop-log INSERT raises a real psycopg2 error inside _write_dropped_signals —
    # exercising both the Gate-2 (commit) and Gate-3 (savepoint) guard paths.
    def _broken_ensure(conn):
        try:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS box5_dropped_signals")
                cur.execute(
                    "CREATE TABLE box5_dropped_signals (id BIGSERIAL PRIMARY KEY, note TEXT)"
                )
            conn.commit()
        except Exception:
            conn.rollback()

    monkeypatch.setattr(bridge, "ensure_box5_dropped_signals_table", _broken_ensure)

    _seed(dropenv, "miss_ft", subject="Weekly newsletter", body="no keyword")
    _seed(dropenv, "hit_ft", subject="Annaberg status", body="no project code here")

    s = bridge.run_tick()

    # Tick completed cleanly and the matched arrival STILL ticketed despite the
    # drop-log INSERTs failing on both the Gate-2 and Gate-3 write paths.
    assert s["ok"] is True
    assert "hit_ft" in _ticketed_ids(dropenv)
    ts_status, ts_written = None, None
    with dropenv.cursor() as cur:
        cur.execute(
            "SELECT terminal_status FROM airport_tickets WHERE raw_source_id = 'hit_ft'"
        )
        row = cur.fetchone()
    assert row is not None and row[0] == "TICKET"


# ── Design item 4 — read-only surface: drops-by-gate summary ─────────────────────────
def test_summarize_recent_drops_counts_by_gate(dropenv):
    _seed(dropenv, "m1", subject="Weekly newsletter", body="nope")
    _seed(dropenv, "m2", subject="Lunch invite", body="noon")
    bridge.run_tick()

    summary = bridge.summarize_recent_drops(dropenv, hours=24)
    by_gate = {row["gate"]: row["count"] for row in summary}
    assert by_gate.get("keyword_prefilter") == 2
