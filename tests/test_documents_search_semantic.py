"""
DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1 (Bug A) — restore the dead Qdrant semantic
branch in GET /api/documents/search and guard its deterministic id-resolution.

ROOT CAUSE this guards against:
    The Qdrant branch did `from memory.retriever import Retriever` (no such symbol;
    the class is SentinelRetriever) and `retriever.search(...)` (wrong method). The
    ImportError was swallowed by `except`, so EVERY query silently ran a Postgres
    `filename/full_text ILIKE` substring match. Document search was dumb keyword
    matching for months.

The fix runs a real Voyage→Qdrant semantic search, then enriches each chunk hit
from Postgres by `source_file` (the only shared join key in the existing corpus),
groups chunks → one result per documents.id keeping the highest score, applies
filters against the authoritative PG row, and drops any hit with no PG row (no
openable documents.id). The ILIKE path is kept only as a fallback.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Source-level guard (always runs, even on Py3.9 where dashboard won't import) ──

def test_handler_uses_sentinelretriever_singleton_in_source():
    """The search handler must use the real retriever API, not the dead import."""
    src = Path("outputs/dashboard.py").read_text()
    # The broken symbol must be gone.
    assert "from memory.retriever import Retriever\n" not in src, (
        "dead `from memory.retriever import Retriever` must be removed — it ImportErrors "
        "and silently degrades document search to ILIKE substring matching"
    )
    # The correct singleton + method must be present.
    assert "SentinelRetriever._get_global_instance()" in src, (
        "handler must use the singleton accessor (CI guard scripts/check_singletons.sh)"
    )
    assert "search_collection(" in src
    assert 'collection="baker-documents"' in src
    # Conn-hold fix: the search handler must no longer grab a conn up-front for the
    # whole body. (We assert the semantic phase calls the retriever before any cursor.)
    assert "_resolve_semantic_doc_hits(" in src


def test_ingest_document_temp_filename_matches_original_in_source():
    """G3 regression guard (codex #1724): /api/ingest must write its temp file under
    the ORIGINAL filename, so ingest_file's Qdrant `source_file` payload (= filepath.name)
    equals documents.filename (= file.filename). A NamedTemporaryFile prefix produced
    `Mandarin_<rand>.pdf` ≠ `Mandarin.pdf`, dropping every /api/ingest doc from the new
    semantic resolver (filename is the Qdrant↔PG join key)."""
    src = Path("outputs/dashboard.py").read_text()
    # Scope to the ingest_document handler (the path that writes Qdrant via
    # ingest_file). upload_document also uses NamedTemporaryFile but never calls
    # ingest_file → no Qdrant source_file → not affected, so don't assert on it.
    start = src.index("async def ingest_document(")
    end = src.index('@app.get("/api/ingest/collections"', start)
    handler = src[start:end]
    # The mangling prefix must be gone from the ingest path.
    assert 'prefix=Path(file.filename).stem + "_"' not in handler, (
        "ingest_document must not prefix the temp basename — it breaks the "
        "Qdrant source_file -> documents.filename join used by semantic search"
    )
    # The fix: temp directory + original filename, cleaned up via rmtree. B3 folded
    # the path-strip into a single `safe_filename` reused across every surface, so the
    # temp basename is now `safe_filename` (== Path(file.filename).name) — same value,
    # same join guarantee.
    assert "tempfile.mkdtemp()" in handler
    assert "safe_filename = Path(file.filename).name" in handler
    assert "Path(tmp_dir) / safe_filename" in handler
    assert "shutil.rmtree(tmp_dir" in handler


# ─── Pure resolution-logic unit tests (run under py3.12 where dashboard imports) ──

def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


pytestmark_helper = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard not importable on this interpreter (needs py3.10+ syntax)",
)


def _hit(source_file, source_path="", score=0.5, content="chunk text"):
    """Mimic a RetrievedContext: attribute access .metadata/.score/.content."""
    return SimpleNamespace(
        metadata={"source_file": source_file, "source_path": source_path},
        score=score,
        content=content,
    )


def _pg(id_, filename, source_path="", matter="", dtype="", ingested=None, preview="prev"):
    return {
        "id": id_,
        "filename": filename,
        "document_type": dtype,
        "matter_slug": matter,
        "source_path": source_path,
        "ingested_at": ingested,
        "text_preview": preview,
    }


@pytestmark_helper
def test_single_pg_row_resolves_to_its_id():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("deal.pdf", "/vault/deal.pdf", score=0.8)]
    pg = {"deal.pdf": [_pg(42, "deal.pdf", "/vault/deal.pdf", matter="mo-vie", dtype="contract")]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 42
    assert results[0]["matter"] == "mo-vie"
    assert results[0]["document_type"] == "contract"
    assert results[0]["score"] == 0.8


@pytestmark_helper
def test_multiple_pg_rows_prefer_source_path_match():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("dup.pdf", "/b/dup.pdf", score=0.7)]
    pg = {"dup.pdf": [
        _pg(1, "dup.pdf", "/a/dup.pdf", ingested=datetime(2026, 1, 1)),
        _pg(2, "dup.pdf", "/b/dup.pdf", ingested=datetime(2025, 1, 1)),  # older but path matches
    ]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 2, "source_path match wins over recency"


@pytestmark_helper
def test_multiple_pg_rows_fall_back_to_most_recent():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("dup.pdf", "/no/match.pdf", score=0.7)]
    pg = {"dup.pdf": [
        _pg(1, "dup.pdf", "/a/dup.pdf", ingested=datetime(2026, 5, 1)),  # most recent
        _pg(2, "dup.pdf", "/b/dup.pdf", ingested=datetime(2025, 1, 1)),
    ]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 1, "no source_path match → newest ingested_at wins"


@pytestmark_helper
def test_zero_pg_rows_drops_hit():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("orphan.pdf", "/vault/orphan.pdf", score=0.9)]
    results, total = _resolve_semantic_doc_hits(hits, {}, [], [], [], 0, 20)

    assert total == 0
    assert results == [], "a hit with no PG row has no openable id → must be dropped"


@pytestmark_helper
def test_multi_chunk_doc_deduped_to_highest_score():
    from outputs.dashboard import _resolve_semantic_doc_hits

    # Three chunks of the same document, different scores.
    hits = [
        _hit("big.pdf", "/v/big.pdf", score=0.4),
        _hit("big.pdf", "/v/big.pdf", score=0.91),
        _hit("big.pdf", "/v/big.pdf", score=0.6),
    ]
    pg = {"big.pdf": [_pg(7, "big.pdf", "/v/big.pdf")]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1, "multi-chunk doc must collapse to a single result"
    assert results[0]["id"] == 7
    assert results[0]["score"] == 0.91, "highest chunk score is kept"


@pytestmark_helper
def test_matter_filter_applied_against_pg_fields():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [
        _hit("a.pdf", "/v/a.pdf", score=0.8),
        _hit("b.pdf", "/v/b.pdf", score=0.7),
    ]
    pg = {
        "a.pdf": [_pg(1, "a.pdf", "/v/a.pdf", matter="mo-vie")],
        "b.pdf": [_pg(2, "b.pdf", "/v/b.pdf", matter="hagenauer-rg7")],
    }
    results, total = _resolve_semantic_doc_hits(hits, pg, ["mo-vie"], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 1


@pytestmark_helper
def test_results_sorted_by_score_desc_and_paginated():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [
        _hit("low.pdf", "/v/low.pdf", score=0.31),
        _hit("high.pdf", "/v/high.pdf", score=0.95),
        _hit("mid.pdf", "/v/mid.pdf", score=0.6),
    ]
    pg = {
        "low.pdf": [_pg(1, "low.pdf", "/v/low.pdf")],
        "high.pdf": [_pg(2, "high.pdf", "/v/high.pdf")],
        "mid.pdf": [_pg(3, "mid.pdf", "/v/mid.pdf")],
    }
    # full page: order by score desc
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)
    assert total == 3
    assert [r["id"] for r in results] == [2, 3, 1]

    # offset/limit paginates the sorted list
    page2, total2 = _resolve_semantic_doc_hits(hits, pg, [], [], [], 1, 1)
    assert total2 == 3
    assert [r["id"] for r in page2] == [3]


@pytestmark_helper
def test_type_and_source_filters_against_pg_fields():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [
        _hit("mail.pdf", "/gmail/mail.pdf", score=0.8),
        _hit("doc.pdf", "/dropbox/doc.pdf", score=0.7),
    ]
    pg = {
        "mail.pdf": [_pg(1, "mail.pdf", "/gmail/mail.pdf", dtype="email")],
        "doc.pdf": [_pg(2, "doc.pdf", "/dropbox/doc.pdf", dtype="contract")],
    }
    # source filter: only email-derived source_path survives
    res_src, tot_src = _resolve_semantic_doc_hits(hits, pg, [], [], ["email"], 0, 20)
    assert tot_src == 1 and res_src[0]["id"] == 1

    # type filter: only contract survives
    res_t, tot_t = _resolve_semantic_doc_hits(hits, pg, [], ["contract"], [], 0, 20)
    assert tot_t == 1 and res_t[0]["id"] == 2


@pytestmark_helper
def test_ingest_filename_parity_resolves_not_dropped():
    """G3 regression witness (codex #1724): a doc uploaded via /api/ingest must be
    found by semantic search. POST-FIX the Qdrant source_file == documents.filename
    ('Mandarin.pdf'), so the resolver returns the PG row. PRE-FIX the source_file was
    the mangled temp basename ('Mandarin_ab12cd.pdf') with no PG row → dropped."""
    from outputs.dashboard import _resolve_semantic_doc_hits

    pg = {"Mandarin.pdf": [_pg(99, "Mandarin.pdf", "Mandarin.pdf", matter="mo-vie")]}

    # POST-FIX: temp basename == original filename → joins → returned (not dropped).
    fixed_hit = [_hit("Mandarin.pdf", "/tmp/abc/Mandarin.pdf", score=0.77)]
    results, total = _resolve_semantic_doc_hits(fixed_hit, pg, [], [], [], 0, 20)
    assert total == 1 and results[0]["id"] == 99, "uploaded doc must be retrievable"

    # PRE-FIX witness: mangled source_file has no matching PG filename → dropped.
    mangled_hit = [_hit("Mandarin_ab12cd.pdf", "/tmp/Mandarin_ab12cd.pdf", score=0.77)]
    dropped, dtotal = _resolve_semantic_doc_hits(mangled_hit, pg, [], [], [], 0, 20)
    assert dtotal == 0 and dropped == [], "mangled basename must NOT join (the bug)"


# ─── INGEST_SEARCH_DURABILITY_FOLLOWUPS_1 A1: observable retrieval mode ─────────


def test_search_handler_reports_mode_in_source():
    """A1: the response dict must carry `mode`, and the three legitimate values
    must exist so a silent ILIKE regression (original Bug A) is observable."""
    src = Path("outputs/dashboard.py").read_text()
    # CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1: the retrieval logic moved into the
    # reusable search_documents_core(); the endpoint is now a thin wrapper. Slice
    # from the core so the mode/logging guards still cover the real logic.
    start = src.index("def search_documents_core(")
    end = src.index("async def get_document_text(", start)
    handler = src[start:end]
    assert '"mode": mode' in handler, "search response must include the mode field"
    assert '"semantic"' in handler
    assert '"ilike_fallback"' in handler
    assert '"filter_only"' in handler


def test_search_handler_splits_fallback_logging_in_source():
    """A1: a RAISED Qdrant/Voyage error is degradation → logger.error; an empty
    result above threshold is a legitimate last-resort → logger.info. They must
    not both collapse to one warning anymore."""
    src = Path("outputs/dashboard.py").read_text()
    # CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1: the retrieval logic moved into the
    # reusable search_documents_core(); the endpoint is now a thin wrapper. Slice
    # from the core so the mode/logging guards still cover the real logic.
    start = src.index("def search_documents_core(")
    end = src.index("async def get_document_text(", start)
    handler = src[start:end]
    assert "logger.error(f\"Qdrant/Voyage semantic search RAISED" in handler, (
        "the Qdrant/Voyage exception path must log at ERROR (it should alert)"
    )
    assert "logger.info(f\"Semantic search returned no hits above threshold" in handler, (
        "the no-hit-above-threshold path must log at INFO (legitimate, not a fault)"
    )


# ─── A1 functional: mode is correct end-to-end (TestClient) ────────────────────


def _search_client(monkeypatch):
    """A FakeStore whose conn is a no-op cursor (COUNT→0, rows→[]), so both the
    ILIKE path and the semantic-enrichment path complete with empty results and
    we can assert `mode` without a live DB."""
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key", raising=False)
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    class _Cur:
        def execute(self, sql, params=None):
            self._count = "COUNT(*)" in sql
        def fetchone(self):
            return {"total": 0}
        def fetchall(self):
            return []
        def close(self):
            pass
    class _Conn:
        def cursor(self, cursor_factory=None):
            return _Cur()
        def rollback(self):
            pass
    class _Store:
        def _get_conn(self):
            return _Conn()
        def _put_conn(self, c):
            pass
    monkeypatch.setattr(dash, "_get_store", lambda: _Store())
    return TestClient(dash.app), dash


def _stub_retriever(monkeypatch, *, hits=None, raise_err=False):
    import memory.retriever as mr

    class _FakeRetriever:
        def _embed_query(self, q):
            if raise_err:
                raise RuntimeError("voyage down")
            return [0.1] * 8
        def search_collection(self, query_vector=None, collection=None, limit=None,
                              score_threshold=None):
            if raise_err:
                raise RuntimeError("qdrant down")
            return hits or []
    monkeypatch.setattr(mr.SentinelRetriever, "_get_global_instance",
                        classmethod(lambda cls: _FakeRetriever()))


@pytestmark_helper
def test_mode_semantic_when_qdrant_returns_hits(monkeypatch):
    client, _ = _search_client(monkeypatch)
    # Hits with no PG row → dropped by resolver, but the SEMANTIC path still ran.
    _stub_retriever(monkeypatch, hits=[_hit("x.pdf", "x.pdf", 0.6)])
    resp = client.get("/api/documents/search", params={"q": "mandarin"},
                      headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "semantic"


@pytestmark_helper
def test_mode_ilike_fallback_when_qdrant_raises(monkeypatch):
    client, _ = _search_client(monkeypatch)
    _stub_retriever(monkeypatch, raise_err=True)
    resp = client.get("/api/documents/search", params={"q": "mandarin"},
                      headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "ilike_fallback"


@pytestmark_helper
def test_mode_filter_only_when_no_query(monkeypatch):
    client, _ = _search_client(monkeypatch)
    resp = client.get("/api/documents/search", params={"matter": "mo-vie"},
                      headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "filter_only"


# ─── INGEST_SEARCH_DURABILITY_FOLLOWUPS_1 A3: cross-store reconciliation ────────


def test_health_exposes_documents_missing_qdrant_in_source():
    """A3: /health must surface the drift count (informational, must NOT flip
    status — legacy backlog can't be allowed to fail Render's liveness probe)."""
    src = Path("outputs/dashboard.py").read_text()
    assert '"documents_missing_qdrant": docs_missing_qdrant' in src
    assert "def _documents_missing_qdrant(" in src
    # Guard: the drift count must not be wired into the degraded-status condition.
    cond_start = src.index("status = \"healthy\"")
    cond = src[cond_start:cond_start + 200]
    assert "documents_missing_qdrant" not in cond, (
        "drift count must stay informational — not flip /health to degraded"
    )


@pytestmark_helper
def test_reconciliation_endpoint_returns_missing_docs(monkeypatch):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    from datetime import datetime

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key", raising=False)
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    class _Cur:
        def execute(self, sql, params=None):
            self._count = "COUNT(*)" in sql
        def fetchone(self):
            return {"c": 2}
        def fetchall(self):
            return [
                {"id": 7, "filename": "a.pdf", "source_path": "email:1/a.pdf",
                 "matter_slug": "mo-vie", "ingested_at": datetime(2026, 6, 1)},
                {"id": 8, "filename": "b.pdf", "source_path": "email:2/b.pdf",
                 "matter_slug": "", "ingested_at": None},
            ]
        def close(self):
            pass
    class _Conn:
        def cursor(self, cursor_factory=None):
            return _Cur()
        def rollback(self):
            pass
    class _Store:
        def _get_conn(self):
            return _Conn()
        def _put_conn(self, c):
            pass
    monkeypatch.setattr(dash, "_get_store", lambda: _Store())

    client = TestClient(dash.app)
    resp = client.get("/api/documents/reconciliation",
                      headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["missing_qdrant_count"] == 2
    assert len(body["documents"]) == 2
    assert body["documents"][0]["id"] == 7
    assert body["documents"][1]["ingested_at"] is None


# ─── Part B: B4 windowed-total + B5.3 enrichment_failed sub-signal ─────────────


@pytestmark_helper
def test_semantic_response_flags_total_is_windowed(monkeypatch):
    """B4: semantic responses carry total_is_windowed=true (total is bounded by the
    over-fetch window, not the corpus)."""
    client, _ = _search_client(monkeypatch)
    _stub_retriever(monkeypatch, hits=[_hit("x.pdf", "x.pdf", 0.6)])
    body = client.get("/api/documents/search", params={"q": "mandarin"},
                      headers={"X-Baker-Key": "test-key"}).json()
    assert body["mode"] == "semantic"
    assert body["total_is_windowed"] is True


@pytestmark_helper
def test_ilike_and_filter_only_omit_windowed_flag(monkeypatch):
    """B4: the exact-COUNT paths must NOT claim a windowed total."""
    client, _ = _search_client(monkeypatch)
    _stub_retriever(monkeypatch, raise_err=True)  # → ilike_fallback
    body_il = client.get("/api/documents/search", params={"q": "x"},
                         headers={"X-Baker-Key": "test-key"}).json()
    assert body_il["mode"] == "ilike_fallback"
    assert "total_is_windowed" not in body_il
    body_fo = client.get("/api/documents/search", params={"matter": "mo-vie"},
                         headers={"X-Baker-Key": "test-key"}).json()
    assert body_fo["mode"] == "filter_only"
    assert "total_is_windowed" not in body_fo


@pytestmark_helper
def test_enrichment_failed_false_on_successful_enrichment(monkeypatch):
    """B5.3: enrichment ran (conn present, query succeeded) → enrichment_failed False
    even though the resolver dropped all hits (no PG rows in the fake)."""
    client, _ = _search_client(monkeypatch)
    _stub_retriever(monkeypatch, hits=[_hit("x.pdf", "x.pdf", 0.6)])
    body = client.get("/api/documents/search", params={"q": "mandarin"},
                      headers={"X-Baker-Key": "test-key"}).json()
    assert body["mode"] == "semantic"
    assert body["enrichment_failed"] is False


@pytestmark_helper
def test_enrichment_failed_true_when_conn_unavailable(monkeypatch):
    """B5.3: Qdrant returned hits but the PG conn is unavailable → enrichment_failed
    True (distinguishes from a genuinely-empty semantic result)."""
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key", raising=False)
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    class _NoConnStore:
        def _get_conn(self):
            return None
        def _put_conn(self, c):
            pass
    monkeypatch.setattr(dash, "_get_store", lambda: _NoConnStore())
    _stub_retriever(monkeypatch, hits=[_hit("x.pdf", "x.pdf", 0.6)])

    body = TestClient(dash.app).get("/api/documents/search", params={"q": "mandarin"},
                                    headers={"X-Baker-Key": "test-key"}).json()
    assert body["mode"] == "semantic"
    assert body["total"] == 0
    assert body["enrichment_failed"] is True


# ─── B1 follow-up (#1761): /api/documents/search resolves on document_id ────────


@pytestmark_helper
def test_resolves_by_document_id_when_source_file_mismatched():
    """The codex #1761 probe: a hit carrying document_id=42 + a stale/legacy source_file
    (no PG filename match) MUST still resolve via the id. Pre-fix this returned ([],0)."""
    from outputs.dashboard import _resolve_semantic_doc_hits

    h = _hit("legacy-name.pdf", "/old/legacy-name.pdf", score=0.7)
    h.metadata["document_id"] = 42
    pg_by_id = {42: _pg(42, "Mandarin.pdf", "/vault/Mandarin.pdf", matter="mo-vie", dtype="contract")}
    # pg_rows_by_filename is EMPTY (source_file doesn't match any PG filename).
    results, total = _resolve_semantic_doc_hits([h], {}, [], [], [], 0, 20, pg_rows_by_id=pg_by_id)
    assert total == 1 and results[0]["id"] == 42, "document_id must resolve despite source_file mismatch"
    assert results[0]["matter"] == "mo-vie"


@pytestmark_helper
def test_document_id_takes_priority_over_filename():
    from outputs.dashboard import _resolve_semantic_doc_hits

    h = _hit("shared.pdf", "/a/shared.pdf", score=0.7)
    h.metadata["document_id"] = 99
    pg_by_id = {99: _pg(99, "shared.pdf", "/a/shared.pdf", matter="rg7")}
    pg_by_fn = {"shared.pdf": [_pg(7, "shared.pdf", "/a/shared.pdf", matter="other")]}
    results, total = _resolve_semantic_doc_hits([h], pg_by_fn, [], [], [], 0, 20, pg_rows_by_id=pg_by_id)
    assert results[0]["id"] == 99, "id resolution wins over the filename join"


@pytestmark_helper
def test_falls_back_to_filename_when_id_row_absent():
    """document_id present but its PG row wasn't fetched (e.g. deleted) → legacy
    filename fallback still resolves; nothing regresses for legacy points."""
    from outputs.dashboard import _resolve_semantic_doc_hits

    h = _hit("a.pdf", "/a.pdf", score=0.5)
    h.metadata["document_id"] = 555  # not present in pg_rows_by_id
    pg_by_fn = {"a.pdf": [_pg(1, "a.pdf", "/a.pdf")]}
    results, total = _resolve_semantic_doc_hits([h], pg_by_fn, [], [], [], 0, 20, pg_rows_by_id={})
    assert total == 1 and results[0]["id"] == 1, "missing id row → legacy filename fallback"


@pytestmark_helper
def test_search_endpoint_resolves_by_document_id_end_to_end(monkeypatch):
    """Endpoint-level proof of the #1761 fix: the enrichment collects document_id from
    hits, fetches the PG row by id, and returns it even when source_file mismatches."""
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key", raising=False)
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    class _Cur:
        def execute(self, sql, params=None):
            self._is_id = "id = ANY" in sql
        def fetchall(self):
            if self._is_id:
                return [{"id": 42, "filename": "Mandarin.pdf", "document_type": "contract",
                         "matter_slug": "mo-vie", "source_path": "/vault/Mandarin.pdf",
                         "ingested_at": None, "text_preview": "prev"}]
            return []  # filename query → no match (the stale source_file)
        def close(self):
            pass
    class _Conn:
        def cursor(self, cursor_factory=None):
            return _Cur()
        def rollback(self):
            pass
    class _Store:
        def _get_conn(self):
            return _Conn()
        def _put_conn(self, c):
            pass
    monkeypatch.setattr(dash, "_get_store", lambda: _Store())

    h = _hit("legacy.pdf", "/old/legacy.pdf", score=0.7)
    h.metadata["document_id"] = 42
    _stub_retriever(monkeypatch, hits=[h])

    body = TestClient(dash.app).get("/api/documents/search", params={"q": "mandarin"},
                                    headers={"X-Baker-Key": "test-key"}).json()
    assert body["mode"] == "semantic"
    assert body["total"] == 1 and body["results"][0]["id"] == 42
    assert body["enrichment_failed"] is False
