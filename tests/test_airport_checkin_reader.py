"""BOX5_RECEIPT_TTL_1 — check-in reader + TTL nudge behaviour tests.

- Pure parser tests (no DB) for ``parse_checkin_outcome``.
- Live-PG tests (via ``needs_live_pg``; auto-skip without ``TEST_DATABASE_URL`` /
  ``NEON_*``; CI runs live) for the Part-1 reader and Part-2 TTL/nudge flows.

The bus is stubbed by monkeypatching the reader's imported ``_request_json`` so no
network is touched; only the DB writes are real.
"""
from __future__ import annotations

import re
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

    def __init__(self, inbox=None, bodies=None, fail_escalation=False):
        self.inbox = inbox or []
        self.bodies = bodies or {}
        self.fail_escalation = fail_escalation
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
            if self.fail_escalation and recipient == "lead":
                return {"ok": False, "error": "http_503"}
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
            "nudge_count", "last_nudged_at", "last_sent_at", "escalated_at"]
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

    # F1: re-applying the same reply is a 0-row no-op, but the resolved replay is
    # STILL ACKed (else the bus reply is re-read forever). Not 'unmatched'.
    bus.acks.clear()
    out2 = reader.run_checkin_reader(pg)
    assert out2["checked_in"] == 0
    assert out2["already"] == 1
    assert out2["unmatched"] == 0
    assert 5001 in bus.acks  # idempotent replay was acked, not stranded
    assert _audit_count(pg, "airport_ticket.checked_in") == 1  # no second receipt


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
    assert out["already"] == 0
    assert bus.acks == []  # no matching ticket -> left un-acked for next tick
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


# --- Part 1b: drain-to-empty + dead-letter (CHECKIN_READER_DRAIN_DEADLETTER_1) ----

class PagingFakeBus(FakeBus):
    """FakeBus that RESPECTS ?limit and DROPS acked messages from the unread set, so the
    drain-to-empty loop pages through a backlog the way the real daemon does."""

    def __init__(self, inbox=None, bodies=None):
        super().__init__(inbox=inbox, bodies=bodies)
        self._acked_ids: set = set()

    def __call__(self, method, url, *, key, payload=None, timeout=15):
        if method == "GET" and "/msg/" in url and "unread=true" in url:
            m = re.search(r"limit=(\d+)", url)
            lim = int(m.group(1)) if m else 25
            unread = [x for x in self.inbox if x.get("id") not in self._acked_ids]
            return {"messages": unread[:lim]}
        if method == "POST" and url.endswith("/ack"):
            mid = int(url.rsplit("/msg/", 1)[1].split("/")[0])
            self._acked_ids.add(mid)
        return super().__call__(method, url, key=key, payload=payload, timeout=timeout)


_T0 = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)


