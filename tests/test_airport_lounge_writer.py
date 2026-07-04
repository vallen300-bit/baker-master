"""BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1 — lounge writer + backlog drain tests.

Two tiers:
  * PURE UNIT (no DB): dup-scan, urgent-first ordering, disposition classification,
    flag-off, cap-plan slicing. Run everywhere, including locally without a DB — these
    are the "tests first" surfaces the brief calls out (idempotency logic, dup-scan, cap,
    flag-off no-op).
  * LIVE-PG (``needs_live_pg`` auto-skips without TEST_DATABASE_URL / NEON_*): the full
    drain against a real ``airport_tickets`` / ``airport_outbound_events`` / ``baker_actions``
    round-trip, ClickUp write through a thin recording fake (no network). Proves AC1-AC6.
"""

from __future__ import annotations

import pytest

from orchestrator import airport_lounge_writer as lounge


# ===========================================================================
# PURE UNIT — no DB, no ClickUp
# ===========================================================================
def _t(ticket_id, *, outcome="VALID", urgency="normal", source_id=None,
       desk="baden-baden-desk", matter="bb-aukera", created_ts=0.0):
    return {
        "ticket_id": ticket_id,
        "source_id": source_id if source_id is not None else ticket_id,
        "thread_id": "th-" + ticket_id,
        "proposed_desk_slug": desk,
        "suspected_matter_slug": matter,
        "urgency_hint": urgency,
        "check_in_outcome": outcome,
        "ticket_payload": {"subject": "re: " + ticket_id},
        "created_ts": created_ts,
    }


def test_flag_off_default(monkeypatch):
    monkeypatch.delenv("AIRPORT_LOUNGE_WRITER_ENABLED", raising=False)
    assert lounge.lounge_enabled() is False


def test_flag_on(monkeypatch):
    monkeypatch.setenv("AIRPORT_LOUNGE_WRITER_ENABLED", "true")
    assert lounge.lounge_enabled() is True


def test_classify_write_happy_path():
    action, list_id, status, reason = lounge.classify_disposition(_t("a"))
    assert action == lounge.ACT_WRITE
    assert list_id == "901524194809"
    assert status == lounge._STATUS_NEW
    assert reason == "checked_in"


def test_classify_block_unknown_desk():
    action, list_id, status, reason = lounge.classify_disposition(_t("a", desk="unknown-desk"))
    assert action == lounge.ACT_BLOCK
    assert list_id is None
    assert reason == "no_target_list"


def test_classify_park_missing_matter():
    action, list_id, status, reason = lounge.classify_disposition(_t("a", matter=""))
    assert action == lounge.ACT_PARK
    assert list_id == "901524194809"
    assert status == lounge._STATUS_PARKED
    assert reason == "no_matter_slug"


def test_priority_urgent_vs_normal():
    assert lounge._priority_for(_t("a", outcome="URGENT")) == lounge._PRIORITY_URGENT
    assert lounge._priority_for(_t("a", urgency="urgent")) == lounge._PRIORITY_URGENT
    assert lounge._priority_for(_t("a", urgency="high")) == lounge._PRIORITY_HIGH
    assert lounge._priority_for(_t("a")) == lounge._PRIORITY_NORMAL


def test_plan_urgent_first():
    rows = [
        _t("valid1", outcome="VALID", created_ts=1),
        _t("urgent1", outcome="URGENT", created_ts=2),
        _t("valid2", outcome="VALID", created_ts=3),
    ]
    plan = lounge.plan_drain(rows)
    # URGENT sorts ahead of both VALIDs regardless of created_ts.
    assert plan[0]["ticket"]["ticket_id"] == "urgent1"
    assert [p["ticket"]["ticket_id"] for p in plan[1:]] == ["valid1", "valid2"]


def test_plan_dup_scan_same_source_message():
    # Two tickets share the same source_id => second is a dup of the first (D-28 guard).
    rows = [
        _t("primary", source_id="msg-1", created_ts=1),
        _t("dup", source_id="msg-1", created_ts=2),
        _t("other", source_id="msg-2", created_ts=3),
    ]
    plan = lounge.plan_drain(rows)
    by_id = {p["ticket"]["ticket_id"]: p for p in plan}
    assert by_id["primary"]["action"] == lounge.ACT_WRITE
    assert by_id["dup"]["action"] == lounge.ACT_DUP
    assert by_id["dup"]["dup_of"] == "primary"
    assert by_id["other"]["action"] == lounge.ACT_WRITE


