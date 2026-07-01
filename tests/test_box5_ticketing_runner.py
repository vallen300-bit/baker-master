"""BOX5_TICKETING_RUNNER_1 — reliability matrix for the extended run_tick.

Asserts the real crash / concurrency / error / idempotency paths, not happy-path
only (codex caught 2 P1 crash-path bugs on the prior Box-5 job; this matrix exists
to catch that class before the gate).

Live-PG via ``tier_b_test_store`` (points SentinelStoreBack._get_global_instance —
which both run_tick AND trigger_state use — at the test DB + bootstraps
baker_actions) and ``needs_live_pg`` (auto-skip without TEST_DATABASE_URL /
NEON_*; CI runs live).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest

from orchestrator import airport_ticketing_bridge as bridge
from kbl import project_registry_store as reg
from kbl import slug_registry
from kbl.db import get_conn

# BOX5_HARD_FAST_LANE_1 branch tests use the fixture vault for slug validation
# (never the prod slugs.yml), mirroring tests/test_project_registry.py.
_FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
_FIXTURE_CANONICAL_SLUG = "alpha"  # canonical in the fixture vault


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def runner(tier_b_test_store, needs_live_pg, monkeypatch):
    """Live runner harness: source tables + clean airport_tickets/watermark, master
    gate ON, fast lane unset, bus post stubbed (no network)."""
    admin = psycopg2.connect(needs_live_pg)
    # Autocommit so admin reads never sit idle-in-transaction holding ACCESS SHARE
    # on airport_tickets — otherwise the next run_tick's ensure (DROP/ADD CONSTRAINT,
    # ACCESS EXCLUSIVE) would block on this connection and the tick would hang.
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
    admin.commit()
    bridge.ensure_airport_ticket_table(admin)  # airport_tickets + BRIEF-B terminal cols
    admin.commit()
    with admin.cursor() as cur:
        cur.execute("DELETE FROM airport_tickets")
        cur.execute("DELETE FROM email_messages")
        cur.execute("DELETE FROM email_attachments")
        cur.execute("DELETE FROM trigger_watermarks WHERE source = %s", (bridge._WATERMARK_SOURCE,))
        cur.execute("DELETE FROM baker_actions WHERE trigger_source = 'airport_ticketing_bridge'")
        # BOX5_OUTBOUND_INGEST_1 logs its capture action under a distinct source.
        cur.execute("DELETE FROM baker_actions WHERE trigger_source = 'airport_outbound_ingest'")
    admin.commit()

    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "true")
    monkeypatch.delenv("BOX5_FAST_LANE_ENABLED", raising=False)
    monkeypatch.setenv("AIRPORT_TICKETING_KEYWORDS", "aukera,annaberg,lilienmatt")
    monkeypatch.setenv("AIRPORT_TICKETING_MAX_POSTS_PER_TICK", "25")
    # Neutralize the real bus POST — no network; pretend it succeeded.
    monkeypatch.setattr(
        bridge, "post_ticket_to_bus",
        lambda ticket: {"ok": True, "message_id": 555, "thread_id": "t-555"},
    )
    yield admin
    admin.close()


# Default arrival sender is an INBOUND counterparty. It must NOT be a Brisen-
# controlled address: BOX5_OUTBOUND_INGEST_1 short-circuits @brisengroup.com senders
# as outbound BEFORE the lanes, so a Brisen default would make every inbound-lane
# test skip. (In prod the fast/soft lanes only ever see inbound arrivals for the
# same reason, so an inbound sender here is the representative case.)
def _seed_email(conn, message_id, *, subject="annaberg status",
                sender_email="counterparty@aukera.lu", body="annaberg update",
                received=None):
    received = received or (_now() - timedelta(hours=1))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_messages
                (message_id, thread_id, sender_name, sender_email, subject,
                 full_body, received_date, source)
            VALUES (%s, %s, 'Sender', %s, %s, %s, %s, 'graph')
            ON CONFLICT (message_id) DO NOTHING
            """,
            (message_id, message_id, sender_email, subject, body, received),
        )
    conn.commit()
    return received


