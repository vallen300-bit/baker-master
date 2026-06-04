"""
OCR_REEXTRACT_MISSING_1 — POST /api/documents/ocr-extract-missing + Part B fail-loud.

Part A recovers the ~580 blank-`full_text` scanned PDFs/DOCX: download from Dropbox,
read with Gemini 2.5 Pro vision, populate `full_text` via a TARGETED UPDATE (preserves
owner). Safe-by-default (dry_run=true), bounded + resumable, single-runner (direct-conn
advisory lock), offloaded to a worker thread. Does NOT embed — feeds reingest-missing.

Part B (document_pipeline) fails loud on silent empty extraction: the pre-triage
`if not full_text` early return now ERRORs + raises a deduped OCR_CANDIDATE alert.

Guards the codex G0 #1836 folds:
  Fold 1 [HIGH]: write via targeted `UPDATE documents ... WHERE id=%s` (NOT
    store_document_full) so `owner` is preserved (408 of the blank set are owner=dimitry).
  Fold 2 [HIGH]: Part B hooks the `if not full_text` early return (:381-384), NOT the
    triage 'empty' branch — a blank scanned PDF never reaches triage.
  Anti-hallucination: all-[[UNREADABLE]] / short OCR ⇒ NO write, lands in `failed`.

Mock Dropbox / fitz / Gemini / DB — no live calls.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Source-level guards (always run, even on Py3.9 where dashboard won't import) ──


def test_endpoint_is_auth_gated_and_safe_by_default():
    src = Path("outputs/dashboard.py").read_text()
    start = src.index('@app.post("/api/documents/ocr-extract-missing"')
    sig_end = src.index("):", start)
    decl = src[start:sig_end]
    assert "dependencies=[Depends(verify_api_key)]" in decl, "must be auth-gated"
    assert 'tags=["documents"]' in decl
    assert "dry_run: bool = Query(True)" in decl, "must default dry_run=True (safe-by-default)"
    assert "limit: int = Query(3, ge=1, le=25)" in decl, "tiny default limit for heavy vision"


def test_write_is_targeted_update_not_store_document_full():
    """Fold 1: the OCR write must be a targeted UPDATE by id (preserves owner), never
    store_document_full (which overwrites owner + content_hash-dedups to another row)."""
    src = Path("outputs/dashboard.py").read_text()
    batch = src[src.index("def _ocr_extract_batch("):]
    batch = batch[: batch.index("\ndef _ocr_blank_count(")]
    assert "UPDATE documents" in batch and "WHERE id = %s" in batch, "must UPDATE the exact row by id"
    # Must not CALL store_document_full (the call form); a comment referencing it is fine.
    assert "store_document_full(" not in batch, "must NOT call store_document_full (owner overwrite)"
    assert "search_vector = to_tsvector('simple', %s)" in batch, "keep keyword search consistent"
    assert "cur.rowcount" in batch, "must verify the target row was actually updated"


def test_write_path_offloads_and_locks_on_direct_conn():
    """Mirror reingest #293: offload to a thread + session lock on a dedicated DIRECT conn."""
    import re
    src = Path("outputs/dashboard.py").read_text()
    ep = src[src.index("async def documents_ocr_extract_missing("):]
    ep = ep[: ep.index('@app.get("/health"')]
    assert "asyncio.to_thread(_ocr_extract_batch" in ep, "offload the blocking loop"
    assert "pg_try_advisory_lock" in ep and "pg_advisory_unlock" in ep
    assert "direct_dsn_params" in ep, "direct (non-pooled) endpoint"
    assert "host_direct" in ep, "fail-loud guard when host_direct unset"
    assert "store._put_conn(lock_conn)" not in ep, "lock conn is dedicated — never returned to pool"
    assert "lock_conn.autocommit = True" in ep, "no idle-in-transaction lock drop (codex #1815)"
    # Distinct lock key from reingest (REIN) so the two backfills don't block each other.
    assert "_OCR_ADVISORY_LOCK_KEY = 0x4F435231" in src


def test_does_not_embed_in_ocr_path():
    """OCR populates full_text only; embedding stays the reingest endpoint's job."""
    src = Path("outputs/dashboard.py").read_text()
    batch = src[src.index("def _ocr_extract_batch("):]
    batch = batch[: batch.index("\ndef _ocr_blank_count(")]
    assert "ingest_text" not in batch, "OCR batch must NOT embed (feeds reingest-missing)"


