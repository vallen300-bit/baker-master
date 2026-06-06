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
        if self.last_sql.startswith("UPDATE documents SET ocr_status"):
            # OCR_UNREADABLE_MARKER_1 terminal marker: params = (doc_id,). Routed to
            # a SEPARATE bucket so `writes` stays recovery-only (full_text) — proves
            # the marker never touches full_text (AC3 no search pollution).
            self.state.setdefault("ocr_marks", []).append(params[0])
            self.rowcount = self.state.get("mark_rowcount", 1)
        elif self.last_sql.startswith("UPDATE documents"):
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
    assert len(body["recovered"]) == 2
    assert {rec["id"] for rec in body["recovered"]} == {1, 2}
    assert all(rec["truncated"] is False for rec in body["recovered"]), "normal docs: not truncated"
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
    assert body["recovered"] == []
    assert state.get("writes") is None, "unreadable doc must NOT be written"
    assert body["failed"] and body["failed"][0]["id"] == 1
    assert body["failed"][0]["reason"] == "unreadable"


def test_short_ocr_below_min_chars_fails(monkeypatch):
    """A legible-but-tiny transcription (< _OCR_MIN_CHARS) is treated as empty_ocr, no write."""
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 1}
    client, calls = _client(monkeypatch, state, gemini_text="ok")  # 2 chars < 20
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["recovered"] == []
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
    assert len(body["recovered"]) == 1, "doc 2 still recovered despite doc 1 download failure"
    assert body["recovered"][0]["id"] == 2
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
    assert len(body["recovered"]) == 1
    assert body["recovered"][0]["truncated"] is False, "DOCX path is never page-truncated"
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


# ─── codex G3 #1865 folds: cost governor (HIGH) + truncation signal (MED) ──────


def test_truncated_flag_surfaces_past_max_pages(monkeypatch):
    """FINDING 2 (MED): a PDF with > _OCR_MAX_PAGES still recovers (first cap pages) but
    its recovered entry carries truncated=true — partial recovery is never silent."""
    import outputs.dashboard as _d
    cap = _d._OCR_MAX_PAGES
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 0}
    client, calls = _client(monkeypatch, state, n_pages=cap + 1)
    # Keep the governor cheap + deterministic for the cap-page loop.
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (True, 0.0))
    monkeypatch.setattr("orchestrator.cost_monitor.log_api_cost", lambda *a, **k: None)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert len(body["recovered"]) == 1
    rec = body["recovered"][0]
    assert rec["id"] == 1
    assert rec["truncated"] is True, "partial recovery past the page cap must be flagged"
    assert calls["gemini"] == cap, "only the first _OCR_MAX_PAGES pages are OCR'd"
    assert [w["id"] for w in state["writes"]] == [1], "partial-but-legible text still written (beats blank)"


def test_cost_breaker_tripped_writes_nothing(monkeypatch):
    """FINDING 1 (HIGH): a tripped circuit breaker ⇒ NO call_pro for the throttled doc,
    it lands in failed(reason=cost_breaker), and NOTHING is written (never a partial)."""
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 1}
    client, calls = _client(monkeypatch, state, n_pages=3)
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (False, 999.0))
    logged = []
    monkeypatch.setattr("orchestrator.cost_monitor.log_api_cost", lambda *a, **k: logged.append(a))
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["recovered"] == []
    assert calls["gemini"] == 0, "breaker trips before the first page call"
    assert logged == [], "no cost logged when nothing was called"
    assert state.get("writes") is None, "tripped breaker writes nothing (never partial)"
    assert body["failed"][0]["id"] == 1 and body["failed"][0]["reason"] == "cost_breaker"


def test_cost_logged_on_allowed_path(monkeypatch):
    """FINDING 1 (HIGH): breaker allows ⇒ each page call_pro happens AND a cost row is
    logged per page with model gemini-2.5-pro + source/capability tags."""
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 0}
    client, calls = _client(monkeypatch, state, n_pages=2)
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (True, 1.0))
    logged = []
    monkeypatch.setattr(
        "orchestrator.cost_monitor.log_api_cost",
        lambda model, *a, **k: logged.append((model, k.get("source"), k.get("capability_id"))),
    )
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert len(body["recovered"]) == 1
    assert calls["gemini"] == 2
    assert len(logged) == 2, "one cost row per page call"
    assert logged[0] == ("gemini-2.5-pro", "document_pipeline", "ocr_extract")


