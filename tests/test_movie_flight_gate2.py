"""MOVIE_FLIGHT_GATE2_ACTIVATION_1 — two-factor per-matter routing tests.

Slice 1: the PURE resolver core (keyword->matter map + factor-B content set + two-factor
decision). No DB, no I/O. Director ruling #8154 (relayed lead #8154) + sign-off #8165.
"""
from __future__ import annotations

from orchestrator import airport_ticketing_bridge as bridge


# ---- Factor B: content keyword -> matter set ------------------------------------------------

def test_content_matter_set_movie_terms_map_to_movie():
    for term in ("Mandarin Oriental", "MOHG", "mo-vie", "MO Vienna"):
        assert bridge._content_matter_set(term, "") == {"movie"}, term


def test_content_matter_set_aukera_maps_to_aukera():
    assert bridge._content_matter_set("Aukera data room", "") == {"aukera"}


def test_content_matter_set_no_keyword_is_empty():
    assert bridge._content_matter_set("Weekly newsletter", "nothing relevant here") == set()


def test_content_matter_set_both_matters_when_both_present():
    got = bridge._content_matter_set("Mandarin Oriental + Aukera update", "")
    assert got == {"movie", "aukera"}


def test_content_matter_set_riemergasse_is_not_mapped():
    # lead #8165 Q2: riemergasse/rg7 deliberately excluded (building-address collision).
    assert bridge._content_matter_set("Riemergasse 7 works + RG7", "") == set()


# ---- Two-factor resolver --------------------------------------------------------------------

def test_two_factor_corroborated_single_matter_routes():
    assert bridge._two_factor_matter({"movie"}, {"movie"}, participant_fetched=True) == ("movie", "")


def test_two_factor_corroborates_regardless_of_participant_flag():
    # A keyword-lane arrival (participant_fetched=False) from a registered sender still corroborates.
    assert bridge._two_factor_matter({"aukera"}, {"aukera"}, participant_fetched=False) == ("aukera", "")


def test_two_factor_multi_matter_sender_resolved_by_content():
    # Director's Buchwalder example: sender in MOVIE + AO, MOVIE content -> MOVIE.
    assert bridge._two_factor_matter({"movie", "ao"}, {"movie"}, participant_fetched=True) == ("movie", "")


def test_two_factor_identity_only_goes_to_review():
    assert bridge._two_factor_matter({"movie"}, set(), participant_fetched=True) == (
        None,
        bridge.REVIEW_REASON_IDENTITY_ONLY,
    )


def test_two_factor_conflict_goes_to_review():
    # Identity says movie, content says aukera -> disjoint -> conflict.
    assert bridge._two_factor_matter({"movie"}, {"aukera"}, participant_fetched=True) == (
        None,
        bridge.REVIEW_REASON_CONFLICT,
    )


def test_two_factor_multi_match_goes_to_review():
    assert bridge._two_factor_matter({"movie", "aukera"}, {"movie", "aukera"}, participant_fetched=True) == (
        None,
        bridge.REVIEW_REASON_MULTI_MATCH,
    )


def test_two_factor_keyword_lane_no_identity_keeps_global():
    # Unregistered sender (A empty), content matches but no corroboration, not participant-fetched
    # -> (None, "") = today's global-desk behavior. This is the lilienmatt-regression shape.
    assert bridge._two_factor_matter(set(), {"movie"}, participant_fetched=False) == (None, "")


def test_two_factor_nothing_keeps_global():
    assert bridge._two_factor_matter(set(), set(), participant_fetched=False) == (None, "")


def test_review_desk_is_lead_and_not_reserved():
    from orchestrator.dispatcher import RESERVED_RECIPIENTS

    assert bridge._REVIEW_DESK == "lead"
    assert bridge._REVIEW_DESK not in RESERVED_RECIPIENTS


# ---- Factor A: sender -> registered-matter set (fake conn, no live DB) -----------------------

class _FakeCursor:
    def __init__(self, rows, raise_on_execute=False):
        self._rows = rows
        self._raise = raise_on_execute

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        if self._raise:
            raise RuntimeError("boom")

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows, raise_on_execute=False):
        self._rows = rows
        self._raise = raise_on_execute
        self.rolled_back = False

    def cursor(self):
        return _FakeCursor(self._rows, self._raise)

    def rollback(self):
        self.rolled_back = True


_REG_ROWS = [
    ("movie", [{"channel": "email", "value": "andrey@aelioholding.com"},
               {"channel": "whatsapp", "value": "491736903746"}]),
    ("aukera", [{"channel": "email", "value": "balazs.csepregi@brisengroup.com"}]),
    ("ao", [{"channel": "email", "value": "andrey@aelioholding.com"}]),  # multi-matter sender
]