def test_part_b_hooks_early_return_not_triage_branch():
    """Fold 2: the fail-loud OCR_CANDIDATE signal lives in the `if not full_text` early
    return of run_pipeline, before triage — not in the triage 'empty' branch."""
    src = Path("tools/document_pipeline.py").read_text()
    rp = src[src.index("def run_pipeline("):]
    rp = rp[: rp.index("\ndef ", 1)]
    early = rp[: rp.index("triage_document")]  # everything before triage = the early return
    assert "OCR_CANDIDATE" in early, "fail-loud marker must be in the pre-triage early return"
    assert 'source="doc_ocr_candidate"' in early, "alert source per codex #1843 relay"
    assert "source_id=str(doc_id)" in early, "dedup by doc id (not title-only)"
    assert "logger.error" in early, "must ERROR (not just warning) for a genuine OCR candidate"


# ─── Live handler tests (py3.10+ where dashboard imports) ─────────────────────


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard not importable on this interpreter (needs py3.10+ syntax)",
)


class _FakeCursor:
    """SQL-routed fake. COUNT(*) → blank_count (or remaining_after post-batch); the
    candidate SELECT returns programmed rows; UPDATE records the (id, full_text) write."""

    def __init__(self, state, dict_mode):
        self.state = state
        self.dict_mode = dict_mode
        self.last_sql = ""
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.last_sql = " ".join(sql.split())
        if self.last_sql.startswith("UPDATE documents"):
            # params = (legible, token_count, legible_for_tsv, doc_id)
            doc_id = params[-1]
            self.state.setdefault("writes", []).append({"id": doc_id, "full_text": params[0]})
            # rowcount mirrors whether the row exists (default 1).
            self.rowcount = self.state.get("update_rowcount", 1)

    def fetchone(self):
        sql = self.last_sql
        if "COUNT(*)" in sql:
            # First COUNT in the request = blank_count; the post-batch COUNT (plain
            # cursor) = remaining_after.
            if self.dict_mode:
                val = self.state["blank_count"]
            else:
                val = self.state.get("remaining_after", 0)
            return {"c": val} if self.dict_mode else (val,)
        return None

    def fetchall(self):
        return [dict(r) for r in self.state["candidates"]]

    def close(self):
        pass


class _FakeConn:
    def __init__(self, state):
        self.state = state

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self.state, dict_mode=cursor_factory is not None)

    def commit(self):
        pass

    def rollback(self):
        pass


class _LockCur:
    def __init__(self, granted):
        self._granted = granted
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql

    def fetchone(self):
        if "pg_try_advisory_lock" in self._sql:
            return (self._granted,)
        return (None,)

    def close(self):
        pass


class _LockConn:
    def __init__(self, granted):
        self._granted = granted
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return _LockCur(self._granted)

    def close(self):
        self.closed = True


class _FakePixmap:
    def tobytes(self, fmt):
        return b"\xff\xd8\xff\xe0fake-jpeg"  # bytes; content irrelevant (Gemini mocked)


class _FakePage:
    def get_pixmap(self, dpi=200):
        return _FakePixmap()


class _FakePdf:
    """Stand-in for fitz.open() result."""

    def __init__(self, n_pages):
        self.page_count = n_pages
        self.closed = False

    def load_page(self, pno):
        return _FakePage()

    def close(self):
        self.closed = True


def _install_fitz(monkeypatch, n_pages=1, open_raises=False):
    import sys
    import types as _t

    def _open(path):
        if open_raises:
            raise RuntimeError("not a pdf")
        return _FakePdf(n_pages)

    fake_fitz = _t.ModuleType("fitz")
    fake_fitz.open = _open
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)


