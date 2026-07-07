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
