"""BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1 (blocks 2-4) — onward-journey tests.

Two tiers:
  * PURE UNIT (no DB): reply-grammar parser incl. ambiguous cases, deterministic accept
    token + verify, D-25 status map, WORK_PACKET format, readonly no-op, flag-off, and
    the migration<->bootstrap constraint SQL-string parity (Lesson #42).
  * LIVE-PG (``needs_live_pg`` auto-skips without TEST_DATABASE_URL): the full state
    machine against real airport_outbound_events / airport_tickets / baker_actions with a
    recording fake ClickUp + a recording fake bus (no network). Proves AC1-AC6:
    boarding->claim->status-mirror->landed->receipt end-to-end, idempotent re-run, guarded
    wrong-order rejection, bad-token rejection, cap + readonly, TTL escalation, reconcile.
"""
from __future__ import annotations

import pytest

from orchestrator import airport_boarding_flow as bf


# ===========================================================================
# PURE UNIT — no DB, no ClickUp, no bus
# ===========================================================================
def test_flag_off_default(monkeypatch):
    monkeypatch.delenv("AIRPORT_BOARDING_FLOW_ENABLED", raising=False)
    assert bf.boarding_enabled() is False


def test_flag_on(monkeypatch):
    monkeypatch.setenv("AIRPORT_BOARDING_FLOW_ENABLED", "true")
    assert bf.boarding_enabled() is True


def test_accept_token_deterministic_and_verifies():
    ev = "airport-lounge:v1:abc"
    t1, t2 = bf.accept_token(ev), bf.accept_token(ev)
    assert t1 == t2 and t1.startswith("claim:v1:")
    assert bf.accept_token("airport-lounge:v1:xyz") != t1     # per-ticket
    assert bf._token_matches(ev, t1) is True
    assert bf._token_matches(ev, "claim:v1:deadbeef") is False
    assert bf._token_matches(ev, "") is False


def test_parse_claim():
    t = bf.accept_token("airport-lounge:v1:a")
    assert bf.parse_desk_reply(f"CLAIM {t}") == {"kind": "CLAIM", "token": t}


def test_parse_claim_extra_junk_rejected():
    t = bf.accept_token("airport-lounge:v1:a")
    assert bf.parse_desk_reply(f"CLAIM {t} and more") is None   # exactly a token only


def test_parse_status_with_note():
    t = bf.accept_token("airport-lounge:v1:a")
    got = bf.parse_desk_reply(f"STATUS BLOCKED {t} awaiting survey")
    assert got == {"kind": "STATUS", "state": "BLOCKED", "token": t, "note": "awaiting survey"}


def test_parse_status_no_note():
    t = bf.accept_token("airport-lounge:v1:a")
    assert bf.parse_desk_reply(f"STATUS WAITING {t}") == {
        "kind": "STATUS", "state": "WAITING", "token": t, "note": ""}


def test_parse_status_bad_state_rejected():
    t = bf.accept_token("airport-lounge:v1:a")
    assert bf.parse_desk_reply(f"STATUS FOO {t}") is None
    assert bf.parse_desk_reply(f"STATUS {t}") is None          # missing state word


def test_parse_landed_with_package():
    t = bf.accept_token("airport-lounge:v1:a")
    got = bf.parse_desk_reply(f"LANDED {t}\nstate: resolved\nevidence: doc1")
    assert got["kind"] == "LANDED" and got["token"] == t
    assert got["package"] == "state: resolved\nevidence: doc1"


def test_parse_ambiguous_two_commands_rejected():
    t = bf.accept_token("airport-lounge:v1:a")
    assert bf.parse_desk_reply(f"CLAIM {t}\nLANDED {t}") is None


def test_parse_none_and_empty():
    assert bf.parse_desk_reply("hello there") is None
    assert bf.parse_desk_reply("") is None
    assert bf.parse_desk_reply(None) is None


def test_status_canonical_map_is_bb_vocab():
    assert bf._STATUS_CANONICAL == {
        "BLOCKED": "blocked", "WAITING": "waiting", "UPDATE_REQUIRED": "update required"}