def _client(monkeypatch, state, *, gemini_text="recovered page text that is plenty long",
            gemini_raises=False, lock_granted=True, n_pages=1, fitz_open_raises=False,
            download_raises=False, docx_text=None):
    """TestClient with auth bypassed; store + Dropbox + fitz + Gemini mocked."""
    from fastapi.testclient import TestClient
    import importlib
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import outputs.dashboard as dash
    importlib.reload(dash)

    state.setdefault("remaining_after", 0)
    conn = _FakeConn(state)

    class _StubStore:
        def _get_conn(self):
            return conn

        def _put_conn(self, c):
            return None

    monkeypatch.setattr(dash, "_get_store", lambda: _StubStore())
    # gemini enabled + direct-conn lock mocks.
    monkeypatch.setattr("config.settings.config.gemini.enabled", True, raising=False)
    monkeypatch.setattr("config.settings.config.postgres.host_direct", "direct.test", raising=False)
    monkeypatch.setattr("psycopg2.connect", lambda **kw: _LockConn(lock_granted))

    # Dropbox download → a temp file (content irrelevant; fitz/docx mocked).
    calls = {"gemini": 0, "downloads": []}

    class _StubDropbox:
        @classmethod
        def _get_global_instance(cls):
            return cls()

        def download_file(self, source_path, dest_dir):
            if download_raises:
                raise RuntimeError("dropbox 409")
            calls["downloads"].append(source_path)
            p = Path(dest_dir) / Path(source_path).name
            p.write_bytes(b"fake")
            return p

    monkeypatch.setattr("triggers.dropbox_client.DropboxClient", _StubDropbox)

    _install_fitz(monkeypatch, n_pages=n_pages, open_raises=fitz_open_raises)

    def _fake_call_pro(messages, max_tokens=2000, system=None):
        calls["gemini"] += 1
        if gemini_raises:
            raise RuntimeError("gemini 503")
        return SimpleNamespace(text=gemini_text)

    monkeypatch.setattr("orchestrator.gemini_client.call_pro", _fake_call_pro)

    if docx_text is not None:
        monkeypatch.setattr("tools.ingest.extractors.extract", lambda p: docx_text)

    client = TestClient(dash.app)
    return client, calls


_HDR = {"X-Baker-Key": "test-key"}


def _row(i, *, fname=None, src=None):
    return {
        "id": i,
        "filename": fname or f"scan-{i}.pdf",
        "source_path": src or f"/Baker-Feed/scan-{i}.pdf",
        "file_hash": f"hash{i}",
        "matter_slug": "hagenauer-rg7",
    }


def test_ac1_dry_run_lists_and_writes_nothing(monkeypatch):
    state = {"blank_count": 12, "candidates": [_row(1), _row(2)]}
    client, calls = _client(monkeypatch, state)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=true&limit=3", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["blank_count"] == 12
    assert len(body["would_process"]) == 2
    assert body["would_process"][0]["source_path"] == "/Baker-Feed/scan-1.pdf"
    # AC1: dry_run downloads nothing, calls no model, writes nothing.
    assert calls["downloads"] == []
    assert calls["gemini"] == 0
    assert state.get("writes") is None


def test_ac2_write_recovers_and_targets_row_by_id(monkeypatch):
    """Happy path: a legible scan is OCR'd and written via targeted UPDATE on its own id."""
    state = {"blank_count": 2, "candidates": [_row(1), _row(2)], "remaining_after": 0}
    client, calls = _client(monkeypatch, state, n_pages=2)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false&limit=3", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["attempted"] == 2
    assert body["recovered"] == 2
    assert body["failed"] == []
    assert body["remaining_after"] == 0
    # Each doc updated its OWN id with non-empty full_text; 2 pages → gemini called 4x.
    writes = {w["id"]: w["full_text"] for w in state["writes"]}
    assert set(writes) == {1, 2}
    assert all(len(t) >= 20 for t in writes.values())
    assert calls["gemini"] == 4


def test_ac3_all_unreadable_writes_nothing_and_fails(monkeypatch):
    """Anti-hallucination: every page [[UNREADABLE]] ⇒ NO write, doc lands in failed."""
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 1}
    client, calls = _client(monkeypatch, state, gemini_text="[[UNREADABLE]]")
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["recovered"] == 0
    assert state.get("writes") is None, "unreadable doc must NOT be written"
    assert body["failed"] and body["failed"][0]["id"] == 1
    assert body["failed"][0]["reason"] == "unreadable"


