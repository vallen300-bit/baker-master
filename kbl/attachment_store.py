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
import re

from kbl.db import get_conn

logger = logging.getLogger(__name__)

# Payloads <= this go inline in Neon (data BYTEA). Strictly larger payloads go to
# R2 object storage (storage='r2', object_key set, data NULL) — Neon never holds
# >5MiB blobs. (BAKER_M365_LARGE_ATTACHMENT_FETCH_1 / deputy-codex F1 #4421.)
MAX_INLINE_BYTES = 5 * 1024 * 1024  # 5MB


def _r2_object_key(source: str | None, content_sha256: str) -> str:
    """Deterministic content-addressed R2 key (idempotency F3).

    ``email-attachments/<source>/<sha256>`` — sha256 is hex (URL-safe, passes
    object_storage._validate_key) and content-addressed, so the SAME bytes always
    map to the SAME object regardless of how many messages carry the attachment
    (natural dedup; re-runs overwrite the identical object, never duplicate it).
    """
    src = re.sub(r"[^a-z0-9]+", "", (source or "").lower()) or "graph"
    return f"email-attachments/{src}/{content_sha256}"


def _route_storage(source: str | None, payload_bytes: bytes, content_type: str | None) -> dict:
    """Decide where an attachment's bytes live and (for R2) upload them.

    Returns a dict with ``storage`` ('db' | 'r2' | 'metadata_only'), ``data``
    (bytes for inline, else None), ``object_key`` (R2 key or None), ``sha256``,
    ``size_bytes``. Fault-tolerant: if R2 is disabled/fails for a >5MiB payload,
    falls back to 'metadata_only' (data NULL) and LOGS loudly — never raises, and
    never silently inlines a >5MiB blob into Neon.
    """
    sha256 = hashlib.sha256(payload_bytes).hexdigest()
    size_bytes = len(payload_bytes)
    if size_bytes <= MAX_INLINE_BYTES:
        return {"storage": "db", "data": payload_bytes, "object_key": None,
                "sha256": sha256, "size_bytes": size_bytes}
    # >5MiB -> R2 object storage (eager-store, Director-ratified #4415).
    key = _r2_object_key(source, sha256)
    ct = (content_type or "application/octet-stream").strip() or "application/octet-stream"
    try:
        from kbl.object_storage import put_object
        res = put_object(key, payload_bytes, ct)
    except Exception as e:  # import or unexpected failure — never raise to ingest
        res = {"ok": False, "error": type(e).__name__}
    if res.get("ok"):
        return {"storage": "r2", "data": None, "object_key": key,
                "sha256": sha256, "size_bytes": size_bytes}
    logger.error(
        "R2 store failed (%s) for %d-byte attachment — falling back to "
        "metadata_only (bytes NOT persisted, surfaced)",
        res.get("error"), size_bytes,
    )
    return {"storage": "metadata_only", "data": None, "object_key": None,
            "sha256": sha256, "size_bytes": size_bytes}


class AttachmentStoreUnavailable(Exception):
    """Raised by the READ surface (list_attachments) when the backing store is
    unreachable, so a genuine outage is never silently flattened to an empty
    result. Mirrors memory.retriever.SearchBackendUnavailable. The write helpers
    (insert_attachment/insert_attachment_meta/get_attachment/attachment_exists)
    keep their swallow-to-None/False contract — they run on the ingest path where
    a non-fatal skip is intended; only the read path must distinguish
    outage-empty from true-empty."""


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
    provider_attachment_id: str | None = None,
    real_message_id: str | None = None,
):
    """Persist a metadata-only attachment row (no payload available/stored).

    For consumers that know an attachment exists but don't fetch bytes
    (e.g. b2's Graph lane skipping oversize/remote payloads). ``meta_key``
    is the provider's attachment id; dedup key is
    sha256("meta:" + meta_key) so re-inserts on the same provider id hit
    the same (message_id, content_sha256) ON CONFLICT path as payload
    inserts. Returns the row id (int) or None on failure.

    ``provider_attachment_id`` + ``real_message_id`` (M365_LARGE_ATTACHMENT_FETCH_1
    G3 F1): persist the REAL addressable AAMk message id + Graph attachment id so
    the read-path on-demand self-heal can address Graph directly even when
    ``message_id`` is a conversationId (AAQk) store key rather than a fetchable id.
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
                         content_sha256, storage, data, provider_attachment_id,
                         real_message_id)
                    VALUES (%s, %s, %s, %s, %s, %s, 'metadata_only', NULL, %s, %s)
                    ON CONFLICT (message_id, content_sha256) DO NOTHING
                    RETURNING id
                    """,
                    (message_id, source, filename, mime_type, size_bytes, sha256,
                     provider_attachment_id, real_message_id),
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