def test_sender_matter_set_none_conn_is_empty():
    assert bridge._sender_matter_set("andrey@aelioholding.com", conn=None) == set()


def test_sender_matter_set_empty_sender_is_empty():
    assert bridge._sender_matter_set("", conn=_FakeConn(_REG_ROWS)) == set()


def test_sender_matter_set_single_matter():
    assert bridge._sender_matter_set(
        "balazs.csepregi@brisengroup.com", conn=_FakeConn(_REG_ROWS)
    ) == {"aukera"}


def test_sender_matter_set_is_case_insensitive():
    assert bridge._sender_matter_set(
        "Balazs.Csepregi@BrisenGroup.com", conn=_FakeConn(_REG_ROWS)
    ) == {"aukera"}


def test_sender_matter_set_multi_matter_sender():
    # andrey is registered in BOTH movie and ao -> factor A is the multi-set; content disambiguates.
    assert bridge._sender_matter_set(
        "andrey@aelioholding.com", conn=_FakeConn(_REG_ROWS)
    ) == {"movie", "ao"}


def test_sender_matter_set_channel_scoping():
    # The whatsapp handle must not match on the email channel.
    assert bridge._sender_matter_set("491736903746", conn=_FakeConn(_REG_ROWS), channel="email") == set()
    assert bridge._sender_matter_set("491736903746", conn=_FakeConn(_REG_ROWS), channel="whatsapp") == {"movie"}


def test_sender_matter_set_unknown_sender():
    assert bridge._sender_matter_set("stranger@example.com", conn=_FakeConn(_REG_ROWS)) == set()


def test_sender_matter_set_fault_tolerant_rolls_back():
    conn = _FakeConn(_REG_ROWS, raise_on_execute=True)
    assert bridge._sender_matter_set("andrey@aelioholding.com", conn=conn) == set()
    assert conn.rolled_back is True


def test_sender_matter_set_handles_json_string_participants():
    import json as _json
    rows = [("movie", _json.dumps([{"channel": "email", "value": "x@y.com"}]))]
    assert bridge._sender_matter_set("x@y.com", conn=_FakeConn(rows)) == {"movie"}


# ---- Slice 3: build_email_ticket wiring (two-factor -> desk/flight/review) -------------------

from datetime import datetime, timezone


def _email(subject="", body="", sender="stranger@example.com", participant_fetched=False):
    return bridge.EmailArrival(
        message_id="m1",
        thread_id="t1",
        sender_name="Someone",
        sender_email=sender,
        subject=subject,
        full_body=body,
        received_date=datetime(2026, 7, 9, 8, 0, tzinfo=timezone.utc),
        source="graph",
        participant_fetched=participant_fetched,
    )


def test_wire_corroborated_movie_routes_to_movie_desk(monkeypatch):
    monkeypatch.setattr(bridge, "_sender_matter_set", lambda *a, **k: {"movie"})
    monkeypatch.setattr(bridge, "_desk_for_matter", lambda m, c=None: "movie-desk")
    monkeypatch.setattr(bridge, "_flight_for_matter", lambda m, c=None: "MO-VIE-001")
    t = bridge.build_email_ticket(
        _email("Mandarin Oriental — Vienna update", "hotel ops", participant_fetched=True),
        conn=object(),
    )
    assert t is not None
    assert t.proposed_desk_slug == "movie-desk"
    assert t.suspected_flight == "MO-VIE-001"
    assert t.suspected_matter_slug == "movie"
    assert t.review_reason == ""
    assert any("two-factor routed" in w and "movie" in w for w in t.why_ticketed)


def test_wire_multimatter_sender_disambiguated_by_content(monkeypatch):
    # Sender in movie AND ao; MOVIE content -> resolves to movie (Director's Buchwalder example).
    monkeypatch.setattr(bridge, "_sender_matter_set", lambda *a, **k: {"movie", "ao"})
    monkeypatch.setattr(bridge, "_desk_for_matter", lambda m, c=None: f"{m}-desk")
    monkeypatch.setattr(bridge, "_flight_for_matter", lambda m, c=None: "MO-VIE-001")
    t = bridge.build_email_ticket(_email("MOHG standards note", "", participant_fetched=True), conn=object())
    assert t is not None
    assert t.proposed_desk_slug == "movie-desk"
    assert t.suspected_matter_slug == "movie"