def test_short_ocr_below_min_chars_fails(monkeypatch):
    """A legible-but-tiny transcription (< _OCR_MIN_CHARS) is treated as empty_ocr, no write."""
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 1}
    client, calls = _client(monkeypatch, state, gemini_text="ok")  # 2 chars < 20
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["recovered"] == 0
    assert state.get("writes") is None
    assert body["failed"][0]["reason"] == "empty_ocr"


def test_one_doc_failure_does_not_abort_batch(monkeypatch):
    """A download failure on one doc must not stop the others from processing."""
    # Make doc 1 fail download by raising only for it: simplest is a per-call toggle.
    from fastapi.testclient import TestClient
    import importlib
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import outputs.dashboard as dash
    importlib.reload(dash)

    state = {"blank_count": 2, "candidates": [_row(1), _row(2)], "remaining_after": 1}
    conn = _FakeConn(state)

    class _StubStore:
        def _get_conn(self):
            return conn

        def _put_conn(self, c):
            return None

    monkeypatch.setattr(dash, "_get_store", lambda: _StubStore())
    monkeypatch.setattr("config.settings.config.gemini.enabled", True, raising=False)
    monkeypatch.setattr("config.settings.config.postgres.host_direct", "direct.test", raising=False)
    monkeypatch.setattr("psycopg2.connect", lambda **kw: _LockConn(True))

    class _StubDropbox:
        @classmethod
        def _get_global_instance(cls):
            return cls()

        def download_file(self, source_path, dest_dir):
            if "scan-1" in source_path:
                raise RuntimeError("dropbox 409 for doc 1")
            p = Path(dest_dir) / Path(source_path).name
            p.write_bytes(b"fake")
            return p

    monkeypatch.setattr("triggers.dropbox_client.DropboxClient", _StubDropbox)
    _install_fitz(monkeypatch, n_pages=1)
    monkeypatch.setattr("orchestrator.gemini_client.call_pro",
                        lambda messages, max_tokens=2000, system=None: SimpleNamespace(
                            text="a perfectly legible recovered transcription"))

    client = TestClient(dash.app)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["attempted"] == 2
    assert body["recovered"] == 1, "doc 2 still recovered despite doc 1 download failure"
    failed_ids = {f["id"]: f["reason"] for f in body["failed"]}
    assert failed_ids == {1: "download_failed"}
    assert [w["id"] for w in state["writes"]] == [2]


def test_lock_held_returns_backfill_in_progress(monkeypatch):
    """A held advisory lock ⇒ second writer gets backfill_in_progress; nothing processed."""
    state = {"blank_count": 3, "candidates": [_row(1), _row(2), _row(3)], "remaining_after": 3}
    client, calls = _client(monkeypatch, state, lock_granted=False)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false&limit=3", headers=_HDR)
    assert r.status_code == 200
    assert r.json().get("error") == "backfill_in_progress"
    assert calls["downloads"] == [] and calls["gemini"] == 0
    assert state.get("writes") is None


def test_gemini_disabled_fails_loud(monkeypatch):
    """config.gemini.enabled == False ⇒ explicit gemini_disabled error, not a silent skip."""
    from fastapi.testclient import TestClient
    import importlib
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import outputs.dashboard as dash
    importlib.reload(dash)
    monkeypatch.setattr("config.settings.config.gemini.enabled", False, raising=False)
    client = TestClient(dash.app)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=true", headers=_HDR)
    assert r.json().get("error") == "gemini_disabled"


def test_docx_path_uses_text_extract_not_vision(monkeypatch):
    """The 4 DOCX in the set extract text directly (not image OCR) — no Gemini call."""
    state = {"blank_count": 1, "candidates": [_row(1, fname="memo.docx", src="/Baker-Project/memo.docx")],
             "remaining_after": 0}
    client, calls = _client(monkeypatch, state,
                            docx_text="A fully legible docx body recovered via extract().")
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["recovered"] == 1
    assert calls["gemini"] == 0, "DOCX must not call Gemini vision"
    assert [w["id"] for w in state["writes"]] == [1]