def test_work_packet_carries_token_and_grammar():
    ev = {"ticket_id": "airport-lounge:v1:a", "clickup_task_id": "CU-1",
          "clickup_list_id": "901524194809", "matter_slug": "bb-aukera",
          "correlation": {"luggage": ["item one", "item two"]}}
    t = bf.accept_token(ev["ticket_id"])
    body = bf._format_work_packet(ev, t)
    assert f"accept_token: {t}" in body
    assert f"CLAIM {t}" in body
    assert "STATUS BLOCKED|WAITING|UPDATE_REQUIRED" in body
    assert f"LANDED {t}" in body
    assert "- item one" in body                                # luggage list rendered


def test_readonly_mirror_is_logged_noop(monkeypatch):
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "true")

    class _Boom:
        def update_task(self, *a, **k):
            raise AssertionError("must not write in readonly")

    out = bf._mirror_clickup_status(_Boom(), "901524194809", "CU-1", "in progress",
                                    comment="x")
    assert out["ok"] is True and out["dry_run"] is True and out["status"] == "in progress"


def test_migration_bootstrap_state_parity():
    """Lesson #42: the migration and BOTH bootstraps must carry the same widened vocab, via
    an idempotent DROP+ADD (not just an inline CREATE that no-ops on an existing table)."""
    mig = open("migrations/20260704a_airport_onward_journey.sql").read()
    conn_src = open("orchestrator/airport_outbound_connector.py").read()
    bridge_src = open("orchestrator/airport_ticketing_bridge.py").read()
    for st in ("BOARDING_POSTED", "CLAIMED", "LANDED", "RECEIPT_WRITTEN"):
        assert st in mig, st
        assert st in conn_src, st
    assert "'closed'" in mig and "'closed'" in bridge_src
    # idempotent amend present in both bootstraps (existing-table path, not just CREATE)
    assert "DROP CONSTRAINT IF EXISTS airport_outbound_events_state_check" in conn_src
    assert "DROP CONSTRAINT IF EXISTS airport_tickets_status_check" in bridge_src
    assert "DROP CONSTRAINT IF EXISTS airport_outbound_events_state_check" in mig
    assert "DROP CONSTRAINT IF EXISTS airport_tickets_status_check" in mig


def test_reader_missing_key_is_graceful(monkeypatch):
    monkeypatch.setattr(bf, "_bridge_key", lambda: "")
    out = bf.run_boarding_reader(object())        # conn never touched when key missing
    assert out["ok"] is False and out["reason"] == "boarding_key_missing"


# ===========================================================================
# LIVE-PG — full state machine round-trip
# ===========================================================================
class _FakeCU:
    """Records update_task / post_comment; mirrors the ClickUpClient per-process cap."""

    def __init__(self, cap=10):
        self.updates = []
        self.comments = []
        self.cap = cap
        self._count = 0
        self.resets = 0

    def reset_cycle_counter(self):
        self._count = 0
        self.resets += 1

    def update_task(self, task_id, **kwargs):
        if self._count >= self.cap:
            raise RuntimeError("Max writes per cycle exceeded (%d)" % self.cap)
        self._count += 1
        self.updates.append((task_id, kwargs.get("status")))
        return {"id": task_id}

    def post_comment(self, task_id, comment_text):
        if self._count >= self.cap:
            raise RuntimeError("Max writes per cycle exceeded (%d)" % self.cap)
        self._count += 1
        self.comments.append((task_id, comment_text))
        return {"id": "comment"}


class _FakeBus:
    """Recording fake for the bus surface: an inbox the reader drains + a post/ack log."""

    def __init__(self):
        self.inbox = []          # list of dicts: {id, from_terminal, body}
        self.posts = []          # list of (recipient, topic, body)
        self.acks = []           # list of message ids
        self._next = 1000

    def queue(self, from_terminal, body):
        mid = self._next
        self._next += 1
        self.inbox.append({"id": mid, "from_terminal": from_terminal, "body": body})
        return mid

    # monkeypatch targets ---------------------------------------------------
    def fetch_inbox(self, base, slug, key, limit):
        return list(self.inbox)

    def fetch_full_body(self, base, mid, key):
        for m in self.inbox:
            if m["id"] == mid:
                return m["body"]
        return ""

    def ack(self, base, mid, key):
        self.acks.append(mid)
        self.inbox = [m for m in self.inbox if m["id"] != mid]

    def post(self, recipient, body, topic):
        mid = self._next
        self._next += 1
        self.posts.append((recipient, topic, body))
        return {"ok": True, "id": mid}


_STATE: dict = {}