def test_plan_dup_scan_urgent_primary_wins():
    # When a source group has an URGENT + a VALID, the URGENT is the primary (writes),
    # the VALID becomes the dup.
    rows = [
        _t("valid_first", outcome="VALID", source_id="msg-1", created_ts=1),
        _t("urgent_later", outcome="URGENT", source_id="msg-1", created_ts=2),
    ]
    plan = lounge.plan_drain(rows)
    by_id = {p["ticket"]["ticket_id"]: p for p in plan}
    assert by_id["urgent_later"]["action"] == lounge.ACT_WRITE
    assert by_id["valid_first"]["action"] == lounge.ACT_DUP
    assert by_id["valid_first"]["dup_of"] == "urgent_later"


def test_event_key_scheme_distinct_from_outbound():
    # Lounge lane key must never collide with the connector's airport-outbound: scheme.
    assert lounge.event_ticket_id("T123") == "airport-lounge:T123"
    assert not lounge.event_ticket_id("T123").startswith("airport-outbound:")


# ===========================================================================
# LIVE-PG — full drain round-trip
# ===========================================================================
class _FakeClickUp:
    """Records create_task calls; mirrors the ClickUpClient surface the writer uses.

    fail_mode: None (success) | 'return_none' (real _request returns None on HTTP>=400)
    | 'raise' (unexpected throw). space: the Space _resolve_space_id_for_list reports."""

    def __init__(self, fail_mode=None, space="901510186446"):
        self.calls = []
        self.fail_mode = fail_mode
        self.space = space
        self._n = 0

    def _resolve_space_id_for_list(self, list_id):
        return self.space

    def create_task(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_mode == "raise":
            raise RuntimeError("clickup 500 (simulated)")
        if self.fail_mode == "return_none":
            return None
        self._n += 1
        return {"id": "CU-%d" % self._n, "url": "http://cu/%d" % self._n}


_STATE: dict = {}


@pytest.fixture
def lg(tier_b_test_store, needs_live_pg, monkeypatch):
    """Live-PG lounge harness: clean airport_tickets / airport_outbound_events /
    baker_actions, flag ON, ClickUp replaced with a recording fake on THIS module."""
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
        cur.execute("DELETE FROM baker_actions WHERE trigger_source = 'airport_lounge_writer'")
    admin.close()

    monkeypatch.setenv("AIRPORT_LOUNGE_WRITER_ENABLED", "true")
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    fake = _FakeClickUp()
    monkeypatch.setattr(lounge, "_get_clickup_client", lambda: fake)
    _STATE["fake"] = fake

    conn = psycopg2.connect(needs_live_pg)
    yield conn
    conn.close()


def _insert_ticket(conn, ticket_id, *, outcome="VALID", urgency="normal",
                   source_id=None, desk="baden-baden-desk", matter="bb-aukera",
                   status="checked_in"):
    src = source_id if source_id is not None else ("src-" + ticket_id)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, status, source_channel, "
            "source_id, proposed_desk_slug, suspected_matter_slug, urgency_hint, "
            "check_in_outcome, check_in_at, ticket) "
            "VALUES (%s, %s, %s, 'email', %s, %s, %s, %s, %s, NOW(), '{}'::jsonb)",
            (ticket_id, "dk-" + ticket_id, status, src, desk, matter or None,
             urgency, outcome),
        )
    conn.commit()


def _fake():
    return _STATE["fake"]


def test_ac_flag_off_noop(lg, monkeypatch):
    monkeypatch.setenv("AIRPORT_LOUNGE_WRITER_ENABLED", "false")
    _insert_ticket(lg, "t1")
    res = lounge.run_lounge_drain(lg)
    assert res["enabled"] is False
    assert res["wrote"] == 0
    assert _fake().calls == []                       # no ClickUp write attempted


def test_ac2_ratifying_creates_one_task_and_event(lg):
    _insert_ticket(lg, "t1", outcome="VALID")
    res = lounge.run_lounge_drain(lg)
    assert res["wrote"] == 1
    assert len(_fake().calls) == 1
    with lg.cursor() as cur:
        cur.execute("SELECT event_state, clickup_task_id, flight_id, flight_to_state "
                    "FROM airport_outbound_events WHERE ticket_id = %s",
                    ("airport-lounge:t1",))
        row = cur.fetchone()
    assert row[0] == lounge.CLICKUP_WRITTEN
    assert row[1] is not None                        # clickup_task_id populated (AC2)
    assert row[2] is None and row[3] is None         # flight columns NULL (AC5 / D-23)


