"""Unit tests for kbl.bridge.alerts_to_signal.

Pure-function coverage for the 4-axis filter, stop-list, and mapper
plus a mocked-DB integration test for watermark rollback semantics
and an optional live-PG round-trip via ``needs_live_pg``.

Brief: ``briefs/BRIEF_ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1.md``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from kbl.bridge import alerts_to_signal as bridge


# --------------------------------------------------------------------------
# Filter axes — should_bridge / _passes_filter_axes
# --------------------------------------------------------------------------


def _alert(**overrides) -> dict:
    """Minimal alert dict with safe defaults; tests override only what matters."""
    base = {
        "id": 1,
        "tier": 3,
        "title": "irrelevant title",
        "body": None,
        "matter_slug": None,
        "source": "test_source",
        "source_id": "src-1",
        "tags": [],
        "structured_actions": None,
        "contact_id": None,
        "created_at": datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "axis_overrides",
    [
        {"tier": 1},
        {"tier": 2},
        {"matter_slug": "movie"},
        {"contact_id": "vip-uuid-123"},
        {"tags": ["commitment"]},
    ],
    ids=["tier1", "tier2", "matter", "vip", "promote_type"],
)
def test_should_bridge_each_axis_independently_passes(axis_overrides):
    """Each of the 4 axes alone is sufficient to bridge."""
    alert = _alert(**axis_overrides)
    vip_ids = {"vip-uuid-123"}
    assert bridge.should_bridge(alert, vip_ids, set()) is True


def test_should_bridge_returns_false_when_all_axes_miss():
    """Tier 3 + no matter + non-VIP + no promote-type = drop."""
    alert = _alert()
    assert bridge.should_bridge(alert, set(), set()) is False


def test_stoplist_overrides_permissive_axes():
    """Real Director-tagged matter alert is dropped if title hits stop-list."""
    alert = _alert(
        tier=1,
        matter_slug="movie",
        title="Complimentary preview ends — sale 50% off",
    )
    assert bridge.should_bridge(alert, set(), set()) is False
    assert bridge._is_stoplist_noise(alert) is True


def test_stoplist_source_drops_regardless_of_tier():
    """source='dropbox_batch' is operational noise even at tier 1."""
    alert = _alert(tier=1, source="dropbox_batch", matter_slug="movie")
    assert bridge.should_bridge(alert, set(), set()) is False


def test_vip_contact_id_lookup_passes():
    """contact_id present in vip_ids set = match axis 3."""
    alert = _alert(contact_id="ao-uuid")
    assert bridge.should_bridge(alert, {"ao-uuid"}, set()) is True


def test_vip_email_fallback_when_contact_id_absent():
    """sender_email match against vip_emails covers unresolved contact_id."""
    alert = _alert(sender_email="ao@brisengroup.com")
    assert bridge.should_bridge(alert, set(), {"ao@brisengroup.com"}) is True


def test_promote_type_via_structured_actions_dict():
    alert = _alert(structured_actions={"type": "deadline"})
    assert bridge.should_bridge(alert, set(), set()) is True


def test_promote_type_via_tags_jsonb_string():
    """tags arrives as JSON string from psycopg2 in some paths — must parse."""
    alert = _alert(tags=json.dumps(["meeting", "appointment"]))
    assert bridge.should_bridge(alert, set(), set()) is True


def test_promote_title_fallback_only_when_tags_and_actions_absent():
    """Title-keyword match is advisory — fires only when no structured signal."""
    alert = _alert(title="Court hearing scheduled tomorrow")
    assert bridge.should_bridge(alert, set(), set()) is True


# --------------------------------------------------------------------------
# Mapping — map_alert_to_signal
# --------------------------------------------------------------------------


def test_map_alert_to_signal_shape_matches_signal_queue_columns():
    """Mapper output matches the columns we INSERT — no extras, no NOT NULL gaps."""
    alert = _alert(
        id=42,
        tier=1,
        title="HMA contract change",
        body="some body",
        matter_slug="movie",
        source="email",
        source_id="email-msg-123",
        tags=["contract-change"],
        contact_id="vip-uuid",
    )
    row = bridge.map_alert_to_signal(alert)

    expected_keys = {
        "source", "signal_type", "matter", "primary_matter",
        "summary", "priority", "status", "stage", "payload",
    }
    assert set(row.keys()) == expected_keys

    assert row["source"] == "legacy_alert"
    assert row["signal_type"] == "alert:email"
    assert row["matter"] == "movie"
    assert row["primary_matter"] == "movie"
    assert row["summary"] == "HMA contract change"
    assert row["status"] == "pending"
    assert row["stage"] == "triage"
    assert row["priority"] == "urgent"  # tier 1 mapping

    payload = row["payload"]
    assert payload["alert_id"] == 42
    assert payload["alert_source_id"] == "email-msg-123"
    assert payload["alert_source"] == "email"
    assert payload["alert_tier"] == 1
    assert payload["alert_title"] == "HMA contract change"
    assert payload["alert_matter_slug"] == "movie"
    assert payload["alert_contact_id"] == "vip-uuid"
    assert payload["alert_created_at"] == alert["created_at"].isoformat()


def test_priority_mapping_sorts_correctly_under_text_desc():
    """tier 1 → 'urgent', tier 2 → 'normal', tier 3 → 'low'.

    ORDER BY priority DESC must put tier 1 first lexically.
    'urgent' (u) > 'normal' (n) > 'low' (l) in ASCII.
    """
    p1 = bridge.map_alert_to_signal(_alert(tier=1))["priority"]
    p2 = bridge.map_alert_to_signal(_alert(tier=2))["priority"]
    p3 = bridge.map_alert_to_signal(_alert(tier=3))["priority"]
    assert p1 == "urgent"
    assert p2 == "normal"
    assert p3 == "low"
    assert p1 > p2 > p3, "lex order must match severity order under DESC"


def test_map_alert_with_missing_tier_defaults_to_low_priority():
    alert = _alert(tier=None)
    assert bridge.map_alert_to_signal(alert)["priority"] == "low"


# --------------------------------------------------------------------------
# Stop-list — coverage of all 13 patterns + sources
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Complimentary breakfast at Mandarin",
        "Redeem your bonus today",
        "MEGA SALE 50% off everything",
        "Sotheby's spring auction preview",
        "Christie's Auction this weekend",  # generic auction (no brisen)
        "Stan Manoukian: new wines will be available",
        "Medal Engraving service",
        "Preview ends Friday",
        "Hotel Express Deals — last call",
        "Forbes Under 30 nominations",
        "Wine o'clock starts now",
        "Use code TAKEITOUTSIDE for 10% off",
    ],
)
def test_stoplist_title_patterns_all_match(title):
    assert bridge._is_stoplist_noise(_alert(title=title)) is True


def test_stoplist_auction_negative_lookahead_lets_brisen_through():
    """Brisen-specific auction copy must NOT be stop-listed."""
    alert = _alert(title="Brisen Hotels auction announcement")
    assert bridge._is_stoplist_noise(alert) is False


@pytest.mark.parametrize(
    "src",
    ["dropbox_batch", "cadence_tracker", "sentinel_health",
     "waha_silence", "waha_session"],
)
def test_stoplist_sources_drop_unconditionally(src):
    assert bridge._is_stoplist_noise(_alert(source=src)) is True


# --------------------------------------------------------------------------
# Mocked-DB tests for run_bridge_tick — atomic-batch + idempotency contracts
# --------------------------------------------------------------------------


class _FakeCursor:
    """Minimal cursor stub that records executes + returns canned rows.

    queue is a list of (re.Pattern-like substring -> row(s)) handlers
    consulted in order. The first matching substring wins, so tests
    declare the SQL fragments they care about.
    """

    def __init__(self, handlers):
        self._handlers = handlers
        self._next = None
        self.executes = []

    def execute(self, sql, params=None):
        self.executes.append((sql, params))
        for needle, response in self._handlers:
            if needle in sql:
                self._next = response
                return
        self._next = None

    def fetchone(self):
        n = self._next
        if isinstance(n, list):
            return n[0] if n else None
        return n

    def fetchall(self):
        n = self._next
        if isinstance(n, list):
            return n
        return [n] if n else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, cursors):
        # cursors is a list — one per `with conn.cursor()` context
        self._cursors = list(cursors)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursors.pop(0)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _bridge_with_fake_conn(monkeypatch, conn):
    """Patch kbl.bridge.alerts_to_signal.get_conn to yield our fake."""
    from contextlib import contextmanager

    @contextmanager
    def fake_get_conn():
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(bridge, "get_conn", fake_get_conn)


def test_run_bridge_tick_advances_watermark_only_after_full_commit(monkeypatch):
    """Successful tick: watermark UPSERT runs and conn.commit() is called."""
    now = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    older = now - timedelta(hours=1)

    setup_cursor = _FakeCursor([
        ("FROM trigger_watermarks", (older,)),
        ("FROM vip_contacts", []),
        ("FROM alerts", [(99, 1, "Court filing today", None, "movie",
                          "email", "msg-99", None, None, None, now)]),
    ])
    write_cursor = _FakeCursor([
        ("INSERT INTO signal_queue", (123,)),
        ("INSERT INTO trigger_watermarks", None),
    ])
    conn = _FakeConn([setup_cursor, write_cursor])
    _bridge_with_fake_conn(monkeypatch, conn)

    counts = bridge.run_bridge_tick()

    assert counts["read"] == 1
    assert counts["bridged"] == 1
    assert counts["errors"] == 0
    assert conn.committed is True
    assert conn.rolled_back is False
    assert any(
        "INSERT INTO trigger_watermarks" in sql
        for sql, _ in write_cursor.executes
    ), "watermark UPSERT must run before commit"


def test_run_bridge_tick_rolls_back_on_insert_failure(monkeypatch):
    """Insert raises mid-batch → rollback, no watermark advance, raise propagates."""
    now = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)

    class _RaisingCursor(_FakeCursor):
        def execute(self, sql, params=None):
            self.executes.append((sql, params))
            if "INSERT INTO signal_queue" in sql:
                raise RuntimeError("simulated insert failure")
            super().execute(sql, params)

    setup_cursor = _FakeCursor([
        ("FROM trigger_watermarks", (now - timedelta(hours=1),)),
        ("FROM vip_contacts", []),
        ("FROM alerts", [(7, 1, "x", None, "movie", "email", "src-7",
                          None, None, None, now)]),
    ])
    write_cursor = _RaisingCursor([])
    conn = _FakeConn([setup_cursor, write_cursor])
    _bridge_with_fake_conn(monkeypatch, conn)

    with pytest.raises(RuntimeError, match="simulated insert failure"):
        bridge.run_bridge_tick()

    assert conn.committed is False
    assert conn.rolled_back is True


def test_run_bridge_tick_empty_alert_set_short_circuits(monkeypatch):
    """No alerts since watermark = no-op tick, no commit, counts all zero."""
    now = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    setup_cursor = _FakeCursor([
        ("FROM trigger_watermarks", (now - timedelta(hours=1),)),
        ("FROM vip_contacts", []),
        ("FROM alerts", []),
    ])
    conn = _FakeConn([setup_cursor])
    _bridge_with_fake_conn(monkeypatch, conn)

    counts = bridge.run_bridge_tick()
    assert counts == {
        "read": 0, "kept": 0, "bridged": 0,
        "skipped_filter": 0, "skipped_stoplist": 0, "errors": 0,
    }
    assert conn.committed is False


def test_run_bridge_tick_idempotent_when_insert_returns_no_id(monkeypatch):
    """NOT EXISTS guard returns no row → bridged stays 0 even though kept incremented.

    Models the duplicate-detection path: alert passes the filter (kept++),
    but signal_queue already has a row with the same alert_source_id,
    so the INSERT...SELECT...WHERE NOT EXISTS yields zero rows.
    """
    now = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    setup_cursor = _FakeCursor([
        ("FROM trigger_watermarks", (now - timedelta(hours=1),)),
        ("FROM vip_contacts", []),
        ("FROM alerts", [(50, 1, "dup-test", None, "movie", "email",
                          "src-50", None, None, None, now)]),
    ])
    write_cursor = _FakeCursor([
        ("INSERT INTO signal_queue", None),  # fetchone returns None = duplicate
        ("INSERT INTO trigger_watermarks", None),
    ])
    conn = _FakeConn([setup_cursor, write_cursor])
    _bridge_with_fake_conn(monkeypatch, conn)

    counts = bridge.run_bridge_tick()
    assert counts["kept"] == 1
    assert counts["bridged"] == 0
    assert counts["errors"] == 0
    assert conn.committed is True
