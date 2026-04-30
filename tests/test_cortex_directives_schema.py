"""Schema tests for migrations/20260430_cortex_directives.sql.

Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.

Live-PG round-trip via ``needs_live_pg`` fixture (auto-skips without
``TEST_DATABASE_URL`` / Neon credentials per ``tests/conftest.py``).
Each test applies the repo migrations dir (idempotent — ``IF NOT EXISTS``
guards every CREATE) before asserting on the schema, so the tests work
against an ephemeral Neon branch or a manually-pointed live DB.
"""
from __future__ import annotations

import pathlib
import uuid

import pytest


REPO_MIGRATIONS_DIR = str(
    pathlib.Path(__file__).resolve().parents[1] / "migrations"
)


@pytest.fixture
def live_db(needs_live_pg):
    """Apply repo migrations + yield a psycopg2 connection.

    Returns the connection object. Caller closes via ``conn.close()`` in
    teardown — pytest ``yield`` handles it via the wrapper here.
    """
    import psycopg2

    from config.migration_runner import run_pending_migrations

    run_pending_migrations(needs_live_pg, migrations_dir=REPO_MIGRATIONS_DIR)

    conn = psycopg2.connect(needs_live_pg)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


def test_cortex_directives_table_exists(live_db):
    cur = live_db.cursor()
    cur.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'cortex_directives'
        ORDER BY ordinal_position
        """
    )
    cols = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    assert cols, "cortex_directives table has no columns / does not exist"
    assert cols["directive_id"][0] == "text"
    assert cols["matter_slug"][0] == "text"
    assert cols["body"][0] == "text"
    # source_cycle is uuid (FK to cortex_cycles)
    assert cols["source_cycle"][0] == "uuid"
    assert cols["status"][0] == "text"
    assert cols["helpful_count"][0] == "integer"
    assert cols["harmful_count"][0] == "integer"
    assert cols["stale_count"][0] == "integer"
    assert cols["pending_count"][0] == "integer"
    assert cols["created_at"][0] == "timestamp with time zone"
    assert cols["updated_at"][0] == "timestamp with time zone"


def test_cortex_directives_indexes_exist(live_db):
    cur = live_db.cursor()
    cur.execute(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'cortex_directives'
        """
    )
    names = {row[0] for row in cur.fetchall()}
    assert "idx_cortex_directives_matter_status" in names
    assert "idx_cortex_directives_scored" in names


def test_directive_insert_and_counter_increment(live_db):
    """Insert a matter-scoped directive, increment helpful_count, round-trip."""
    cur = live_db.cursor()
    suffix = uuid.uuid4().hex[:8]
    directive_id = f"test-matter-{suffix}-001"
    cur.execute(
        """
        INSERT INTO cortex_directives
            (directive_id, matter_slug, body, status)
        VALUES (%s, %s, %s, 'active')
        """,
        (directive_id, f"test-matter-{suffix}", "Sample directive body"),
    )
    cur.execute(
        "UPDATE cortex_directives SET helpful_count = helpful_count + 1 "
        "WHERE directive_id = %s",
        (directive_id,),
    )
    cur.execute(
        "SELECT helpful_count, harmful_count, stale_count, pending_count, status "
        "FROM cortex_directives WHERE directive_id = %s",
        (directive_id,),
    )
    row = cur.fetchone()
    live_db.commit()
    assert row is not None
    helpful, harmful, stale, pending, status = row
    assert helpful == 1
    assert harmful == 0
    assert stale == 0
    assert pending == 0
    assert status == "active"

    # Cleanup
    cur.execute(
        "DELETE FROM cortex_directives WHERE directive_id = %s",
        (directive_id,),
    )
    live_db.commit()


def test_directive_status_check_constraint_rejects_invalid(live_db):
    """status CHECK should reject values outside {active,deprecated,draft}."""
    import psycopg2

    cur = live_db.cursor()
    suffix = uuid.uuid4().hex[:8]
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            """
            INSERT INTO cortex_directives
                (directive_id, matter_slug, body, status)
            VALUES (%s, %s, %s, 'foo')
            """,
            (f"test-bad-{suffix}-001", f"test-bad-{suffix}", "x"),
        )
    live_db.rollback()


