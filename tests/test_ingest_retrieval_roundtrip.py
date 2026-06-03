"""
INGEST_RETRIEVAL_GAP_DIAGNOSE_FIX_1 — round-trip ingest→retrieve guard.

ROOT CAUSE this guards against (Lesson #8 / #86 — green-but-broken):
    POST /api/ingest used to write ONLY Qdrant chunks (via tools.ingest.pipeline
    .ingest_file) + an ingestion_log row. It NEVER wrote the Postgres `documents`
    table. Meanwhile GET /api/documents/search reads the `documents` table (its
    Qdrant branch — `from memory.retriever import Retriever` — has ImportError'd
    since DOCUMENTS-REDESIGN-1 and silently falls back to a Postgres ILIKE). So a
    doc ingested via /api/ingest reported `status=success, chunks=N` but was
    invisible to /api/documents/search.

The fix mirrors triggers/dropbox_trigger.py's established two-write pattern:
store_document_full() for Postgres + ingest_file() for Qdrant. These tests assert
the write reaches the read store, so "ingest success" can never again mean
"not stored".
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Source-level checks (always run, even on Py3.9 where dashboard won't import) ──


def test_ingest_endpoint_writes_documents_table_in_source():
    """The /api/ingest endpoint must call store_document_full (the documents-table
    writer) — not just ingest_file (Qdrant). This is the core fix."""
    src = Path("outputs/dashboard.py").read_text()
    # Locate the /api/ingest handler body.
    assert "async def ingest_document(" in src
    assert "store_document_full(" in src, (
        "/api/ingest must persist to the Postgres documents table via "
        "store_document_full — else ingested docs are invisible to /api/documents/search"
    )
    # Response must surface whether the read-store write happened (fail-loud).
    assert '"stored_postgres"' in src


def test_ingest_result_exposes_full_text():
    """ingest_file must expose extracted text so the endpoint can persist it
    without re-extracting (re-extract = double Vision cost on images)."""
    from tools.ingest.models import IngestResult

    r = IngestResult(
        filename="x.md", file_hash="h", file_size_bytes=1,
        collection="baker-documents", chunk_count=1,
    )
    assert hasattr(r, "full_text")
    assert hasattr(r, "token_count")
    assert hasattr(r, "document_id")


# ─── Pipeline unit test (always run; voyage/qdrant mocked, no network/DB) ──────


_SENTINEL = "ROUNDTRIP_SENTINEL_TOKEN_77f3a9"


def _patch_pipeline(monkeypatch):
    """Stub Voyage + Qdrant so ingest_file runs offline."""
    import tools.ingest.pipeline as pipe

    class _FakeVoyage:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts, model=None, input_type=None):
            return SimpleNamespace(embeddings=[[0.1] * 8 for _ in texts])

    class _FakeQdrant:
        def __init__(self, *a, **k):
            self.upserts = []

        def upsert(self, collection_name=None, points=None):
            self.upserts.append((collection_name, points))

    monkeypatch.setattr(pipe, "voyageai", SimpleNamespace(Client=_FakeVoyage))
    monkeypatch.setattr(pipe, "QdrantClient", _FakeQdrant)
    monkeypatch.setattr(pipe, "ensure_collection", lambda *a, **k: None)
    monkeypatch.setattr(pipe, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(pipe, "log_ingestion", lambda *a, **k: None)
    # Avoid the 25s inter-batch sleep default.
    monkeypatch.setenv("INGEST_EMBED_DELAY", "0")
    monkeypatch.setenv("INGEST_EMBED_BATCH", "50")


def test_ingest_file_carries_full_text_to_caller(monkeypatch, tmp_path):
    """ingest_file extracts the sentinel token and exposes it on the result so the
    endpoint can persist it to the documents table."""
    _patch_pipeline(monkeypatch)
    from tools.ingest.pipeline import ingest_file

    doc = tmp_path / "sentinel_doc.md"
    doc.write_text(f"# Round-trip probe\n\nUnique marker {_SENTINEL} for retrieval.\n")

    result = ingest_file(filepath=doc, collection="baker-documents", skip_llm=True)

    assert result.error is None
    assert not result.skipped
    assert result.chunk_count >= 1
    assert result.full_text is not None
    assert _SENTINEL in result.full_text
    assert result.token_count > 0


# ─── Endpoint round-trip (TestClient; ingest_file + store mocked) ──────────────


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


class _CapturingStore:
    """Captures store_document_full calls so we can assert the doc reached the
    Postgres read store, and serves an ILIKE-style query to prove retrievability."""

    def __init__(self):
        self.docs: list[dict] = []
        self._next_id = 1

    def store_document_full(self, source_path, filename, file_hash, full_text,
                            token_count=0, owner="shared"):
        doc_id = self._next_id
        self._next_id += 1
        self.docs.append({
            "id": doc_id,
            "source_path": source_path,
            "filename": filename,
            "file_hash": file_hash,
            "full_text": full_text,
            "token_count": token_count,
            "owner": owner,
        })
        return doc_id

    def search_ilike(self, q: str) -> list[dict]:
        """Mirror /api/documents/search Postgres fallback: full_text/filename ILIKE."""
        ql = q.lower()
        return [d for d in self.docs
                if ql in (d["full_text"] or "").lower()
                or ql in (d["filename"] or "").lower()]


@_skip_without_dashboard
def test_api_ingest_persists_to_documents_and_is_retrievable(monkeypatch):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    from tools.ingest.models import IngestResult

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key", raising=False)
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    store = _CapturingStore()
    monkeypatch.setattr(dash, "_get_store", lambda: store)

    # Stub the Qdrant ingest so the endpoint exercises ONLY the documents-write fix.
    def _fake_ingest_file(filepath, collection=None, image_type=None,
                          project=None, role=None, **kwargs):
        return IngestResult(
            filename=Path(filepath).name, file_hash="deadbeef",
            file_size_bytes=42, collection="baker-documents", chunk_count=2,
            full_text=f"Probe body with {_SENTINEL} inside.", token_count=9,
        )

    monkeypatch.setattr(dash, "ingest_file", _fake_ingest_file)
    # queue_extraction is best-effort; neutralize it.
    import tools.document_pipeline as dp
    monkeypatch.setattr(dp, "queue_extraction", lambda *a, **k: None)

    client = TestClient(dash.app)
    resp = client.post(
        "/api/ingest",
        headers={"X-Baker-Key": "test-key"},
        files={"file": ("probe.md", f"Probe body with {_SENTINEL} inside.", "text/markdown")},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["stored_postgres"] is True
    assert body["document_id"] is not None

    # Write half: the doc reached the Postgres read store with the sentinel token.
    assert len(store.docs) == 1
    assert _SENTINEL in store.docs[0]["full_text"]

    # Read half: the documents-search query path now returns it. Round-trip closed.
    hits = store.search_ilike(_SENTINEL)
    assert len(hits) == 1
    assert hits[0]["id"] == body["document_id"]


# ─── Live-PG round-trip (real Postgres; auto-skips without TEST_DATABASE_URL) ──


def test_live_documents_roundtrip(needs_live_pg):
    """End-to-end against real Postgres (Lesson #86): store a sentinel doc via the
    SAME writer the endpoint uses, then run the SAME ILIKE query the search endpoint
    uses, and assert it returns. Mock-green alone is not acceptance for this bug."""
    import psycopg2
    from memory.store_back import SentinelStoreBack

    token = _SENTINEL + "_live"
    dsn = needs_live_pg

    # Point the store's connection helpers at the live test DB.
    store = SentinelStoreBack.__new__(SentinelStoreBack)

    def _get_conn():
        return psycopg2.connect(dsn)

    def _put_conn(conn):
        try:
            conn.close()
        except Exception:
            pass

    store._get_conn = _get_conn          # type: ignore[attr-defined]
    store._put_conn = _put_conn          # type: ignore[attr-defined]

    # Ensure the documents table exists in the ephemeral DB.
    store._ensure_documents_table()

    doc_id = store.store_document_full(
        source_path="roundtrip-probe.md",
        filename="roundtrip-probe.md",
        file_hash="live-" + token,
        full_text=f"Live round-trip probe carrying {token}.",
        token_count=8,
    )
    assert doc_id is not None

    # Mirror the GET /api/documents/search Postgres fallback query.
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, filename FROM documents "
            "WHERE filename ILIKE %s OR full_text ILIKE %s",
            (f"%{token}%", f"%{token}%"),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    assert any(r[0] == doc_id for r in rows), (
        "doc written by store_document_full was not retrievable via the "
        "documents ILIKE query — the round-trip is broken"
    )
