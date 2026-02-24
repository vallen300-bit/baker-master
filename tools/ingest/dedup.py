"""Baker AI — Duplicate detection.

Uses SHA-256 file hash + filename checked against PostgreSQL ingestion_log table.
"""
import hashlib
import logging
from pathlib import Path
from typing import Optional

import psycopg2

from config.settings import config

logger = logging.getLogger("baker.ingest.dedup")


def compute_file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_duplicate(filename: str, file_hash: str) -> bool:
    """Check if a file with same name+hash already exists in ingestion_log.

    Args:
        filename: Original filename.
        file_hash: SHA-256 hex digest.

    Returns:
        True if duplicate found, False otherwise.
    """
    conn = None
    try:
        conn = psycopg2.connect(**config.postgres.dsn_params)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM ingestion_log WHERE filename = %s AND file_hash = %s LIMIT 1",
                (filename, file_hash),
            )
            found = cur.fetchone() is not None
        if found:
            logger.info("Duplicate detected: %s (hash: %s...)", filename, file_hash[:12])
        return found
    except psycopg2.errors.UndefinedTable:
        logger.warning("ingestion_log table does not exist — skipping dedup check")
        return False
    except Exception as e:
        logger.warning("Dedup check failed (proceeding anyway): %s", e)
        return False
    finally:
        if conn:
            conn.close()


def log_ingestion(
    filename: str,
    file_hash: str,
    file_size_bytes: int,
    collection: str,
    chunk_count: int,
    point_ids: list[str],
    source_path: Optional[str] = None,
    project: Optional[str] = None,
    role: Optional[str] = None,
) -> None:
    """Record a completed ingestion in PostgreSQL.

    Args:
        filename: Original filename.
        file_hash: SHA-256 hex digest.
        file_size_bytes: File size in bytes.
        collection: Target Qdrant collection.
        chunk_count: Number of chunks created.
        point_ids: List of Qdrant point UUIDs.
        source_path: Full source path (optional).
        project: Project tag (optional).
        role: Role tag (optional).
    """
    conn = None
    try:
        conn = psycopg2.connect(**config.postgres.dsn_params)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingestion_log
                   (filename, file_hash, file_size_bytes, collection,
                    project, role, chunk_count, point_ids, source_path)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (filename, file_hash) DO UPDATE SET
                       chunk_count = EXCLUDED.chunk_count,
                       point_ids = EXCLUDED.point_ids,
                       project = EXCLUDED.project,
                       role = EXCLUDED.role,
                       ingested_at = NOW()
                """,
                (filename, file_hash, file_size_bytes, collection,
                 project, role, chunk_count, point_ids, source_path),
            )
        conn.commit()
        logger.info("Logged ingestion: %s → %s (%d chunks)", filename, collection, chunk_count)
    except psycopg2.errors.UndefinedTable:
        logger.warning("ingestion_log table does not exist — skipping log write")
    except Exception as e:
        logger.warning("Failed to log ingestion: %s", e)
    finally:
        if conn:
            conn.close()
