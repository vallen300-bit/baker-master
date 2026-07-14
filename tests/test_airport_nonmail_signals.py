"""BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — Plaud + WhatsApp ticketing lanes (phase 1).

Two tiers:
  * PURE UNIT (no DB): the two flag helpers + build_plaud_ticket / build_whatsapp_ticket
    contract — source_channel/source_id/dedup_key, keyword lane, identity lane
    (matter_slug for Plaud / participant for WA), and the no-match -> None guard.
  * LIVE-PG (``needs_live_pg`` auto-skips without TEST_DATABASE_URL): the vertical seam the
    brief names — insert one fake Plaud transcript + one fake WhatsApp message, run the new
    fetchers (assert exactly one candidate each with the right dedup_key), issue them
    through the SAME spine (one candidate row per source_channel), re-run (dedup -> zero
    new rows), and dry-run mode (logs, inserts nothing, advances no watermark).

Literal pytest only — no "by inspection".
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orchestrator import airport_ticketing_bridge as bridge
from scripts import backfill_airport_ticket_suspected_flight as flight_backfill


# ===========================================================================
# PURE UNIT — no DB
# ===========================================================================
def test_nonmail_flags_default_off(monkeypatch):
    monkeypatch.delenv("AIRPORT_NONMAIL_SOURCES_ENABLED", raising=False)
    monkeypatch.delenv("AIRPORT_NONMAIL_DRY_RUN", raising=False)
    assert bridge.nonmail_sources_enabled() is False
    assert bridge.nonmail_dry_run() is False


def test_nonmail_flags_on(monkeypatch):
    monkeypatch.setenv("AIRPORT_NONMAIL_SOURCES_ENABLED", "true")
    monkeypatch.setenv("AIRPORT_NONMAIL_DRY_RUN", "1")
    assert bridge.nonmail_sources_enabled() is True
    assert bridge.nonmail_dry_run() is True


def _plaud(**over) -> bridge.PlaudArrival:
    base = dict(
        transcript_id="plaud-abc-1",
        title="Aukera Annaberg financing sync",
        summary="Discussed the data room and closing actions.",
        full_transcript="Full transcript body about aukera annaberg.",
        received_at=datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc),
        matter_slug="aukera",
        matter_matched=False,
    )
    base.update(over)
    return bridge.PlaudArrival(**base)


def _wa(**over) -> bridge.WhatsAppArrival:
    base = dict(
        message_id="wa-msg-1",
        sender="41790000000",
        sender_name="Balazs Csepregi",
        chat_id="41790000000@c.us",
        full_text="Quick note on the aukera annaberg closing.",
        received_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        participant_matched=False,
    )
    base.update(over)
    return bridge.WhatsAppArrival(**base)


def test_build_plaud_ticket_keyword_match(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    ticket = bridge.build_plaud_ticket(_plaud(), now=datetime(2026, 7, 3, 12, tzinfo=timezone.utc))
    assert ticket is not None
    assert ticket.source_channel == "plaud"
    assert ticket.source_id == "plaud-abc-1"
    assert ticket.dedup_key == bridge._dedup_key("plaud", "plaud-abc-1", ticket.proposed_desk_slug)
    assert ticket.proposed_desk_slug == "baden-baden-desk"
    assert ticket.urgency_hint == "high"  # keyword lane
    assert any("matched active flight keyword" in w for w in ticket.why_ticketed)
    assert "VALID" in ticket.known_limits[-1]


def test_build_plaud_ticket_matter_lane_only(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    # No keyword anywhere, but fetched via the active-matter lane.
    arrival = _plaud(
        title="Weekly ops",
        summary="no flight terms here",
        full_transcript="nothing relevant",
        matter_slug="aukera",
        matter_matched=True,
    )
    ticket = bridge.build_plaud_ticket(arrival)
    assert ticket is not None
    assert ticket.source_channel == "plaud"
    assert ticket.urgency_hint == "normal"  # identity lane, not keyword
    assert any("registry matter_slug: aukera" in w for w in ticket.why_ticketed)


class _SeqCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None


class _SeqConn:
    def __init__(self, *rowsets):
        self._rowsets = list(rowsets)
        self.rollbacks = 0

    def cursor(self):
        rows = self._rowsets.pop(0) if self._rowsets else []
        return _SeqCursor(rows)

    def rollback(self):
        self.rollbacks += 1


class _BoomConn:
    def __init__(self):
        self.rollbacks = 0

    def cursor(self):
        raise RuntimeError("db unavailable")

    def rollback(self):
        self.rollbacks += 1


def test_flight_for_matter_resolves_project_number(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_FLIGHT", raising=False)
    conn = _SeqConn([("AO-OSK-001",)])
    assert bridge._flight_for_matter("ao", conn) == "AO-OSK-001"


def test_flight_for_matter_falls_back_on_none_unknown_invalid_and_error(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_FLIGHT", raising=False)
    assert bridge._flight_for_matter("ao", None) == "aukera-annaberg-financing"
    assert bridge._flight_for_matter("unknown", _SeqConn([])) == "aukera-annaberg-financing"
    assert bridge._flight_for_matter("ao", _SeqConn([("not-a-flight",)])) == "aukera-annaberg-financing"
    boom = _BoomConn()
    assert bridge._flight_for_matter("ao", boom) == "aukera-annaberg-financing"
    assert boom.rollbacks == 1


def test_build_plaud_ticket_uses_per_matter_flight_when_conn_present(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    monkeypatch.delenv("AIRPORT_TICKETING_FLIGHT", raising=False)
    # First cursor is _desk_for_matter -> ao-desk; second is _flight_for_matter -> AO-OSK-001.
    conn = _SeqConn([("ao-desk",)], [("AO-OSK-001",)])
    arrival = _plaud(
        title="AO weekly ops",
        summary="no flight terms here",
        full_transcript="nothing relevant",
        matter_slug="ao",
        matter_matched=True,
    )
    ticket = bridge.build_plaud_ticket(arrival, conn=conn)
    assert ticket is not None
    assert ticket.proposed_desk_slug == "ao-desk"
    assert ticket.suspected_matter_slug == "ao"
    assert ticket.suspected_flight == "AO-OSK-001"


def test_backfill_planner_registry_and_legacy_dual_match():
    rows = [
        {"id": 1, "suspected_matter_slug": "ao", "suspected_flight": "aukera-annaberg-financing"},
        {"id": 2, "suspected_matter_slug": "lilienmatt", "suspected_flight": "aukera-annaberg-financing"},
        {"id": 3, "suspected_matter_slug": "hagenauer-rg7", "suspected_flight": "aukera-annaberg-financing"},
        {"id": 4, "suspected_matter_slug": "ao", "suspected_flight": "AO-OSK-001"},
    ]
    plans = flight_backfill.plan_ticket_flight_backfill(
        rows,
        matter_to_project={"ao": "AO-OSK-001"},
        legacy_pairs={("lilienmatt", "aukera-annaberg-financing"): "BB-AUK-001"},
    )
    assert [(p.ticket_id, p.new_flight, p.reason) for p in plans] == [
        (1, "AO-OSK-001", "registry_matter"),
        (2, "BB-AUK-001", "legacy_default_matter_flight"),
    ]


def test_backfill_loader_reads_explicit_legacy_snapshot_fields(tmp_path):
    (tmp_path / "BB-AUK-001.json").write_text(
        """
        {
          "project_code": "BB-AUK-001",
          "suspected_flight": "BB-AUK-001",
          "legacy_suspected_flights": ["aukera-annaberg-financing"],
          "legacy_matter_slugs": ["lilienmatt"]
        }
        """
    )
    assert flight_backfill.load_snapshot_legacy_pairs(tmp_path) == {
        ("lilienmatt", "aukera-annaberg-financing"): "BB-AUK-001"
    }


def test_build_plaud_ticket_no_match_returns_none():
    arrival = _plaud(
        title="Weekly ops",
        summary="no flight terms",
        full_transcript="nothing relevant",
        matter_slug="",
        matter_matched=False,
    )
    assert bridge.build_plaud_ticket(arrival) is None


def test_build_whatsapp_ticket_keyword_match(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    ticket = bridge.build_whatsapp_ticket(_wa(), now=datetime(2026, 7, 3, 12, tzinfo=timezone.utc))
    assert ticket is not None
    assert ticket.source_channel == "whatsapp"
    assert ticket.source_id == "wa-msg-1"
    assert ticket.dedup_key == bridge._dedup_key("whatsapp", "wa-msg-1", ticket.proposed_desk_slug)
    assert ticket.urgency_hint == "high"
    assert any("body_preview:" in item for item in ticket.luggage)


def test_build_whatsapp_ticket_participant_lane_only():
    arrival = _wa(full_text="no flight terms here", participant_matched=True)
    ticket = bridge.build_whatsapp_ticket(arrival)
    assert ticket is not None
    assert ticket.source_channel == "whatsapp"
    assert ticket.urgency_hint == "normal"
    assert any("participant identity" in w for w in ticket.why_ticketed)


def test_build_whatsapp_ticket_no_match_returns_none():
    arrival = _wa(full_text="no flight terms here", participant_matched=False)
    assert bridge.build_whatsapp_ticket(arrival) is None


# ---------------------------------------------------------------------------
# DATA_OPS_AO_PLAUD_BACKFILL_WA_NOISE_1 task 6 — WA identity-only ticket suppression
# (config reader + predicates; pure unit, no DB). build_whatsapp_ticket is UNCHANGED —
# suppression happens in _run_nonmail_lane via suppress_fn, so these test the policy.
# ---------------------------------------------------------------------------
def test_wa_identity_ticket_max_age_hours_reader(monkeypatch):
    monkeypatch.delenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", raising=False)
    assert bridge._wa_identity_ticket_max_age_hours() == 0  # default: suppress all
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "168")
    assert bridge._wa_identity_ticket_max_age_hours() == 168
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "-1")
    assert bridge._wa_identity_ticket_max_age_hours() == -1  # disabled (legacy)
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "not-an-int")
    assert bridge._wa_identity_ticket_max_age_hours() == 0  # garbage -> default
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "99999")
    assert bridge._wa_identity_ticket_max_age_hours() == 8760  # bounded at 1y


def test_wa_identity_only_predicate(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_KEYWORDS", raising=False)
    # participant identity + NO keyword -> identity-only
    assert bridge._wa_identity_only(_wa(full_text="call you later", participant_matched=True)) is True
    # participant identity + keyword hit -> NOT identity-only (keyword always tickets)
    assert bridge._wa_identity_only(_wa(full_text="aukera closing", participant_matched=True)) is False
    # not a participant fetch -> never identity-only
    assert bridge._wa_identity_only(_wa(full_text="call you later", participant_matched=False)) is False


def test_wa_identity_suppressed_default_all(monkeypatch):
    monkeypatch.delenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", raising=False)
    now = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    # even a same-day identity-only arrival is suppressed under the default (#6619)
    fresh = _wa(full_text="call later", participant_matched=True,
                received_at=datetime(2026, 7, 4, 11, tzinfo=timezone.utc))
    assert bridge._wa_identity_suppressed(fresh, now) is True


def test_wa_identity_suppressed_age_ceiling(monkeypatch):
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "168")
    now = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    old = _wa(full_text="call later", participant_matched=True,
              received_at=datetime(2026, 6, 8, 10, tzinfo=timezone.utc))  # >168h
    young = _wa(full_text="call later", participant_matched=True,
                received_at=datetime(2026, 7, 4, 6, tzinfo=timezone.utc))  # 6h
    assert bridge._wa_identity_suppressed(old, now) is True
    assert bridge._wa_identity_suppressed(young, now) is False


def test_wa_identity_suppressed_keyword_exempt(monkeypatch):
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "0")  # suppress-all
    now = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    # keyword match is never identity-only -> never suppressed, even under suppress-all
    kw = _wa(full_text="aukera closing", participant_matched=True,
             received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert bridge._wa_identity_suppressed(kw, now) is False


def test_wa_identity_suppressed_disabled_escape_hatch(monkeypatch):
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "-1")
    now = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    ident = _wa(full_text="call later", participant_matched=True,
                received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert bridge._wa_identity_suppressed(ident, now) is False  # legacy: still tickets


def test_wa_identity_suppressed_null_received_at(monkeypatch):
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", "168")
    now = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    ident = _wa(full_text="call later", participant_matched=True, received_at=None)
    # cannot prove recency under an age-ceiling -> suppress (noise-reduction default)
    assert bridge._wa_identity_suppressed(ident, now) is True


# ---------------------------------------------------------------------------
# TICKETING_AO_IDENTITY_REROUTE_1 (lead ruling #10238, Option A) — AO identity-only WA
# routes to the ao-desk review lane instead of being suppressed / dumped on the BB default.
# Pure unit (DB-free via _SeqConn); the live-PG fetch tagging test is in the LIVE-PG section.
# ---------------------------------------------------------------------------
def test_wa_identity_route_matters_reader(monkeypatch):
    monkeypatch.delenv("AIRPORT_WA_IDENTITY_ROUTE_MATTERS", raising=False)
    assert bridge._wa_identity_route_matters() == ("ao",)  # default
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_ROUTE_MATTERS", "ao, origination")
    assert bridge._wa_identity_route_matters() == ("ao", "origination")
    monkeypatch.setenv("AIRPORT_WA_IDENTITY_ROUTE_MATTERS", "   ")
    assert bridge._wa_identity_route_matters() == ("ao",)  # blank -> default


def test_wa_identity_route_map_pure(monkeypatch):
    # one ACTIVE 'ao' row (two WA participants + an email participant) + a non-route 'aukera' row.
    rows = [
        ("ao", [
            {"channel": "whatsapp", "value": "35799492642@c.us"},
            {"channel": "whatsapp", "value": "41799605092@c.us"},
            {"channel": "email", "value": "cpohanis@brisengroup.com"},
        ]),
        ("aukera", [{"channel": "whatsapp", "value": "49999@c.us"}]),
    ]
    m = bridge._wa_identity_route_map(_SeqConn(rows), ("ao",))
    assert m == {"35799492642@c.us": "ao", "41799605092@c.us": "ao"}  # email + non-route excluded
    assert bridge._wa_identity_route_map(None, ("ao",)) == {}  # no conn -> {}
    assert bridge._wa_identity_route_map(_SeqConn(rows), ()) == {}  # no route matters -> {}
    boom = _BoomConn()
    assert bridge._wa_identity_route_map(boom, ("ao",)) == {}  # fault-tolerant
    assert boom.rollbacks == 1


def test_wa_identity_suppressed_route_matter_exempt(monkeypatch):
    monkeypatch.delenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", raising=False)  # suppress-all
    now = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    recv = datetime(2026, 7, 13, 11, tzinfo=timezone.utc)
    # AO-route participant identity-only WA -> NEVER suppressed (money/route-relevant, not noise)
    routed = _wa(full_text="2.3m arrives tomorrow", participant_matched=True,
                 identity_route_matter="ao", received_at=recv)
    assert bridge._wa_identity_suppressed(routed, now) is False
    # regression: the SAME shape without the route tag stays suppressed (BB/movie untouched)
    plain = _wa(full_text="2.3m arrives tomorrow", participant_matched=True,
                identity_route_matter="", received_at=recv)
    assert bridge._wa_identity_suppressed(plain, now) is True


def test_build_whatsapp_ticket_ao_identity_route_lane(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)   # global desk = baden-baden-desk
    monkeypatch.delenv("AIRPORT_TICKETING_FLIGHT", raising=False)
    monkeypatch.delenv("AIRPORT_TICKETING_KEYWORDS", raising=False)
    # Pohanis/Director sender shape: identity-only (no keyword), tagged 'ao' at fetch. Cursor
    # order: _sender_matter_set (empty) -> _desk_for_matter('ao')=ao-desk -> _flight_for_matter=AO-OSK-001.
    conn = _SeqConn([], [("ao-desk",)], [("AO-OSK-001",)])
    arrival = _wa(
        message_id="wa-ao-1",
        sender="35799492642@c.us",
        sender_name="Constantinos Pohanis",
        chat_id="35799492642@c.us",
        full_text="2.3m will arrive tomorrow, Eli will update me on what to do with the money",
        participant_matched=True,
        identity_route_matter="ao",
    )
    ticket = bridge.build_whatsapp_ticket(arrival, conn=conn)
    assert ticket is not None
    assert ticket.proposed_desk_slug == "ao-desk"        # AO review lane, NOT baden-baden-desk
    assert ticket.suspected_matter_slug == "ao"
    assert ticket.suspected_flight == "AO-OSK-001"       # AO flight, NOT aukera-annaberg-financing
    assert ticket.review_reason == bridge.REVIEW_REASON_IDENTITY_ONLY  # still a REVIEW ticket (#5035)
    assert any("identity-route review lane" in w for w in ticket.why_ticketed)


def test_build_whatsapp_ticket_identity_only_no_route_stays_lead(monkeypatch):
    """Regression: an identity-only WA with NO route tag stays unassigned in lead review."""
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    monkeypatch.delenv("AIRPORT_TICKETING_FLIGHT", raising=False)
    monkeypatch.delenv("AIRPORT_TICKETING_MATTER_SLUG", raising=False)
    conn = _SeqConn([])  # only _sender_matter_set touches the conn; review lane is conn-free
    arrival = _wa(full_text="call you later", participant_matched=True, identity_route_matter="")
    ticket = bridge.build_whatsapp_ticket(arrival, conn=conn)
    assert ticket is not None
    assert ticket.proposed_desk_slug == "lead"
    assert ticket.suspected_matter_slug == ""
    assert ticket.suspected_flight == ""
    assert ticket.review_reason == bridge.REVIEW_REASON_IDENTITY_ONLY


def test_build_whatsapp_ticket_route_desk_unresolved_falls_to_lead_not_bb(monkeypatch):
    """Defense-in-depth: if the route matter's desk does NOT resolve to a distinct valid desk
    (_desk_for_matter returns the global BB fallback), a route-tagged arrival falls to the lead
    review lane — NEVER the global baden-baden-desk (the exact mis-route being fixed)."""
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)  # global = baden-baden-desk
    # Cursor order: _sender_matter_set (empty) -> desk_owner_for_matter('ao') returns [] -> None
    # -> _desk_for_matter falls back to global baden-baden-desk == global_desk -> guard -> lead.
    conn = _SeqConn([], [])
    arrival = _wa(full_text="Eli money movement", participant_matched=True, identity_route_matter="ao")
    ticket = bridge.build_whatsapp_ticket(arrival, conn=conn)
    assert ticket is not None
    assert ticket.proposed_desk_slug == "lead"
    assert ticket.proposed_desk_slug != "baden-baden-desk"


def test_dedup_keys_distinct_per_channel():
    same_id, desk = "shared-id", "baden-baden-desk"
    email_k = bridge._dedup_key("email", same_id, desk)
    plaud_k = bridge._dedup_key("plaud", same_id, desk)
    wa_k = bridge._dedup_key("whatsapp", same_id, desk)
    assert len({email_k, plaud_k, wa_k}) == 3


# ===========================================================================
# LIVE-PG — real Plaud/WhatsApp/registry/airport_tickets round-trip
# ===========================================================================
def _fake_bus_ok(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "post_ticket_to_bus",
        lambda ticket: {"ok": True, "message_id": 1, "thread_id": "test-thread"},
    )


@pytest.fixture
def nm_conn(needs_live_pg, monkeypatch):
    """Live-PG harness: ensure the three source tables + the registry + airport_tickets,
    clean fixture rows, seed one ACTIVE registry row (matter_slug='aukera' + a WhatsApp
    participant), and fake the bus post. Yields a psycopg2 connection."""
    import psycopg2
    from memory.store_back import SentinelStoreBack
    from kbl.project_registry_store import ensure_project_registry_table, register_project

    conn = psycopg2.connect(needs_live_pg)
    conn.autocommit = False

    bridge.ensure_airport_ticket_table(conn)
    ensure_project_registry_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meeting_transcripts (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, meeting_date TIMESTAMPTZ,
                duration TEXT, organizer TEXT, participants TEXT, summary TEXT,
                full_transcript TEXT, source TEXT NOT NULL DEFAULT 'fireflies',
                matter_slug TEXT, ingested_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id TEXT PRIMARY KEY, sender TEXT, sender_name TEXT, chat_id TEXT,
                full_text TEXT, timestamp TIMESTAMPTZ, is_director BOOLEAN DEFAULT FALSE,
                ingested_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute("DELETE FROM meeting_transcripts WHERE id LIKE 'nmtest-%'")
        cur.execute("DELETE FROM whatsapp_messages WHERE id LIKE 'nmtest-%'")
        cur.execute("DELETE FROM airport_tickets WHERE source_channel IN ('plaud','whatsapp')")
    conn.commit()

    register_project(
        conn,
        project_number="BB-AUK-001",
        desk_owner="baden-baden-desk",
        matter_slug="aukera",
        participants=[{"channel": "whatsapp", "value": "41790000000"}],
    )
    conn.commit()

    monkeypatch.setenv("AIRPORT_TICKETING_DESK", "baden-baden-desk")
    _fake_bus_ok(monkeypatch)
    yield conn
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meeting_transcripts WHERE id LIKE 'nmtest-%'")
            cur.execute("DELETE FROM whatsapp_messages WHERE id LIKE 'nmtest-%'")
        conn.commit()
    finally:
        conn.close()


def _insert_plaud(conn, tid, *, title, summary="", transcript="", matter=None, when=None):
    when = when or datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meeting_transcripts (id, title, summary, full_transcript, "
            "source, matter_slug, meeting_date) VALUES (%s,%s,%s,%s,'plaud',%s,%s)",
            (tid, title, summary, transcript, matter, when),
        )
    conn.commit()


def _insert_wa(conn, mid, *, sender, chat_id, text, when=None):
    when = when or datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO whatsapp_messages (id, sender, sender_name, chat_id, full_text, "
            "timestamp) VALUES (%s,%s,%s,%s,%s,%s)",
            (mid, sender, "Test Sender", chat_id, text, when),
        )
    conn.commit()


def _count(conn, channel):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM airport_tickets WHERE source_channel = %s", (channel,)
        )
        return cur.fetchone()[0]


def test_fetch_plaud_arrivals_keyword_and_matter_lanes(nm_conn):
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    _insert_plaud(nm_conn, "nmtest-p-kw", title="Aukera closing", summary="s", transcript="t", matter=None)
    _insert_plaud(nm_conn, "nmtest-p-matter", title="Weekly ops", summary="no terms", transcript="none", matter="aukera")
    _insert_plaud(nm_conn, "nmtest-p-none", title="Weekly ops", summary="no terms", transcript="none", matter=None)

    got = bridge.fetch_plaud_arrivals(nm_conn, since=since, limit=50)
    ids = {a.transcript_id for a in got}
    assert "nmtest-p-kw" in ids
    assert "nmtest-p-matter" in ids
    assert "nmtest-p-none" not in ids
    matter_row = next(a for a in got if a.transcript_id == "nmtest-p-matter")
    assert matter_row.matter_matched is True
    kw_row = next(a for a in got if a.transcript_id == "nmtest-p-kw")
    assert kw_row.matter_matched is False


def test_fetch_whatsapp_arrivals_keyword_and_participant_lanes(nm_conn):
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    _insert_wa(nm_conn, "nmtest-w-kw", sender="41799999999", chat_id="x@c.us", text="aukera update")
    _insert_wa(nm_conn, "nmtest-w-part", sender="41790000000", chat_id="41790000000@c.us", text="no terms here")
    _insert_wa(nm_conn, "nmtest-w-none", sender="41798888888", chat_id="y@c.us", text="no terms here")

    got = bridge.fetch_whatsapp_arrivals(nm_conn, since=since, limit=50)
    ids = {a.message_id for a in got}
    assert "nmtest-w-kw" in ids
    assert "nmtest-w-part" in ids
    assert "nmtest-w-none" not in ids
    part_row = next(a for a in got if a.message_id == "nmtest-w-part")
    assert part_row.participant_matched is True


def test_fetch_whatsapp_arrivals_tags_ao_identity_route(nm_conn, monkeypatch):
    """LIVE-PG: TICKETING_AO_IDENTITY_REROUTE_1 end-to-end at fetch. An identity-only WA from a
    registered AO-OSK-001 participant is tagged identity_route_matter='ao'; a non-AO participant
    (the fixture's BB matter) identity-only WA is NOT tagged (BB/movie routing untouched)."""
    from kbl.project_registry_store import register_project

    monkeypatch.delenv("AIRPORT_WA_IDENTITY_ROUTE_MATTERS", raising=False)  # default 'ao'
    register_project(
        nm_conn,
        project_number="AO-OSK-001",
        desk_owner="ao-desk",
        matter_slug="ao",
        participants=[{"channel": "whatsapp", "value": "35799492642@c.us"}],
    )
    nm_conn.commit()

    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # AO participant, identity-only (no keyword) -> tagged 'ao'.
    _insert_wa(nm_conn, "nmtest-w-ao", sender="35799492642@c.us", chat_id="35799492642@c.us",
               text="2.3m will arrive tomorrow, Eli will update me")
    # BB participant (fixture 41790000000), identity-only -> NOT tagged.
    _insert_wa(nm_conn, "nmtest-w-bbid", sender="41790000000", chat_id="41790000000@c.us",
               text="no terms here")

    got = bridge.fetch_whatsapp_arrivals(nm_conn, since=since, limit=50)
    ao = next(a for a in got if a.message_id == "nmtest-w-ao")
    bb = next(a for a in got if a.message_id == "nmtest-w-bbid")
    assert ao.participant_matched is True
    assert ao.identity_route_matter == "ao"
    assert bb.participant_matched is True
    assert bb.identity_route_matter == ""


# ===========================================================================
# AO_FLIGHT_PROD_TICKET_ROUTING_1 — per-matter desk routing via project_registry
# ===========================================================================
def test_desk_for_matter_no_conn_global_fallback(monkeypatch):
    """PURE UNIT (DB-free): with no conn, _desk_for_matter never touches the registry and
    returns the global _desk_slug() — byte-identical to today's routing."""
    monkeypatch.setenv("AIRPORT_TICKETING_DESK", "baden-baden-desk")
    assert bridge._desk_for_matter("ao", conn=None) == "baden-baden-desk"
    assert bridge._desk_for_matter(None, conn=None) == "baden-baden-desk"
    assert bridge._desk_for_matter("", conn=None) == "baden-baden-desk"


def test_desk_for_matter_registry_routes_by_matter(nm_conn):
    """LIVE-PG: registry desk_owner drives routing. AO matter -> ao-desk; the fixture's
    BB matter (aukera) -> baden-baden-desk; an unmapped matter -> global fallback."""
    from kbl.project_registry_store import register_project

    register_project(
        nm_conn,
        project_number="AO-OSK-001",
        desk_owner="ao-desk",
        matter_slug="ao",
    )
    nm_conn.commit()
    assert bridge._desk_for_matter("ao", conn=nm_conn) == "ao-desk"
    assert bridge._desk_for_matter("aukera", conn=nm_conn) == "baden-baden-desk"
    assert bridge._desk_for_matter("no-such-matter", conn=nm_conn) == "baden-baden-desk"


def test_build_plaud_ticket_routes_ao_by_registry(nm_conn):
    """AC1 + AC2: an AO-manifest Plaud arrival mints proposed_desk_slug='ao-desk' while a
    BB-matter Plaud arrival still mints to baden-baden-desk."""
    from kbl.project_registry_store import register_project

    register_project(
        nm_conn,
        project_number="AO-OSK-001",
        desk_owner="ao-desk",
        matter_slug="ao",
    )
    nm_conn.commit()

    # AC1 — AO-manifest arrival (identity lane, no keyword) boards ao-desk.
    ao_arrival = _plaud(
        title="AO weekly sync",
        summary="no flight terms here",
        full_transcript="nothing relevant",
        matter_slug="ao",
        matter_matched=True,
    )
    ao_ticket = bridge.build_plaud_ticket(ao_arrival, conn=nm_conn)
    assert ao_ticket is not None
    assert ao_ticket.proposed_desk_slug == "ao-desk"
    assert ao_ticket.suspected_matter_slug == "ao"
    assert ao_ticket.dedup_key == bridge._dedup_key("plaud", ao_arrival.transcript_id, "ao-desk")

    # AC2 regression — BB-matter arrival still boards baden-baden-desk.
    bb_arrival = _plaud(matter_slug="aukera")  # 'aukera' keyword in default title/body
    bb_ticket = bridge.build_plaud_ticket(bb_arrival, conn=nm_conn)
    assert bb_ticket is not None
    assert bb_ticket.proposed_desk_slug == "baden-baden-desk"

    # AC2 regression — an unmapped matter falls back to the global desk.
    unmapped = _plaud(
        transcript_id="plaud-unmapped-1",
        title="aukera annaberg note",
        matter_slug="no-such-matter",
    )
    unmapped_ticket = bridge.build_plaud_ticket(unmapped, conn=nm_conn)
    assert unmapped_ticket is not None
    assert unmapped_ticket.proposed_desk_slug == "baden-baden-desk"


def test_nonmail_vertical_candidate_and_idempotent(nm_conn):
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    _insert_plaud(nm_conn, "nmtest-p-v", title="Aukera sync", summary="s", transcript="t", matter="aukera")
    _insert_wa(nm_conn, "nmtest-w-v", sender="41790000000", chat_id="41790000000@c.us", text="aukera note")

    plaud_arr = bridge.fetch_plaud_arrivals(nm_conn, since=since, limit=50)
    wa_arr = bridge.fetch_whatsapp_arrivals(nm_conn, since=since, limit=50)
    assert len([a for a in plaud_arr if a.transcript_id == "nmtest-p-v"]) == 1
    assert len([a for a in wa_arr if a.message_id == "nmtest-w-v"]) == 1

    pt = bridge.build_plaud_ticket(next(a for a in plaud_arr if a.transcript_id == "nmtest-p-v"))
    wt = bridge.build_whatsapp_ticket(next(a for a in wa_arr if a.message_id == "nmtest-w-v"))
    assert pt.dedup_key == bridge._dedup_key("plaud", "nmtest-p-v", "baden-baden-desk")
    assert wt.dedup_key == bridge._dedup_key("whatsapp", "nmtest-w-v", "baden-baden-desk")

    assert bridge.issue_ticket(pt, nm_conn).get("ok") is True
    nm_conn.commit()
    assert bridge.issue_ticket(wt, nm_conn).get("ok") is True
    nm_conn.commit()
    assert _count(nm_conn, "plaud") == 1
    assert _count(nm_conn, "whatsapp") == 1

    # Re-issue the SAME tickets — dedup_key UNIQUE -> duplicate skip, no new rows.
    assert bridge.issue_ticket(pt, nm_conn).get("skipped") is True
    nm_conn.commit()
    assert bridge.issue_ticket(wt, nm_conn).get("skipped") is True
    nm_conn.commit()
    assert _count(nm_conn, "plaud") == 1
    assert _count(nm_conn, "whatsapp") == 1


def test_dry_run_inserts_nothing(nm_conn, monkeypatch):
    _insert_plaud(nm_conn, "nmtest-p-dry", title="Aukera sync", summary="s", transcript="t", matter="aukera")
    current = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    stats = bridge._run_nonmail_lane(
        nm_conn,
        source_label="plaud",
        fetch_fn=bridge.fetch_plaud_arrivals,
        build_fn=bridge.build_plaud_ticket,
        watermark_source=bridge._WATERMARK_SOURCE_PLAUD,
        current=current,
        cap=5,
        dry_run=True,
    )
    assert stats["issued"] == 0


def test_run_nonmail_lane_suppresses_identity_wa_and_advances_watermark(nm_conn, monkeypatch):
    """Task 6 + 3b + 7: an identity-only WA arrival is NOT ticketed but the watermark
    ADVANCES past it (so it never re-tickets next tick), while a keyword match from the
    same participant STILL tickets. In-memory watermark to avoid trigger_state coupling."""
    monkeypatch.delenv("AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS", raising=False)  # default: suppress all
    wm: dict = {}
    monkeypatch.setattr(bridge, "trigger_state_watermark_raw", lambda src: wm.get(src))
    monkeypatch.setattr(bridge, "trigger_state_set_watermark", lambda src, ts: wm.__setitem__(src, ts))

    # Dates MUST fall inside _run_nonmail_lane's lookback floor (current - nonmail_lookback_hours,
    # clamped <=14d) or fetch_whatsapp_arrivals never returns them. Keep them a few hours before current.
    # identity-only: registered participant (41790000000), NO keyword
    _insert_wa(nm_conn, "nmtest-w-idonly", sender="41790000000", chat_id="41790000000@c.us",
               text="call you later", when=datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc))
    # keyword match from the SAME participant -> must still ticket (never suppressed)
    _insert_wa(nm_conn, "nmtest-w-kw", sender="41790000000", chat_id="41790000000@c.us",
               text="aukera closing note", when=datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc))

    current = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    kwargs = dict(
        source_label="whatsapp",
        fetch_fn=bridge.fetch_whatsapp_arrivals,
        build_fn=bridge.build_whatsapp_ticket,
        watermark_source=bridge._WATERMARK_SOURCE_WHATSAPP,
        current=current,
        cap=50,
        dry_run=False,
        suppress_fn=bridge._wa_identity_suppressed,
    )
    stats = bridge._run_nonmail_lane(nm_conn, **kwargs)

    assert stats["suppressed"] >= 1            # identity-only suppressed
    assert stats["issued"] == 1               # only the keyword arrival ticketed
    assert _count(nm_conn, "whatsapp") == 1   # no identity-only ticket row
    # watermark advanced past BOTH arrivals (both handled: suppressed + issued)
    assert wm[bridge._WATERMARK_SOURCE_WHATSAPP] >= datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc)

    # 3b: a SECOND tick mints no new ticket (idempotent; no re-ticket churn)
    stats2 = bridge._run_nonmail_lane(nm_conn, **kwargs)
    assert stats2["issued"] == 0
    assert _count(nm_conn, "whatsapp") == 1
    assert _count(nm_conn, "plaud") == 0


