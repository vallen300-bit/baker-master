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


def _seed_email(conn, message_id, *, subject="annaberg status",
                sender_email="balazs@brisengroup.com", body="annaberg update",
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
_BOUND_SENDER = "balazs@brisengroup.com"


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
                sender_email="stranger@brisengroup.com", body="review BB-AUK-001 please")
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


# 17 — D case 7: an exception in the resolve/bind composition NEVER auto-FAST_TICKETs —
#      it counts `failed`, falls through to TICKET, and the batch continues.
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
    assert s["fast_ticket"] == 0
    assert s["failed"] >= 1
    assert s["deterministic_cleared"] == 0
    # errored row fell through to the safe default, never FAST_TICKET
    assert _terminal(runner, "hl_err")[0] in ("TICKET", None)
    assert _terminal(runner, "hl_err")[0] != "FAST_TICKET"
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