def _terminal(conn, message_id):
    """(terminal_status, terminal_outcome_written_at) for a row by raw_source_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT terminal_status, terminal_outcome_written_at FROM airport_tickets "
            "WHERE raw_source_id = %s LIMIT 1",
            (message_id,),
        )
        row = cur.fetchone()
    return row if row else (None, None)


# 1 — IDEMPOTENCY (highest value): run twice, the terminal write happens once.
def test_idempotent_terminal_write(runner):
    _seed_email(runner, "m1")
    s1 = bridge.run_tick()
    assert s1["ok"] and s1["terminal_written"] == 1
    ts_status, ts_written = _terminal(runner, "m1")
    assert ts_status == "TICKET" and ts_written is not None

    s2 = bridge.run_tick()
    assert s2["terminal_written"] == 0          # status-guard: second pass writes nothing
    ts_status2, ts_written2 = _terminal(runner, "m1")
    assert ts_status2 == "TICKET"
    assert ts_written2 == ts_written            # timestamp UNCHANGED -> no double-write


# 2 — SKIP-LOCKED concurrency: a row another tx holds is skipped, not blocked.
def test_claim_for_terminal_skips_locked_row(runner, needs_live_pg):
    with runner.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, source_channel, source_id, proposed_desk_slug) "
            "VALUES ('lk','lk','email','lk','baden-baden-desk') RETURNING id"
        )
        row_id = cur.fetchone()[0]
    runner.commit()

    holder = psycopg2.connect(needs_live_pg)
    other = psycopg2.connect(needs_live_pg)
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT id FROM airport_tickets WHERE id=%s FOR UPDATE", (row_id,))
            cur.fetchone()  # holder now locks the row (no commit)
        # The claim must return None (skipped), NOT hang/block.
        assert bridge._claim_for_terminal(other, row_id) is None
    finally:
        holder.rollback(); holder.close()
        other.rollback(); other.close()


# 3 — SAFE DEFAULT TICKET: a relevant, non-dup, non-noise arrival -> TICKET + bus post.
def test_safe_default_ticket(runner):
    _seed_email(runner, "m3", subject="annaberg closing")
    s = bridge.run_tick()
    assert s["defaulted_ticket"] == 1
    assert s["issued"] == 1               # bus post happened (stubbed ok)
    status, _ = _terminal(runner, "m3")
    assert status == "TICKET"
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason, status FROM airport_tickets WHERE raw_source_id='m3'")
        reason, live_status = cur.fetchone()
    assert reason == "safe_default_desk_review"
    assert live_status == "sent"          # issue path unchanged (live status axis)


# 4a — DUPLICATE deterministic clear via dedup_key collision.
def test_duplicate_deterministic_clear(runner):
    received = _seed_email(runner, "mdup", subject="annaberg dup")
    # Pre-seed the colliding row (status='sent' + bus_message_id so reserve_ticket
    # treats it as an existing duplicate, not a failed-retry), terminal_status NULL.
    dedup = bridge._dedup_key("email", "mdup", "baden-baden-desk")
    with runner.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, status, source_channel, source_id, "
            "source_received_at, proposed_desk_slug, bus_message_id) "
            "VALUES ('pre-mdup',%s,'sent','email','mdup',%s,'baden-baden-desk',999) RETURNING id",
            (dedup, received),
        )
        pre_id = cur.fetchone()[0]
    runner.commit()

    s = bridge.run_tick()
    assert s["deterministic_cleared"] >= 1
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_status, terminal_reason FROM airport_tickets WHERE id=%s", (pre_id,))
        status, reason = cur.fetchone()
    assert status == "DUPLICATE"
    assert reason == "dedup_key_collision"


# 4b — REJECT_NOISE deterministic clear (automated sender).
def test_reject_noise_deterministic_clear(runner):
    _seed_email(runner, "mnoise", subject="aukera newsletter",
                sender_email="noreply@example.com")
    s = bridge.run_tick()
    assert s["deterministic_cleared"] >= 1
    status, _ = _terminal(runner, "mnoise")
    assert status == "REJECT_NOISE"


# 4c — None-id reserve race: id=None must be a no-op, never a crash.
def test_none_id_reserve_race_is_noop(runner, monkeypatch):
    _seed_email(runner, "mrace", subject="annaberg race")
    monkeypatch.setattr(
        bridge, "issue_ticket",
        lambda ticket, conn: {"skipped": True, "reason": "duplicate", "id": None},
    )
    s = bridge.run_tick()
    assert s["ok"]                       # no crash
    assert s["lease_skipped"] >= 1
    assert s["terminal_written"] == 0
    status, _ = _terminal(runner, "mrace")
    assert status is None                # nothing written


# 5 — ERROR NEVER AUTO-CLEARS + one bad row doesn't stop the batch.
def test_error_never_auto_clears(runner, monkeypatch):
    _seed_email(runner, "mbad", subject="annaberg bad", received=_now() - timedelta(hours=2))
    _seed_email(runner, "mgood", subject="annaberg good", received=_now() - timedelta(hours=1))

    real_build = bridge.build_email_ticket

    def _boom(arrival, **kw):
        if arrival.message_id == "mbad":
            raise RuntimeError("classify exploded")
        return real_build(arrival, **kw)

    monkeypatch.setattr(bridge, "build_email_ticket", _boom)

    s = bridge.run_tick()
    assert s["failed"] >= 1
    assert s["deterministic_cleared"] == 0      # an error is NEVER a clear
    bad_status, _ = _terminal(runner, "mbad")
    assert bad_status is None                    # errored row left NULL, not cleared
    good_status, _ = _terminal(runner, "mgood")
    assert good_status == "TICKET"               # batch continued past the bad row


# 6 — CURSOR advances to max processed received_date on the DISTINCT key.
def test_cursor_advances_on_distinct_key(runner):
    r_old = _now() - timedelta(hours=3)
    r_new = _now() - timedelta(hours=1)
    _seed_email(runner, "mc1", subject="annaberg old", received=r_old)
    _seed_email(runner, "mc2", subject="annaberg new", received=r_new)

    bridge.run_tick()
    wm = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm - r_new).total_seconds()) < 1.0   # advanced to the max processed
    assert bridge._WATERMARK_SOURCE == "airport_ticketing:email"  # never the live email_poll


# 7 — KILL SWITCH: master gate off -> skip, nothing written.
def test_master_gate_off_writes_nothing(runner, monkeypatch):
    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "false")
    _seed_email(runner, "mk", subject="annaberg gated")
    s = bridge.run_tick()
    assert s.get("skipped") is True
    status, _ = _terminal(runner, "mk")
    assert status is None


# 8 — STUCK gauge counts un-terminal aged arrivals; flag default false.
def test_stuck_gauge_and_flag_default(runner):
    assert bridge.fast_lane_enabled() is False   # default closed
    # an aged row with no terminal_status is "stuck"
    with runner.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id, dedup_key, source_channel, source_id, "
            "source_received_at, proposed_desk_slug) "
            "VALUES ('stuck','stuck','email','stuck', NOW() - INTERVAL '90 minutes', 'baden-baden-desk')"
        )
    runner.commit()
    assert bridge._count_stuck_arrivals(runner) >= 1


# 9 — P1-A: under a per-tick cap the watermark must NOT jump to the newest row and
# strand older un-processed rows. Oldest-first + contiguous-prefix advance means the
# cap freezes the cursor at the oldest processed row; nothing is lost across ticks.
def test_p1a_cap_does_not_strand_older_rows(runner, monkeypatch):
    monkeypatch.setenv("AIRPORT_TICKETING_MAX_POSTS_PER_TICK", "1")  # cap = 1
    r_old = _now() - timedelta(hours=3)
    r_mid = _now() - timedelta(hours=2)
    r_new = _now() - timedelta(hours=1)
    _seed_email(runner, "e_old", subject="annaberg old", received=r_old)
    _seed_email(runner, "e_mid", subject="annaberg mid", received=r_mid)
    _seed_email(runner, "e_new", subject="annaberg new", received=r_new)

    # Tick 1: only the OLDEST is issued (cap=1). The cursor freezes at r_old, NOT r_new.
    s1 = bridge.run_tick()
    assert s1["issued"] == 1
    assert _terminal(runner, "e_old")[0] == "TICKET"
    assert _terminal(runner, "e_mid")[0] is None      # not stranded — still NULL
    assert _terminal(runner, "e_new")[0] is None
    wm1 = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm1 - r_old).total_seconds()) < 1.0   # froze at OLDEST, not newest

    # Tick 2: e_old is an idempotent no-op, e_mid is issued; cursor moves to r_mid.
    s2 = bridge.run_tick()
    assert s2["issued"] == 1
    assert s2["terminal_written"] == 1                # only e_mid written this tick
    assert _terminal(runner, "e_mid")[0] == "TICKET"
    assert _terminal(runner, "e_new")[0] is None
    wm2 = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm2 - r_mid).total_seconds()) < 1.0

    # Tick 3: e_new is finally issued — nothing was ever stranded.
    s3 = bridge.run_tick()
    assert s3["issued"] == 1
    assert _terminal(runner, "e_new")[0] == "TICKET"


# 10 — P1-B: a bus-post failure is a FAILURE (terminal stays NULL, `failed` counts),
# the watermark must NOT advance past it, and reserve_ticket retries it next tick.
def test_p1b_bus_fail_is_failure_and_retried(runner, monkeypatch):
    r = _now() - timedelta(hours=1)
    _seed_email(runner, "ebus", subject="annaberg bus", received=r)

    # Tick 1: bus down -> issue_ticket returns bus_failed (ok=False, no id).
    monkeypatch.setattr(
        bridge, "post_ticket_to_bus",
        lambda ticket: {"ok": False, "error": "bus_down"},
    )
    s1 = bridge.run_tick()
    assert s1["failed"] >= 1
    assert s1["terminal_written"] == 0
    assert _terminal(runner, "ebus")[0] is None          # NOT cleared, NOT ticketed
    with runner.cursor() as cur:
        cur.execute("SELECT status FROM airport_tickets WHERE source_id='ebus'")
        assert cur.fetchone()[0] == "failed"             # live status axis marked failed
    wm1 = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert wm1 < r                                        # cursor did NOT advance past it

    # Tick 2: bus recovers -> the SAME arrival is re-fetched (cursor never passed it)
    # and reserve_ticket's failed-retry branch re-posts it to a clean TICKET.
    monkeypatch.setattr(
        bridge, "post_ticket_to_bus",
        lambda ticket: {"ok": True, "message_id": 777, "thread_id": "t-777"},
    )
    s2 = bridge.run_tick()
    assert s2["issued"] == 1
    assert _terminal(runner, "ebus")[0] == "TICKET"      # retried and cleared
    wm2 = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm2 - r).total_seconds()) < 1.0          # now advanced past the row


# 11 — P1-C: REJECT_NOISE in C = AUTOMATED-SENDER ONLY. The reason is the precise
# 'automated_sender'; a no-active-keyword arrival is prefiltered at fetch and never
# enters the runner (that branch is dead here — no terminal row is written for it).
def test_p1c_reject_noise_is_automated_sender_only(runner):
    # (a) automated sender WITH an active keyword -> REJECT_NOISE / automated_sender.
    _seed_email(runner, "eauto", subject="aukera digest",
                sender_email="noreply@example.com")
    # (b) human sender, NO active keyword -> prefiltered at fetch, never processed.
    _seed_email(runner, "enokw", subject="weekly lunch menu",
                sender_email="balazs@brisengroup.com", body="sandwiches on friday")

    s = bridge.run_tick()
    assert s["deterministic_cleared"] >= 1
    status, _ = _terminal(runner, "eauto")
    assert status == "REJECT_NOISE"
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason FROM airport_tickets WHERE raw_source_id='eauto'")
        assert cur.fetchone()[0] == "automated_sender"   # not the old no-keyword blend
        # the no-keyword arrival was prefiltered at fetch -> no airport_tickets row.
        cur.execute("SELECT COUNT(*) FROM airport_tickets WHERE source_id='enokw'")
        assert cur.fetchone()[0] == 0


# 12 — BLANK CURSOR: on FIRST activation (no watermark row) the runner must scan the
# FULL lookback floor (default 48h), not get_watermark's NOW-24h fallback. A 30h-old
# keyword email in the 24h→48h gap would be stranded permanently under the fallback.
def test_p1_blank_cursor_scans_full_lookback(runner):
    # No AIRPORT_TICKETING_LOOKBACK_HOURS set -> default 48h floor.
    with runner.cursor() as cur:
        cur.execute("DELETE FROM trigger_watermarks WHERE source = %s",
                    (bridge._WATERMARK_SOURCE,))
    runner.commit()
    assert bridge.trigger_state_watermark_raw(bridge._WATERMARK_SOURCE) is None  # blank

    r_30h = _now() - timedelta(hours=30)          # inside 48h floor, beyond 24h fallback
    _seed_email(runner, "eblank", subject="annaberg blank cursor", received=r_30h)

    s = bridge.run_tick()
    assert s["issued"] == 1
    assert s["terminal_written"] == 1
    # Would be NULL (stranded) if `since` had collapsed to the NOW-24h fallback.
    assert _terminal(runner, "eblank")[0] == "TICKET"
    wm = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm - r_30h).total_seconds()) < 1.0


# ============================================================================
# BOX5_HARD_FAST_LANE_1 (D) — project-number hard fast lane branch in run_tick.
# ============================================================================
# INBOUND counterparty participant (external project participant). NOT a Brisen
# address: an @brisengroup.com sender would short-circuit as outbound before D's/E's
# lanes (BOX5_OUTBOUND_INGEST_1), so the lane tests must bind an inbound participant.
_BOUND_SENDER = "partner@aukera.lu"


@pytest.fixture
def hard_lane(runner, needs_live_pg, monkeypatch):
    """Extend `runner`: wire project_registry to the SAME DB, point slug validation
    at the fixture vault, and hand back a clean registry + a `register` helper. Each
    test seeds exactly the codes it needs and sets BOX5_FAST_LANE_ENABLED itself."""
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(_FIXTURE_VAULT))
    slug_registry.reload()
    with get_conn() as conn:
        reg.ensure_project_registry_table(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_registry")
        conn.commit()

    def register(project_number, desk_owner="baden-baden-desk", participants=None):
        with get_conn() as conn:
            return reg.register_project(
                conn, project_number=project_number, desk_owner=desk_owner,
                matter_slug=_FIXTURE_CANONICAL_SLUG, participants=participants or [],
            )

    yield register
    slug_registry.reload()


# 13 — D case 3: a 1-code arrival whose code is UNREGISTERED never fast-clears
#      (regex shape alone is not a clearance, #4679.3) -> TICKET.
def test_hard_lane_regex_only_no_row_is_ticket(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    # registry is empty -> resolve_project_number returns None
    _seed_email(runner, "hl_unreg", subject="aukera update",
                sender_email=_BOUND_SENDER, body="ref BB-AUK-001 (unregistered)")
    s = bridge.run_tick()
    assert s["fast_ticket"] == 0
    assert _terminal(runner, "hl_unreg")[0] == "TICKET"


# 14 — D case 4: registered ACTIVE code + sender in the participant set -> FAST_TICKET.
def test_hard_lane_valid_code_and_binding_is_fast_ticket(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001", participants=[{"channel": "email", "value": _BOUND_SENDER}])
    _seed_email(runner, "hl_ok", subject="aukera funding",
                sender_email=_BOUND_SENDER, body="please review BB-AUK-001 for closing")
    s = bridge.run_tick()
    assert s["fast_ticket"] == 1
    status, _ = _terminal(runner, "hl_ok")
    assert status == "FAST_TICKET"
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason FROM airport_tickets WHERE raw_source_id='hl_ok'")
        assert cur.fetchone()[0].startswith("hard_lane_project_code_participant_bound")
    assert s["deterministic_cleared"] == 0   # a fast-lane clear is NOT a deterministic clear
    assert s["defaulted_ticket"] == 0


# 15 — D case 5: registered ACTIVE code but sender NOT bound -> TICKET (binding mandatory).
def test_hard_lane_valid_code_no_binding_is_ticket(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001", participants=[{"channel": "email", "value": _BOUND_SENDER}])
    _seed_email(runner, "hl_unbound", subject="aukera funding",
                sender_email="stranger@example.com", body="review BB-AUK-001 please")
    s = bridge.run_tick()
    assert s["fast_ticket"] == 0
    assert _terminal(runner, "hl_unbound")[0] == "TICKET"


# 16 — D case 6: >1 distinct code = cross-matter CONFLICT (F4) -> TICKET, never fast-board.
def test_hard_lane_conflict_two_codes_is_ticket(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001", participants=[{"channel": "email", "value": _BOUND_SENDER}])
    hard_lane("AO-MOV-002", desk_owner="ao-desk",
              participants=[{"channel": "email", "value": _BOUND_SENDER}])
    _seed_email(runner, "hl_conflict", subject="aukera cross ref",
                sender_email=_BOUND_SENDER, body="both BB-AUK-001 and AO-MOV-002 appear")
    s = bridge.run_tick()
    assert s["fast_ticket"] == 0
    assert _terminal(runner, "hl_conflict")[0] == "TICKET"


# 17 — D case 7: an exception in D's resolve/BIND composition NEVER auto-FAST_TICKETs.
#      The hard-lane throw rolls back ONLY D's partial work (savepoint), PRESERVES the
#      issue_ticket reservation, and STILL ends the arrival at a visible terminal TICKET
#      — never FAST_TICKET, never stranded as None (blocker-D3 / every-arrival-visible).
#      It counts `failed`, and the batch keeps processing the next arrival.
#
#      ROUTING-REVERSAL interaction (BOX5_ROUTING_REVERSAL_E_1): the boom is scoped to
#      resolve_by_participant — D's BINDING step. After D rolls back + falls through,
#      E's explicit-code lane runs. E does NOT use participant binding, so it is
#      unaffected by the boom: it routes the valid registered ACTIVE code to its desk as
#      a code-routed TICKET (reason explicit_code_routed_ticket:<pn>). So the arrival now
#      ends at E's routed TICKET, not (f) safe-default — still visible, still never
#      FAST_TICKET. This is intended: a valid registered code reaches its desk even when
#      the binding lookup errors. (The code-less second arrival still lands (f) default.)
def test_hard_lane_error_never_fast_tickets(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001", participants=[{"channel": "email", "value": _BOUND_SENDER}])

    def _boom(channel, value):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(bridge, "resolve_by_participant", _boom)
    _seed_email(runner, "hl_err", subject="aukera funding",
                sender_email=_BOUND_SENDER, body="review BB-AUK-001",
                received=_now() - timedelta(hours=2))
    _seed_email(runner, "hl_plain", subject="aukera plain note",
                sender_email=_BOUND_SENDER, body="no code here",
                received=_now() - timedelta(hours=1))
    s = bridge.run_tick()
    assert s["fast_ticket"] == 0           # D's binding step threw -> never fast-tickets
    assert s["failed"] >= 1                # D counted the throw
    assert s["deterministic_cleared"] == 0
    # D's throw preserved the reservation (scoped rollback); E then routed the valid code,
    # and the code-less second arrival landed (f) default -> both wrote a visible terminal.
    assert s["terminal_written"] >= 1
    assert s["code_routed_ticket"] >= 1    # E routed hl_err's valid code (binding not needed)
    assert s["defaulted_ticket"] >= 1      # hl_plain (no code) -> (f) default
    err_status, err_written = _terminal(runner, "hl_err")
    assert err_status == "TICKET"          # visible terminal, NOT None (and NOT FAST_TICKET)
    assert err_written is not None         # terminal_outcome_written_at stamped
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason FROM airport_tickets WHERE raw_source_id='hl_err'")
        # E's routed TICKET after D's binding error — the valid code still reaches its desk.
        assert cur.fetchone()[0] == "explicit_code_routed_ticket:BB-AUK-001"
    # the batch kept processing the second (code-less) arrival
    assert _terminal(runner, "hl_plain")[0] == "TICKET"


# 18 — D case 8: flag OFF -> the whole branch is skipped; a registered+bound arrival
#      lands on C's safe-default TICKET (D adds nothing live until the flag flips).
def test_hard_lane_flag_off_is_noop(runner, hard_lane, monkeypatch):
    monkeypatch.delenv("BOX5_FAST_LANE_ENABLED", raising=False)  # default false
    hard_lane("BB-AUK-001", participants=[{"channel": "email", "value": _BOUND_SENDER}])
    _seed_email(runner, "hl_off", subject="aukera funding",
                sender_email=_BOUND_SENDER, body="review BB-AUK-001 please")
    s = bridge.run_tick()
    assert s["fast_ticket"] == 0
    assert _terminal(runner, "hl_off")[0] == "TICKET"


# ============================================================================
# BOX5_ROUTING_REVERSAL_E_1 (E) — EXPLICIT-CODE routed lane. Routing reversal
# (Director ruling 2026-07-01): name/alias matching is UNSAFE for multi-matter
# counterparties, so alias is NO LONGER a routing signal. E's block (e.7) sits
# AFTER D's (e.5) hard lane and BEFORE C's (f) safe default, guarded
# `if fast_lane and row_id and not handled:` — it runs ONLY when D did not
# FAST_TICKET. E routes ONLY on a single registered ACTIVE project code that D
# left unrouted (code present, sender not participant-bound) -> routed TICKET
# (confidence 0.80), never FAST_TICKET. 0 / >1 / unregistered / retired codes, and
# any alias/participant-only match, fall through to (f) TICKET. Tests exercise the
# merged run_tick (live-PG); the `hard_lane` fixture wires the registry DB + fixture
# vault, `_register_soft` still registers alias rows to prove alias no longer routes.
# ============================================================================

_OTHER_SENDER = "other@aukera.lu"  # inbound (see _BOUND_SENDER note); non-arrival participant


def _register_soft(project_number, *, participants, aliases,
                   desk_owner="baden-baden-desk"):
    """Register an ACTIVE project WITH aliases (the hard_lane fixture's own helper is
    participant-only). matter_slug MUST be the fixture-vault canonical slug —
    register_project rejects non-canonical slugs and the harness points slug_registry
    at tests/fixtures/vault, where only 'alpha' is canonical ('aukera' is canonical
    only against the prod vault)."""
    with get_conn() as conn:
        return reg.register_project(
            conn, project_number=project_number, desk_owner=desk_owner,
            matter_slug=_FIXTURE_CANONICAL_SLUG,
            participants=participants, aliases=aliases,
        )


def _routing(conn, message_id):
    """(matter_slug, desk_owner, confidence, manifest_match_signals) for a row — the
    columns ONLY the soft lane populates on a TICKET."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT matter_slug, desk_owner, confidence, manifest_match_signals "
            "FROM airport_tickets WHERE raw_source_id = %s LIMIT 1",
            (message_id,),
        )
        row = cur.fetchone()
    return row if row else (None, None, None, None)