def test_reader_dead_letters_aged_unmatched(pg, monkeypatch):
    # reply matches NO ticket and is older than the dead-letter budget -> ACK + audit
    bus = FakeBus(
        inbox=[{"id": 6001, "parent_id": 999999, "thread_id": "nope",
                "from_terminal": "baden-baden-desk", "body_preview": "FAKE",
                "created_at": _T0.isoformat()}],
        bodies={6001: "FAKE"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)
    out = reader.run_checkin_reader(pg, now=_T0 + timedelta(minutes=45))
    assert out["dead_lettered"] == 1
    assert out["unmatched"] == 0
    assert 6001 in bus.acks
    assert _audit_count(pg, "airport_checkin.dead_letter") == 1


def test_reader_keeps_young_unmatched_unacked(pg, monkeypatch):
    # same unmatched reply but YOUNG -> not dead-lettered, left un-acked for retry
    bus = FakeBus(
        inbox=[{"id": 6002, "parent_id": 999999, "thread_id": "nope",
                "from_terminal": "baden-baden-desk", "body_preview": "FAKE",
                "created_at": _T0.isoformat()}],
        bodies={6002: "FAKE"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)
    out = reader.run_checkin_reader(pg, now=_T0 + timedelta(minutes=5))
    assert out["dead_lettered"] == 0
    assert out["unmatched"] == 1
    assert 6002 not in bus.acks
    assert _audit_count(pg, "airport_checkin.dead_letter") == 0


def test_reader_dead_letters_aged_parsed_none(pg, monkeypatch):
    _insert_ticket(pg, ticket_id="TK6", bus_message_id=4610)
    bus = FakeBus(
        inbox=[{"id": 6003, "parent_id": 4610, "thread_id": "t",
                "from_terminal": "baden-baden-desk", "body_preview": "hmm",
                "created_at": _T0.isoformat()}],
        bodies={6003: "just some free text, no outcome word"},
    )
    monkeypatch.setattr(reader, "_request_json", bus)
    out = reader.run_checkin_reader(pg, now=_T0 + timedelta(minutes=45))
    assert out["dead_lettered"] == 1
    assert out["parsed_none"] == 0
    assert 6003 in bus.acks


def test_reader_drain_to_empty_multi_page(pg, monkeypatch):
    # 12 real disposes, poll limit 5 -> must page (5+5+2) to clear all in one sweep
    monkeypatch.setattr(reader, "_poll_limit", lambda: 5)
    inbox, bodies = [], {}
    for i in range(12):
        _insert_ticket(pg, ticket_id=f"TKd{i}", bus_message_id=7000 + i)
        inbox.append({"id": 8000 + i, "parent_id": 7000 + i, "thread_id": f"th{i}",
                      "from_terminal": "baden-baden-desk", "body_preview": "FAKE",
                      "created_at": _T0.isoformat()})
        bodies[8000 + i] = "FAKE"
    bus = PagingFakeBus(inbox=inbox, bodies=bodies)
    monkeypatch.setattr(reader, "_request_json", bus)
    out = reader.run_checkin_reader(pg, now=_T0 + timedelta(minutes=1))
    assert out["checked_in"] == 12
    assert len(bus.acks) == 12
    for i in range(12):
        assert _ticket(pg, f"TKd{i}")["status"] == "rejected"  # FAKE -> rejected


def test_reader_dead_letter_unblocks_dispose_behind_wall(pg, monkeypatch):
    # AC scenario: a WALL of 5 aged un-ackable junk replies sits at the front of the
    # oldest-first window, ahead of a real dispose. poll limit 5 => without dead-letter
    # the real dispose would never be reached. With dead-letter, junk clears and the
    # real dispose checks in within the SAME sweep.
    monkeypatch.setattr(reader, "_poll_limit", lambda: 5)
    _insert_ticket(pg, ticket_id="TKreal", bus_message_id=7777)
    inbox = [
        {"id": 9000 + i, "parent_id": 111000 + i, "thread_id": f"junk{i}",
         "from_terminal": "baden-baden-desk", "body_preview": "FAKE",
         "created_at": _T0.isoformat()}
        for i in range(5)
    ]
    inbox.append({"id": 9500, "parent_id": 7777, "thread_id": "real",
                  "from_terminal": "baden-baden-desk", "body_preview": "FAKE",
                  "created_at": _T0.isoformat()})
    bodies = {m["id"]: "FAKE" for m in inbox}
    bus = PagingFakeBus(inbox=inbox, bodies=bodies)
    monkeypatch.setattr(reader, "_request_json", bus)
    out = reader.run_checkin_reader(pg, now=_T0 + timedelta(minutes=45))
    assert out["dead_lettered"] == 5      # the wall of aged junk
    assert out["checked_in"] == 1         # the real dispose behind it
    assert _ticket(pg, "TKreal")["status"] == "rejected"
    assert 9500 in bus.acks


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
    t = _ticket(pg, "TKN2")
    assert t["nudge_count"] == 3
    assert t["escalated_at"] is not None
    assert any(p["to"] == "lead" for p in bus.posts)
    assert _audit_count(pg, "airport_ticket.escalated") == 1

    # Escalated + at max -> falls out of both scans; no further nudge or escalation.
    out2 = reader.run_ttl_nudge(pg)
    assert out2["nudged"] == 0
    assert out2["escalated"] == 0


def test_ttl_nudge_escalation_failure_is_retryable(pg, monkeypatch):
    """F2: a transient escalation-POST failure must NOT strand the row at
    nudge_count>=max — escalated_at stays NULL and the next sweep retries the
    escalation (with no extra desk re-ping)."""
    _insert_ticket(
        pg, ticket_id="TKN4", last_sent_at=_now() - timedelta(hours=2),
        last_nudged_at=_now() - timedelta(hours=2), nudge_count=2,
        ticket={"proposed_desk_slug": "baden-baden-desk"},
    )
    bad_bus = FakeBus(fail_escalation=True)
    monkeypatch.setattr(reader, "_request_json", bad_bus)

    out = reader.run_ttl_nudge(pg)
    assert out["nudged"] == 1        # the final re-ping still happened
    assert out["escalated"] == 0     # escalation POST failed
    assert out["errors"] >= 1
    t = _ticket(pg, "TKN4")
    assert t["nudge_count"] == 3
    assert t["escalated_at"] is None  # NOT stranded — still eligible to escalate
    assert _audit_count(pg, "airport_ticket.escalated") == 0

    # Retry with a healthy bus: escalates, and does NOT re-ping the desk again.
    good_bus = FakeBus()
    monkeypatch.setattr(reader, "_request_json", good_bus)
    out2 = reader.run_ttl_nudge(pg)
    assert out2["nudged"] == 0                                   # count==max, no re-ping
    assert out2["escalated"] == 1
    assert [p["to"] for p in good_bus.posts] == ["lead"]         # only the escalation
    assert _ticket(pg, "TKN4")["escalated_at"] is not None
    assert _audit_count(pg, "airport_ticket.escalated") == 1


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
