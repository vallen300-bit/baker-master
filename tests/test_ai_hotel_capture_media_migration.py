from __future__ import annotations

from pathlib import Path


def test_ai_hotel_capture_media_migration_shape():
    mig = Path("migrations/20260619d_ai_hotel_capture_media.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS ai_hotel_capture_media" in mig
    assert "capture_id       BIGINT NOT NULL REFERENCES ai_hotel_captures(id) ON DELETE CASCADE" in mig
    assert "media_type       TEXT NOT NULL" in mig
    assert "storage_key      TEXT NOT NULL" in mig
    assert "thumbnail_key    TEXT" in mig
    assert "content_type     TEXT NOT NULL" in mig
    assert "size_bytes       BIGINT NOT NULL" in mig
    assert "duration_seconds REAL" in mig
    assert "media_type IN ('video', 'image', 'audio')" in mig
    assert "CHECK (size_bytes >= 0)" in mig
    assert "conrelid = 'public.ai_hotel_capture_media'::regclass" in mig
    up = mig.split("-- == migrate:down ==")[0]
    assert "DROP TABLE" not in up


def test_ai_hotel_capture_media_migration_idempotent_live(needs_live_pg):
    import psycopg2

    from config.migration_runner import run_pending_migrations

    repo_mig_dir = str(Path(__file__).resolve().parents[1] / "migrations")
    run_pending_migrations(needs_live_pg, migrations_dir=repo_mig_dir)
    assert run_pending_migrations(needs_live_pg, migrations_dir=repo_mig_dir) == []

    with psycopg2.connect(needs_live_pg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_name = 'ai_hotel_capture_media'
                """
            )
            cols = {r[0] for r in cur.fetchall()}
            assert {
                "id",
                "capture_id",
                "media_type",
                "storage_key",
                "thumbnail_key",
                "content_type",
                "size_bytes",
                "duration_seconds",
                "created_at",
            } <= cols

            cur.execute(
                """
                SELECT conname
                  FROM pg_constraint
                 WHERE conrelid = 'public.ai_hotel_capture_media'::regclass
                """
            )
            constraints = {r[0] for r in cur.fetchall()}
            assert "ai_hotel_capture_media_media_type_check" in constraints
            assert "ai_hotel_capture_media_size_bytes_nonneg" in constraints