# 19 — AC1 (replaces the old E success test): a bound participant + a registry
#      alias agree on ONE project but there is NO explicit code in the text ->
#      E no longer routes. Lands (f) safe_default_desk_review, no routing columns.
#      This is the routing reversal: the old soft lane fast-routed this exact arrival.
def test_ac1_participant_and_alias_no_code_does_not_route(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    _register_soft("BB-AUK-001",
                   participants=[{"channel": "email", "value": _BOUND_SENDER}],
                   aliases=["annaberg"])
    # participant (sender bound) + alias ('annaberg') both hit BB-AUK-001, NO code
    # in the text. Under the old soft lane this routed; alias is no longer a signal.
    _seed_email(runner, "e_ac1", subject="status update",
                sender_email=_BOUND_SENDER, body="please review annaberg closing")
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 0
    assert s["fast_ticket"] == 0
    status, _ = _terminal(runner, "e_ac1")
    assert status == "TICKET"
    matter_slug, desk_owner, _, signals = _routing(runner, "e_ac1")
    assert matter_slug is None and desk_owner is None    # E did NOT route
    assert signals == []                                 # default '[]' untouched
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason FROM airport_tickets WHERE raw_source_id='e_ac1'")
        assert cur.fetchone()[0] == "safe_default_desk_review"


# 20 — AC2: a single registered ACTIVE code with the sender NOT participant-bound
#      (so D's hard lane fell through) -> E routes a TICKET (desk review), reason
#      explicit_code_routed_ticket:<pn>, routing columns set, confidence 0.80,
#      NEVER FAST_TICKET.
def test_ac2_explicit_code_unbound_is_routed_ticket(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001")   # registered ACTIVE, NO participants -> sender unbound
    _seed_email(runner, "e_ac2", subject="aukera funding",
                sender_email=_BOUND_SENDER, body="please review BB-AUK-001 for closing")
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 1
    assert s["fast_ticket"] == 0
    assert s["deterministic_cleared"] == 0
    status, written = _terminal(runner, "e_ac2")
    assert status == "TICKET"            # ROUTED, not FAST_TICKET
    assert written is not None
    matter_slug, desk_owner, confidence, signals = _routing(runner, "e_ac2")
    assert matter_slug == _FIXTURE_CANONICAL_SLUG        # 'alpha' in the fixture vault
    assert desk_owner == "baden-baden-desk"
    assert float(confidence) == 0.80
    assert isinstance(signals, list) and len(signals) == 1
    assert signals[0]["signal"] == "project_code"
    assert signals[0]["value"] == "BB-AUK-001"
    assert signals[0]["binding"] == "registry_active"
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason FROM airport_tickets WHERE raw_source_id='e_ac2'")
        assert cur.fetchone()[0] == "explicit_code_routed_ticket:BB-AUK-001"


# 21 — AC3: a single registered ACTIVE code AND the sender participant-bound -> D's
#      hard lane writes FAST_TICKET first; E is never reached (D-before-E precedence),
#      code_routed_ticket stays 0.
def test_ac3_explicit_code_bound_is_fast_ticket_e_not_reached(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001", participants=[{"channel": "email", "value": _BOUND_SENDER}])
    _seed_email(runner, "e_ac3", subject="aukera funding",
                sender_email=_BOUND_SENDER, body="review BB-AUK-001 for closing")
    s = bridge.run_tick()
    assert s["fast_ticket"] == 1
    assert s["code_routed_ticket"] == 0
    assert _terminal(runner, "e_ac3")[0] == "FAST_TICKET"


# 22 — AC4: the registry alias 'annaberg' + a bound participant, NO code -> E does
#      not route (alias is not a routing signal) -> (f) TICKET, no routing columns.
def test_ac4_alias_annaberg_participant_no_code_does_not_route(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    _register_soft("BB-AUK-001",
                   participants=[{"channel": "email", "value": _BOUND_SENDER}],
                   aliases=["annaberg"])
    _seed_email(runner, "e_ac4", subject="annaberg status",
                sender_email=_BOUND_SENDER, body="annaberg update please review")
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 0
    assert _terminal(runner, "e_ac4")[0] == "TICKET"
    assert _routing(runner, "e_ac4")[0] is None


# 23 — AC5: the multiword registry alias 'aukera annaberg' + a bound participant,
#      NO code -> E does not route -> (f) TICKET.
def test_ac5_alias_multiword_participant_no_code_does_not_route(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    _register_soft("BB-AUK-001",
                   participants=[{"channel": "email", "value": _BOUND_SENDER}],
                   aliases=["aukera annaberg"])
    _seed_email(runner, "e_ac5", subject="aukera annaberg",
                sender_email=_BOUND_SENDER, body="aukera annaberg matter update")
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 0
    assert _terminal(runner, "e_ac5")[0] == "TICKET"
    assert _routing(runner, "e_ac5")[0] is None


# 24 — AC6: two DISTINCT explicit codes in one row = cross-matter CONFLICT ->
#      len(set(codes)) != 1 -> E does not route -> (f) TICKET.
def test_ac6_two_distinct_codes_conflict_does_not_route(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001")
    hard_lane("AO-MOV-002", desk_owner="ao-desk")
    _seed_email(runner, "e_ac6", subject="aukera cross ref",
                sender_email=_BOUND_SENDER, body="both BB-AUK-001 and AO-MOV-002 appear")
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 0
    assert s["fast_ticket"] == 0
    assert _terminal(runner, "e_ac6")[0] == "TICKET"
    assert _routing(runner, "e_ac6")[0] is None


# 25 — AC7: a single code of valid SHAPE but UNREGISTERED (empty registry) ->
#      resolve_project_number returns None -> E does not route -> (f) TICKET. A
#      retired code resolves identically (the ACTIVE-only query returns None), so
#      unregistered is the representative no-route case for both.
def test_ac7_unregistered_code_does_not_route(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    # registry left empty -> BB-AUK-001 is unregistered -> resolve returns None.
    _seed_email(runner, "e_ac7", subject="aukera update",
                sender_email=_BOUND_SENDER, body="ref BB-AUK-001 (unregistered)")
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 0
    assert s["fast_ticket"] == 0
    assert _terminal(runner, "e_ac7")[0] == "TICKET"
    assert _routing(runner, "e_ac7")[0] is None


# 26 — E error path: a raise inside E's routed write NEVER routes. It rolls back to
#      the SAVEPOINT (preserving issue_ticket's reservation), counts failed, and STILL
#      ends the arrival at a visible (f) TICKET — never stranded, never
#      code_routed_ticket++ (the savepoint-strand P1 class codex caught on D). The
#      boom is scoped to E's routed write (matter_slug kwarg) so D's FAST_TICKET path
#      and (f)'s default write are untouched.
def test_e_error_never_routes_and_ends_visible(runner, hard_lane, monkeypatch):
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    hard_lane("BB-AUK-001")   # ACTIVE, no participants -> D falls through, E runs

    real_wts = bridge.write_terminal_status

    def _boom_on_route(*args, **kwargs):
        # ONLY E's routed write carries matter_slug; D's FAST_TICKET and (f)'s
        # default write do not -> let those through, blow up ONLY E's route.
        if kwargs.get("matter_slug"):
            raise RuntimeError("routed terminal write exploded")
        return real_wts(*args, **kwargs)

    monkeypatch.setattr(bridge, "write_terminal_status", _boom_on_route)
    _seed_email(runner, "e_err", subject="aukera funding",
                sender_email=_BOUND_SENDER, body="review BB-AUK-001",
                received=_now() - timedelta(hours=2))
    _seed_email(runner, "e_next", subject="aukera plain",
                sender_email=_BOUND_SENDER, body="a second note, no code",
                received=_now() - timedelta(hours=1))
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 0
    assert s["fast_ticket"] == 0
    assert s["deterministic_cleared"] == 0
    assert s["failed"] >= 1
    # errored row still ends at a (f) TICKET (savepoint preserved the reservation),
    # NOT a routed clear and NOT stranded as None.
    err_status, err_written = _terminal(runner, "e_err")
    assert err_status == "TICKET"
    assert err_written is not None
    with runner.cursor() as cur:
        cur.execute("SELECT terminal_reason FROM airport_tickets WHERE raw_source_id='e_err'")
        assert cur.fetchone()[0] == "safe_default_desk_review"   # (f), not routed
    assert _routing(runner, "e_err")[0] is None                  # no routing columns
    # the batch kept processing the next arrival
    assert _terminal(runner, "e_next")[0] == "TICKET"


# 27 — Regression: flag OFF -> E's branch is not entered; a registered-code arrival
#      lands on C's safe-default TICKET with no routing columns (E adds nothing live
#      until BOX5_FAST_LANE_ENABLED flips).
def test_e_flag_off_is_noop(runner, hard_lane, monkeypatch):
    monkeypatch.delenv("BOX5_FAST_LANE_ENABLED", raising=False)  # default false
    hard_lane("BB-AUK-001")
    _seed_email(runner, "e_off", subject="aukera funding",
                sender_email=_BOUND_SENDER, body="review BB-AUK-001 please")
    s = bridge.run_tick()
    assert s["code_routed_ticket"] == 0
    assert s["fast_ticket"] == 0
    assert _terminal(runner, "e_off")[0] == "TICKET"
    assert _routing(runner, "e_off")[0] is None



# ============================================================================
# BOX5_OUTBOUND_INGEST_1 — direction-aware ingestion (Increment 1). Outbound
# (Brisen-controlled sender) short-circuits BEFORE build_email_ticket + every lane:
# it NEVER boards a desk / nudges / fast-soft-routes. Dark behind
# AIRPORT_OUTBOUND_INGEST_ENABLED (default false). AC1 is a pure classifier unit;
# AC2-AC5 exercise the merged run_tick on live-PG via the `runner` harness.
# ============================================================================
_OUTBOUND_SENDER = "dvallen@brisengroup.com"       # Brisen-controlled domain
_COUNTERPARTY_SENDER = "someone@aukera.lu"          # external -> inbound


# AC1 — classifier: Brisen domain + each Director personal address -> outbound;
#       counterparty / unknown / junk / empty / None -> inbound; never raises.
def test_ac1_classify_direction():
    # Brisen-controlled domain -> outbound (case-insensitive).
    assert bridge._classify_direction("dvallen@brisengroup.com") == "outbound"
    assert bridge._classify_direction("balazs@brisengroup.com") == "outbound"
    assert bridge._classify_direction("Office.Vienna@BrisenGroup.COM") == "outbound"
    # Director personal addresses in the allowlist -> outbound.
    assert bridge._classify_direction("vallen300@gmail.com") == "outbound"
    assert bridge._classify_direction("dvallen@bluewin.ch") == "outbound"
    assert bridge._classify_direction("office.vienna@brisengroup.com") == "outbound"
    # Counterparty / unknown / non-allowlisted personal -> inbound.
    assert bridge._classify_direction("someone@aukera.lu") == "inbound"
    assert bridge._classify_direction("random.person@gmail.com") == "inbound"
    assert bridge._classify_direction("mohg@example.com") == "inbound"
    # Junk / empty / None -> inbound, never raises.
    assert bridge._classify_direction("") == "inbound"
    assert bridge._classify_direction("not-an-email") == "inbound"      # no '@'
    assert bridge._classify_direction("   ") == "inbound"               # whitespace only
    assert bridge._classify_direction(None) == "inbound"                # type: ignore[arg-type]
    # Domain-match wins even with an empty local part (never a real sender, but the
    # classifier is deterministic: a Brisen domain part -> outbound).
    assert bridge._classify_direction("@brisengroup.com") == "outbound"


# AC2 — flag ON: an outbound-sender arrival persists direction='outbound', creates
#       NO desk ticket (no bus post, terminal_status stays NULL, status='candidate'),
#       NO nudge, and logs EXACTLY ONE 'airport_ticket.outbound_signal'.
def test_ac2_outbound_flag_on_captures_signal_no_desk(runner, monkeypatch):
    monkeypatch.setenv("AIRPORT_OUTBOUND_INGEST_ENABLED", "true")
    _seed_email(runner, "ob1", subject="annaberg status - closing actions",
                sender_email=_OUTBOUND_SENDER, body="annaberg step plan, DV to sign")
    s = bridge.run_tick()
    assert s["ok"]
    assert s["outbound_signal"] == 1
    assert s["issued"] == 0                 # NO bus post / boarding pass
    assert s["terminal_written"] == 0       # NO terminal desk clear
    assert s["defaulted_ticket"] == 0
    assert s["fast_ticket"] == 0 and s["code_routed_ticket"] == 0
    with runner.cursor() as cur:
        cur.execute(
            "SELECT direction, status, terminal_status, proposed_desk_slug "
            "FROM airport_tickets WHERE source_id='ob1'"
        )
        direction, status, term, desk = cur.fetchone()
    assert direction == "outbound"
    assert term is None                     # never a terminal desk outcome
    assert status == "candidate"            # never advanced to 'sent' (never boarded)
    assert desk == bridge._OUTBOUND_DESK    # sentinel, not a real desk
    # exactly ONE outbound_signal action for THIS ticket; NO 'created'/'terminal' action.
    ticket_id = "airport-outbound:ob1"
    with runner.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM baker_actions "
            "WHERE action_type='airport_ticket.outbound_signal' AND target_task_id=%s",
            (ticket_id,),
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT COUNT(*) FROM baker_actions WHERE target_task_id=%s "
            "AND action_type IN ('airport_ticket.created','airport_ticket.terminal_written')",
            (ticket_id,),
        )
        assert cur.fetchone()[0] == 0


# AC2b — flag ON: re-tick is idempotent — the second pass logs NO second action.
def test_ac2b_outbound_capture_idempotent(runner, monkeypatch):
    monkeypatch.setenv("AIRPORT_OUTBOUND_INGEST_ENABLED", "true")
    _seed_email(runner, "ob_idem", subject="annaberg funding",
                sender_email=_OUTBOUND_SENDER, body="annaberg to sign")
    s1 = bridge.run_tick()
    assert s1["outbound_signal"] == 1
    s2 = bridge.run_tick()
    assert s2["outbound_signal"] == 0       # already captured -> no new signal
    with runner.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM baker_actions "
            "WHERE action_type='airport_ticket.outbound_signal' "
            "AND target_task_id='airport-outbound:ob_idem'"
        )
        assert cur.fetchone()[0] == 1       # still exactly one


# AC3 — flag ON: an inbound-sender arrival is unchanged (routes as today -> safe
#       default TICKET + bus post) and persists direction='inbound' (column default).
def test_ac3_outbound_flag_on_inbound_unchanged(runner, monkeypatch):
    monkeypatch.setenv("AIRPORT_OUTBOUND_INGEST_ENABLED", "true")
    _seed_email(runner, "ib1", subject="annaberg closing",
                sender_email=_COUNTERPARTY_SENDER, body="annaberg review please")
    s = bridge.run_tick()
    assert s["defaulted_ticket"] == 1       # routes exactly as today
    assert s["issued"] == 1                 # boards the desk (bus post)
    assert s["outbound_signal"] == 0
    assert _terminal(runner, "ib1")[0] == "TICKET"
    with runner.cursor() as cur:
        cur.execute("SELECT direction FROM airport_tickets WHERE source_id='ib1'")
        assert cur.fetchone()[0] == "inbound"   # via NOT NULL DEFAULT 'inbound'


# AC4 — flag OFF (dark): BOTH inbound AND outbound-sender arrivals are processed
#       byte-identical to pre-change — outbound is NOT skipped when dark, so a merge is
#       a pure no-op. (Corrected by lead #4837: the (b.5) short-circuit is itself gated
#       behind the flag, so nothing classifies/skips until the flag flips.)
def test_ac4_flag_off_outbound_processed_as_pre_change(runner, monkeypatch):
    monkeypatch.delenv("AIRPORT_OUTBOUND_INGEST_ENABLED", raising=False)  # default false
    r_ob = _now() - timedelta(hours=2)
    r_ib = _now() - timedelta(hours=1)
    _seed_email(runner, "ob_off", subject="annaberg to sign",
                sender_email=_OUTBOUND_SENDER, body="annaberg outbound note", received=r_ob)
    _seed_email(runner, "ib_off", subject="annaberg closing",
                sender_email=_COUNTERPARTY_SENDER, body="annaberg inbound note", received=r_ib)
    s = bridge.run_tick()
    assert s["outbound_signal"] == 0            # no capture when dark
    # the outbound-sender arrival is processed exactly like any inbound keyword
    # arrival: safe-default TICKET + bus post, a row carrying direction via the column
    # DEFAULT (the classifier is never consulted when dark).
    assert s["defaulted_ticket"] == 2          # BOTH ob_off + ib_off ticketed
    assert s["issued"] == 2
    assert _terminal(runner, "ob_off")[0] == "TICKET"
    assert _terminal(runner, "ib_off")[0] == "TICKET"
    with runner.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM airport_tickets WHERE source_id='ob_off'")
        assert cur.fetchone()[0] == 1          # a row EXISTS (not skipped)
        cur.execute("SELECT direction FROM airport_tickets WHERE source_id='ob_off'")
        assert cur.fetchone()[0] == "inbound"  # column default; NOT classified when dark
    wm = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm - r_ib).total_seconds()) < 1.0


# AC4b — flag ON: an OLDEST outbound-sender arrival (captured + lane-skipped) must not
#        strand a NEWER inbound one; the cursor advances past the capture (exercises the
#        replicated (P1-A) cursor-advance in the (b.5) block).
def test_ac4b_flag_on_outbound_capture_does_not_strand_batch(runner, monkeypatch):
    monkeypatch.setenv("AIRPORT_OUTBOUND_INGEST_ENABLED", "true")
    monkeypatch.setenv("AIRPORT_TICKETING_MAX_POSTS_PER_TICK", "25")
    r_ob = _now() - timedelta(hours=3)      # oldest = captured outbound
    r_ib = _now() - timedelta(hours=1)
    _seed_email(runner, "ob_head", subject="annaberg lead",
                sender_email=_OUTBOUND_SENDER, body="annaberg outbound", received=r_ob)
    _seed_email(runner, "ib_tail", subject="annaberg tail",
                sender_email=_COUNTERPARTY_SENDER, body="annaberg inbound", received=r_ib)
    s = bridge.run_tick()
    assert s["outbound_signal"] == 1
    assert _terminal(runner, "ib_tail")[0] == "TICKET"   # processed same tick, not stranded
    assert s["issued"] == 1
    wm = bridge.trigger_state_get_watermark(bridge._WATERMARK_SOURCE)
    assert abs((wm - r_ib).total_seconds()) < 1.0        # advanced past the outbound head


# AC5 — the direction column exists after bootstrap (NOT NULL DEFAULT 'inbound'),
#       existing rows backfill to 'inbound', and the bootstrap is idempotent.
def test_ac5_direction_column_and_bootstrap_idempotent(runner):
    with runner.cursor() as cur:
        cur.execute(
            "SELECT data_type, column_default, is_nullable FROM information_schema.columns "
            "WHERE table_name='airport_tickets' AND column_name='direction'"
        )
        row = cur.fetchone()
    assert row is not None                       # column present after fixture bootstrap
    assert row[1] is not None and "inbound" in row[1]   # DEFAULT 'inbound'
    assert row[2] == "NO"                        # NOT NULL
    # an INSERT that omits direction backfills to 'inbound' (safe on populated tables).
    with runner.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id,dedup_key,source_channel,source_id,"
            "proposed_desk_slug) VALUES ('bf','bf','email','bf','baden-baden-desk')"
        )
        cur.execute("SELECT direction FROM airport_tickets WHERE source_id='bf'")
        assert cur.fetchone()[0] == "inbound"
    runner.commit()
    # bootstrap idempotent: re-run ensure on a populated table -> no error, value intact.
    bridge.ensure_airport_ticket_table(runner)
    runner.commit()
    with runner.cursor() as cur:
        cur.execute("SELECT direction FROM airport_tickets WHERE source_id='bf'")
        assert cur.fetchone()[0] == "inbound"


# AC5b — captured OUTBOUND rows (terminal_status NULL by design) are NOT counted as
#        stuck by the journey gauge; a genuinely-stalled inbound row still is.
def test_ac5b_outbound_rows_excluded_from_stuck_gauge(runner):
    with runner.cursor() as cur:
        # aged outbound capture (terminal_status NULL) -> must NOT count as stuck.
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id,dedup_key,source_channel,source_id,"
            "source_received_at,proposed_desk_slug,direction) "
            "VALUES ('so','so','email','so', NOW() - INTERVAL '90 minutes','outbound','outbound')"
        )
        # aged inbound row with no terminal_status -> genuinely stuck.
        cur.execute(
            "INSERT INTO airport_tickets (ticket_id,dedup_key,source_channel,source_id,"
            "source_received_at,proposed_desk_slug) "
            "VALUES ('si','si','email','si', NOW() - INTERVAL '90 minutes','baden-baden-desk')"
        )
    runner.commit()
    assert bridge._count_stuck_arrivals(runner) == 1   # only the inbound row, not the outbound one


# AC6 — flag ON: an outbound-sender arrival skips ALL lanes (even when the HARD lane
#       WOULD otherwise fast-track it) and captures exactly one outbound_signal — no
#       desk ticket, no nudge, no FAST_TICKET. Proves the (b.5) short-circuit runs
#       BEFORE D's / E's lanes. (lead #4837.)
def test_ac6_flag_on_outbound_skips_lanes_even_when_hard_lane_would_fire(
    runner, hard_lane, monkeypatch
):
    monkeypatch.setenv("AIRPORT_OUTBOUND_INGEST_ENABLED", "true")
    monkeypatch.setenv("BOX5_FAST_LANE_ENABLED", "true")
    # register the outbound sender as a participant of an active project + put its code
    # in the body: D's hard lane WOULD FAST_TICKET this if it ran. It must not run.
    hard_lane("BB-AUK-001",
              participants=[{"channel": "email", "value": _OUTBOUND_SENDER}])
    _seed_email(runner, "ob_lane", subject="aukera funding",
                sender_email=_OUTBOUND_SENDER, body="review BB-AUK-001 for closing")
    s = bridge.run_tick()
    assert s["outbound_signal"] == 1
    assert s["fast_ticket"] == 0          # hard lane never ran
    assert s["code_routed_ticket"] == 0
    assert s["issued"] == 0               # no bus / no desk boarding
    assert _terminal(runner, "ob_lane")[0] is None   # no terminal desk outcome
    with runner.cursor() as cur:
        cur.execute("SELECT direction, status FROM airport_tickets WHERE source_id='ob_lane'")
        direction, live_status = cur.fetchone()
    assert direction == "outbound"
    assert live_status == "candidate"     # never boarded a desk