# ===========================================================================
# AO_FLIGHT_PROD_TICKET_ROUTING_1 — G3 fix round: per-matter desk FALLBACK safety
# (codex gate/ao-ticket-routing-g3 #6979 F2). A registry desk_owner that is not a
# wired bus recipient must fall back to the global desk, never mint a bogus desk.
# ===========================================================================
def test_desk_for_matter_matter_without_registry_row_falls_back_global(nm_conn):
    """F2 (a): a matter with NO active registry row (the AO state at deploy, before its row
    is seeded — F1) resolves to the GLOBAL desk. Inert-safe: never a bogus desk, never a
    freeze while the row is absent."""
    with nm_conn.cursor() as cur:
        cur.execute("DELETE FROM project_registry WHERE LOWER(matter_slug) = 'ao'")
    nm_conn.commit()
    assert bridge._desk_for_matter("ao", conn=nm_conn) == "baden-baden-desk"


def _fake_bus_recipient_guarded(monkeypatch):
    """Bus fake that mirrors post_ticket_to_bus's REAL recipient guard (bridge :1830-1832):
    an unresolvable / reserved desk is rejected as invalid_recipient (so a bogus desk truly
    reproduces the reported bus_failed cursor freeze); a valid desk succeeds. Overrides the
    fixture's blanket _fake_bus_ok for this test only."""

    def _post(ticket):
        recipient = bridge.resolve_owner_slug(ticket.proposed_desk_slug)
        if not recipient or recipient in bridge.RESERVED_RECIPIENTS:
            return {"ok": False, "error": "invalid_recipient"}
        return {"ok": True, "message_id": 1, "thread_id": "test-thread"}

    monkeypatch.setattr(bridge, "post_ticket_to_bus", _post)


