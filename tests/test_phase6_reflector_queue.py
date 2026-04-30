"""prompt_review_queue insert tests for orchestrator.cortex_phase6_reflector.

Brief: CORTEX_PHASE6_REFLECTOR_1 §5.3.

Live-PG via ``needs_live_pg``. Auto-skips without TEST_DATABASE_URL.
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
    import psycopg2
    from config.migration_runner import run_pending_migrations

    run_pending_migrations(needs_live_pg, migrations_dir=REPO_MIGRATIONS_DIR)
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


def _create_cycle(conn, matter_slug: str = "queue-test") -> str:
    """prompt_review_queue.cycle_id is FK to cortex_cycles — seed a real cycle."""
    cycle_id = str(uuid.uuid4())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by,
            current_phase, status)
        VALUES (%s, %s, 'test', 'archive', 'proposed')
        """,
        (cycle_id, matter_slug),
    )
    conn.commit()
    cur.close()
    return cycle_id


def test_log_no_citation(live_db):
    from orchestrator.cortex_phase6_reflector import log_untraceable_proposal

    cycle_id = _create_cycle(live_db)
    queue_id = log_untraceable_proposal(
        cycle_id=cycle_id,
        matter_slug="queue-test",
        proposal_text="proposal without any [directive: ...] block",
        flagged_reason="no_citation",
    )
    assert queue_id > 0

    cur = live_db.cursor()
    cur.execute(
        """SELECT cycle_id, flagged_reason, reviewed
              FROM prompt_review_queue WHERE queue_id = %s""",
        (queue_id,),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    assert str(row[0]) == cycle_id
    assert row[1] == "no_citation"
    assert row[2] is False  # default reviewed=false


def test_log_unknown_directive_id(live_db):
    from orchestrator.cortex_phase6_reflector import log_untraceable_proposal

    cycle_id = _create_cycle(live_db)
    queue_id = log_untraceable_proposal(
        cycle_id=cycle_id,
        matter_slug="queue-test",
        proposal_text="proposal [directive: nonexistent-001]",
        flagged_reason="unknown_directive_id",
    )
    cur = live_db.cursor()
    cur.execute(
        "SELECT flagged_reason FROM prompt_review_queue WHERE queue_id = %s",
        (queue_id,),
    )
    assert cur.fetchone()[0] == "unknown_directive_id"
    cur.close()


def test_invalid_flagged_reason_raises():
    """Reject unknown reason BEFORE hitting DB CHECK constraint — fails fast."""
    from orchestrator.cortex_phase6_reflector import log_untraceable_proposal

    with pytest.raises(ValueError):
        log_untraceable_proposal(
            cycle_id=str(uuid.uuid4()),
            matter_slug="x",
            proposal_text="x",
            flagged_reason="not_a_real_reason",
        )


def test_unreviewed_partial_index_finds_inserted_rows(live_db):
    """Insert 3 rows; idx_prompt_review_queue_unreviewed (reviewed=FALSE)
    should return all 3."""
    from orchestrator.cortex_phase6_reflector import log_untraceable_proposal

    suffix = uuid.uuid4().hex[:8]
    cycle_id = _create_cycle(live_db, matter_slug=f"qidx-{suffix}")
    for reason in ("no_citation", "malformed_citation", "unknown_directive_id"):
        log_untraceable_proposal(
            cycle_id=cycle_id,
            matter_slug=f"qidx-{suffix}",
            proposal_text=f"proposal {reason}",
            flagged_reason=reason,
        )

    cur = live_db.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM prompt_review_queue
              WHERE matter_slug = %s AND reviewed = FALSE""",
        (f"qidx-{suffix}",),
    )
    count = cur.fetchone()[0]
    cur.close()
    assert count == 3


def test_malformed_citation_reason_accepted(live_db):
    """Round-trip the third valid reason value."""
    from orchestrator.cortex_phase6_reflector import log_untraceable_proposal

    cycle_id = _create_cycle(live_db)
    queue_id = log_untraceable_proposal(
        cycle_id=cycle_id,
        matter_slug="queue-test",
        proposal_text="[directive: NotKebab]",
        flagged_reason="malformed_citation",
    )
    cur = live_db.cursor()
    cur.execute(
        "SELECT flagged_reason FROM prompt_review_queue WHERE queue_id = %s",
        (queue_id,),
    )
    assert cur.fetchone()[0] == "malformed_citation"
    cur.close()
