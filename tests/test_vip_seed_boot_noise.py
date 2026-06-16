"""STARTUP_NOISE_DEADLINES_VIP_FIX_1 — regression for boot-log noise.

Reproduces the two ERROR-level log lines that ``models/deadlines`` emitted on
*every* boot against the live schema, and proves the fix is clean + non-destructive:

  1. ``ensure_tables`` ran ``CREATE OR REPLACE VIEW contacts`` unconditionally.
     In production ``contacts`` is an independent table, so that errored every
     boot with ``"contacts" is not a view``.
  2. ``seed_vip_contacts`` did ``DELETE FROM vip_contacts`` whenever the row
     count != 11 (always — the table holds hundreds of contacts). The DELETE was
     rejected every boot by the ``contact_interactions``/``trip_contacts``
     foreign keys.

The fix: guard the view behind ``to_regclass`` and replace the
DELETE-then-reinsert with an idempotent per-row upsert keyed on ``email``.

Live-PG only — gated behind the shared ``needs_live_pg`` fixture (conftest).
Isolated in its own schema so it never touches real app tables.
"""
from __future__ import annotations

import logging

import psycopg2
import pytest

import models.deadlines as deadlines

_SCHEMA = "b2_vipseed_boot_test"

# A subset of the seed list is enough to exercise both code paths; the real
# list lives in models/deadlines.seed_vip_contacts().
_SEED_EMAILS = {
    "edita.vallen@brisengroup.com",
    "balazs.csepregi@brisengroup.com",
    "conrad.weiss@brisengroup.com",
}


def _scalar(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    val = cur.fetchone()[0]
    cur.close()
    return val


@pytest.fixture
def vip_conn(needs_live_pg, monkeypatch):
    """Single connection pinned to a private schema; module get/put patched to it."""
    conn = psycopg2.connect(needs_live_pg)
    cur = conn.cursor()
    cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    cur.execute(f"CREATE SCHEMA {_SCHEMA}")
    cur.execute(f"SET search_path TO {_SCHEMA}")
    conn.commit()
    cur.close()

    # ensure_tables()/seed_vip_contacts() pull connections via these helpers;
    # hand them our schema-pinned connection and keep it open across calls.
    monkeypatch.setattr(deadlines, "get_conn", lambda: conn)
    monkeypatch.setattr(deadlines, "put_conn", lambda c: None)

    yield conn

    try:
        cur = conn.cursor()
        cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _build_prod_like_state(conn):
    """vip_contacts (>seed-size, FK-referenced) + `contacts` as an independent table."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE vip_contacts (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            role VARCHAR(200),
            email VARCHAR(200),
            whatsapp_id VARCHAR(50),
            fireflies_speaker_label VARCHAR(200),
            added_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    # Seed VIPs already present + non-VIP general contacts (must survive).
    cur.execute(
        """
        INSERT INTO vip_contacts (name, role, email, whatsapp_id) VALUES
            ('Edita Vallen','COO / Brisen Internal','edita.vallen@brisengroup.com','41799439246@c.us'),
            ('Balazs Csepregi','Brisen Internal','balazs.csepregi@brisengroup.com','36303005919@c.us'),
            ('Conrad Weiss','Brisen Internal','conrad.weiss@brisengroup.com','41794033419@c.us'),
            ('General Contact A', NULL, NULL, NULL),
            ('General Contact B', NULL, 'gcb@example.com', NULL),
            ('General Contact C', NULL, NULL, NULL)
        """
    )
    # FK into vip_contacts — this is what rejected the old DELETE every boot.
    cur.execute(
        """
        CREATE TABLE contact_interactions (
            id SERIAL PRIMARY KEY,
            contact_id INTEGER REFERENCES vip_contacts(id),
            note TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO contact_interactions (contact_id, note) "
        "SELECT id, 'historical' FROM vip_contacts WHERE email='edita.vallen@brisengroup.com'"
    )
    # `contacts` exists as an independent TABLE — CREATE OR REPLACE VIEW would error.
    cur.execute("CREATE TABLE contacts (id SERIAL PRIMARY KEY, name TEXT)")
    cur.execute("INSERT INTO contacts (name) VALUES ('independent contacts row')")
    conn.commit()
    cur.close()


def test_boot_is_clean_and_nondestructive(vip_conn, caplog):
    conn = vip_conn
    _build_prod_like_state(conn)

    vip_before = _scalar(conn, "SELECT count(*) FROM vip_contacts")
    contacts_before = _scalar(conn, "SELECT count(*) FROM contacts")

    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="baker.models.deadlines"):
        deadlines.ensure_tables()
        deadlines.seed_vip_contacts()

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, f"boot logged ERROR lines: {[r.getMessage() for r in errors]}"

    # Nothing deleted: count only grows (missing seed VIPs inserted), never drops;
    # general contacts + the FK-referenced row all survive.
    vip_after = _scalar(conn, "SELECT count(*) FROM vip_contacts")
    assert vip_after >= vip_before
    assert _scalar(
        conn, "SELECT count(*) FROM vip_contacts WHERE name LIKE 'General Contact%'"
    ) == 3
    assert _scalar(conn, "SELECT count(*) FROM contact_interactions") == 1

    # `contacts` stays an independent table (relkind 'r'), never replaced.
    assert _scalar(
        conn, "SELECT relkind FROM pg_class WHERE relname='contacts' "
              f"AND relnamespace = '{_SCHEMA}'::regnamespace"
    ) == "r"
    assert _scalar(conn, "SELECT count(*) FROM contacts") == contacts_before

    # Seed VIPs are present.
    for email in _SEED_EMAILS:
        assert _scalar(
            conn, f"SELECT count(*) FROM vip_contacts WHERE email = '{email}'"
        ) == 1

    # Idempotent: a second cycle is also clean and does not change counts.
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="baker.models.deadlines"):
        deadlines.ensure_tables()
        deadlines.seed_vip_contacts()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    # All 11 seed VIPs now present, so a second cycle inserts nothing.
    assert _scalar(conn, "SELECT count(*) FROM vip_contacts") == vip_after


def test_missing_seed_vip_is_inserted(vip_conn, caplog):
    conn = vip_conn
    _build_prod_like_state(conn)

    # Remove a seed VIP (and its FK row) to exercise the INSERT-when-missing path.
    cur = conn.cursor()
    cur.execute("DELETE FROM contact_interactions")
    cur.execute("DELETE FROM vip_contacts WHERE email = 'conrad.weiss@brisengroup.com'")
    conn.commit()
    cur.close()
    assert _scalar(
        conn, "SELECT count(*) FROM vip_contacts WHERE email='conrad.weiss@brisengroup.com'"
    ) == 0

    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="baker.models.deadlines"):
        deadlines.seed_vip_contacts()

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    # The missing VIP is re-inserted exactly once.
    assert _scalar(
        conn, "SELECT count(*) FROM vip_contacts WHERE email='conrad.weiss@brisengroup.com'"
    ) == 1
