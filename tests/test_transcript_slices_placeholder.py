"""TRANSCRIPT_CURATION_PHASE_1 — verify placeholder slice row creation.

Tests live under TEST_DATABASE_URL (CI auto-provisions ephemeral Neon branch)
or auto-skip locally if TEST_DATABASE_URL unset.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set; live-PG tests auto-skip",
)


def _get_store():
    # _get_global_instance is a classmethod on SentinelStoreBack — call on the class, not module-level.
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def test_transcript_slices_table_exists():
    """Bootstrap creates table with all E1 columns."""
    store = _get_store()
    store._ensure_transcript_slices_table()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'transcript_slices'
        """)
        cols = {row[0] for row in cur.fetchall()}
        expected = {
            "id", "transcript_id", "boundary_start", "boundary_end", "slice_text",
            "chunk_header", "primary_desk", "cross_ref_desks", "visibility",
            "confidence_boundary", "confidence_classifier", "statement_type",
            "temporal_type", "valid_at", "invalidated_by", "privilege_scope",
            "routing_provenance", "status", "target_folder",
            "cross_ref_stub_targets", "created_at", "updated_at",
        }
        missing = expected - cols
        assert not missing, f"Missing columns: {missing}"
        cur.close()
    finally:
        store._put_conn(conn)


def test_placeholder_inserted_on_transcript_store():
    """store_meeting_transcript triggers placeholder write."""
    store = _get_store()
    store._ensure_meeting_transcripts_table()
    store._ensure_transcript_slices_table()
    tid = "test_phase1_placeholder_001"
    ok = store.store_meeting_transcript(
        transcript_id=tid,
        title="Phase 1 placeholder test",
        full_transcript="alpha beta gamma " * 20,
        source="test",
    )
    assert ok is True
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, transcript_id, boundary_start, boundary_end, status
            FROM transcript_slices
            WHERE transcript_id = %s LIMIT 1
        """, (tid,))
        row = cur.fetchone()
        assert row is not None, "placeholder row missing"
        assert row[0] == f"{tid}:placeholder"
        assert row[2] == 0
        assert row[3] > 0
        assert row[4] == "pending_classification"
        cur.close()
    finally:
        store._put_conn(conn)
        # cleanup
        conn2 = store._get_conn()
        try:
            cur = conn2.cursor()
            cur.execute("DELETE FROM meeting_transcripts WHERE id = %s", (tid,))
            conn2.commit()
            cur.close()
        finally:
            store._put_conn(conn2)


def test_placeholder_idempotent_on_reingest():
    """Re-ingesting same transcript_id does not create duplicate placeholder."""
    store = _get_store()
    store._ensure_meeting_transcripts_table()
    store._ensure_transcript_slices_table()
    tid = "test_phase1_placeholder_idempotent_001"
    for _ in range(3):
        store.store_meeting_transcript(
            transcript_id=tid,
            title="idempotent",
            full_transcript="text",
            source="test",
        )
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transcript_slices WHERE transcript_id = %s", (tid,))
        count = cur.fetchone()[0]
        assert count == 1, f"expected 1 placeholder, got {count}"
        cur.close()
    finally:
        store._put_conn(conn)
        conn2 = store._get_conn()
        try:
            cur = conn2.cursor()
            cur.execute("DELETE FROM meeting_transcripts WHERE id = %s", (tid,))
            conn2.commit()
            cur.close()
        finally:
            store._put_conn(conn2)


def test_placeholder_failure_does_not_break_transcript_write():
    """If placeholder insert fails, transcript still commits."""
    store = _get_store()
    store._ensure_meeting_transcripts_table()
    # Don't create transcript_slices table — placeholder insert will fail; transcript should still land.
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS transcript_slices CASCADE")
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)
    tid = "test_phase1_placeholder_resilient_001"
    ok = store.store_meeting_transcript(
        transcript_id=tid,
        title="resilient",
        full_transcript="text",
        source="test",
    )
    assert ok is True, "transcript write must succeed even when placeholder fails"
    # restore for downstream tests
    store._ensure_transcript_slices_table()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM meeting_transcripts WHERE id = %s", (tid,))
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)