def test_directive_global_id_passthrough(live_db):
    """Cross-matter '_global-NNN' directives use matter_slug='_global'."""
    cur = live_db.cursor()
    suffix = uuid.uuid4().hex[:8]
    directive_id = f"_global-test-{suffix}-001"
    cur.execute(
        """
        INSERT INTO cortex_directives
            (directive_id, matter_slug, body)
        VALUES (%s, '_global', %s)
        """,
        (directive_id, "Generic cross-matter directive"),
    )
    cur.execute(
        "SELECT matter_slug FROM cortex_directives WHERE directive_id = %s",
        (directive_id,),
    )
    row = cur.fetchone()
    live_db.commit()
    assert row is not None
    assert row[0] == "_global"

    cur.execute(
        "DELETE FROM cortex_directives WHERE directive_id = %s",
        (directive_id,),
    )
    live_db.commit()


def test_prompt_review_queue_exists(live_db):
    cur = live_db.cursor()
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'prompt_review_queue'
        ORDER BY ordinal_position
        """
    )
    cols = {row[0]: row[1] for row in cur.fetchall()}
    assert cols, "prompt_review_queue table missing"
    assert cols["queue_id"] == "bigint"
    assert cols["cycle_id"] == "uuid"
    assert cols["matter_slug"] == "text"
    assert cols["proposal_text"] == "text"
    assert cols["flagged_reason"] == "text"
    assert cols["reviewed"] == "boolean"


def test_prompt_review_queue_flagged_reason_check(live_db):
    """flagged_reason must be one of the three enumerated values."""
    import psycopg2

    cur = live_db.cursor()
    # Need a real cycle_id for the FK; create a throwaway cycle row.
    cycle_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by)
        VALUES (%s, %s, 'director')
        """,
        (cycle_id, "test-slug-prompt-queue"),
    )
    live_db.commit()

    try:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO prompt_review_queue
                    (cycle_id, matter_slug, proposal_text, flagged_reason)
                VALUES (%s, 'test-slug-prompt-queue', 'x', 'bogus_reason')
                """,
                (cycle_id,),
            )
        live_db.rollback()

        # Happy path: known reason inserts.
        cur.execute(
            """
            INSERT INTO prompt_review_queue
                (cycle_id, matter_slug, proposal_text, flagged_reason)
            VALUES (%s, 'test-slug-prompt-queue', 'proposal text', 'no_citation')
            RETURNING queue_id
            """,
            (cycle_id,),
        )
        qid = cur.fetchone()[0]
        live_db.commit()

        cur.execute(
            "DELETE FROM prompt_review_queue WHERE queue_id = %s",
            (qid,),
        )
        live_db.commit()
    finally:
        cur.execute(
            "DELETE FROM cortex_cycles WHERE cycle_id = %s",
            (cycle_id,),
        )
        live_db.commit()


def test_reflector_complete_partial_unique_index(live_db):
    """Partial unique idx ensures one reflector_complete row per cycle.

    Brief 3 (Reflector) sweep depends on this for ON CONFLICT DO NOTHING
    when two sweep firings collide on the same cycle.
    """
    import psycopg2

    cur = live_db.cursor()
    cur.execute(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'cortex_phase_outputs'
          AND indexname = 'idx_cortex_phase_outputs_reflector_complete'
        """
    )
    assert cur.fetchone() is not None, (
        "partial unique index for reflector_complete is missing"
    )

    cycle_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by)
        VALUES (%s, %s, 'director')
        """,
        (cycle_id, "test-slug-reflector"),
    )
    live_db.commit()

    try:
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs
                (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'archive', 6, 'reflector_complete', '{}'::jsonb)
            """,
            (cycle_id,),
        )
        live_db.commit()
        # Second insert on same cycle_id with same artifact_type must fail
        # the partial unique index.
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                """
                INSERT INTO cortex_phase_outputs
                    (cycle_id, phase, phase_order, artifact_type, payload)
                VALUES (%s, 'archive', 6, 'reflector_complete', '{}'::jsonb)
                """,
                (cycle_id,),
            )
        live_db.rollback()
    finally:
        # ON DELETE CASCADE on cortex_phase_outputs cleans children.
        cur.execute(
            "DELETE FROM cortex_cycles WHERE cycle_id = %s",
            (cycle_id,),
        )
        live_db.commit()
