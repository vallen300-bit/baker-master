"""TICKET_ID_DEDUP_1 + BUS_WILDCARD_PENDING_FIX (lead #7327 / #7335).

Root cause (b2 forensics, bus #7341, lead ruling #7342 = A + B1):
    A ticketing-bridge bus POST that hits a read-timeout ("The read operation
    timed out") is recorded as bus_failed; the contiguous watermark freezes at that
    arrival and reserve_ticket's failed-retry path re-POSTs it every ~10-min tick.
    A read-timeout is AMBIGUOUS — the daemon likely created the message — so each
    retry delivered a DUPLICATE to the desk (BB #7310 "re-mint"), and the desk's
    check-in could not land (it requires status='sent', but the row flapped
    candidate<->failed). The brief's disposed-dedup premise alone would NOT stop this.

Fix, in two layers:
    A  (bridge)  reserve_ticket refuses to re-issue an already-DISPOSED row
                 (terminal_status set / desk check-in / terminal live-status), even
                 when a transient failure left it status='failed'.
    B1 (daemon)  brisen_lab_msg carries an optional idempotency_key; a retried POST
                 with the same (from_terminal, idempotency_key) returns the ORIGINAL
                 message instead of creating a duplicate. The bridge sends
                 idempotency_key = ticket_id, so any number of read-timeout retries
                 deliver EXACTLY ONE desk message.

BUS_WILDCARD_PENDING_FIX (#7335): unackable to_terminals=['*'] lifecycle broadcasts
    are excluded from a named terminal's UNREAD (pending) view — read-side only.

Hermetic unit tests (always run) cover A + the client idempotency key. The daemon
idempotency dedup, keyless regression, and wildcard exclusion are SQL behaviors,
covered by live-PG tests that auto-skip without TEST_DATABASE_URL (CI provisions an
ephemeral Neon branch). The inline table mirrors the exact shipped DDL
(brisen-lab/db.py: idempotency_key column + uq_brisen_lab_msg_idempotency partial
unique index); the daemon re-asserts that DDL on every boot via bootstrap().
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orchestrator import airport_ticketing_bridge as bridge


# ---------------------------------------------------------------------------
# Fake conn/cursor for reserve_ticket unit tests (no DB).
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, existing):
        self._existing = existing  # (id, status, bus_message_id, terminal_status, check_in_at) | None
        self.executed: list[tuple[str, object]] = []
        self._last = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        head = " ".join(sql.split()).upper()
        if head.startswith("SELECT"):
            self._last = self._existing
        elif head.startswith("UPDATE"):
            self._last = (self._existing[0],) if self._existing else None
        elif head.startswith("INSERT"):
            self._last = (999,)
        else:
            self._last = None

    def fetchone(self):
        return self._last

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, existing):
        self._cur = _FakeCursor(existing)

    def cursor(self, *a, **k):
        return self._cur


def _ticket():
    t = bridge.AirportTicket(
        ticket_id="airport-ticket-v1-deadbeefdeadbeef0001",
        dedup_key="airport-ticket:v1:email:MSG-1:baden-baden-desk",
        created_at=bridge._utc_now(),
        source_channel="email",
        source_id="MSG-1",
        source_received_at=None,
        originator="Someone <a@b.com>",
        suspected_matter_slug="lilienmatt",
        suspected_flight="aukera-annaberg-financing",
        proposed_desk_slug="baden-baden-desk",
        urgency_hint="high",
        luggage=("email subject: x",),
        why_ticketed=("matched active flight keyword(s): aukera",),
        known_limits=("Owning desk must check in as VALID ...",),
    )
    return t


def _executed_verbs(cur: _FakeCursor) -> list[str]:
    return [" ".join(sql.split()).upper().split(" ", 1)[0] for sql, _ in cur.executed]


# ---------------------------------------------------------------------------
# A — disposed-ticket guard (AC2: disposed-id guard holds).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "existing",
    [
        # (id, status, bus_message_id, terminal_status, check_in_at)
        (10, "failed", None, "TICKET", None),        # terminal_status set, status stuck failed
        (11, "sent", 7306, "TICKET", None),          # terminal_status set, already sent
        (12, "rejected", 7312, "TICKET", "2026-07-08T14:12:42+00:00"),  # desk checked-in
        (13, "checked_in", 42, None, "2026-07-08T00:00:00+00:00"),      # check-in, no terminal_status
        (14, "closed", 43, None, None),              # terminal live-status
    ],
    ids=["failed+terminal", "sent+terminal", "rejected+checkin", "checkin_only", "closed"],
)
def test_reserve_ticket_disposed_row_never_reissues(existing):
    conn = _FakeConn(existing)
    out = bridge.reserve_ticket(conn, _ticket())
    assert out["reserved"] is False
    assert out.get("disposed") is True
    assert out["id"] == existing[0]
    # The load-bearing property: NO UPDATE ran — the failed-retry path did not
    # resurrect a disposed row (only the dedup SELECT executed).
    assert _executed_verbs(conn._cur) == ["SELECT"]


def test_reserve_ticket_failed_but_undisposed_still_retries():
    # A genuinely-failed post (no terminal disposition) MUST still retry — the guard
    # must not break legitimate at-least-once delivery.
    conn = _FakeConn((20, "failed", None, None, None))
    out = bridge.reserve_ticket(conn, _ticket())
    assert out["reserved"] is True
    assert out.get("retry") is True
    assert "UPDATE" in _executed_verbs(conn._cur)


def test_reserve_ticket_sent_undisposed_is_plain_duplicate():
    # status='sent' with a bus_message_id but no terminal disposition yet -> a plain
    # dedup duplicate (reserved False, NOT disposed), so run_tick's DUPLICATE terminal
    # path still owns it.
    conn = _FakeConn((30, "sent", 999, None, None))
    out = bridge.reserve_ticket(conn, _ticket())
    assert out["reserved"] is False
    assert out.get("disposed") is not True
    assert _executed_verbs(conn._cur) == ["SELECT"]


def test_issue_ticket_disposed_does_not_post(monkeypatch):
    post = MagicMock()
    monkeypatch.setattr(
        bridge, "reserve_ticket",
        lambda conn, ticket: {"reserved": False, "id": 7, "disposed": True},
    )
    monkeypatch.setattr(bridge, "post_ticket_to_bus", post)
    out = bridge.issue_ticket(_ticket(), MagicMock())
    assert out == {"skipped": True, "reason": "disposed", "id": 7}
    post.assert_not_called()


def test_issue_ticket_plain_duplicate_reason_unchanged(monkeypatch):
    # Regression: a non-disposed reserved-False stays reason='duplicate'.
    monkeypatch.setattr(
        bridge, "reserve_ticket",
        lambda conn, ticket: {"reserved": False, "id": 7},
    )
    monkeypatch.setattr(bridge, "post_ticket_to_bus", MagicMock())
    out = bridge.issue_ticket(_ticket(), MagicMock())
    assert out == {"skipped": True, "reason": "duplicate", "id": 7}


# ---------------------------------------------------------------------------
# B1 client — the bridge sends idempotency_key = ticket_id on ticket posts.
# ---------------------------------------------------------------------------
def test_post_ticket_to_bus_sends_ticket_id_as_idempotency_key(monkeypatch):
    monkeypatch.setenv("AIRPORT_TICKETING_TERMINAL_KEY", "k-test")
    captured = {}

    def _fake_request_json(method, url, *, key, payload=None, timeout=15):
        captured["payload"] = payload
        return {"id": 5555}

    monkeypatch.setattr(bridge, "_request_json", _fake_request_json)
    ticket = _ticket()
    out = bridge.post_ticket_to_bus(ticket)
    assert out["ok"] is True
    assert captured["payload"]["idempotency_key"] == ticket.ticket_id


# ---------------------------------------------------------------------------
# B1 daemon + #7335 — SQL behavior against live PG (auto-skip without a DB).
# ---------------------------------------------------------------------------
_MSG_DDL = """
CREATE TABLE IF NOT EXISTS ticket_dedup_test_msg (
    id BIGSERIAL PRIMARY KEY,
    from_terminal TEXT NOT NULL,
    to_terminals TEXT[] NOT NULL,
    body TEXT NOT NULL,
    acknowledged_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- mirrors brisen-lab/db.py brisen_lab_msg.idempotency_key
    idempotency_key TEXT
);
"""
# mirrors uq_brisen_lab_msg_idempotency in brisen-lab/db.py bootstrap()
_MSG_UQ = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_dedup_test_msg_idem "
    "ON ticket_dedup_test_msg (from_terminal, idempotency_key) "
    "WHERE idempotency_key IS NOT NULL"
)

# mirrors brisen-lab/bus.py _insert() B1 upsert
_INSERT_SQL = """
INSERT INTO ticket_dedup_test_msg (from_terminal, to_terminals, body, idempotency_key)
VALUES (%s, %s, %s, %s)
ON CONFLICT (from_terminal, idempotency_key) WHERE idempotency_key IS NOT NULL
    DO NOTHING
