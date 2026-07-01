"""BOX5_OUTBOUND_INGEST_2 — the 12 acceptance criteria (spec §"Increment 2 Tests").

Live-PG tests (``needs_live_pg`` auto-skips without TEST_DATABASE_URL / NEON_*). Kept
in a SEPARATE file from ``test_box5_ticketing_runner.py`` because b3 edits that file's
E lane in parallel (BOX5_ROUTING_REVERSAL_E_1) — non-overlapping build surfaces.

The connector's ClickUp write is exercised through a thin recording fake (no network);
correlation + the event state machine + audit run against the real DB. Flight is
RECORD-ONLY (lead #4851): assertions read the recorded flight_to_state / event_state,
not a live flight store (none exists).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest

from orchestrator import airport_ticketing_bridge as bridge
from orchestrator import airport_outbound_connector as connector
from kbl import project_registry_store as reg
from kbl import slug_registry
from kbl.db import get_conn

_FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
_FIXTURE_CANONICAL_SLUG = "alpha"          # canonical in the fixture vault
_OUTBOUND_SENDER = "dvallen@brisengroup.com"   # Brisen-controlled -> outbound
_LIST_ID = "901510186446777"               # a BAKER-space ClickUp list id (fake)

# psycopg2 connection objects reject arbitrary attributes, so the recording ClickUp
# fake lives here and is set by the `ob` fixture.
_STATE: dict = {}


def _fake():
    return _STATE["fake"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeClickUp:
    """Records write calls; mirrors the ClickUpClient surface the connector uses.

    fail_mode: None (success) | 'return_none' (the real `_request` returns None on
    HTTP>=400 / exhausted retries — F1/AC10) | 'raise' (unexpected throw — AC10b).
    space: the Space id `_resolve_space_id_for_list` reports (BAKER by default; a
    non-BAKER value exercises the F2 enforcement)."""

    def __init__(self, fail_mode=None, space="901510186446"):
        self.calls = []
        self.fail_mode = fail_mode
        self.space = space
        self._n = 0

    def _resolve_space_id_for_list(self, list_id):
        return self.space

    def create_task(self, **kwargs):
        self.calls.append(("create_task", kwargs))
        if self.fail_mode == "raise":
            raise RuntimeError("clickup 500 (simulated)")
        if self.fail_mode == "return_none":
            return None
        self._n += 1
        return {"id": "CU-%d" % self._n, "url": "http://cu/%d" % self._n}

    def update_task(self, task_id, **kwargs):
        self.calls.append(("update_task", dict(task_id=task_id, **kwargs)))
        return {"id": task_id}

    def post_comment(self, task_id, comment_text):
        self.calls.append(("post_comment", dict(task_id=task_id, comment_text=comment_text)))
        return {"id": "cmt"}


@pytest.fixture
def ob(tier_b_test_store, needs_live_pg, monkeypatch):
    """Outbound Increment-2 harness: source tables + clean airport_tickets /
    airport_outbound_events / project_registry / baker_actions, flag ON, registry wired
    to the same DB + fixture vault, bus stubbed, ClickUp replaced with a recording fake.
    """
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
    connector.ensure_airport_outbound_events_table(admin)
    reg.ensure_project_registry_table(admin)
    with admin.cursor() as cur:
        cur.execute("DELETE FROM airport_outbound_events")
        cur.execute("DELETE FROM airport_tickets")
        cur.execute("DELETE FROM email_messages")
        cur.execute("DELETE FROM email_attachments")
        cur.execute("DELETE FROM project_registry")
        cur.execute("DELETE FROM trigger_watermarks WHERE source = %s", (bridge._WATERMARK_SOURCE,))
        cur.execute("DELETE FROM baker_actions WHERE trigger_source IN "
                    "('airport_ticketing_bridge','airport_outbound_ingest','airport_outbound_increment2')")

    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("AIRPORT_OUTBOUND_INGEST_ENABLED", "true")
    monkeypatch.setenv("AIRPORT_TICKETING_KEYWORDS", "aukera,annaberg,lilienmatt")
    monkeypatch.setenv("AIRPORT_TICKETING_MAX_POSTS_PER_TICK", "25")
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(_FIXTURE_VAULT))
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    monkeypatch.delenv("BOX5_FAST_LANE_ENABLED", raising=False)
    slug_registry.reload()
    monkeypatch.setattr(
        bridge, "post_ticket_to_bus",
        lambda ticket: {"ok": True, "message_id": 555, "thread_id": "t-555"},
    )
    fake = _FakeClickUp()
    monkeypatch.setattr(connector, "_get_clickup_client", lambda: fake)
    _STATE["fake"] = fake
    yield admin
    slug_registry.reload()
    admin.close()


# --------------------------------------------------------------------------- helpers
def _seed_email(conn, message_id, *, subject, body, sender_email=_OUTBOUND_SENDER,
                received=None):
    received = received or (_now() - timedelta(hours=1))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO email_messages (message_id, thread_id, sender_name, "
            "sender_email, subject, full_body, received_date, source) "
            "VALUES (%s, %s, 'Sender', %s, %s, %s, %s, 'graph') "
            "ON CONFLICT (message_id) DO NOTHING",
            (message_id, message_id, sender_email, subject, body, received),
        )
    conn.commit()
    return received


def _register(project_number="BB-AUK-001", desk_owner="baden-baden-desk",
              clickup_list_id=_LIST_ID, participants=None):
    with get_conn() as conn:
        out = reg.register_project(
            conn, project_number=project_number, desk_owner=desk_owner,
            matter_slug=_FIXTURE_CANONICAL_SLUG, clickup_list_id=clickup_list_id,
            participants=participants or [],
        )
        conn.commit()
    return out


def _seed_flight(conn, thread_id, flight="aukera-annaberg-financing"):
    """A prior NON-outbound ticket on `thread_id` carrying a suspected_flight — the
    record-only proxy for an 'active flight' (correlation step 4). Keyed per-flight so
    seeding two distinct flights on one thread creates two rows (F4 conflict test)."""
    key = "prior:%s:%s" % (thread_id, flight)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, source_channel, "
            "source_id, bus_thread_id, proposed_desk_slug, suspected_flight) "
            "VALUES (%s, %s, 'email', %s, %s, 'baden-baden-desk', %s)",
            (key, key, "src-" + key, thread_id, flight),
        )
    conn.commit()


_EV_COLS = ("event_state", "ratification_class", "clickup_task_id", "clickup_status",
            "clickup_idempotency_key", "flight_id", "flight_to_state",
            "flight_idempotency_key")


def _event(conn, message_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT " + ", ".join(_EV_COLS) + " FROM airport_outbound_events "
            "WHERE ticket_id = %s", ("airport-outbound:" + message_id,),
        )
        return cur.fetchone()


def _creates():
    return [c for c in _fake().calls if c[0] == "create_task"]


def _audit_count(conn, action_type, message_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM baker_actions WHERE action_type = %s "
            "AND payload->>'message_id' = %s", (action_type, message_id),
        )
        return cur.fetchone()[0]


# --------------------------------------------------------------------------- the 12 ACs
# AC1 — flag OFF: outbound sender byte-identical pre-change (no capture / no skip / no
#       connector). The outbound-sender arrival flows through the inbound safe-default.
def test_ac1_flag_off_byte_identical(ob, monkeypatch):
    monkeypatch.setenv("AIRPORT_OUTBOUND_INGEST_ENABLED", "false")
    _seed_email(ob, "ac1", subject="aukera approved",
                body="Approved. DV to sign by 2026-07-10, proceed with wiring.")
    s = bridge.run_tick()
    assert s["outbound_signal"] == 0            # no capture when dark
    assert s["defaulted_ticket"] == 1           # processed as a normal inbound keyword row
    assert s["issued"] == 1
    assert _event(ob, "ac1") is None            # NO outbound event row
    assert _fake().calls == []                 # connector never ran


# AC2 — flag ON, routine outbound: captures + evidence, NO ClickUp, NO flight.
def test_ac2_routine_outbound_evidence_only(ob):
    _seed_email(ob, "ac2", subject="annaberg fyi",
                body="annaberg quick note, nothing to action here")
    s = bridge.run_tick()
    assert s["outbound_signal"] == 1
    assert _event(ob, "ac2")[0] == "EVIDENCE_ONLY"
    assert _fake().calls == []
    assert _audit_count(ob, "airport_outbound.clickup_write", "ac2") == 0
    assert _audit_count(ob, "airport_outbound.flight_transition_recorded", "ac2") == 0


# AC3 — ratifying outbound (project code + complete task fields): creates exactly ONE
#       ClickUp task with the idempotency key.
def test_ac3_ratifying_creates_one_clickup_task(ob):
    _register()
    _seed_email(ob, "ac3", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, proceed with wiring, due 2026-07-10.")
    s = bridge.run_tick()
    assert s["outbound_signal"] == 1
    ev = _event(ob, "ac3")
    assert ev[2] is not None                                  # clickup_task_id set
    assert ev[3] == "Ready for Baker Relay"                   # complete -> ready
    assert ev[4] == "outbound-clickup:v1:ac3:BB-AUK-001:approval"  # idempotency key
    assert ev[0] == "FLIGHT_BLOCKED"                          # wrote ClickUp; no active flight
    creates = _creates()
    assert len(creates) == 1
    assert creates[0][1]["list_id"] == _LIST_ID
    assert creates[0][1]["status"] == "Ready for Baker Relay"
    assert _audit_count(ob, "airport_outbound.clickup_write", "ac3") == 1


# AC4 — re-tick same outbound: NO duplicate ClickUp write, NO duplicate flight transition.
def test_ac4_retick_no_duplicate(ob):
    _register()
    _seed_flight(ob, "ac4")
    _seed_email(ob, "ac4", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, due 2026-07-10.")
    bridge.run_tick()
    assert _event(ob, "ac4")[0] == "FLIGHT_PROGRESSED"
    assert len(_creates()) == 1
    bridge.run_tick()                                         # re-tick (row re-fetched)
    assert len(_creates()) == 1                             # no second create
    assert _audit_count(ob, "airport_outbound.clickup_write", "ac4") == 1
    assert _audit_count(ob, "airport_outbound.flight_transition_recorded", "ac4") == 1
    assert _event(ob, "ac4")[0] == "FLIGHT_PROGRESSED"       # unchanged


# AC5 — ratifying outbound missing owner/date/action: CLICKUP_BLOCKED, no write, no flight.
def test_ac5_missing_fields_clickup_blocked(ob):
    _register()
    _seed_flight(ob, "ac5")                                   # even w/ a flight, blocked stops first
    _seed_email(ob, "ac5", subject="aukera approved", body="Approved BB-AUK-001.")
    bridge.run_tick()
    assert _event(ob, "ac5")[0] == "CLICKUP_BLOCKED"
    assert _fake().calls == []                               # no API write
    assert _audit_count(ob, "airport_outbound.flight_transition_recorded", "ac5") == 0


# AC6 — ratifying outbound with no active flight: ClickUp may write; flight FLIGHT_BLOCKED.
def test_ac6_no_flight_clickup_writes_flight_blocked(ob):
    _register()
    _seed_email(ob, "ac6", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, due 2026-07-10.")
    bridge.run_tick()
    ev = _event(ob, "ac6")
    assert ev[2] is not None                                 # ClickUp task created
    assert ev[0] == "FLIGHT_BLOCKED"
    assert len(_creates()) == 1
    assert _audit_count(ob, "airport_outbound.clickup_write", "ac6") == 1
    assert _audit_count(ob, "airport_outbound.flight_transition_recorded", "ac6") == 0


# AC7 — external-send outbound: task 'Waiting Reply', flight 'waiting_counterparty', NOT Closed.
def test_ac7_external_send_waiting_reply_not_closed(ob):
    _register()
    _seed_flight(ob, "ac7")
    _seed_email(ob, "ac7", subject="aukera sent",
                body="I have sent the term sheet to counterparty for BB-AUK-001, "
                     "awaiting their reply. owner: balazs, due 2026-07-10.")
    bridge.run_tick()
    ev = _event(ob, "ac7")
    assert ev[3] == "Waiting Reply"
    assert ev[3] != "Closed"
    assert ev[0] == "FLIGHT_PROGRESSED"
    assert ev[6] == "waiting_counterparty"
    assert _creates()[0][1]["status"] == "Waiting Reply"


# AC8 — final-acceptance without returned package: no 'landed'; waiting_receipt + Controller.
def test_ac8_final_acceptance_no_package_no_landed(ob):
    _register()
    _seed_flight(ob, "ac8")
    _seed_email(ob, "ac8", subject="aukera closing",
                body="We accept the final terms for BB-AUK-001 and close out. "
                     "owner: balazs, due 2026-07-10.")
    bridge.run_tick()
    ev = _event(ob, "ac8")
    assert ev[0] == "NEEDS_CONTROLLER"
    assert ev[6] == "waiting_receipt"
    assert ev[6] != "landed"
    assert ev[3] == "Needs Director"            # ClickUp status is NOT 'Closed'
    assert _audit_count(ob, "airport_outbound.flight_transition_recorded", "ac8") == 1  # recorded, success=false


# AC9 — final-acceptance WITH returned package + receipt: flight can 'landed'.
def test_ac9_final_acceptance_with_package_lands(ob):
    _register()
    _seed_flight(ob, "ac9")
    _seed_email(ob, "ac9", subject="aukera closing",
                body="We accept and close BB-AUK-001. Signed and returned, executed "
                     "copy attached. owner: balazs, due 2026-07-10.")
    bridge.run_tick()
    ev = _event(ob, "ac9")
    assert ev[0] == "FLIGHT_PROGRESSED"
    assert ev[6] == "landed"
    assert ev[3] == "Closed"


# AC10 — ClickUp write FAILURE via None return (real `_request` returns None on
#        HTTP>=400 / exhausted retries): CLICKUP_BLOCKED, audit success=false, no flight,
#        event durably recorded (the email cursor does not silently drop it). [F1]
def test_ac10_clickup_none_return_blocked_not_dropped(ob, monkeypatch):
    _register()
    none_ret = _FakeClickUp(fail_mode="return_none")
    monkeypatch.setattr(connector, "_get_clickup_client", lambda: none_ret)
    _seed_email(ob, "ac10", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, due 2026-07-10.")
    bridge.run_tick()
    ev = _event(ob, "ac10")
    assert ev is not None                        # event durably recorded (not dropped)
    assert ev[0] == "CLICKUP_BLOCKED"            # None return = handled FAILURE, not success
    assert ev[2] is None                         # no clickup_task_id
    assert _audit_count(ob, "airport_outbound.clickup_write", "ac10") == 1
    assert _audit_count(ob, "airport_outbound.flight_transition_recorded", "ac10") == 0
    with ob.cursor() as cur:
        cur.execute(
            "SELECT success FROM baker_actions WHERE action_type='airport_outbound.clickup_write' "
            "AND payload->>'message_id'='ac10'"
        )
        assert cur.fetchone()[0] is False        # failure audited (NOT success)
        cur.execute("SELECT COUNT(*) FROM airport_tickets WHERE source_id='ac10'")
        assert cur.fetchone()[0] == 1            # outbound capture committed (nothing lost)


# AC10b — ClickUp write raises (unexpected throw): ERROR_RETRY; caught, never re-raised,
#         so the bridge freezes the cursor for retry. [F1 exception path]
def test_ac10b_clickup_exception_error_retry(ob, monkeypatch):
    _register()
    raising = _FakeClickUp(fail_mode="raise")
    monkeypatch.setattr(connector, "_get_clickup_client", lambda: raising)
    _seed_email(ob, "ac10b", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, due 2026-07-10.")
    bridge.run_tick()
    ev = _event(ob, "ac10b")
    assert ev[0] == "ERROR_RETRY"
    assert ev[2] is None
    with ob.cursor() as cur:
        cur.execute(
            "SELECT success FROM baker_actions WHERE action_type='airport_outbound.clickup_write' "
            "AND payload->>'message_id'='ac10b'"
        )
        assert cur.fetchone()[0] is False
        cur.execute("SELECT COUNT(*) FROM airport_tickets WHERE source_id='ac10b'")
        assert cur.fetchone()[0] == 1            # capture committed


# AC11 — system / task-notification email never becomes an outbound ratification.
def test_ac11_system_notification_never_ratifies(ob):
    _register()
    _seed_flight(ob, "ac11")
    _seed_email(ob, "ac11", subject="aukera approved - task notification",
                sender_email="notifications@brisengroup.com",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, due 2026-07-10.")
    bridge.run_tick()
    assert _event(ob, "ac11")[0] == "EVIDENCE_ONLY"
    assert _fake().calls == []
    assert _audit_count(ob, "airport_outbound.clickup_write", "ac11") == 0


# AC12 — more than one correlated project: NEEDS_CONTROLLER, no write.
def test_ac12_multi_project_needs_controller(ob):
    _register("BB-AUK-001")
    _register("AO-MOV-002", desk_owner="ao-desk")
    _seed_email(ob, "ac12", subject="aukera cross ref",
                body="Approved both BB-AUK-001 and AO-MOV-002. owner: balazs, "
                     "DV to sign, due 2026-07-10.")
    bridge.run_tick()
    assert _event(ob, "ac12")[0] == "NEEDS_CONTROLLER"
    assert _fake().calls == []
    assert _audit_count(ob, "airport_outbound.clickup_write", "ac12") == 0


# --------------------------------------------------------------------- codex G3 fixes
# AC5b (F3) — ratifying, owner+action present but NO due date -> CLICKUP_BLOCKED.
def test_ac5b_missing_due_clickup_blocked(ob):
    _register()
    _seed_email(ob, "ac5b", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, proceed with wiring.")
    bridge.run_tick()
    assert _event(ob, "ac5b")[0] == "CLICKUP_BLOCKED"   # missing date blocks (F3)
    assert _fake().calls == []


# F2 — target ClickUp list not in BAKER Space (901510186446) -> no write (repo HARD RULE).
def test_f2_non_baker_space_blocked(ob, monkeypatch):
    _register()
    non_baker = _FakeClickUp(space="901500000000")      # NOT BAKER space
    monkeypatch.setattr(connector, "_get_clickup_client", lambda: non_baker)
    _seed_email(ob, "f2", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, due 2026-07-10.")
    bridge.run_tick()
    assert _event(ob, "f2")[0] == "CLICKUP_BLOCKED"
    assert non_baker.calls == []                        # create_task never attempted


# F4 — more than one distinct correlated flight -> NEEDS_CONTROLLER, no write.
def test_f4_multi_flight_needs_controller(ob):
    _register()
    _seed_flight(ob, "f4", flight="aukera-annaberg-financing")
    _seed_flight(ob, "f4", flight="mo-vie-exit")        # a SECOND distinct flight on the thread
    _seed_email(ob, "f4", subject="aukera approved",
                body="Approved BB-AUK-001. owner: balazs, DV to sign, due 2026-07-10.")
    bridge.run_tick()
    assert _event(ob, "f4")[0] == "NEEDS_CONTROLLER"
    assert _fake().calls == []
    assert _audit_count(ob, "airport_outbound.clickup_write", "f4") == 0