def test_wire_identity_only_goes_to_lead_review_lane(monkeypatch):
    monkeypatch.setattr(bridge, "_sender_matter_set", lambda *a, **k: {"movie"})
    # No content keyword -> identity_only -> review lane (desk=lead), NOT movie-desk / BB.
    t = bridge.build_email_ticket(
        _email("Quick question", "call me later", participant_fetched=True), conn=object()
    )
    assert t is not None
    assert t.proposed_desk_slug == "lead"
    assert t.review_reason == bridge.REVIEW_REASON_IDENTITY_ONLY
    assert any("review lane (identity_only)" in w for w in t.why_ticketed)


def test_wire_conflict_goes_to_lead_review_lane(monkeypatch):
    # Identity=movie, content=aukera -> conflict -> review lane.
    monkeypatch.setattr(bridge, "_sender_matter_set", lambda *a, **k: {"movie"})
    t = bridge.build_email_ticket(
        _email("Aukera data room", "closing actions", participant_fetched=True), conn=object()
    )
    assert t is not None
    assert t.proposed_desk_slug == "lead"
    assert t.review_reason == bridge.REVIEW_REASON_CONFLICT


def test_wire_lilienmatt_keyword_regression_stays_baden_baden(monkeypatch):
    # Unregistered sender, keyword-lane (lilienmatt), conn=None -> global desk, byte-identical.
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    monkeypatch.delenv("AIRPORT_TICKETING_MATTER_SLUG", raising=False)
    t = bridge.build_email_ticket(
        _email("Lilienmatt Annaberg status", "closing checklist"), conn=None
    )
    assert t is not None
    assert t.proposed_desk_slug == "baden-baden-desk"
    assert t.suspected_matter_slug == "lilienmatt"
    assert t.review_reason == ""
    assert not any("review lane" in w for w in t.why_ticketed)


def test_wire_conn_none_is_byte_identical_global(monkeypatch):
    # conn=None (DB-free): factor A empty; an aukera keyword mail from an unknown sender keeps
    # today's global routing (no per-matter, no review lane).
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    t = bridge.build_email_ticket(_email("Aukera update", "data room"), conn=None)
    assert t is not None
    assert t.proposed_desk_slug == "baden-baden-desk"
    assert t.review_reason == ""


# ---- Slice 4: WhatsApp builder parity -------------------------------------------------------

def _wa(text="", sender="491000000@c.us", participant_matched=False):
    return bridge.WhatsAppArrival(
        message_id="wa1",
        sender=sender,
        sender_name="Someone",
        chat_id="c1",
        full_text=text,
        received_at=datetime(2026, 7, 9, 8, 0, tzinfo=timezone.utc),
        participant_matched=participant_matched,
    )


def test_wa_corroborated_movie_routes_to_movie_desk(monkeypatch):
    monkeypatch.setattr(bridge, "_sender_matter_set", lambda *a, **k: {"movie"})
    monkeypatch.setattr(bridge, "_desk_for_matter", lambda m, c=None: "movie-desk")
    monkeypatch.setattr(bridge, "_flight_for_matter", lambda m, c=None: "MO-VIE-001")
    t = bridge.build_whatsapp_ticket(
        _wa("update on the Mandarin Oriental opening", participant_matched=True), conn=object()
    )
    assert t is not None
    assert t.proposed_desk_slug == "movie-desk"
    assert t.suspected_flight == "MO-VIE-001"
    assert t.suspected_matter_slug == "movie"
    assert t.review_reason == ""


def test_wa_wa_channel_used_for_factor_a(monkeypatch):
    captured = {}

    def _fake(sender, conn=None, channel="email"):
        captured["channel"] = channel
        return {"movie"}

    monkeypatch.setattr(bridge, "_sender_matter_set", _fake)
    monkeypatch.setattr(bridge, "_desk_for_matter", lambda m, c=None: "movie-desk")
    monkeypatch.setattr(bridge, "_flight_for_matter", lambda m, c=None: "MO-VIE-001")
    bridge.build_whatsapp_ticket(_wa("Mandarin Oriental", participant_matched=True), conn=object())
    assert captured["channel"] == "whatsapp"


def test_wa_conflict_goes_to_lead_review(monkeypatch):
    monkeypatch.setattr(bridge, "_sender_matter_set", lambda *a, **k: {"movie"})
    t = bridge.build_whatsapp_ticket(
        _wa("aukera data room question", participant_matched=True), conn=object()
    )
    assert t is not None
    assert t.proposed_desk_slug == "lead"
    assert t.review_reason == bridge.REVIEW_REASON_CONFLICT


def test_wa_keyword_only_unregistered_stays_global(monkeypatch):
    # WA keyword match ("lilienmatt") from an unregistered sender, conn=None -> global (byte-identical).
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    t = bridge.build_whatsapp_ticket(_wa("lilienmatt closing note"), conn=None)
    assert t is not None
    assert t.proposed_desk_slug == "baden-baden-desk"
    assert t.review_reason == ""
