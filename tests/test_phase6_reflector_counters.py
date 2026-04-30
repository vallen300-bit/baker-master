"""Counter-increment tests for orchestrator.cortex_phase6_reflector.

Brief: CORTEX_PHASE6_REFLECTOR_1 §5.2.

Live-PG via ``needs_live_pg`` fixture (auto-skips without TEST_DATABASE_URL).
Exercises increment_counters_on_cited_directives directly + cross-matter
scope hardening.
"""
from __future__ import annotations

import pathlib
import uuid

import pytest


REPO_MIGRATIONS_DIR = str(
    pathlib.Path(__file__).resolve().parents[1] / "migrations"
)


@pytest.fixture
def live_db(needs_live_pg, monkeypatch):
    """Apply repo migrations + force the reflector module to use this DB."""
    import psycopg2
    from config.migration_runner import run_pending_migrations

    run_pending_migrations(needs_live_pg, migrations_dir=REPO_MIGRATIONS_DIR)

    # Reset the SentinelStoreBack singleton so it re-resolves DATABASE_URL
    # from env (which conftest sets to the ephemeral Neon URL).
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    from memory.store_back import SentinelStoreBack
    SentinelStoreBack._global_instance = None  # type: ignore[attr-defined]

    conn = psycopg2.connect(needs_live_pg)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        SentinelStoreBack._global_instance = None  # type: ignore[attr-defined]


def _seed_directive(conn, directive_id: str, matter_slug: str, status: str = "active"):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cortex_directives (directive_id, matter_slug, body, status)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (directive_id) DO UPDATE
            SET status = EXCLUDED.status, matter_slug = EXCLUDED.matter_slug
        """,
        (directive_id, matter_slug, "test body", status),
    )
    conn.commit()
    cur.close()


def _read_counters(conn, directive_id: str) -> dict:
    cur = conn.cursor()
    cur.execute(
        """SELECT helpful_count, harmful_count, stale_count, pending_count
              FROM cortex_directives WHERE directive_id = %s""",
        (directive_id,),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return {}
    return {
        "helpful": row[0],
        "harmful": row[1],
        "stale": row[2],
        "pending": row[3],
    }


def test_increment_helpful_on_cited_directives(live_db):
    """Two cited directives + one un-cited -> only the two get +1."""
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    suffix = uuid.uuid4().hex[:8]
    matter = f"counter-test-{suffix}"
    a = f"{matter}-001"
    b = f"{matter}-002"
    c = f"{matter}-003"  # not cited
    _seed_directive(live_db, a, matter)
    _seed_directive(live_db, b, matter)
    _seed_directive(live_db, c, matter)

    rows, unknown = increment_counters_on_cited_directives(
        cycle_id=str(uuid.uuid4()),
        matter_slug=matter,
        cited_ids=[a, b],
        counter_field="helpful_count",
    )
    assert rows == 2
    assert unknown == []
    assert _read_counters(live_db, a)["helpful"] == 1
    assert _read_counters(live_db, b)["helpful"] == 1
    assert _read_counters(live_db, c)["helpful"] == 0


def test_unknown_id_returned_no_update(live_db):
    """Citation of a directive that doesn't exist returns it in unknown list."""
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    suffix = uuid.uuid4().hex[:8]
    matter = f"unknown-test-{suffix}"
    real = f"{matter}-001"
    fake = f"{matter}-fake-999"
    _seed_directive(live_db, real, matter)

    rows, unknown = increment_counters_on_cited_directives(
        cycle_id=str(uuid.uuid4()),
        matter_slug=matter,
        cited_ids=[real, fake],
        counter_field="helpful_count",
    )
    assert rows == 1
    assert unknown == [fake]
    assert _read_counters(live_db, real)["helpful"] == 1


def test_cross_matter_scope_hardening(live_db):
    """Cite from matter A but directive belongs to matter B -> unknown,
    no increment. Prevents AO cycle from incrementing MOVIE counters via
    fabricated id."""
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    suffix = uuid.uuid4().hex[:8]
    matter_a = f"cross-a-{suffix}"
    matter_b = f"cross-b-{suffix}"
    b_directive = f"{matter_b}-001"
    _seed_directive(live_db, b_directive, matter_b)

    rows, unknown = increment_counters_on_cited_directives(
        cycle_id=str(uuid.uuid4()),
        matter_slug=matter_a,           # cycle on matter A
        cited_ids=[b_directive],         # but cites matter B's directive
        counter_field="helpful_count",
    )
    assert rows == 0
    assert unknown == [b_directive]
    # B's counters untouched (cross-matter increment refused).
    assert _read_counters(live_db, b_directive)["helpful"] == 0


def test_global_id_passes_scope_check(live_db):
    """`_global-*` directives bypass matter_slug scope check."""
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    suffix = uuid.uuid4().hex[:8]
    g_id = f"_global-{suffix}-001"
    _seed_directive(live_db, g_id, "_global")

    rows, unknown = increment_counters_on_cited_directives(
        cycle_id=str(uuid.uuid4()),
        matter_slug=f"any-matter-{suffix}",
        cited_ids=[g_id],
        counter_field="helpful_count",
    )
    assert rows == 1
    assert unknown == []
    assert _read_counters(live_db, g_id)["helpful"] == 1


def test_empty_cited_ids_no_op(live_db):
    """Empty cited list returns (0, []) without raising."""
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    rows, unknown = increment_counters_on_cited_directives(
        cycle_id=str(uuid.uuid4()),
        matter_slug="anything",
        cited_ids=[],
        counter_field="helpful_count",
    )
    assert rows == 0
    assert unknown == []


def test_invalid_counter_field_raises():
    """ValueError on unknown counter field — defends f-string interpolation."""
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    with pytest.raises(ValueError):
        increment_counters_on_cited_directives(
            cycle_id="x",
            matter_slug="y",
            cited_ids=["foo-001"],
            counter_field="DROP TABLE cortex_directives",
        )


def test_repeated_increment_accumulates(live_db):
    """Two sequential calls -> +2 total. Sanity that UPDATE is additive,
    not idempotent at this layer (idempotency lives at reflect_cycle level
    via cortex_phase_outputs marker)."""
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    suffix = uuid.uuid4().hex[:8]
    matter = f"accum-{suffix}"
    d = f"{matter}-001"
    _seed_directive(live_db, d, matter)

    for _ in range(2):
        increment_counters_on_cited_directives(
            cycle_id=str(uuid.uuid4()),
            matter_slug=matter,
            cited_ids=[d],
            counter_field="harmful_count",
        )
    assert _read_counters(live_db, d)["harmful"] == 2


def test_deprecated_directive_skipped(live_db):
    """status='deprecated' directives are not eligible for increment.

    WHERE status='active' filter means a cycle citing a deprecated id
    returns it as unknown — Director's deprecation decision sticks even
    if the model has a stale playbook in context.
    """
    from orchestrator.cortex_phase6_reflector import (
        increment_counters_on_cited_directives,
    )

    suffix = uuid.uuid4().hex[:8]
    matter = f"deprecated-{suffix}"
    d = f"{matter}-001"
    _seed_directive(live_db, d, matter, status="deprecated")

    rows, unknown = increment_counters_on_cited_directives(
        cycle_id=str(uuid.uuid4()),
        matter_slug=matter,
        cited_ids=[d],
        counter_field="helpful_count",
    )
    assert rows == 0
    assert unknown == [d]