def test_ac2_idempotent_rerun_no_duplicate(lg):
    _insert_ticket(lg, "t1")
    lounge.run_lounge_drain(lg)
    res2 = lounge.run_lounge_drain(lg)               # second live run
    assert res2["wrote"] == 0
    assert res2["skipped_idempotent"] == 1
    assert len(_fake().calls) == 1                   # still exactly one ClickUp task


def test_ac1_reconcile_zero_orphans_after_drain(lg):
    for i in range(3):
        _insert_ticket(lg, "t%d" % i, outcome=("URGENT" if i == 0 else "VALID"))
    lounge.run_lounge_drain(lg)
    rec = lounge.reconcile(lg)
    assert rec["orphan_count"] == 0                  # AC1
    assert rec["flight_column_leak_count"] == 0      # AC5
    assert rec["unresolved_count"] == 0
    assert rec["clean"] is True


def test_reconcile_flags_blocked_not_false_pass(lg, monkeypatch):
    # A ticket that could not be written (None-return) leaves a CLICKUP_BLOCKED row: NOT
    # an orphan, but NOT clean either — reconcile must surface it (codex finding).
    none_ret = _FakeClickUp(fail_mode="return_none")
    monkeypatch.setattr(lounge, "_get_clickup_client", lambda: none_ret)
    _STATE["fake"] = none_ret
    _insert_ticket(lg, "t1")
    lounge.run_lounge_drain(lg)
    rec = lounge.reconcile(lg)
    assert rec["orphan_count"] == 0                  # it HAS a row
    assert rec["unresolved_count"] == 1              # but it's blocked
    assert rec["clean"] is False                     # so NOT a false pass


def test_ac3_exception_lane_visible_parking(lg):
    # A checked-in ticket with no matter_slug → exception lane: visible parking task
    # ("update required") + NEEDS_CONTROLLER event row (nothing silently discarded).
    _insert_ticket(lg, "t1", matter="")
    res = lounge.run_lounge_drain(lg)
    assert res["parked"] == 1
    assert _fake().calls[0]["status"] == lounge._STATUS_PARKED
    with lg.cursor() as cur:
        cur.execute("SELECT event_state, correlation FROM airport_outbound_events "
                    "WHERE ticket_id = %s", ("airport-lounge:t1",))
        state, corr = cur.fetchone()
    assert state == lounge.NEEDS_CONTROLLER
    assert corr.get("ttl_renudge_pending") is True   # re-nudge marker recorded


def test_ac4_write_cap_enforced_two_cycles(lg):
    # 12 tickets, cap 5 → cycle 1 writes 5 + defers 7; repeated cycles drain the rest,
    # never exceeding the cap in any single cycle.
    for i in range(12):
        _insert_ticket(lg, "c%02d" % i)
    r1 = lounge.run_lounge_drain(lg, cap=5)
    assert r1["wrote"] == 5
    assert r1["writes_this_cycle"] == 5
    assert r1["deferred_cap"] == 7
    r2 = lounge.run_lounge_drain(lg, cap=5)
    assert r2["writes_this_cycle"] == 5
    r3 = lounge.run_lounge_drain(lg, cap=5)
    assert r3["writes_this_cycle"] <= 5
    # Fully drained across cycles: 0 orphans, 12 ClickUp tasks total.
    assert lounge.reconcile(lg)["orphan_count"] == 0
    assert len(_fake().calls) == 12


def test_ac4_dry_run_readonly_non_mutating(lg, monkeypatch):
    # Dry-run is NON-MUTATING: no ClickUp call AND no event row (so it can't brick the
    # later live run — codex P1-1). It only reports the plan.
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "true")
    _insert_ticket(lg, "t1")
    res = lounge.run_lounge_drain(lg)
    assert res["dry_run"] is True
    assert res["planned"] == 1
    assert res["wrote"] == 0 and res["blocked"] == 0
    assert _fake().calls == []                       # kill switch: no ClickUp write
    with lg.cursor() as cur:
        cur.execute("SELECT count(*) FROM airport_outbound_events "
                    "WHERE ticket_id = %s", ("airport-lounge:t1",))
        assert cur.fetchone()[0] == 0                # NO residue row written


def test_dry_run_then_live_actually_writes(lg, monkeypatch):
    # codex P1-1 regression: a dry-run must NOT prevent the subsequent live run from
    # actually creating the ClickUp task.
    _insert_ticket(lg, "t1")
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "true")
    dry = lounge.run_lounge_drain(lg)
    assert dry["planned"] == 1 and _fake().calls == []
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    live = lounge.run_lounge_drain(lg)
    assert live["wrote"] == 1                        # NOT skipped as idempotent
    assert len(_fake().calls) == 1
    with lg.cursor() as cur:
        cur.execute("SELECT event_state, clickup_task_id FROM airport_outbound_events "
                    "WHERE ticket_id = %s", ("airport-lounge:t1",))
        state, task = cur.fetchone()
    assert state == lounge.CLICKUP_WRITTEN and task is not None


