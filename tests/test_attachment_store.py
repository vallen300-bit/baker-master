"""EMAIL_ATTACHMENT_STORE_1 — tests for kbl/attachment_store.py +
``GET /api/attachments/{att_id}``.

Two groups:

Live-PG (gated on ``needs_live_pg`` — TEST_DATABASE_URL or CI ephemeral
Neon branch; auto-skip otherwise):
  L1. Migration applies clean on fresh AND existing DB (run twice — AC1).
  L2. Round-trip: insert small payload → get returns identical bytes,
      storage='db', sha256 correct.
  L3. Dedup: same (message_id, payload) twice → same id, one row (AC2).
  L4. >5MB synthetic payload → storage='metadata_only', data NULL.
  L5. attachment_exists true for stored sha, false for unknown.

Endpoint (self-contained, DB monkeypatched — AC3):
  E1. Source-level: route registered with auth + tag.
  E2. 401 without X-Baker-Key.
  E3. 200 bytes + content-type with auth.
  E4. 404 for metadata_only row.
  E5. 404 for missing id.
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_MIGRATION = _REPO / "migrations" / "20260610_email_attachments.sql"


# ---------------------------------------------------------------------------
# Live-PG group
# ---------------------------------------------------------------------------


@pytest.fixture
def attachment_pg(needs_live_pg, monkeypatch):
    """Point kbl.db at the live test DB and apply the migration.

    Applies migrations/20260610_email_attachments.sql (idempotent — IF NOT
    EXISTS throughout). Cleans up only rows created by this test run
    (delete-by-message_id; never TRUNCATE — the test DB is shared across
    B-code clones).
    """
    import psycopg2

    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    sql = _MIGRATION.read_text()

    conn = psycopg2.connect(needs_live_pg)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql)

    created_message_ids: list[str] = []
    yield created_message_ids

    try:
        with conn.cursor() as cur:
            if created_message_ids:
                cur.execute(
                    "DELETE FROM email_attachments WHERE message_id = ANY(%s)",
                    (created_message_ids,),
                )
    finally:
        conn.close()


def test_migration_applies_clean_fresh_and_existing(needs_live_pg):
    """L1 / AC1 — migration runs twice without error (IF NOT EXISTS)."""
    import psycopg2

    sql = _MIGRATION.read_text()
    conn = psycopg2.connect(needs_live_pg)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)   # fresh (or already-present) apply
            cur.execute(sql)   # re-apply on existing DB — must be a no-op
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name IN ('email_attachments', 'email_backfill_progress')"
            )
            assert cur.fetchone()[0] == 2
    finally:
        conn.close()


def test_insert_and_get_round_trip(attachment_pg):
    """L2 — bytes in == bytes out; storage db; sha256 correct."""
    from kbl.attachment_store import get_attachment, insert_attachment

    msg_id = f"test-att-{uuid.uuid4()}"
    attachment_pg.append(msg_id)
    payload = b"%PDF-1.4 fake invoice bytes \x00\x01\x02"

    att_id = insert_attachment(msg_id, "bluewin", "invoice.pdf", "application/pdf", payload)
    assert isinstance(att_id, int)

    row = get_attachment(att_id)
    assert row is not None
    assert row["data"] == payload
    assert row["storage"] == "db"
    assert row["size_bytes"] == len(payload)
    assert row["content_sha256"] == hashlib.sha256(payload).hexdigest()
    assert row["filename"] == "invoice.pdf"
    assert row["mime_type"] == "application/pdf"
    assert row["source"] == "bluewin"


def test_dedup_same_payload_twice_one_row(attachment_pg):
    """L3 / AC2 — same (message_id, payload) twice → same id, single row."""
    import psycopg2

    from kbl.attachment_store import insert_attachment

    msg_id = f"test-att-{uuid.uuid4()}"
    attachment_pg.append(msg_id)
    payload = b"duplicate payload"

    id1 = insert_attachment(msg_id, "graph", "a.txt", "text/plain", payload)
    id2 = insert_attachment(msg_id, "graph", "a.txt", "text/plain", payload)
    assert isinstance(id1, int)
    assert id1 == id2

    import os
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM email_attachments WHERE message_id = %s",
                (msg_id,),
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_oversize_payload_metadata_only(attachment_pg):
    """L4 — >5MB synthetic payload stored metadata_only, data NULL."""
    from kbl.attachment_store import get_attachment, insert_attachment

    msg_id = f"test-att-{uuid.uuid4()}"
    attachment_pg.append(msg_id)
    payload = b"x" * (5 * 1024 * 1024 + 1)

    att_id = insert_attachment(msg_id, "bluewin", "huge.zip", "application/zip", payload)
    assert isinstance(att_id, int)

    row = get_attachment(att_id)
    assert row is not None
    assert row["storage"] == "metadata_only"
    assert row["data"] is None
    assert row["size_bytes"] == len(payload)
    assert row["content_sha256"] == hashlib.sha256(payload).hexdigest()


def test_attachment_exists(attachment_pg):
    """L5 — exists true for stored (message_id, sha); false for unknown."""
    from kbl.attachment_store import attachment_exists, insert_attachment

    msg_id = f"test-att-{uuid.uuid4()}"
    attachment_pg.append(msg_id)
    payload = b"exists-check"
    sha = hashlib.sha256(payload).hexdigest()

    assert attachment_exists(msg_id, sha) is False
    insert_attachment(msg_id, "email", None, None, payload)
    assert attachment_exists(msg_id, sha) is True
    assert attachment_exists(msg_id, "0" * 64) is False


# ---------------------------------------------------------------------------
# Endpoint group (no DB — kbl.attachment_store monkeypatched)
# ---------------------------------------------------------------------------


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


def test_endpoint_route_registered_in_dashboard_source():
    """E1 — source-level: route registered with auth + tag."""
    src = Path("outputs/dashboard.py").read_text()
    assert "/api/attachments/{att_id}" in src
    assert "async def get_email_attachment(" in src
    idx = src.index("async def get_email_attachment(")
    decorator_block = src[max(0, idx - 400):idx]
    assert "dependencies=[Depends(verify_api_key)]" in decorator_block


def _client(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import importlib

    import outputs.dashboard as dash
    importlib.reload(dash)
    return TestClient(dash.app)


@_skip_without_dashboard
def test_endpoint_401_without_key(monkeypatch):
    """E2 — no X-Baker-Key → 401."""
    client = _client(monkeypatch)
    resp = client.get("/api/attachments/1")
    assert resp.status_code == 401


@_skip_without_dashboard
def test_endpoint_200_bytes_and_content_type(monkeypatch):
    """E3 / AC3 — auth'd fetch returns stored bytes with stored mime."""
    import kbl.attachment_store as store

    payload = b"\x89PNG\r\n fake png"
    monkeypatch.setattr(
        store,
        "get_attachment",
        lambda att_id: {
            "id": att_id,
            "message_id": "m1",
            "source": "bluewin",
            "filename": "pic.png",
            "mime_type": "image/png",
            "size_bytes": len(payload),
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "storage": "db",
            "data": payload,
            "created_at": None,
        },
    )
    client = _client(monkeypatch)
    resp = client.get("/api/attachments/7", headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"] == "image/png"


@_skip_without_dashboard
def test_endpoint_404_metadata_only(monkeypatch):
    """E4 / AC3 — metadata_only row → 404."""
    import kbl.attachment_store as store

    monkeypatch.setattr(
        store,
        "get_attachment",
        lambda att_id: {
            "id": att_id,
            "message_id": "m2",
            "source": "graph",
            "filename": "huge.zip",
            "mime_type": "application/zip",
            "size_bytes": 6 * 1024 * 1024,
            "content_sha256": "0" * 64,
            "storage": "metadata_only",
            "data": None,
            "created_at": None,
        },
    )
    client = _client(monkeypatch)
    resp = client.get("/api/attachments/8", headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 404
    assert "metadata_only" in resp.json()["detail"]


@_skip_without_dashboard
def test_endpoint_404_missing(monkeypatch):
    """E5 / AC3 — unknown id → 404."""
    import kbl.attachment_store as store

    monkeypatch.setattr(store, "get_attachment", lambda att_id: None)
    client = _client(monkeypatch)
    resp = client.get("/api/attachments/999999", headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 404