def test_desk_for_matter_garbage_owner_falls_back_and_cursor_advances(nm_conn, monkeypatch):
    """F2 (b) BUG REPRO: an active registry row whose desk_owner is not a wired bus recipient
    ('ghost-desk-unwired') must resolve to the GLOBAL desk, not the raw string. Pre-fix
    ``resolve_owner_slug(owner) or owner`` passed the raw owner through, minted a bogus desk,
    the bus rejected it (invalid_recipient), and the plaud cursor FROZE on bus_failed. Post-
    fix: global fallback -> the ticket boards baden-baden-desk, the bus accepts it, and the
    cursor ADVANCES past the arrival."""
    from kbl.project_registry_store import desk_owner_for_matter

    # Isolate matter 'ao' to exactly one active row carrying an unresolvable desk_owner.
    with nm_conn.cursor() as cur:
        cur.execute("DELETE FROM project_registry WHERE LOWER(matter_slug) = 'ao'")
        cur.execute(
            "INSERT INTO project_registry "
            "(project_number, match_key, desk_code, desk_owner, matter_slug, status) "
            "VALUES (%s, %s, %s, %s, %s, 'active')",
            ("AO-GHOST-001", "ao-ghost-match-key", "AO", "ghost-desk-unwired", "ao"),
        )
    nm_conn.commit()
    try:
        # The registry hands back the garbage owner unambiguously (single active row)...
        assert desk_owner_for_matter(nm_conn, "ao") == "ghost-desk-unwired"
        # ...and it is genuinely unresolvable as a bus recipient (the trigger for the bug).
        assert bridge.resolve_owner_slug("ghost-desk-unwired") is None
        # (b1) direct: unresolvable owner -> GLOBAL fallback (FAILS pre-fix: returned raw owner).
        assert bridge._desk_for_matter("ao", conn=nm_conn) == "baden-baden-desk"

        # (b2) end-to-end: recipient-guarded bus + in-memory watermark so a bogus desk would
        # genuinely freeze the cursor. Post-fix it must issue to the global desk and advance.
        _fake_bus_recipient_guarded(monkeypatch)
        wm: dict = {}
        monkeypatch.setattr(bridge, "trigger_state_watermark_raw", lambda src: wm.get(src))
        monkeypatch.setattr(
            bridge, "trigger_state_set_watermark", lambda src, ts: wm.__setitem__(src, ts)
        )
        arrival_at = datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc)
        _insert_plaud(
            nm_conn, "nmtest-p-ghost", title="AO ghost sync", summary="no terms",
            transcript="none", matter="ao", when=arrival_at,
        )
        current = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
        stats = bridge._run_nonmail_lane(
            nm_conn,
            source_label="plaud",
            fetch_fn=bridge.fetch_plaud_arrivals,
            build_fn=bridge.build_plaud_ticket,
            watermark_source=bridge._WATERMARK_SOURCE_PLAUD,
            current=current,
            cap=50,
            dry_run=False,
        )
        assert stats["issued"] == 1            # minted (global desk), not frozen
        assert stats["failed"] == 0            # no bus_failed
        # cursor advanced past the arrival (KeyError here would mean a freeze -> pre-fix fail)
        assert wm[bridge._WATERMARK_SOURCE_PLAUD] >= arrival_at
        # the minted ticket boards the GLOBAL desk, never the ghost desk
        with nm_conn.cursor() as cur:
            cur.execute(
                "SELECT proposed_desk_slug FROM airport_tickets "
                "WHERE source_channel = 'plaud' AND source_id = %s",
                ("nmtest-p-ghost",),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "baden-baden-desk"
    finally:
        with nm_conn.cursor() as cur:
            cur.execute("DELETE FROM project_registry WHERE project_number = 'AO-GHOST-001'")
            cur.execute("DELETE FROM airport_tickets WHERE source_id = 'nmtest-p-ghost'")
        nm_conn.commit()
