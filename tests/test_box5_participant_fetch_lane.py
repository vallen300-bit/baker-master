"""BOX5_GATE2_PARTICIPANT_FETCH_LANE_1 — participant-identity fetch lane acceptance matrix.

Proves the SECOND, DECOUPLED fetch lane (sender identity in the project registry) widens
Gate-2 reachability WITHOUT changing the keyword match set, unions safely (dedup + global
ASC re-sort for watermark safety), tickets participant-only arrivals on identity alone, is
fault-tolerant, and is a pure no-op when its dark flag is OFF.

Two tiers:
  * ``TestFetchLaneUnit`` — fake-conn unit tests (NO DB). Run everywhere; prove the
    deterministic fetch/union/sort/dedup/dark-safe/fault-tolerance logic + the AC1
    reachability assertion that FAILS on main (no lane) and PASSES after.
  * live-PG ``run_tick`` tests (``tier_b_test_store`` + ``needs_live_pg``) — end-to-end
    reachability -> TICKET, keyword parity, watermark-advance safety, run_tick fault
    tolerance, dark-safe. Auto-skip without TEST_DATABASE_URL / NEON_*; CI runs live.
    Mirrors tests/test_box5_drop_observability.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from orchestrator import airport_ticketing_bridge as bridge
from kbl import project_registry_store as registry_store

# A registered project participant, and an EXTERNAL (non-Brisen) inbound sender so the
# outbound short-circuit never applies and it is not an automated-noise pattern.
_PARTICIPANT = "counterparty@aukera.lu"
# A non-participant counterparty (keyword lane only).
_STRANGER = "stranger@example.org"

_LANE_ENV = "BOX5_PARTICIPANT_FETCH_LANE_ENABLED"


def _dt(hours_ago: float) -> datetime:
    # Fixed base with microseconds stripped so TIMESTAMPTZ round-trips compare cleanly.
    base = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    return base - timedelta(hours=hours_ago)


# ─────────────────────────────────────────────────────────────────────────────────────
# TIER 1 — fake-conn unit tests (no DB). A tiny cursor that dispatches canned rows by SQL
# so we can exercise fetch_email_arrivals' two-lane union deterministically + offline.
# ─────────────────────────────────────────────────────────────────────────────────────

_COLS = ("message_id", "thread_id", "sender_name", "sender_email",
         "subject", "full_body", "received_date", "source")


def _row(mid, *, sender, received, subject="", body="", thread=None):
    return (mid, thread or mid, "Sender", sender, subject, body, received, "graph")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._result: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if self._conn.fail_on and self._conn.fail_on in s:
            raise RuntimeError(f"forced failure on: {self._conn.fail_on}")
        if "email_attachments" in s:
            self._result = []
        elif "FROM project_registry" in s:
            self._result = self._conn.registry_rows
        elif "LOWER(sender_email) = ANY" in s:
            self._result = list(self._conn.participant_rows)
        elif "NOT (" in s:                       # keyword miss-fetch (drop-log only)
            self._result = []
        elif "FROM email_messages" in s:         # keyword MATCH fetch
            self._result = list(self._conn.keyword_rows)
        else:
            self._result = []

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeConn:
    def __init__(self, *, keyword_rows=(), participant_rows=(), registry_rows=(),
                 fail_on=None):
        self.keyword_rows = keyword_rows
        self.participant_rows = participant_rows
        self.registry_rows = registry_rows
        self.fail_on = fail_on
        self.rolled_back = 0
        self.committed = 0

    def cursor(self):
        return _FakeCursor(self)

    def rollback(self):
        self.rolled_back += 1

    def commit(self):
        self.committed += 1


@pytest.fixture(autouse=True)
def _lane_env(monkeypatch):
    monkeypatch.setenv("AIRPORT_TICKETING_KEYWORDS", "aukera,annaberg,lilienmatt")
    # default: lane ON for unit tests (individual tests flip it OFF as needed)
    monkeypatch.setenv(_LANE_ENV, "true")


class TestFetchLaneUnit:
    def _fetch(self, conn):
        return bridge.fetch_email_arrivals(conn, since=_dt(48), limit=50)

    # ── AC1 (reachability) — FAILS on main (no lane), PASSES here ────────────────────
    def test_participant_only_arrival_is_fetched(self):
        """A registered-participant, keyword-LESS arrival on a new thread appears as an
        arrival. On main fetch_email_arrivals has no participant lane -> arrivals is empty
        -> `assert len == 1` fails cleanly (fail-on-main proof)."""
        conn = _FakeConn(
            keyword_rows=[],  # zero keyword matches
            participant_rows=[_row("part_only", sender=_PARTICIPANT, received=_dt(1),
                                   subject="Quick question on timing",
                                   body="Can we align next week?", thread="thread_new")],
            registry_rows=[([{"channel": "email", "value": _PARTICIPANT}],)],
        )
        arrivals = self._fetch(conn)
        assert len(arrivals) == 1                       # <-- fails on main (0 != 1)
        assert arrivals[0].message_id == "part_only"
        assert arrivals[0].participant_fetched is True

    # ── AC3 (union dedup) — a both-lanes row appears once; keyword lane wins ──────────
    def test_row_in_both_lanes_dedups_keyword_wins(self):
        both = _row("dual", sender=_PARTICIPANT, received=_dt(2),
                    subject="Aukera data room", body="please review")
        conn = _FakeConn(
            keyword_rows=[both],
            participant_rows=[both],  # same message_id from the participant lane
            registry_rows=[([{"channel": "email", "value": _PARTICIPANT}],)],
        )
        arrivals = self._fetch(conn)
        assert [a.message_id for a in arrivals] == ["dual"]      # exactly once
        # keyword lane won the merge -> NOT tagged participant-only -> keeps keyword path
        assert arrivals[0].participant_fetched is False

    # ── AC4 (watermark safety) — the unioned list is GLOBALLY received_date ASC ───────
    def test_union_is_globally_sorted_ascending(self):
        """Naive concat of two individually-ASC lanes is NOT globally sorted. Assert the
        union is non-decreasing so the runner's contiguous-prefix cursor can never advance
        past an OLDER un-processed participant arrival."""
        conn = _FakeConn(
            keyword_rows=[_row("k_mid", sender=_STRANGER, received=_dt(3),
                               subject="Annaberg status", body="update")],
            participant_rows=[
                _row("p_old", sender=_PARTICIPANT, received=_dt(5), subject="hi", body="a"),
                _row("p_new", sender=_PARTICIPANT, received=_dt(1), subject="hi", body="b"),
            ],
            registry_rows=[([{"channel": "email", "value": _PARTICIPANT}],)],
        )
        arrivals = self._fetch(conn)
        dates = [a.received_date for a in arrivals]
        assert dates == sorted(dates)                            # globally ASC
        assert [a.message_id for a in arrivals] == ["p_old", "k_mid", "p_new"]
        tagged = {a.message_id: a.participant_fetched for a in arrivals}
        assert tagged == {"p_old": True, "k_mid": False, "p_new": True}

    # ── AC5 (fault tolerance) — a participant-lane read error never loses keyword rows ─
    def test_participant_lane_failure_preserves_keyword_rows(self):
        conn = _FakeConn(
            keyword_rows=[_row("kw", sender=_STRANGER, received=_dt(2),
                               subject="Aukera update", body="x")],
            participant_rows=[_row("p", sender=_PARTICIPANT, received=_dt(1))],
            registry_rows=[([{"channel": "email", "value": _PARTICIPANT}],)],
            fail_on="LOWER(sender_email) = ANY",   # participant fetch raises
        )
        arrivals = self._fetch(conn)
        assert [a.message_id for a in arrivals] == ["kw"]   # keyword lane unaffected
        assert conn.rolled_back >= 1                        # shared conn kept usable

    def test_registry_enumerate_failure_is_swallowed(self):
        conn = _FakeConn(
            keyword_rows=[_row("kw", sender=_STRANGER, received=_dt(2),
                               subject="Aukera update", body="x")],
            participant_rows=[_row("p", sender=_PARTICIPANT, received=_dt(1))],
            registry_rows=[([{"channel": "email", "value": _PARTICIPANT}],)],
            fail_on="FROM project_registry",       # enumerate raises
        )
        arrivals = self._fetch(conn)
        assert [a.message_id for a in arrivals] == ["kw"]
        assert conn.rolled_back >= 1

    # ── AC6 (dark-safe) — flag OFF -> byte-identical to the keyword-only fetch ────────
    def test_lane_off_is_keyword_only_noop(self, monkeypatch):
        monkeypatch.setenv(_LANE_ENV, "false")
        conn = _FakeConn(
            keyword_rows=[_row("kw", sender=_STRANGER, received=_dt(2),
                               subject="Aukera update", body="x")],
            participant_rows=[_row("p_never", sender=_PARTICIPANT, received=_dt(1))],
            registry_rows=[([{"channel": "email", "value": _PARTICIPANT}],)],
        )
        arrivals = self._fetch(conn)
        assert [a.message_id for a in arrivals] == ["kw"]   # participant row NOT fetched
        assert all(a.participant_fetched is False for a in arrivals)


# ── enumerate primitive: active_participant_values (distinct, lower-cased, fault-tol) ──
class TestActiveParticipantValues:
    def test_distinct_lowercased_email_set(self):
        conn = _FakeConn(registry_rows=[
            ([{"channel": "email", "value": "A@X.COM"},
              {"channel": "whatsapp", "value": "+41"}],),
            ([{"channel": "email", "value": "a@x.com"},          # dup (case)
              {"channel": "email", "value": "b@y.com"}],),
        ])
        vals = registry_store.active_participant_values(conn, "email")
        assert vals == ["a@x.com", "b@y.com"]                    # distinct + lowered

    def test_error_returns_empty_and_rolls_back(self):
        conn = _FakeConn(registry_rows=[], fail_on="FROM project_registry")
        assert registry_store.active_participant_values(conn, "email") == []
        assert conn.rolled_back >= 1


# ── build_email_ticket: identity tickets a keyword-less participant arrival (branch) ───
class TestBuildTicketIdentity:
    def _arr(self, *, participant_fetched):
        return bridge.EmailArrival(
            message_id="m", thread_id="t", sender_name="CP", sender_email=_PARTICIPANT,
            subject="Quick question", full_body="no keyword here",
            received_date=_dt(1), source="graph", participant_fetched=participant_fetched,
        )

    def test_participant_identity_tickets_without_keyword(self):
        t = bridge.build_email_ticket(self._arr(participant_fetched=True))
        assert t is not None
        assert any("participant identity" in w for w in t.why_ticketed)

    def test_no_keyword_non_participant_still_none(self):
        assert bridge.build_email_ticket(self._arr(participant_fetched=False)) is None


# ─────────────────────────────────────────────────────────────────────────────────────
# TIER 2 — live-PG run_tick acceptance (CI). Auto-skip without TEST_DATABASE_URL / NEON_*.
# ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def partenv(tier_b_test_store, needs_live_pg, monkeypatch):
    """Live harness: source tables + clean airport_tickets / drop-log / watermark /
    project_registry seeded with an ACTIVE project whose participant set contains
    _PARTICIPANT. Master gate ON, participant lane ON, bus post stubbed."""
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
    with admin.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS box5_dropped_signals")
    bridge.ensure_box5_dropped_signals_table(admin)
    registry_store.ensure_project_registry_table(admin)
    with admin.cursor() as cur:
        cur.execute("DELETE FROM airport_tickets")
        cur.execute("DELETE FROM email_messages")
        cur.execute("DELETE FROM email_attachments")
        cur.execute("DELETE FROM box5_dropped_signals")
        cur.execute("DELETE FROM project_registry")
        cur.execute(
            "DELETE FROM trigger_watermarks WHERE source = %s",
            (bridge._WATERMARK_SOURCE,),
        )
        cur.execute(
            "DELETE FROM baker_actions WHERE trigger_source = 'airport_ticketing_bridge'"
        )
        # Seed one ACTIVE project with _PARTICIPANT in its email participant set.
        cur.execute(
            """
            INSERT INTO project_registry
                (project_number, match_key, desk_code, desk_owner, matter_slug,
                 clickup_list_id, participants, aliases, status)
            VALUES ('BB-AUK-001','BBAUK001','BB','baden-baden-desk','aukera',
                    '901524194809', %s::jsonb, '[]'::jsonb, 'active')
            ON CONFLICT (match_key) DO UPDATE SET participants = EXCLUDED.participants
            """,
            (json.dumps([{"channel": "email", "value": _PARTICIPANT}]),),
        )

    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "true")
    monkeypatch.setenv(_LANE_ENV, "true")
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


def _seed(conn, message_id, *, subject, body, sender, received, thread_id=None):
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


def _ticketed_ids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_source_id FROM airport_tickets WHERE raw_source_id IS NOT NULL"
        )
        return {r[0] for r in cur.fetchall()}


def _watermark(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_seen FROM trigger_watermarks WHERE source = %s",
            (bridge._WATERMARK_SOURCE,),
        )
        row = cur.fetchone()
    return row[0] if row else None


# ── AC1 (reachability, live) — participant + no keyword + new thread -> a TICKET ──────
def test_ac1_participant_no_keyword_new_thread_tickets(partenv):
    _seed(partenv, "part_live", subject="Quick question on timing",
          body="Can we align next week?", sender=_PARTICIPANT, received=_dt(1),
          thread_id="brand_new_thread")
    s = bridge.run_tick()
    assert s["ok"] is True
    assert "part_live" in _ticketed_ids(partenv)          # reachable now
    with partenv.cursor() as cur:
        cur.execute(
            "SELECT terminal_status FROM airport_tickets WHERE raw_source_id = 'part_live'"
        )
        assert cur.fetchone()[0] == "TICKET"


# ── AC2 (keyword parity, live) — keyword set unchanged; non-participant miss never tickets
def test_ac2_keyword_set_unchanged(partenv):
    _seed(partenv, "hit_auk", subject="Aukera data room", body="review",
          sender=_STRANGER, received=_dt(2))
    _seed(partenv, "miss_news", subject="Weekly newsletter", body="nothing relevant",
          sender=_STRANGER, received=_dt(2))       # keyword miss, non-participant
    _seed(partenv, "part_live", subject="hello", body="no keyword", sender=_PARTICIPANT,
          received=_dt(1))
    s = bridge.run_tick()
    assert s["ok"] is True
    ids = _ticketed_ids(partenv)
    assert "hit_auk" in ids                # keyword hit tickets exactly as before
    assert "miss_news" not in ids          # non-participant keyword miss still dropped
    assert "part_live" in ids              # participant lane is purely additive


# ── AC3 (union dedup, live) — a both-lanes row yields exactly ONE ticket ──────────────
def test_ac3_both_lanes_single_ticket(partenv):
    _seed(partenv, "dual", subject="Aukera data room", body="review",
          sender=_PARTICIPANT, received=_dt(2))     # keyword AND participant
    s = bridge.run_tick()
    assert s["ok"] is True
    with partenv.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM airport_tickets WHERE raw_source_id = 'dual'")
        assert cur.fetchone()[0] == 1


# ── AC4 (watermark safety, live) — cursor never advances past an un-processed older
#    participant arrival: with cap=1 and participant(older)+keyword(newer), the watermark
#    freezes at the OLDER participant row, not the newer keyword row (no silent drop).
def test_ac4_watermark_frozen_at_unprocessed_participant_row(partenv, monkeypatch):
    monkeypatch.setenv("AIRPORT_TICKETING_MAX_POSTS_PER_TICK", "1")
    t_old, t_new = _dt(3), _dt(1)
    _seed(partenv, "p_old", subject="hello", body="no keyword", sender=_PARTICIPANT,
          received=t_old)
    _seed(partenv, "k_new", subject="Aukera data room", body="review", sender=_STRANGER,
          received=t_new)
    s = bridge.run_tick()
    assert s["ok"] is True
    wm = _watermark(partenv)
    assert wm is not None
    # Global ASC sort put p_old first; cap=1 froze the cursor there. Watermark == t_old
    # (NOT t_new) -> k_new stays >= watermark and is re-fetchable; p_old not stranded.
    assert abs(wm - t_old) < timedelta(seconds=1)
    assert wm < t_new
    # A naive keyword-first concat would have advanced the watermark to t_new and lost
    # p_old (t_old < t_new). The older participant row still tickets this tick.
    assert "p_old" in _ticketed_ids(partenv)


# ── AC5 (fault tolerance, live) — participant lane failure never aborts the tick ──────
def test_ac5_participant_lane_failure_does_not_abort_tick(partenv, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("participant enumerate exploded")
    monkeypatch.setattr(bridge, "active_participant_values", _boom)
    _seed(partenv, "kw_ft", subject="Aukera data room", body="review", sender=_STRANGER,
          received=_dt(2))
    s = bridge.run_tick()
    assert s["ok"] is True
    assert "kw_ft" in _ticketed_ids(partenv)     # keyword ticketing unaffected


# ── AC6 (dark-safe, live) — flag OFF -> participant-only row is never fetched ─────────
def test_ac6_lane_off_participant_row_not_ticketed(partenv, monkeypatch):
    monkeypatch.setenv(_LANE_ENV, "false")
    _seed(partenv, "hit_auk", subject="Aukera data room", body="review",
          sender=_STRANGER, received=_dt(2))
    _seed(partenv, "part_off", subject="hello", body="no keyword", sender=_PARTICIPANT,
          received=_dt(1))
    s = bridge.run_tick()
    assert s["ok"] is True
    ids = _ticketed_ids(partenv)
    assert "hit_auk" in ids                # keyword path unchanged
    assert "part_off" not in ids           # lane off -> not reachable (byte-identical)