def test_exception_then_retry_succeeds(lg, monkeypatch):
    # codex P1-2 regression: an ERROR_RETRY row is re-attempted next cycle (not treated
    # as terminal). First cycle raises → ERROR_RETRY; second cycle (client now healthy)
    # → the SAME ticket is re-processed and written.
    raising = _FakeClickUp(fail_mode="raise")
    monkeypatch.setattr(lounge, "_get_clickup_client", lambda: raising)
    _STATE["fake"] = raising
    _insert_ticket(lg, "t1")
    r1 = lounge.run_lounge_drain(lg)
    assert r1["error_retry"] == 1
    with lg.cursor() as cur:
        cur.execute("SELECT event_state FROM airport_outbound_events WHERE ticket_id=%s",
                    ("airport-lounge:t1",))
        assert cur.fetchone()[0] == lounge.ERROR_RETRY

    healthy = _FakeClickUp()                          # client recovers
    monkeypatch.setattr(lounge, "_get_clickup_client", lambda: healthy)
    _STATE["fake"] = healthy
    r2 = lounge.run_lounge_drain(lg)
    assert r2["wrote"] == 1                           # re-processed, not skipped
    assert r2["skipped_idempotent"] == 0
    assert len(healthy.calls) == 1
    with lg.cursor() as cur:
        cur.execute("SELECT event_state FROM airport_outbound_events WHERE ticket_id=%s",
                    ("airport-lounge:t1",))
        assert cur.fetchone()[0] == lounge.CLICKUP_WRITTEN
    assert lounge.reconcile(lg)["clean"] is True      # now clean


def test_dup_source_message_one_task(lg):
    _insert_ticket(lg, "primary", source_id="shared-msg")
    _insert_ticket(lg, "dup", source_id="shared-msg")
    res = lounge.run_lounge_drain(lg)
    assert res["wrote"] == 1
    assert res["dup"] == 1
    assert len(_fake().calls) == 1                   # exactly one ClickUp task (D-28)
    with lg.cursor() as cur:
        cur.execute("SELECT correlation FROM airport_outbound_events "
                    "WHERE ticket_id = %s", ("airport-lounge:dup",))
        corr = cur.fetchone()[0]
    assert corr.get("dup_of") == "primary"


def test_clickup_none_return_blocked_not_dropped(lg, monkeypatch):
    none_ret = _FakeClickUp(fail_mode="return_none")
    monkeypatch.setattr(lounge, "_get_clickup_client", lambda: none_ret)
    _STATE["fake"] = none_ret
    _insert_ticket(lg, "t1")
    res = lounge.run_lounge_drain(lg)
    assert res["blocked"] == 1
    with lg.cursor() as cur:
        cur.execute("SELECT event_state, last_error FROM airport_outbound_events "
                    "WHERE ticket_id = %s", ("airport-lounge:t1",))
        state, err = cur.fetchone()
    assert state == lounge.CLICKUP_BLOCKED           # handled failure, not a silent drop
    assert err == "clickup_write_failed_no_id"


def test_clickup_exception_error_retry(lg, monkeypatch):
    raising = _FakeClickUp(fail_mode="raise")
    monkeypatch.setattr(lounge, "_get_clickup_client", lambda: raising)
    _STATE["fake"] = raising
    _insert_ticket(lg, "t1")
    res = lounge.run_lounge_drain(lg)
    assert res["error_retry"] == 1
    with lg.cursor() as cur:
        cur.execute("SELECT event_state FROM airport_outbound_events "
                    "WHERE ticket_id = %s", ("airport-lounge:t1",))
        state = cur.fetchone()[0]
    assert state == lounge.ERROR_RETRY               # retried next cycle, never dropped


def test_non_baker_space_blocked(lg, monkeypatch):
    non_baker = _FakeClickUp(space="999999")
    monkeypatch.setattr(lounge, "_get_clickup_client", lambda: non_baker)
    _STATE["fake"] = non_baker
    _insert_ticket(lg, "t1")
    res = lounge.run_lounge_drain(lg)
    assert res["blocked"] == 1
    assert non_baker.calls == []                     # F2: create_task never attempted
