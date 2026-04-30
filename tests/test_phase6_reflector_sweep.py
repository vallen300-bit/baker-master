"""Sweep + reflect_cycle tests for orchestrator.cortex_phase6_reflector.

Brief: CORTEX_PHASE6_REFLECTOR_1 §5.7.

Live-PG via ``needs_live_pg``. Auto-skips without TEST_DATABASE_URL.
Exercises:
  * sweep enumerates cycles aged past TTL (status=proposed, no director_action)
  * sweep skips cycles already marked reflector_complete
  * reflect_cycle increments helpful counter on Triaga-decided cycle
  * reflect_cycle is idempotent: second call sees existing marker, no-ops
"""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

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


def _create_cycle(
    conn,
    *,
    matter_slug: str,
    status: str = "proposed",
    director_action=None,
    started_at: datetime = None,
    proposal_text: str = "",
) -> str:
    """Seed a cortex_cycles row + optional proposal_card artifact."""
    cycle_id = str(uuid.uuid4())
    cur = conn.cursor()
    if started_at is None:
        cur.execute(
            """
            INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by,
                current_phase, status, director_action)
            VALUES (%s, %s, 'test', 'propose', %s, %s)
            """,
            (cycle_id, matter_slug, status, director_action),
        )
    else:
        cur.execute(
            """
            INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by,
                current_phase, status, director_action, started_at)
            VALUES (%s, %s, 'test', 'propose', %s, %s, %s)
            """,
            (cycle_id, matter_slug, status, director_action, started_at),
        )
    if proposal_text:
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs
                (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 7, 'proposal_card', %s::jsonb)
            """,
            (cycle_id, json.dumps({"proposal_text": proposal_text})),
        )
    conn.commit()
    cur.close()
    return cycle_id


def _seed_directive(conn, directive_id, matter_slug):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO cortex_directives (directive_id, matter_slug, body, status)
              VALUES (%s, %s, 'body', 'active')
              ON CONFLICT (directive_id) DO NOTHING""",
        (directive_id, matter_slug),
    )
    conn.commit()
    cur.close()


def _has_reflector_marker(conn, cycle_id) -> bool:
    cur = conn.cursor()
    cur.execute(
        """SELECT 1 FROM cortex_phase_outputs
              WHERE cycle_id = %s AND artifact_type = 'reflector_complete'""",
        (cycle_id,),
    )
    found = cur.fetchone() is not None
    cur.close()
    return found