@pytest.fixture
def bfx(tier_b_test_store, needs_live_pg, monkeypatch):
    """Live-PG onward-journey harness: clean tables, flag ON, ClickUp + bus faked."""
    import psycopg2
    from orchestrator import airport_ticketing_bridge as bridge
    from orchestrator import airport_outbound_connector as connector

    admin = psycopg2.connect(needs_live_pg)
    admin.autocommit = True
    bridge.ensure_airport_ticket_table(admin)
    connector.ensure_airport_outbound_events_table(admin)
    with admin.cursor() as cur:
        cur.execute("DELETE FROM airport_outbound_events")
        cur.execute("DELETE FROM airport_tickets")
        cur.execute("DELETE FROM baker_actions WHERE trigger_source = 'airport_boarding_flow'")
    admin.close()

    monkeypatch.setenv("AIRPORT_BOARDING_FLOW_ENABLED", "true")
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    cu, bus = _FakeCU(), _FakeBus()
    monkeypatch.setattr(bf, "_get_clickup_client", lambda: cu)
    monkeypatch.setattr(bf, "_bridge_key", lambda: "test-key")
    monkeypatch.setattr(bf, "_fetch_inbox", bus.fetch_inbox)
    monkeypatch.setattr(bf, "_fetch_full_body", bus.fetch_full_body)
    monkeypatch.setattr(bf, "_ack", bus.ack)
    monkeypatch.setattr(bf, "_post_bus", bus.post)
    _STATE["cu"], _STATE["bus"] = cu, bus

    conn = psycopg2.connect(needs_live_pg)
    yield conn
    conn.close()


def _cu():
    return _STATE["cu"]


def _bus():
    return _STATE["bus"]


def _insert_lounge_row(conn, ev_id, state, *, task_id="CU-1", list_id="901524194809",
                       matter="bb-aukera", correlation=None, aged_hours=0.0):
    import json
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_outbound_events (ticket_id, message_id, event_state, "
            "desk_owner, clickup_list_id, clickup_task_id, matter_slug, correlation, "
            "updated_at) VALUES (%s, %s, %s, 'baden-baden-desk', %s, %s, %s, %s::jsonb, "
            "NOW() - (%s * INTERVAL '1 hour'))",
            (ev_id, "msg-" + ev_id, state, list_id, task_id, matter,
             json.dumps(correlation or {}), aged_hours),
        )
    conn.commit()


def _state(conn, ev_id):
    with conn.cursor() as cur:
        cur.execute("SELECT event_state FROM airport_outbound_events WHERE ticket_id = %s",
                    (ev_id,))
        row = cur.fetchone()
    return row[0] if row else None


def _corr(conn, ev_id):
    with conn.cursor() as cur:
        cur.execute("SELECT correlation FROM airport_outbound_events WHERE ticket_id = %s",
                    (ev_id,))
        row = cur.fetchone()
    return row[0] if row else None


# --- T1 boarding poster -----------------------------------------------------
def test_poster_posts_and_advances(bfx):
    ev = "airport-lounge:v1:a"
    _insert_lounge_row(bfx, ev, bf.CLICKUP_WRITTEN)
    out = bf.run_boarding_poster(bfx)
    assert out["posted"] == 1 and out["errors"] == 0
    assert _state(bfx, ev) == bf.BOARDING_POSTED
    assert _corr(bfx, ev)["accept_token"] == bf.accept_token(ev)
    assert len(_bus().posts) == 1 and _bus().posts[0][0] == "baden-baden-desk"


def test_poster_idempotent(bfx):
    ev = "airport-lounge:v1:a"
    _insert_lounge_row(bfx, ev, bf.CLICKUP_WRITTEN)
    bf.run_boarding_poster(bfx)
    out2 = bf.run_boarding_poster(bfx)                # already BOARDING_POSTED
    assert out2["posted"] == 0 and out2["candidates"] == 0
    assert len(_bus().posts) == 1                     # no duplicate packet


# --- T1 claim ---------------------------------------------------------------
def test_claim_advances_and_mirrors(bfx):
    ev = "airport-lounge:v1:a"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.BOARDING_POSTED, correlation={"accept_token": tok})
    _bus().queue("baden-baden-desk", f"CLAIM {tok}")
    out = bf.run_boarding_reader(bfx)
    assert out["claimed"] == 1
    assert _state(bfx, ev) == bf.CLAIMED
    assert ("CU-1", "in progress") in _cu().updates
    assert _bus().acks                                # committed then acked


