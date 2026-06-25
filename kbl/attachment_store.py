"""Email attachment store — EMAIL_ATTACHMENT_STORE_1 (EMAIL_HISTORY_BACKFILL lane 1).

Shared persistence layer for the bluewin (b1 IMAP) + brisengroup (b2 Graph)
historical backfills and the deputy-codex forward-parity writer. Schema lives
in migrations/20260610_email_attachments.sql (locked by lead 2026-06-10).

Shape rules (from the brief, exact):
- sha256 computed here, never passed in.
- Payloads > 5MB are stored metadata_only: row persists (filename/mime/size/
  sha256) but ``data`` is NULL and ``storage='metadata_only'``.
- Dedup on (message_id, content_sha256): ON CONFLICT DO NOTHING, then the
  existing row's id is returned — callers can treat insert as idempotent.
- Plain functions on kbl.db.get_conn (short-lived connection, no singletons).
- All DB calls try/except → None/False on failure, never raise to the caller.
"""

from __future__ import annotations

import hashlib
import logging

from kbl.db import get_conn

logger = logging.getLogger(__name__)

# Payloads strictly larger than this are persisted metadata-only (data=NULL).
MAX_INLINE_BYTES = 5 * 1024 * 1024  # 5MB


def insert_attachment(
    message_id: str,
    source: str,
    filename: str | None,
    mime_type: str | None,
    payload_bytes: bytes,
):
    """Persist one attachment; return its row id (int) or None on failure.

    Idempotent: re-inserting the same (message_id, payload) returns the
    existing row's id. Payloads > MAX_INLINE_BYTES store metadata only.
    """
    if not message_id or not source or payload_bytes is None:
        logger.warning("insert_attachment: missing message_id/source/payload")
        return None
    sha256 = hashlib.sha256(payload_bytes).hexdigest()
    size_bytes = len(payload_bytes)
    metadata_only = size_bytes > MAX_INLINE_BYTES
    storage = "metadata_only" if metadata_only else "db"
    data = None if metadata_only else payload_bytes
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_attachments
                        (message_id, source, filename, mime_type, size_bytes,
                         content_sha256, storage, data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (message_id, content_sha256) DO NOTHING
                    RETURNING id
                    """,
                    (message_id, source, filename, mime_type, size_bytes,
                     sha256, storage, data),
                )
                row = cur.fetchone()
                if row is not None:
                    conn.commit()
                    return row[0]
                # Conflict path — fetch the existing row's id.
                cur.execute(
                    """
                    SELECT id FROM email_attachments
                     WHERE message_id = %s AND content_sha256 = %s
                     LIMIT 1
                    """,
                    (message_id, sha256),
                )
                existing = cur.fetchone()
                conn.commit()
                return existing[0] if existing else None
    except Exception as e:
        logger.error("insert_attachment failed for %s: %s", message_id, e)
        return None


def insert_attachment_meta(
    message_id: str,
    source: str,
    filename: str | None,
    mime_type: str | None,
    size_bytes: int | None,
    meta_key: str,
):
    """Persist a metadata-only attachment row (no payload available/stored).

    For consumers that know an attachment exists but don't fetch bytes
    (e.g. b2's Graph lane skipping oversize/remote payloads). ``meta_key``
    is the provider's attachment id; dedup key is
    sha256("meta:" + meta_key) so re-inserts on the same provider id hit
    the same (message_id, content_sha256) ON CONFLICT path as payload
    inserts. Returns the row id (int) or None on failure.
    """
    if not message_id or not source or not meta_key:
        logger.warning("insert_attachment_meta: missing message_id/source/meta_key")
        return None
    sha256 = hashlib.sha256(("meta:" + meta_key).encode("utf-8")).hexdigest()
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_attachments
                        (message_id, source, filename, mime_type, size_bytes,
                         content_sha256, storage, data)
                    VALUES (%s, %s, %s, %s, %s, %s, 'metadata_only', NULL)
                    ON CONFLICT (message_id, content_sha256) DO NOTHING
                    RETURNING id
                    """,
                    (message_id, source, filename, mime_type, size_bytes, sha256),
                )
                row = cur.fetchone()
                if row is not None:
                    conn.commit()
                    return row[0]
                # Conflict path — fetch the existing row's id.
                cur.execute(
                    """
                    SELECT id FROM email_attachments
                     WHERE message_id = %s AND content_sha256 = %s
                     LIMIT 1
                    """,
                    (message_id, sha256),
                )
                existing = cur.fetchone()
                conn.commit()
                return existing[0] if existing else None
    except Exception as e:
        logger.error("insert_attachment_meta failed for %s: %s", message_id, e)
        return None


def get_attachment(att_id: int):
    """Return the attachment row as a dict, or None if missing / on failure.

    Keys: id, message_id, source, filename, mime_type, size_bytes,
    content_sha256, storage, data (bytes or None), created_at.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, message_id, source, filename, mime_type,
                           size_bytes, content_sha256, storage, data, created_at
                      FROM email_attachments
                     WHERE id = %s
                     LIMIT 1
                    """,
                    (att_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                data = bytes(row[8]) if row[8] is not None else None
                return {
                    "id": row[0],
                    "message_id": row[1],
                    "source": row[2],
                    "filename": row[3],
                    "mime_type": row[4],
                    "size_bytes": row[5],
                    "content_sha256": row[6],
                    "storage": row[7],
                    "data": data,
                    "created_at": row[9],
                }
    except Exception as e:
        logger.error("get_attachment failed for id=%s: %s", att_id, e)
        return None


def attachment_exists(message_id: str, sha256: str) -> bool:
    """True if a row exists for (message_id, sha256); False otherwise/on failure."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM email_attachments
                     WHERE message_id = %s AND content_sha256 = %s
                     LIMIT 1
                    """,
                    (message_id, sha256),
                )
                return cur.fetchone() is not None
    except Exception as e:
        logger.error("attachment_exists failed for %s: %s", message_id, e)
        return False


def list_attachments(message_id: str, source: str | None = None):
    """List attachment METADATA rows for a message_id (no payload bytes).

    Read surface for BAKER_M365_ATTACHMENT_READ_SURFACE_1: the store is the only
    place M365/Graph attachment bytes are durably held, but nothing enumerated
    them. Returns a list of dicts ordered by id (stable, deterministic for
    1-based indexing), or [] when none / on failure. Optional ``source`` filter
    ('graph' | 'bluewin' | 'email' | 'exchange'). Payload bytes are intentionally
    NOT selected here — fetch a specific row's bytes via ``get_attachment(id)``.
    """
    if not message_id:
        return []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if source:
                    cur.execute(
                        """
                        SELECT id, message_id, source, filename, mime_type,
                               size_bytes, content_sha256, storage
                          FROM email_attachments
                         WHERE message_id = %s AND source = %s
                         ORDER BY id
                        """,
                        (message_id, source),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, message_id, source, filename, mime_type,
                               size_bytes, content_sha256, storage
                          FROM email_attachments
                         WHERE message_id = %s
                         ORDER BY id
                        """,
                        (message_id,),
                    )
                rows = cur.fetchall()
                return [
                    {
                        "id": r[0],
                        "message_id": r[1],
                        "source": r[2],
                        "filename": r[3],
                        "mime_type": r[4],
                        "size_bytes": r[5],
                        "content_sha256": r[6],
                        "storage": r[7],
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error("list_attachments failed for %s: %s", message_id, e)
        return []