def test_recent_cycle_no_action_skipped(live_db, tmp_path):
    """status=proposed, director_action=None, age=1d -> NOT picked up by sweep."""
    import asyncio
    from orchestrator.cortex_phase6_reflector import sweep_pending_cycles

    suffix = uuid.uuid4().hex[:8]
    matter = f"sweep-recent-{suffix}"
    cycle_id = _create_cycle(
        live_db,
        matter_slug=matter,
        status="proposed",
        director_action=None,
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    counts = asyncio.run(sweep_pending_cycles(staging_root=tmp_path))
    # cycle should NOT be in the checked set (recent + no action).
    assert not _has_reflector_marker(live_db, cycle_id)


def test_aged_cycle_no_action_classified_stale(live_db, tmp_path):
    """status=proposed, age >= 14d, no director_action -> sweep classifies stale."""
    import asyncio
    from orchestrator.cortex_phase6_reflector import sweep_pending_cycles

    suffix = uuid.uuid4().hex[:8]
    matter = f"sweep-stale-{suffix}"
    d_id = f"{matter}-001"
    _seed_directive(live_db, d_id, matter)
    cycle_id = _create_cycle(
        live_db,
        matter_slug=matter,
        status="proposed",
        director_action=None,
        started_at=datetime.now(timezone.utc) - timedelta(days=20),
        proposal_text=f"proposal [directive: {d_id}]",
    )

    counts = asyncio.run(sweep_pending_cycles(staging_root=tmp_path))
    assert counts["checked"] >= 1
    assert counts["stale"] >= 1
    # Marker present; stale_count incremented on the cited directive.
    assert _has_reflector_marker(live_db, cycle_id)
    cur = live_db.cursor()
    cur.execute(
        "SELECT stale_count FROM cortex_directives WHERE directive_id = %s",
        (d_id,),
    )
    assert cur.fetchone()[0] == 1
    cur.close()


def test_already_reflected_cycle_skipped(live_db, tmp_path):
    """Cycle with existing reflector_complete artifact is not re-processed."""
    import asyncio
    from orchestrator.cortex_phase6_reflector import sweep_pending_cycles

    suffix = uuid.uuid4().hex[:8]
    matter = f"sweep-already-{suffix}"
    d_id = f"{matter}-001"
    _seed_directive(live_db, d_id, matter)
    cycle_id = _create_cycle(
        live_db,
        matter_slug=matter,
        status="approved",
        director_action="gold_approved",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        proposal_text=f"[directive: {d_id}]",
    )

    # Pre-seed the reflector_complete marker (simulating prior sweep run).
    cur = live_db.cursor()
    cur.execute(
        """
        INSERT INTO cortex_phase_outputs
            (cycle_id, phase, phase_order, artifact_type, payload)
        VALUES (%s, 'archive', 6, 'reflector_complete', '{}'::jsonb)
        """,
        (cycle_id,),
    )
    live_db.commit()
    cur.close()

    counts = asyncio.run(sweep_pending_cycles(staging_root=tmp_path))
    # Sweep's enumeration WHERE excludes already-marked cycles.
    cur = live_db.cursor()
    cur.execute(
        "SELECT helpful_count FROM cortex_directives WHERE directive_id = %s",
        (d_id,),
    )
    # Counter should still be 0 — already-reflected cycle was not re-counted.
    assert cur.fetchone()[0] == 0
    cur.close()


def test_reflect_cycle_increments_helpful(live_db, tmp_path):
    """Direct reflect_cycle: gold_approved cycle -> helpful_count += 1."""
    from orchestrator.cortex_phase6_reflector import reflect_cycle

    suffix = uuid.uuid4().hex[:8]
    matter = f"refl-helpful-{suffix}"
    d_id = f"{matter}-001"
    _seed_directive(live_db, d_id, matter)
    cycle_id = _create_cycle(
        live_db,
        matter_slug=matter,
        status="approved",
        director_action="gold_approved",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        proposal_text=f"My proposal [directive: {d_id}]",
    )

    res = reflect_cycle(
        cycle_id=cycle_id,
        matter_slug=matter,
        director_action="gold_approved",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        staging_root=tmp_path,
    )
    assert res["outcome"] == "helpful"
    assert d_id in res["cited_ids"]
    assert res["already_reflected"] is False

    cur = live_db.cursor()
    cur.execute(
        "SELECT helpful_count FROM cortex_directives WHERE directive_id = %s",
        (d_id,),
    )
    assert cur.fetchone()[0] == 1
    cur.close()
    assert _has_reflector_marker(live_db, cycle_id)


def test_reflect_cycle_idempotent_via_marker(live_db, tmp_path):
    """Second reflect_cycle call on same cycle -> already_reflected=True,
    no second counter increment."""
    from orchestrator.cortex_phase6_reflector import reflect_cycle

    suffix = uuid.uuid4().hex[:8]
    matter = f"refl-idempotent-{suffix}"
    d_id = f"{matter}-001"
    _seed_directive(live_db, d_id, matter)
    cycle_id = _create_cycle(
        live_db,
        matter_slug=matter,
        status="rejected",
        director_action="gold_rejected",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        proposal_text=f"[directive: {d_id}]",
    )

    res1 = reflect_cycle(
        cycle_id=cycle_id,
        matter_slug=matter,
        director_action="gold_rejected",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        staging_root=tmp_path,
    )
    assert res1["outcome"] == "harmful"

    res2 = reflect_cycle(
        cycle_id=cycle_id,
        matter_slug=matter,
        director_action="gold_rejected",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        staging_root=tmp_path,
    )
    assert res2["already_reflected"] is True

    cur = live_db.cursor()
    cur.execute(
        "SELECT harmful_count FROM cortex_directives WHERE directive_id = %s",
        (d_id,),
    )
    # Only one increment despite two calls.
    assert cur.fetchone()[0] == 1
    cur.close()


def test_no_citation_logs_to_prompt_review_queue(live_db, tmp_path):
    """gold_approved cycle with proposal lacking citation -> queue row."""
    from orchestrator.cortex_phase6_reflector import reflect_cycle

    suffix = uuid.uuid4().hex[:8]
    matter = f"refl-uncited-{suffix}"
    cycle_id = _create_cycle(
        live_db,
        matter_slug=matter,
        status="approved",
        director_action="gold_approved",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        proposal_text="proposal text with no directive citation at all",
    )

    res = reflect_cycle(
        cycle_id=cycle_id,
        matter_slug=matter,
        director_action="gold_approved",
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
        staging_root=tmp_path,
    )
    assert res["outcome"] == "helpful"
    assert res["cited_ids"] == []
    assert res["queue_id"] is not None

    cur = live_db.cursor()
    cur.execute(
        "SELECT flagged_reason FROM prompt_review_queue WHERE queue_id = %s",
        (res["queue_id"],),
    )
    assert cur.fetchone()[0] == "no_citation"
    cur.close()