def test_claim_wrong_order_left_unacked(bfx):
    """CLAIM against a row still at CLICKUP_WRITTEN (never boarded) is out-of-order."""
    ev = "airport-lounge:v1:a"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.CLICKUP_WRITTEN, correlation={"accept_token": tok})
    _bus().queue("baden-baden-desk", f"CLAIM {tok}")
    out = bf.run_boarding_reader(bfx)
    assert out["claimed"] == 0
    assert _state(bfx, ev) == bf.CLICKUP_WRITTEN      # no advance
    assert _bus().acks == []                          # left un-acked for a human/next look


def test_bad_token_rejected(bfx):
    ev = "airport-lounge:v1:a"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.BOARDING_POSTED, correlation={"accept_token": tok})
    _bus().queue("baden-baden-desk", "CLAIM claim:v1:not-the-real-token")
    out = bf.run_boarding_reader(bfx)
    assert out["claimed"] == 0 and out["unmatched"] == 1
    assert _state(bfx, ev) == bf.BOARDING_POSTED
    assert _bus().acks == []


def test_claim_replay_is_acked(bfx):
    ev = "airport-lounge:v1:a"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.CLAIMED, correlation={"accept_token": tok})
    _bus().queue("baden-baden-desk", f"CLAIM {tok}")   # duplicate claim
    out = bf.run_boarding_reader(bfx)
    assert out["replay"] == 1 and out["claimed"] == 0
    assert _state(bfx, ev) == bf.CLAIMED
    assert _bus().acks                                 # replay must be acked (no re-read forever)


# --- T2 status mirror -------------------------------------------------------
def test_status_mirror_stays_claimed(bfx):
    ev = "airport-lounge:v1:a"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.CLAIMED, correlation={"accept_token": tok})
    _bus().queue("baden-baden-desk", f"STATUS BLOCKED {tok} awaiting survey")
    out = bf.run_boarding_reader(bfx)
    assert out["mirrored"] == 1
    assert _state(bfx, ev) == bf.CLAIMED               # mirror is ClickUp-surface only
    assert ("CU-1", "blocked") in _cu().updates
    assert _cu().comments and "awaiting survey" in _cu().comments[0][1]
    assert _corr(bfx, ev)["last_mirrored_status"] == "blocked"


# --- T3 landing + receipt ---------------------------------------------------
def test_landed_then_receipt_closes_everything(bfx):
    ev = "airport-lounge:v1:src-a"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.CLAIMED, correlation={"accept_token": tok})
    # source ticket must exist at checked_in for the close guard
    with bfx.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, status, source_channel, "
            "source_id, proposed_desk_slug, suspected_matter_slug, urgency_hint, "
            "check_in_outcome, check_in_at, ticket) VALUES "
            "('src-a', 'dk-a', 'checked_in', 'email', 's-a', 'baden-baden-desk', "
            "'bb-aukera', 'normal', 'VALID', NOW(), '{}'::jsonb)")
    bfx.commit()

    _bus().queue("baden-baden-desk", f"LANDED {tok}\nstate: resolved\nevidence: SEPA doc")
    r_read = bf.run_boarding_reader(bfx)
    assert r_read["landed"] == 1 and _state(bfx, ev) == bf.LANDED
    assert _corr(bfx, ev)["package"].startswith("state: resolved")

    r_rec = bf.run_receipt_writer(bfx)
    assert r_rec["written"] == 1 and r_rec["errors"] == 0
    assert _state(bfx, ev) == bf.RECEIPT_WRITTEN
    assert ("CU-1", "complete") in _cu().updates
    assert _corr(bfx, ev)["receipt_bus_id"] is not None
    # source ticket closed
    with bfx.cursor() as cur:
        cur.execute("SELECT status FROM airport_tickets WHERE ticket_id = 'src-a'")
        assert cur.fetchone()[0] == "closed"
    # bus RECEIPT proof posted back to the desk
    assert any(topic.startswith("receipt/") for _, topic, _ in _bus().posts)


def test_receipt_idempotent(bfx):
    ev = "airport-lounge:v1:src-a"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.LANDED,
                       correlation={"accept_token": tok, "package": "p"})
    bf.run_receipt_writer(bfx)
    updates_after_1 = len(_cu().updates)
    posts_after_1 = len(_bus().posts)
    out2 = bf.run_receipt_writer(bfx)                  # already RECEIPT_WRITTEN
    assert out2["candidates"] == 0
    assert len(_cu().updates) == updates_after_1       # no double close
    assert len(_bus().posts) == posts_after_1