def insert_attachment_routed(
    message_id: str,
    source: str,
    filename: str | None,
    mime_type: str | None,
    payload_bytes: bytes,
    provider_attachment_id: str | None = None,
):
    """Persist a NEW attachment with size routing; return its row id or None.

    Forward-ingest path (BAKER_M365_LARGE_ATTACHMENT_FETCH_1 F1). Unlike
    ``insert_attachment`` (which stores >5MiB metadata_only), this routes >5MiB
    payloads to R2 (storage='r2', object_key set) and <=5MiB inline to Neon.
    Idempotent on (message_id, content_sha256): ON CONFLICT returns the existing
    row's id. Fault-tolerant: returns None on failure, never raises.
    """
    if not message_id or not source or payload_bytes is None:
        logger.warning("insert_attachment_routed: missing message_id/source/payload")
        return None
    routed = _route_storage(source, payload_bytes, mime_type)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_attachments
                        (message_id, source, filename, mime_type, size_bytes,
                         content_sha256, storage, data, object_key,
                         provider_attachment_id, fetched_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (message_id, content_sha256) DO NOTHING
                    RETURNING id
                    """,
                    (message_id, source, filename, mime_type, routed["size_bytes"],
                     routed["sha256"], routed["storage"], routed["data"],
                     routed["object_key"], provider_attachment_id),
                )
                row = cur.fetchone()
                if row is not None:
                    conn.commit()
                    return row[0]
                cur.execute(
                    """
                    SELECT id FROM email_attachments
                     WHERE message_id = %s AND content_sha256 = %s
                     LIMIT 1
                    """,
                    (message_id, routed["sha256"]),
                )
                existing = cur.fetchone()
                conn.commit()
                return existing[0] if existing else None
    except Exception as e:
        logger.error("insert_attachment_routed failed for %s: %s", message_id, e)
        return None


def update_attachment_payload(
    att_id: int,
    source: str | None,
    payload_bytes: bytes,
    mime_type: str | None = None,
    provider_attachment_id: str | None = None,
) -> str:
    """Give an EXISTING byte-empty row its bytes, UPDATING that exact row in place.

    Backfill + read-path persist-on-first-read (F2). Routes >5MiB -> R2,
    <=5MiB -> Neon, and stamps content_sha256 / size / storage / object_key /
    fetched_at / provider_attachment_id on the row identified by ``att_id``.

    Guarded so it only fills a still-empty, non-true-empty row
    (``data IS NULL AND object_key IS NULL AND size_bytes > 0``) — it never
    clobbers an already-byte-carrying row (idempotent) nor a 0-byte true-empty.

    Returns one of: 'updated' (bytes now on the row), 'duplicate' (the real
    content_sha256 already exists for this message_id on a twin row — this empty
    row is redundant cruft, caller may delete it), 'skipped' (row not empty /
    not found), 'error'. Never raises.
    """
    if not att_id or payload_bytes is None:
        return "error"
    routed = _route_storage(source, payload_bytes, mime_type)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE email_attachments
                       SET size_bytes = %s,
                           content_sha256 = %s,
                           mime_type = COALESCE(%s, mime_type),
                           storage = %s,
                           data = %s,
                           object_key = %s,
                           provider_attachment_id = COALESCE(%s, provider_attachment_id),
                           fetched_at = now()
                     WHERE id = %s
                       AND data IS NULL
                       AND object_key IS NULL
                       AND size_bytes > 0
                    RETURNING id
                    """,
                    (routed["size_bytes"], routed["sha256"], mime_type,
                     routed["storage"], routed["data"], routed["object_key"],
                     provider_attachment_id, att_id),
                )
                row = cur.fetchone()
                conn.commit()
                return "updated" if row is not None else "skipped"
    except Exception as e:
        # A unique (message_id, content_sha256) violation means the real bytes are
        # ALREADY stored on a twin row for this message — this empty row is a
        # redundant duplicate (e.g. the 25 same-file-in-same-message groups).
        # No manual rollback needed: get_conn() uses a fresh connection per call
        # and closes it in finally (close rolls back the in-flight txn).
        msg = str(e).lower()
        if "unique" in msg or "duplicate key" in msg or "content_sha256" in msg:
            logger.warning("update_attachment_payload id=%s: content already stored on a twin (duplicate)", att_id)
            return "duplicate"
        logger.error("update_attachment_payload failed for id=%s: %s", att_id, e)
        return "error"