RETURNING id
"""


@pytest.fixture()
def _msg_table(needs_live_pg):
    import psycopg2

    conn = psycopg2.connect(needs_live_pg)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS ticket_dedup_test_msg")
        cur.execute(_MSG_DDL)
        cur.execute(_MSG_UQ)
    yield conn
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS ticket_dedup_test_msg")
    conn.close()


def _post_with_key(conn, key):
    """Mirror the daemon _insert(): upsert, then SELECT the existing row on conflict."""
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, ("ticketing-desk", ["baden-baden-desk"], "AIRPORT_TICKET v1", key))
        fresh = cur.fetchone()
        if fresh is not None:
            return int(fresh[0]), True
        cur.execute(
            "SELECT id FROM ticket_dedup_test_msg WHERE from_terminal=%s AND idempotency_key=%s "
            "ORDER BY id ASC LIMIT 1",
            ("ticketing-desk", key),
        )
        return int(cur.fetchone()[0]), False


def test_daemon_idempotency_key_dedup_delivers_one_message(_msg_table):
    # AC1/AC4: a read-timeout retry (same ticket_id key) creates exactly ONE row and
    # the retry returns the ORIGINAL message id — no duplicate desk delivery.
    conn = _msg_table
    tid = "airport-ticket-v1-deadbeefdeadbeef0001"
    id1, new1 = _post_with_key(conn, tid)
    id2, new2 = _post_with_key(conn, tid)
    id3, new3 = _post_with_key(conn, tid)
    assert new1 is True and new2 is False and new3 is False
    assert id1 == id2 == id3
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ticket_dedup_test_msg WHERE idempotency_key=%s", (tid,))
        assert cur.fetchone()[0] == 1


def test_daemon_keyless_posts_are_not_deduped(_msg_table):
    # Regression: NULL idempotency_key never hits the partial index — keyless posts
    # behave exactly as before (each POST is a distinct row).
    conn = _msg_table
    id1, new1 = _post_with_key(conn, None)
    id2, new2 = _post_with_key(conn, None)
    assert new1 is True and new2 is True
    assert id1 != id2
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ticket_dedup_test_msg WHERE idempotency_key IS NULL")
        assert cur.fetchone()[0] == 2


def test_unread_view_excludes_wildcard_broadcast(_msg_table):
    # #7335: a to_terminals=['*'] broadcast is unackable by any named terminal. It must
    # be EXCLUDED from a named terminal's UNREAD (pending) view but still present in the
    # full-history view. Mirrors brisen-lab/bus.py get_msg() recipient clauses.
    conn = _msg_table
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ticket_dedup_test_msg (from_terminal, to_terminals, body) VALUES "
            "('daemon', ARRAY['*'], 'lifecycle broadcast'), "
            "('lead', ARRAY['b4'], 'named dispatch')"
        )
        # UNREAD (pending) view — named recipient only (the shipped fix).
        cur.execute(
            "SELECT count(*) FROM ticket_dedup_test_msg "
            "WHERE %s = ANY(to_terminals) AND acknowledged_at IS NULL AND deleted_at IS NULL",
            ("b4",),
        )
        pending = cur.fetchone()[0]
        # FULL-history view — keeps the '*' OR so broadcasts still deliver.
        cur.execute(
            "SELECT count(*) FROM ticket_dedup_test_msg "
            "WHERE (%s = ANY(to_terminals) OR '*' = ANY(to_terminals)) AND deleted_at IS NULL",
            ("b4",),
        )
        full = cur.fetchone()[0]
    assert pending == 1   # only the named dispatch — wildcard excluded from pending
    assert full == 2      # wildcard still visible in full history
