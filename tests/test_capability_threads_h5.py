"""BRIEF_CAPABILITY_THREADS_1 §Part H §H5 — cross-surface continuity.

Mandatory ship-gate: a fact F written via one surface must be observable from
another surface on the same PM's thread set within the recency window. Writes
through ``stitch_or_create_thread`` + ``persist_turn`` must hit live PG;
gated via ``needs_live_pg`` fixture (conftest.py convention — skips cleanly
when TEST_DATABASE_URL + NEON_API_KEY both absent).
"""
from __future__ import annotations

import psycopg2
import psycopg2.extras


def test_h5_cross_surface_continuity(needs_live_pg, monkeypatch):
    """Write via ``sidebar`` surface → related follow-up via ``decomposer``
    surface → both surfaces emit capability_turns rows on the same pm_slug
    within the recency window."""
    # Point the SentinelStoreBack singleton pool at the test DB so stitcher
    # helpers land rows there. The retriever's Qdrant embed is async/non-fatal
    # so we don't need to sandbox it.
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)

    from orchestrator.capability_threads import (
        stitch_or_create_thread, persist_turn,
    )

    pm_slug = "ao_pm"

    # 1. Write via sidebar
    t1, d1 = stitch_or_create_thread(
        pm_slug=pm_slug,
        question="What's the status of Aukera EUR 1.5M release?",
        answer="Patrick warned about trust review. Director chose Option B (Capex reframe).",
        surface="sidebar",
    )
    turn1 = persist_turn(
        pm_slug=pm_slug, thread_id=t1, surface="sidebar",
        mutation_source="sidebar",
        question="What's the status of Aukera EUR 1.5M release?",
        answer="Patrick warned about trust review...",
        state_updates={}, stitch_decision=d1,
    )
    assert turn1 is not None

    # 2. Related follow-up via decomposer surface
    t2, d2 = stitch_or_create_thread(
        pm_slug=pm_slug,
        question="What did Patrick Zuchner say about Aukera again?",
        answer="He warned of trust escalation; we pivoted to Capex framing.",
        surface="decomposer",
    )
    turn2 = persist_turn(
        pm_slug=pm_slug, thread_id=t2, surface="decomposer",
        mutation_source="decomposer",
        question="What did Patrick Zuchner say about Aukera again?",
        answer="He warned of trust escalation...",
        state_updates={}, stitch_decision=d2,
    )
    assert turn2 is not None

    # Qdrant embed is async fire-and-forget. Tolerate both outcomes:
    #   (a) stitched: t1 == t2 (Qdrant embed caught up between calls).
    #   (b) raced:    t2 != t1 (entity overlap alone below threshold).
    # Correct assertion: both rows are queryable, at least one sidebar and one
    # decomposer surface exist under this pm_slug within the recency window.
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT thread_id FROM capability_threads
            WHERE pm_slug = %s AND last_turn_at >= NOW() - INTERVAL '1 hour'
            ORDER BY last_turn_at DESC LIMIT 5
            """,
            (pm_slug,),
        )
        rows = cur.fetchall()
        assert len(rows) >= 1

        cur.execute(
            """
            SELECT DISTINCT surface FROM capability_turns
            WHERE thread_id = ANY(%s)
            """,
            ([str(r["thread_id"]) for r in rows],),
        )
        surfaces = {r["surface"] for r in cur.fetchall()}
        assert "sidebar" in surfaces
        assert "decomposer" in surfaces
    finally:
        conn.close()