def delete_empty_attachment(att_id: int) -> bool:
    """Delete a STILL-EMPTY attachment row (cruft cleanup for the 'duplicate'
    case in ``update_attachment_payload``). Guarded: only removes a row whose
    bytes are absent (``data IS NULL AND object_key IS NULL``), so a
    byte-carrying row can never be deleted by a stale caller. Returns True iff a
    row was deleted. Never raises."""
    if not att_id:
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM email_attachments
                     WHERE id = %s AND data IS NULL AND object_key IS NULL
                    RETURNING id
                    """,
                    (att_id,),
                )
                row = cur.fetchone()
                conn.commit()
                return row is not None
    except Exception as e:
        logger.error("delete_empty_attachment failed for id=%s: %s", att_id, e)
        return False


_ATTACHMENT_BY_ID_SQL = """
    SELECT id, message_id, source, filename, mime_type,
           size_bytes, content_sha256, storage, data, created_at, object_key
      FROM email_attachments
     WHERE id = %s
     LIMIT 1
"""


def _map_attachment_row(row):
    """Map a get-by-id row tuple to a dict, or None when the row is absent."""
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
        "object_key": row[10],
    }


def get_attachment(att_id: int):
    """Return the attachment row as a dict, or None if missing / on failure.

    Ingest/forward-parity callers rely on the swallow-to-None contract (a
    backend hiccup is a non-fatal skip there). The READ surface must instead
    distinguish outage from a true miss — use ``get_attachment_read``.

    Keys: id, message_id, source, filename, mime_type, size_bytes,
    content_sha256, storage, data (bytes or None), created_at.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_ATTACHMENT_BY_ID_SQL, (att_id,))
                return _map_attachment_row(cur.fetchone())
    except Exception as e:
        logger.error("get_attachment failed for id=%s: %s", att_id, e)
        return None


def get_attachment_read(att_id: int):
    """READ-surface twin of ``get_attachment``: same row dict on success, None
    ONLY when the row genuinely does not exist, but RAISES
    ``AttachmentStoreUnavailable`` on a backend outage.

    This is the byte-fetch counterpart to ``list_attachments``' outage contract:
    a swallowed None would let a store outage read as 'payload missing' (the
    false-empty class). The read tool maps the typed outage to
    {backend_unavailable: true}; a real None stays a true 'payload unavailable'.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_ATTACHMENT_BY_ID_SQL, (att_id,))
                return _map_attachment_row(cur.fetchone())
    except Exception as e:
        logger.error("get_attachment_read backend failure for id=%s: %s", att_id, e)
        raise AttachmentStoreUnavailable(str(e)) from e


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
    1-based indexing), or [] when the message genuinely has no attachments.
    Optional ``source`` filter ('graph' | 'bluewin' | 'email' | 'exchange').
    Payload bytes are intentionally NOT selected here — fetch a specific row's
    bytes via ``get_attachment(id)``.

    Raises ``AttachmentStoreUnavailable`` on a backend outage so the caller can
    distinguish 'store down' from 'no attachments' (a swallowed [] would
    re-create the silent false-empty class — cf. the M365 mail blindspot).
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
                               size_bytes, content_sha256, storage, object_key,
                               real_message_id, provider_attachment_id
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
                               size_bytes, content_sha256, storage, object_key,
                               real_message_id, provider_attachment_id
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
                        "object_key": r[8],
                        "real_message_id": r[9],
                        "provider_attachment_id": r[10],
                    }
                    for r in rows
                ]
    except Exception as e:
        # Do NOT swallow to [] — that masks a store outage as 'no attachments'
        # (false-empty, the M365-blindspot failure class). Surface it loudly.
        logger.error("list_attachments backend failure for %s: %s", message_id, e)
        raise AttachmentStoreUnavailable(str(e)) from e