# --- T4 exception lane ------------------------------------------------------
def test_ttl_nudge_then_escalate(bfx):
    ev = "airport-lounge:v1:a"
    tok = bf.accept_token(ev)
    # aged past the 48h default TTL, never nudged
    _insert_lounge_row(bfx, ev, bf.BOARDING_POSTED,
                       correlation={"accept_token": tok, "nudge_count": 0}, aged_hours=72)
    n1 = bf.run_boarding_ttl_nudge(bfx)
    assert n1["nudged"] == 1 and n1["escalated"] == 0
    assert _state(bfx, ev) == bf.BOARDING_POSTED
    assert _corr(bfx, ev)["nudge_count"] == 1

    # bump the row age again (nudge reset updated_at); simulate second expiry
    with bfx.cursor() as cur:
        cur.execute("UPDATE airport_outbound_events SET updated_at = NOW() - INTERVAL '72 hours' "
                    "WHERE ticket_id = %s", (ev,))
    bfx.commit()
    n2 = bf.run_boarding_ttl_nudge(bfx)
    assert n2["escalated"] == 1
    assert _state(bfx, ev) == bf.NEEDS_CONTROLLER
    assert ("CU-1", "update required") in _cu().updates


# --- AC4 readonly + AC5 reconcile ------------------------------------------
def test_readonly_sweep_is_nonmutating(bfx, monkeypatch):
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "true")
    _insert_lounge_row(bfx, "airport-lounge:v1:a", bf.CLICKUP_WRITTEN,
                       correlation={"accept_token": "t"})
    ev = "airport-lounge:v1:b"
    tok = bf.accept_token(ev)
    _insert_lounge_row(bfx, ev, bf.CLAIMED, correlation={"accept_token": tok})
    _bus().queue("baden-baden-desk", f"STATUS BLOCKED {tok}")
    report = bf.run_onward_journey_sweep(bfx)
    assert report["dry_run"] is True
    assert report["plan"]["would_post_boarding"] == 1     # the CLICKUP_WRITTEN row
    assert report["plan"]["in_flight"] == 1               # the CLAIMED row
    # NON-MUTATING end-to-end: zero ClickUp writes, no bus posts, no ACK, no state change
    assert _cu().updates == [] and _cu().comments == []
    assert _bus().posts == [] and _bus().acks == []
    assert _state(bfx, "airport-lounge:v1:a") == bf.CLICKUP_WRITTEN
    assert _state(bfx, ev) == bf.CLAIMED


def test_reconcile_clean_no_flight_leak(bfx):
    _insert_lounge_row(bfx, "airport-lounge:v1:a", bf.BOARDING_POSTED,
                       correlation={"accept_token": "t"})
    _insert_lounge_row(bfx, "airport-lounge:v1:b", bf.RECEIPT_WRITTEN,
                       correlation={"accept_token": "t2"})
    rec = bf.reconcile_onward(bfx)
    assert rec["flight_column_leak_count"] == 0
    assert rec["undefined_states"] == {}
    assert rec["clean"] is True
    assert rec["by_state"].get(bf.BOARDING_POSTED) == 1
    assert rec["non_terminal_count"] == 1                 # only the BOARDING_POSTED row


def test_cap_stops_writes_and_leaves_unacked(bfx):
    """11th ClickUp write in one reader cycle hits the per-process cap -> that reply raises,
    is rolled back, and left un-acked (retried next cycle). Cap is never exceeded."""
    _STATE["cu"].cap = 2                                   # tiny cap for the proof
    # 3 CLAIMED rows, each gets a STATUS mirror = 1 update + 1 comment = 2 writes each
    for i in range(3):
        ev = f"airport-lounge:v1:{i}"
        tok = bf.accept_token(ev)
        _insert_lounge_row(bfx, ev, bf.CLAIMED, task_id=f"CU-{i}",
                           correlation={"accept_token": tok})
        _bus().queue("baden-baden-desk", f"STATUS WAITING {tok}")
    bf.run_boarding_reader(bfx)
    assert _cu()._count <= _cu().cap                      # cap never breached
    assert len(_bus().acks) < 3                           # at least one reply left un-acked