def test_select_error_returns_conn_to_pool_exactly_once(monkeypatch):
    """On a select/count error the conn is returned to the pool exactly once (the finally)."""
    from fastapi.testclient import TestClient
    import importlib
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import outputs.dashboard as dash
    importlib.reload(dash)
    monkeypatch.setattr("config.settings.config.gemini.enabled", True, raising=False)

    class _ErrConn:
        def cursor(self, cursor_factory=None):
            return self

        def execute(self, sql, params=None):
            raise RuntimeError("select boom")

        def rollback(self):
            pass

    err_conn = _ErrConn()
    put_calls = []

    class _CountingStore:
        def _get_conn(self):
            return err_conn

        def _put_conn(self, c):
            put_calls.append(c)

    monkeypatch.setattr(dash, "_get_store", lambda: _CountingStore())
    client = TestClient(dash.app)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["error"] == "select_failed"
    assert "select boom" in body["reason"]
    assert put_calls == [err_conn], "conn returned to the pool exactly once"


# ─── Part B: fail-loud on silent empty extraction (document_pipeline) ──────────


def _pipeline_importable() -> bool:
    try:
        import tools.document_pipeline  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pipeline_importable(), reason="document_pipeline not importable")
def test_part_b_empty_pdf_raises_ocr_candidate_alert(monkeypatch, caplog):
    """run_pipeline with empty full_text for a PDF ⇒ ERROR(OCR_CANDIDATE) + one deduped alert."""
    import logging
    import tools.document_pipeline as dp

    monkeypatch.setattr(dp, "_get_document_text", lambda doc_id: "")
    monkeypatch.setattr(dp, "_get_document_meta",
                        lambda doc_id: ("scan-9.pdf", "/Baker-Feed/scan-9.pdf"))

    created = []

    class _AlertStore:
        def create_alert(self, **kw):
            created.append(kw)
            return 1

    monkeypatch.setattr(dp, "_get_store", lambda: _AlertStore())

    with caplog.at_level(logging.ERROR, logger="baker.document_pipeline"):
        dp.run_pipeline(9)

    assert any("OCR_CANDIDATE" in rec.message for rec in caplog.records), "must ERROR with OCR_CANDIDATE"
    assert len(created) == 1, "exactly one alert per empty OCR candidate"
    assert created[0]["source"] == "doc_ocr_candidate"
    assert created[0]["source_id"] == "9", "dedup by doc id (codex #1843 relay)"


@pytest.mark.skipif(not _pipeline_importable(), reason="document_pipeline not importable")
def test_part_b_non_pdf_empty_does_not_alert(monkeypatch, caplog):
    """An empty non-PDF/DOCX (no Dropbox source) is NOT an OCR candidate — no alert, warning only."""
    import logging
    import tools.document_pipeline as dp

    monkeypatch.setattr(dp, "_get_document_text", lambda doc_id: "")
    monkeypatch.setattr(dp, "_get_document_meta", lambda doc_id: ("note.txt", ""))

    created = []

    class _AlertStore:
        def create_alert(self, **kw):
            created.append(kw)
            return 1

    monkeypatch.setattr(dp, "_get_store", lambda: _AlertStore())

    with caplog.at_level(logging.WARNING, logger="baker.document_pipeline"):
        dp.run_pipeline(7)

    assert created == [], "non-OCR-candidate must not raise an alert"
    assert not any("OCR_CANDIDATE" in rec.message for rec in caplog.records)


@pytest.mark.skipif(not _pipeline_importable(), reason="document_pipeline not importable")
def test_part_b_non_empty_doc_unaffected(monkeypatch):
    """A normal non-empty doc must flow past the early return untouched (no alert)."""
    import tools.document_pipeline as dp

    monkeypatch.setattr(dp, "_get_document_text", lambda doc_id: "real extracted body text")
    monkeypatch.setattr(dp, "_get_document_meta", lambda doc_id: ("deal.pdf", "/Baker-Feed/deal.pdf"))
    monkeypatch.setattr(dp, "_set_content_class", lambda doc_id, cc: None)
    # Triage as a non-document so the pipeline returns early AFTER the empty check —
    # proves the empty-branch alert path was NOT taken for a non-empty doc.
    monkeypatch.setattr(dp, "triage_document", lambda fn, txt, sp: "image")

    created = []

    class _AlertStore:
        def create_alert(self, **kw):
            created.append(kw)
            return 1

    monkeypatch.setattr(dp, "_get_store", lambda: _AlertStore())
    dp.run_pipeline(5)
    assert created == [], "non-empty doc must not trigger the OCR_CANDIDATE alert"
