"""BOX5_RECEIPT_TTL_1 — check-in reader + TTL nudge behaviour tests.

- Pure parser tests (no DB) for ``parse_checkin_outcome``.
- Live-PG tests (via ``needs_live_pg``; auto-skip without ``TEST_DATABASE_URL`` /
  ``NEON_*``; CI runs live) for the Part-1 reader and Part-2 TTL/nudge flows.

The bus is stubbed by monkeypatching the reader's imported ``_request_json`` so no
network is touched; only the DB writes are real.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
import pytest

from orchestrator import airport_checkin_reader as reader


# --- pure parser (no DB) ----------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ("VALID", "VALID"),
        ("valid", "VALID"),
        ("VALID — proceed", "VALID"),
        ("Reply: needs_luggage_read please", "NEEDS_LUGGAGE_READ"),
        ("WRONG_TERMINAL", "WRONG_TERMINAL"),
        ("VALID or FAKE?", None),          # two tokens -> ambiguous
        ("thanks, will look later", None),  # no token
        ("INVALID submission", None),       # 'VALID' inside a word does not match
        ("", None),
        (None, None),
    ],
)
def test_parse_checkin_outcome(body, expected):
    assert reader.parse_checkin_outcome(body) == expected


# --- live-PG scaffolding ----------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeBus:
    """Stub for ``_request_json``: serves a canned inbox + bodies, records POSTs
    (re-nudge / escalate) and ACKs. Routes purely on (method, url)."""

    def __init__(self, inbox=None, bodies=None):
        self.inbox = inbox or []
        self.bodies = bodies or {}
        self.posts: list[dict] = []
        self.acks: list[int] = []

    def __call__(self, method, url, *, key, payload=None, timeout=15):
        if method == "GET" and "/msg/" in url and "unread=true" in url:
            return {"messages": self.inbox}
        if method == "GET" and url.endswith("/full"):
            mid = int(url.rsplit("/event/", 1)[1].split("/")[0])
            return {"body": self.bodies.get(mid, "")}
        if method == "POST" and url.endswith("/ack"):
            mid = int(url.rsplit("/msg/", 1)[1].split("/")[0])
            self.acks.append(mid)
            return {"ok": True}
        if method == "POST" and "/msg/" in url:
            recipient = url.rsplit("/msg/", 1)[1]
            self.posts.append({"to": recipient, "payload": payload})
            return {"ok": True, "message_id": 90000 + len(self.posts)}
        return {"ok": True}


@pytest.fixture
def pg(needs_live_pg, monkeypatch):
    """Live conn with airport_tickets (+ nudge cols) and a minimal baker_actions,
    cleaned to a deterministic slate. Stubs the bridge key so the reader proceeds."""
    conn = psycopg2.connect(needs_live_pg)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS baker_actions (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                target_task_id TEXT,
                payload JSONB,
                trigger_source TEXT,
                success BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    conn.commit()
    reader.ensure_airport_ticket_table(conn)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM airport_tickets")
        cur.execute("DELETE FROM baker_actions WHERE trigger_source = 'airport_checkin_reader'")
    conn.commit()

    monkeypatch.setattr(reader, "_bridge_key", lambda: "test-key")
    yield conn
    conn.close()


def _insert_ticket(conn, *, ticket_id, status="sent", bus_message_id=None,
                   bus_thread_id=None, desk="baden-baden-desk", last_sent_at=None,
                   last_nudged_at=None, nudge_count=0, check_in_at=None, ticket=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO airport_tickets
                (ticket_id, dedup_key, status, source_channel, source_id,
                 proposed_desk_slug, ticket, bus_message_id, bus_thread_id,
                 last_sent_at, last_nudged_at, nudge_count, check_in_at)
            VALUES (%s, %s, %s, 'email', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (ticket_id, f"dedup-{ticket_id}", status, ticket_id, desk,
             psycopg2.extras.Json(ticket or {}), bus_message_id, bus_thread_id,
             last_sent_at, last_nudged_at, nudge_count, check_in_at),
        )
    conn.commit()


def _ticket(conn, ticket_id) -> dict:
    cols = ["status", "check_in_outcome", "check_in_by", "check_in_at",
            "nudge_count", "last_nudged_at", "last_sent_at"]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(cols)} FROM airport_tickets WHERE ticket_id = %s",
            (ticket_id,),
        )
        row = cur.fetchone()
    return dict(zip(cols, row)) if row else {}


def _audit_count(conn, action_type) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM baker_actions "
            "WHERE action_type = %s AND trigger_source = 'airport_checkin_reader'",
            (action_type,),
        )
        return cur.fetchone()[0]


# --- Part 1: reader ---------------------------------------------------------


def test_reader_writes_receipt_acks_and_is_idempotent(pg, monkeypatch):
    _insert_ticket(pg, ticket_id="TK1", bus_message_id=4588, bus_thread_id="th1")
    bus = FakeBus(
        inbox=[{"id": 5001, "parent_id": 4588, "thread_id": "th1",
                "from_terminal": "baden-baden-desk", "body_preview": "VALID"}],
        bodies={5001: "VALID — proceed"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)

    out = reader.run_checkin_reader(pg)
    assert out["checked_in"] == 1
    t = _ticket(pg, "TK1")
    assert t["status"] == "checked_in"
    assert t["check_in_outcome"] == "VALID"
    assert t["check_in_by"] == "baden-baden-desk"
    assert t["check_in_at"] is not None
    assert 5001 in bus.acks
    assert _audit_count(pg, "airport_ticket.checked_in") == 1

    # Re-applying the same reply is a no-op (status no longer 'sent').
    out2 = reader.run_checkin_reader(pg)
    assert out2["checked_in"] == 0
    assert out2["unmatched"] == 1
    assert _audit_count(pg, "airport_ticket.checked_in") == 1


def test_reader_rejected_outcome_maps_to_rejected(pg, monkeypatch):
    _insert_ticket(pg, ticket_id="TK2", bus_message_id=4600)
    bus = FakeBus(
        inbox=[{"id": 5002, "parent_id": 4600, "thread_id": None,
                "from_terminal": "baden-baden-desk", "body_preview": "FAKE"}],
        bodies={5002: "FAKE — not a real arrival"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)

    reader.run_checkin_reader(pg)
    t = _ticket(pg, "TK2")
    assert t["status"] == "rejected"
    assert t["check_in_outcome"] == "FAKE"


def test_reader_ambiguous_reply_not_written(pg, monkeypatch):
    _insert_ticket(pg, ticket_id="TK3", bus_message_id=4601)
    bus = FakeBus(
        inbox=[{"id": 5003, "parent_id": 4601, "thread_id": None,
                "from_terminal": "baden-baden-desk", "body_preview": "VALID or FAKE?"}],
        bodies={5003: "VALID or FAKE?"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)

    out = reader.run_checkin_reader(pg)
    assert out["parsed_none"] == 1
    assert out["checked_in"] == 0
    assert _ticket(pg, "TK3")["status"] == "sent"
    assert _audit_count(pg, "airport_ticket.checked_in") == 0
    assert bus.acks == []


def test_reader_unmatched_parent_no_write(pg, monkeypatch):
    _insert_ticket(pg, ticket_id="TK4", bus_message_id=4602)
    bus = FakeBus(
        inbox=[{"id": 5004, "parent_id": 999999, "thread_id": None,
                "from_terminal": "baden-baden-desk", "body_preview": "VALID"}],
        bodies={5004: "VALID"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)

    out = reader.run_checkin_reader(pg)
    assert out["unmatched"] == 1
    assert out["checked_in"] == 0
    assert _ticket(pg, "TK4")["status"] == "sent"  # untouched


def test_reader_one_bad_reply_does_not_stop_batch(pg, monkeypatch):
    _insert_ticket(pg, ticket_id="TK5", bus_message_id=4605)
    bus = FakeBus(
        inbox=[
            # malformed: no "id" -> int(msg["id"]) raises, counted as error
            {"parent_id": 4605, "thread_id": "t", "from_terminal": "baden-baden-desk",
             "body_preview": "VALID"},
            # good reply after the bad one still processes
            {"id": 5006, "parent_id": 4605, "thread_id": "t",
             "from_terminal": "baden-baden-desk", "body_preview": "VALID"},
        ],
        bodies={5006: "VALID"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)

    out = reader.run_checkin_reader(pg)
    assert out["errors"] == 1
    assert out["checked_in"] == 1
    assert _ticket(pg, "TK5")["status"] == "checked_in"


# --- Part 2: TTL / nudge ----------------------------------------------------


def test_ttl_nudge_renudges_then_respects_cooldown(pg, monkeypatch):
    _insert_ticket(
        pg, ticket_id="TKN1", last_sent_at=_now() - timedelta(hours=2),
        nudge_count=0,
        ticket={"suspected_flight": "aukera-annaberg-financing",
                "originator": "balazs", "proposed_desk_slug": "baden-baden-desk",
                "luggage": ["attachment: vdr.xlsx"]},
    )
    bus = FakeBus()
    monkeypatch.setattr(reader, "_request_json", bus)

    out = reader.run_ttl_nudge(pg)
    assert out["nudged"] == 1
    assert out["escalated"] == 0
    t = _ticket(pg, "TKN1")
    assert t["nudge_count"] == 1
    assert t["last_nudged_at"] is not None
    assert len(bus.posts) == 1
    assert bus.posts[0]["to"] == "baden-baden-desk"
    assert _audit_count(pg, "airport_ticket.renudged") == 1

    # Immediate re-run: inside cooldown -> not selected.
    out2 = reader.run_ttl_nudge(pg)
    assert out2["nudged"] == 0


def test_ttl_nudge_escalates_at_max_then_stops(pg, monkeypatch):
    # nudge_count = max-1 (default max 3); past TTL + past cooldown.
    _insert_ticket(
        pg, ticket_id="TKN2", last_sent_at=_now() - timedelta(hours=2),
        last_nudged_at=_now() - timedelta(hours=2), nudge_count=2,
        ticket={"proposed_desk_slug": "baden-baden-desk"},
    )
    bus = FakeBus()
    monkeypatch.setattr(reader, "_request_json", bus)

    out = reader.run_ttl_nudge(pg)
    assert out["nudged"] == 1
    assert out["escalated"] == 1
    assert _ticket(pg, "TKN2")["nudge_count"] == 3
    assert any(p["to"] == "lead" for p in bus.posts)
    assert _audit_count(pg, "airport_ticket.escalated") == 1

    # nudge_count now == max -> falls out of the scan; no further nudge.
    out2 = reader.run_ttl_nudge(pg)
    assert out2["nudged"] == 0


def test_ttl_nudge_skips_checked_in(pg, monkeypatch):
    _insert_ticket(
        pg, ticket_id="TKN3", status="checked_in",
        last_sent_at=_now() - timedelta(hours=2), check_in_at=_now(),
    )
    bus = FakeBus()
    monkeypatch.setattr(reader, "_request_json", bus)

    out = reader.run_ttl_nudge(pg)
    assert out["nudged"] == 0
    assert bus.posts == []