def test_cost_instrumentation_failure_is_fail_open(monkeypatch):
    """FINDING 1 (HIGH): an instrumentation error (breaker raises) must NOT abort
    recovery — OCR fails open and the doc still recovers."""
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 0}
    client, calls = _client(monkeypatch, state, n_pages=2)

    def _boom():
        raise RuntimeError("cost_monitor exploded")

    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", _boom)
    monkeypatch.setattr("orchestrator.cost_monitor.log_api_cost", lambda *a, **k: None)
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert len(body["recovered"]) == 1, "breaker failure must fail-open (OCR still runs)"
    assert calls["gemini"] == 2


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


# ─── OCR_UNREADABLE_MARKER_1: terminal marker for un-OCR-able docs ─────────────


def test_marker_ac1_unreadable_doc_marked_terminal_full_text_untouched(monkeypatch):
    """AC1 + AC3: a doc that returns all-pages [[UNREADABLE]] is marked terminal via
    ocr_status='unreadable' — and full_text is NEVER written (no search pollution), so a
    second drain (which excludes the marked set) won't re-send it to Gemini."""
    state = {"blank_count": 1, "candidates": [_row(1)], "remaining_after": 1}
    client, calls = _client(monkeypatch, state, gemini_text="[[UNREADABLE]]")
    r = client.post("/api/documents/ocr-extract-missing?dry_run=false", headers=_HDR)
    body = r.json()
    # Lands in failed(unreadable) exactly as before...
    assert body["failed"] and body["failed"][0]["id"] == 1
    assert body["failed"][0]["reason"] == "unreadable"
    assert body["recovered"] == []
    # ...AND is now marked terminal (the new behaviour)...
    assert state.get("ocr_marks") == [1], "unreadable doc must be marked ocr_status='unreadable'"
    # ...with full_text left untouched (AC3 — marker lives only in ocr_status).
    assert state.get("writes") is None, "marker must NOT write full_text (no search pollution)"


def test_marker_ac2_candidate_query_and_count_exclude_marked_set(monkeypatch):
    """AC2: BOTH blank-set consumers — the candidate SELECT and _ocr_blank_count (which
    feeds blank_count + the remaining_after convergence signal) — drop the terminal set on
    a normal drain, and the exclusion is gated so the force path can restore it."""
    src = Path("outputs/dashboard.py").read_text()
    # The shared exclusion fragment exists and targets ocr_status terminal state.
    assert "_OCR_UNREADABLE_EXCLUDE" in src
    assert "ocr_status IS DISTINCT FROM 'unreadable'" in src, \
        "IS DISTINCT FROM keeps NULL (unmarked) rows eligible"

    # _ocr_blank_count applies it, gated by include_unreadable (default excludes).
    bc = src[src.index("def _ocr_blank_count("):]
    bc = bc[: bc.index("\n\n", bc.index("return"))]
    assert "include_unreadable: bool = False" in bc, "count defaults to excluding the dead set"
    assert "_OCR_UNREADABLE_EXCLUDE" in bc and "if include_unreadable else" in bc

    # The endpoint: candidate SELECT applies the same gated exclusion, and
    # remaining_after re-counts with the SAME flag so convergence is real (stops at 0).
    ep = src[src.index("async def documents_ocr_extract_missing("):]
    ep = ep[: ep.index('@app.get("/health"')]
    sel = ep[ep.index('"SELECT d.id, d.filename'): ep.index("ORDER BY d.ingested_at")]
    assert "_OCR_UNREADABLE_EXCLUDE" in sel and "if include_unreadable else" in sel, \
        "candidate SELECT must drop the marked set unless forced"
    assert "_ocr_blank_count(cur2, include_unreadable=include_unreadable)" in ep, \
        "remaining_after must use the same exclusion as the candidate query"


def test_marker_ac4_force_include_unreadable_reattempts_marked_set(monkeypatch):
    """AC4: ?include_unreadable=true re-includes the terminal set (force re-OCR path) and
    the response echoes the flag so the caller can confirm which mode ran."""
    state = {"blank_count": 5, "candidates": [_row(1), _row(2)]}
    client, calls = _client(monkeypatch, state)
    # dry_run echoes the flag and still lists candidates (the force path processes them).
    r = client.post(
        "/api/documents/ocr-extract-missing?dry_run=true&include_unreadable=true", headers=_HDR)
    body = r.json()
    assert body["include_unreadable"] is True, "force flag must surface in the response"
    assert len(body["would_process"]) == 2, "force path re-includes the marked candidates"
    # Default (no flag) drain reports include_unreadable=false — the idempotent mode.
    r2 = client.post("/api/documents/ocr-extract-missing?dry_run=true", headers=_HDR)
    assert r2.json()["include_unreadable"] is False
