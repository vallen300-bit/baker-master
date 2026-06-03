"""
INGEST_SEARCH_DURABILITY_FOLLOWUPS_1 — Part B (PR2) durability hardening.

Covers:
  B5.1 — Voyage cardinality guard in _embed_and_upsert (short embeddings array → failed batch).
  B1   — durable document_id+matter_slug in the Qdrant payload (threaded at embed time)
         + set_document_payload (patch-after for /api/ingest) + retriever document_id resolution
         + attachments.promote threading.
  B2   — SOURCE_PREFIXES single-source contract (helpers + no hardcoded duplicates).
  B3   — safe_filename computed once in /api/ingest (source guard).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


# ───────────────────────── pipeline fakes ─────────────────────────


def _patch_pipeline(monkeypatch, *, short_by=0):
    """Fake Voyage + Qdrant; capture upserts + set_payload. short_by shrinks the
    embeddings array to simulate a Voyage cardinality mismatch."""
    import tools.ingest.pipeline as pipe

    class _FakeVoyage:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts, model=None, input_type=None):
            n = max(0, len(texts) - short_by)
            return SimpleNamespace(embeddings=[[0.1] * 8 for _ in range(n)])

    captured = {"upserts": [], "set_payload": []}

    class _FakeQdrant:
        def __init__(self, *a, **k):
            pass

        def upsert(self, collection_name=None, points=None):
            captured["upserts"].append((collection_name, points))

        def set_payload(self, collection_name=None, payload=None, points=None):
            captured["set_payload"].append((collection_name, payload, points))

    monkeypatch.setattr(pipe, "voyageai", SimpleNamespace(Client=_FakeVoyage))
    monkeypatch.setattr(pipe, "QdrantClient", _FakeQdrant)
    monkeypatch.setattr(pipe, "ensure_collection", lambda *a, **k: None)
    monkeypatch.setenv("INGEST_EMBED_DELAY", "0")
    monkeypatch.setenv("INGEST_EMBED_BATCH", "50")
    return captured


# ───────────────────────── B5.1 cardinality guard ─────────────────────────


def test_voyage_short_array_marks_failed_batch(monkeypatch):
    """If Voyage returns fewer embeddings than texts WITHOUT raising, the batch is
    treated as failed (not silently truncated by zip)."""
    _patch_pipeline(monkeypatch, short_by=1)
    import tools.ingest.pipeline as pipe

    point_ids, failed_batches = pipe._embed_and_upsert(
        ["a", "b", "c"], "baker-documents", "f.txt", "src/f.txt"
    )
    assert failed_batches == [1]
    assert point_ids == []  # nothing sealed from a short batch


def test_voyage_full_array_no_failed_batch(monkeypatch):
    _patch_pipeline(monkeypatch, short_by=0)
    import tools.ingest.pipeline as pipe

    point_ids, failed_batches = pipe._embed_and_upsert(
        ["a", "b"], "baker-documents", "f.txt", "src/f.txt"
    )
    assert failed_batches == []
    assert len(point_ids) == 2


# ───────────────────────── B1 durable payload ─────────────────────────


def test_embed_writes_document_id_and_matter_into_payload(monkeypatch):
    captured = _patch_pipeline(monkeypatch)
    import tools.ingest.pipeline as pipe

    pipe._embed_and_upsert(
        ["a", "b"], "baker-documents", "deal.pdf", "/vault/deal.pdf",
        document_id=42, matter_slug="mo-vie",
    )
    # All upserted points carry the durable join keys.
    points = [p for _, pts in captured["upserts"] for p in pts]
    assert points, "expected upserted points"
    for p in points:
        assert p.payload["document_id"] == 42
        assert p.payload["matter_slug"] == "mo-vie"
        assert p.payload["source_file"] == "deal.pdf"


def test_embed_omits_join_keys_when_not_provided(monkeypatch):
    captured = _patch_pipeline(monkeypatch)
    import tools.ingest.pipeline as pipe

    pipe._embed_and_upsert(["a"], "baker-documents", "x.pdf", "/x.pdf")
    p = captured["upserts"][0][1][0]
    assert "document_id" not in p.payload
    assert "matter_slug" not in p.payload


def test_ingest_text_threads_document_id_to_payload(monkeypatch):
    captured = _patch_pipeline(monkeypatch)
    import tools.ingest.pipeline as pipe
    monkeypatch.setattr(pipe, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(pipe, "log_ingestion", lambda *a, **k: None)

    pipe.ingest_text(full_text="some body text", filename="a.pdf",
                     source_path="email:1/a.pdf", document_id=7, matter_slug="rg7")
    points = [p for _, pts in captured["upserts"] for p in pts]
    assert points and all(p.payload["document_id"] == 7 for p in points)
    assert all(p.payload["matter_slug"] == "rg7" for p in points)


def test_set_document_payload_patches_points(monkeypatch):
    captured = _patch_pipeline(monkeypatch)
    import tools.ingest.pipeline as pipe

    pipe.set_document_payload("baker-documents", ["p1", "p2"], document_id=9, matter_slug="mo-vie")
    assert captured["set_payload"] == [("baker-documents", {"document_id": 9, "matter_slug": "mo-vie"}, ["p1", "p2"])]


def test_set_document_payload_noops_without_ids_or_points(monkeypatch):
    captured = _patch_pipeline(monkeypatch)
    import tools.ingest.pipeline as pipe

    pipe.set_document_payload("baker-documents", [], document_id=9)        # no points
    pipe.set_document_payload("baker-documents", ["p1"], document_id=None)  # nothing to set
    assert captured["set_payload"] == []


# ───────────────────────── B1 retriever resolution ─────────────────────────


def test_retriever_get_full_document_text_prefers_document_id():
    """_get_full_document_text(document_id=...) must query documents by id."""
    from memory.retriever import SentinelRetriever

    seen = {}

    class _Cur:
        def execute(self, sql, params=None):
            seen["sql"] = sql
            seen["params"] = params

        def fetchone(self):
            return ("full text body",)

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

    r = SentinelRetriever.__new__(SentinelRetriever)  # bypass heavy __init__
    r._get_pg_conn = lambda: _Conn()
    r._reset_pg_conn = lambda: None

    out = r._get_full_document_text(source_path="/v/a.pdf", filename="a.pdf", document_id=5)
    assert out == "full text body"
    assert "WHERE id = %s" in seen["sql"]
    assert seen["params"] == (5,)


def test_retriever_falls_back_to_source_path_without_id():
    from memory.retriever import SentinelRetriever

    seen = {}

    class _Cur:
        def execute(self, sql, params=None):
            seen["sql"] = sql
            seen["params"] = params

        def fetchone(self):
            return ("body",)

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

    r = SentinelRetriever.__new__(SentinelRetriever)
    r._get_pg_conn = lambda: _Conn()
    r._reset_pg_conn = lambda: None

    r._get_full_document_text(source_path="/v/a.pdf", filename="a.pdf", document_id=None)
    assert "WHERE source_path = %s" in seen["sql"]
    assert seen["params"] == ("/v/a.pdf",)


# ───────────────────────── B1 attachments threading ─────────────────────────


def test_promote_attachment_threads_document_id_in_source():
    """B1: promote_attachment_text_to_document_and_qdrant writes the PG row first
    (Half 1), then must thread that documents.id into the ingest_text (Half 2) Qdrant
    write so the payload carries the durable join key.

    Source-guard rather than behavioural: promote fetches the store via an internal
    `from memory.store_back import SentinelStoreBack` import, and another test in the
    suite leaks a MagicMock into sys.modules['memory.store_back'] (not restored), which
    makes a behavioural monkeypatch of the store order-dependent/flaky. The threading
    is what B1 requires; assert it deterministically in the source."""
    src = Path("tools/ingest/attachments.py").read_text()
    fn = src[src.index("def promote_attachment_text_to_document_and_qdrant"):]
    assert 'document_id=result["doc_id"]' in fn, (
        "promote must pass the Half-1 documents.id into ingest_text (B1 durable join)"
    )


# ───────────────────────── B2 source contract ─────────────────────────


def test_derive_source_parity_and_m365():
    import outputs.dashboard as d
    assert d._derive_source("x/email/a") == "email"
    assert d._derive_source("g/gmail/b") == "email"
    assert d._derive_source("w/whatsapp") == "whatsapp"
    assert d._derive_source("c/clickup") == "clickup"
    assert d._derive_source("f/fireflies") == "fireflies"
    assert d._derive_source("random/path") == "dropbox"
    assert d._derive_source("") == "dropbox"
    assert d._derive_source("m365:abc/x") == "m365"  # inert mapping present


def test_source_helpers_emit_expected_sql():
    import outputs.dashboard as d
    assert d._source_ilike_clause("email") == "(source_path ILIKE '%%email%%' OR source_path ILIKE '%%gmail%%')"
    assert d._source_ilike_clause("whatsapp") == "(source_path ILIKE '%%whatsapp%%')"
    # default label → NOT any known prefix (incl. m365)
    default = d._source_ilike_clause("dropbox")
    assert "NOT ILIKE '%%email%%'" in default and "NOT ILIKE '%%m365%%'" in default
    case = d._source_case_sql()
    assert case.startswith("CASE ") and "THEN 'email'" in case and "ELSE 'dropbox' END AS name" in case


def test_source_contract_no_hardcoded_duplicate_case_in_source():
    """The facet CASE + filter chain must route through the helpers, not hardcode
    the prefix list again (the drift B2 exists to prevent)."""
    src = Path("outputs/dashboard.py").read_text()
    assert "SOURCE_PREFIXES = {" in src
    assert "_source_case_sql()" in src
    assert "_source_ilike_clause(src)" in src
    # the old hardcoded facet CASE literal must be gone
    assert "WHEN source_path ILIKE '%%email%%' OR source_path ILIKE '%%gmail%%' THEN 'email'" not in src


# ───────────────────────── B3 safe_filename ─────────────────────────


def test_api_ingest_uses_safe_filename_once_in_source():
    """B3: /api/ingest must compute safe_filename once and use it for the PG row,
    response, and temp path — not raw file.filename."""
    src = Path("outputs/dashboard.py").read_text()
    start = src.index("async def ingest_document(")
    end = src.index('@app.get("/api/ingest/collections"', start)
    handler = src[start:end]
    assert "safe_filename = Path(file.filename).name" in handler
    assert "source_path=safe_filename" in handler
    assert "filename=safe_filename" in handler
    assert '"filename": safe_filename' in handler
    assert "Path(tmp_dir) / safe_filename" in handler
