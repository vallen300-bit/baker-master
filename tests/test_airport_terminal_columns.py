"""BOX5_SCHEMA_FOUNDATION_1 — airport_tickets terminal-status schema tests.

Live-PG (via ``needs_live_pg``; auto-skip without ``TEST_DATABASE_URL`` / ``NEON_*``;
CI runs live). Proves the additive terminal axis lands, the 6-state CHECK is exact
(VISIBLE_HOLD excluded by design), and the two live orthogonal CHECKs are untouched.
"""
from __future__ import annotations

import re

import psycopg2
import psycopg2.errors
import pytest

from orchestrator import airport_ticketing_bridge as bridge

SIX_STATES = {
    "DUPLICATE", "REJECT_NOISE", "REJECT_LOW_RELEVANCE",
    "FAST_TICKET", "TICKET", "FILE_UNSORTED",
}
TERMINAL_COLUMNS = {
    "terminal_status", "terminal_reason", "project_code", "matter_slug", "desk_owner",
    "source_refs", "confidence", "model_used", "cost_tier", "classification_version",
    "registry_version", "manifest_match_signals", "raw_source_table", "raw_source_id",
    "processed_at", "terminal_outcome_written_at",
}


@pytest.fixture
def pg(needs_live_pg):
    conn = psycopg2.connect(needs_live_pg)
    # ensure_airport_ticket_table mirrors ensure_airport_ticket_terminal_columns;
    # call twice to prove the additive ALTER + DROP/ADD CONSTRAINT is idempotent.
    bridge.ensure_airport_ticket_table(conn)
    bridge.ensure_airport_ticket_table(conn)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM airport_tickets")
    conn.commit()
    yield conn
    conn.close()


def _constraintdef(conn, name) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
    return row[0] if row else ""


def test_terminal_columns_present(pg):
    with pg.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'airport_tickets'"
        )
        cols = {r[0] for r in cur.fetchall()}
    missing = TERMINAL_COLUMNS - cols
    assert not missing, f"missing terminal columns: {missing}"


def test_terminal_status_check_is_exactly_six_states_no_visible_hold(pg):
    d = _constraintdef(pg, "airport_tickets_terminal_status_check")
    assert d, "terminal_status CHECK constraint missing"
    assert "VISIBLE_HOLD" not in d  # deliberately excluded (locked #4677.7)
    quoted = set(re.findall(r"'([A-Z_]+)'", d))
    assert quoted == SIX_STATES, f"enum drift: {quoted ^ SIX_STATES}"
    # NULL-tolerant so existing populated rows pass.
    assert "IS NULL" in d


def test_live_status_and_outcome_checks_unchanged(pg):
    status_def = _constraintdef(pg, "airport_tickets_status_check")
    for s in ("candidate", "sent", "failed", "checked_in", "rejected"):
        assert s in status_def
    # the terminal axis must NOT have been blended into the live status CHECK
    assert "terminal" not in status_def.lower()
    for s in SIX_STATES:
        assert s not in status_def  # no terminal state leaked into the status CHECK

    outcome_def = _constraintdef(pg, "airport_tickets_check_in_outcome_check")
    for s in ("VALID", "FAKE", "DUPLICATE", "WRONG_TERMINAL", "URGENT", "NEEDS_LUGGAGE_READ"):
        assert s in outcome_def
    assert "terminal_status" not in outcome_def


def _insert(conn, ticket_id, terminal_status):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_tickets "
            "(ticket_id, dedup_key, source_channel, source_id, proposed_desk_slug, terminal_status) "
            "VALUES (%s, %s, 'email', %s, 'baden-baden-desk', %s)",
            (ticket_id, f"d-{ticket_id}", ticket_id, terminal_status),
        )
    conn.commit()


def test_terminal_status_accepts_six_states_and_null(pg):
    for i, s in enumerate(sorted(SIX_STATES)):
        _insert(pg, f"ok-{i}", s)
    _insert(pg, "null-ok", None)  # NULL / unset must pass the CHECK
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM airport_tickets")
        assert cur.fetchone()[0] == len(SIX_STATES) + 1


@pytest.mark.parametrize("bad", ["VISIBLE_HOLD", "BOGUS", "ticket", "Fast_Ticket"])
def test_terminal_status_rejects_out_of_set(pg, bad):
    with pytest.raises(psycopg2.errors.CheckViolation):
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO airport_tickets "
                "(ticket_id, dedup_key, source_channel, source_id, proposed_desk_slug, terminal_status) "
                "VALUES (%s, %s, 'email', 'x', 'baden-baden-desk', %s)",
                (f"bad-{bad}", f"d-bad-{bad}", bad),
            )
    pg.rollback()  # clear the aborted transaction
