"""
REINGEST_MISSING_QDRANT_ENDPOINT_1 — POST /api/documents/reingest-missing.

Re-embeds the legacy backlog of `documents` rows that have extracted text in
Postgres but no `baker-documents` Qdrant embedding (the keyword-only ~19% that
predates the two-write). Safe-by-default (dry_run=true), bounded + resumable,
embed-only (never re-classify / re-extract), idempotent.

Guards the G0 codex #1772 folds (data-proven on prod):
  Fold 1 [HIGH]: the REPAIR selector must be ROW-LEVEL (filename + file_hash, the
    ingestion_log dedup key), not filename-only — else rows sharing a filename
    with an already-embedded sibling are hidden yet never embedded (76 dup
    filenames cover 165 of 1036 live rows) and the resume loop never converges.
  Fold 2 [HIGH]: empty/blank full_text rows (576 of 1036 live) must be excluded
    from the repair selector — they can never be embedded (ingest_text returns
    "Empty text", writes no ingestion_log) so they'd be re-selected forever and
    STALL the loop. remaining_after counts EMBEDDABLE rows only.
  Fold 3 [MED]: pass documents.file_hash into ingest_text (do not re-hash text),
    keep skip_dedup=False.

Mock store / Qdrant / Voyage — no live calls.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Source-level guards (always run, even on Py3.9 where dashboard won't import) ──


def test_endpoint_is_auth_gated_and_safe_by_default():
    src = Path("outputs/dashboard.py").read_text()
    start = src.index('@app.post("/api/documents/reingest-missing"')
    sig_end = src.index("):", start)
    decl = src[start:sig_end]
    assert "dependencies=[Depends(verify_api_key)]" in decl, "must be auth-gated"
    assert 'tags=["documents"]' in decl
    assert "dry_run: bool = Query(True)" in decl, "must default dry_run=True (safe-by-default)"
    assert "limit: int = Query(50, ge=1, le=500)" in decl


def test_repair_selector_is_row_level_and_embeddable_only():
    """Fold 1 + 2: the REPAIR path keys on (filename + file_hash) AND non-blank text,
    while the reconciliation REPORT keeps its legacy filename-only predicate."""
    src = Path("outputs/dashboard.py").read_text()
    # Two distinct named predicates exist and the row-level one carries file_hash.
    assert "_RECON_MISSING_QDRANT_PREDICATE" in src
    assert "_REINGEST_MISSING_QDRANT_PREDICATE" in src
    reingest_pred = src[src.index("_REINGEST_MISSING_QDRANT_PREDICATE = ("):]
    reingest_pred = reingest_pred[: reingest_pred.index(")\n")]
    assert "il.file_hash = d.file_hash" in reingest_pred, "repair predicate must be row-level"
    assert "il.filename = d.filename" in reingest_pred
    # The repair endpoint's candidate SELECT must use the row-level predicate + the
    # embeddable filter (never the filename-only recon predicate).
    ep = src[src.index("async def documents_reingest_missing("):]
    ep = ep[: ep.index("@app.get(", 1)] if "@app.get(" in ep else ep
    assert "_REINGEST_MISSING_QDRANT_PREDICATE" in ep
    assert "_HAS_EXTRACTED_TEXT" in ep
    assert "_RECON_MISSING_QDRANT_PREDICATE" not in ep, (
        "repair endpoint must NOT select on the filename-only recon predicate"
    )


def test_ingest_call_threads_file_hash_document_id_matter_slug():
    """Fold 3: ingest_text must receive documents.file_hash (not a re-hash), plus
    document_id + matter_slug; skip_dedup must NOT be set True."""
    src = Path("outputs/dashboard.py").read_text()
    ep = src[src.index("async def documents_reingest_missing("):]
    ep = ep[: ep.index("@app.get(", 1)] if "@app.get(" in ep else ep
    assert "file_hash=c.get(\"file_hash\")" in ep, "must thread documents.file_hash"
    assert "document_id=doc_id" in ep
    assert "matter_slug=c.get(\"matter_slug\")" in ep
    assert "skip_dedup=True" not in ep, "must rely on dedup (idempotency) — never skip it"


def test_remaining_after_counts_embeddable_not_total():
    """Fold 2: remaining_after must re-count EMBEDDABLE rows so the loop converges
    even while never-embeddable legacy empties remain."""
    src = Path("outputs/dashboard.py").read_text()
    ep = src[src.index("async def documents_reingest_missing("):]
    # Anchor on the recount CODE (remaining_after = None), not the docstring mention.
    tail = ep[ep.index("remaining_after = None"):]
    block = tail[: tail.index("return {")]
    assert "_REINGEST_MISSING_QDRANT_PREDICATE" in block and "_HAS_EXTRACTED_TEXT" in block


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
    """SQL-routed fake. COUNT(*) routes by predicate markers; the candidate SELECT
    returns the programmed rows. dict_mode mirrors RealDictCursor vs plain cursor."""

    def __init__(self, state, dict_mode):
        self.state = state
        self.dict_mode = dict_mode
        self.last_sql = ""

    def execute(self, sql, params=None):
        self.last_sql = " ".join(sql.split())  # normalise whitespace

    def fetchone(self):
        sql = self.last_sql
        if "COUNT(*)" in sql:
            if "il.file_hash" not in sql:
                val = self.state["total_missing"]
            elif "NOT (d.full_text" in sql:
                val = self.state["skipped_empty_total"]
            elif self.dict_mode:
                val = self.state["embeddable_missing"]
            else:
                # plain cursor COUNT == remaining_after (post-batch)
                val = self.state["remaining_after"]
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

    def rollback(self):
        pass


def _client(monkeypatch, state, ingest_behaviour=None):
    """Returns (TestClient, calls) with auth bypassed and store/ingest_text mocked.

    ingest_behaviour(row) -> IngestResult-like SimpleNamespace, or raises.
    Defaults to a clean embed (skipped=False).
    """
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

    calls = []

    def _default_behaviour(row):
        return SimpleNamespace(skipped=False, skip_reason=None, chunk_count=3,
                               point_ids=["p1", "p2", "p3"])

    behaviour = ingest_behaviour or _default_behaviour

    import tools.ingest.pipeline as pipe

    def _fake_ingest_text(**kwargs):
        calls.append(kwargs)
        return behaviour(kwargs)

    monkeypatch.setattr(pipe, "ingest_text", _fake_ingest_text)

    # verify_api_key bypass: send the configured key.
    client = TestClient(dash.app)
    return client, calls


_HDR = {"X-Baker-Key": "test-key"}


def _row(i, *, text="real extracted text", fhash=None, fname=None, slug="hagenauer-rg7"):
    return {
        "id": i,
        "filename": fname or f"doc-{i}.pdf",
        "source_path": f"vault/doc-{i}.pdf",
        "matter_slug": slug,
        "file_hash": fhash or f"hash{i}",
        "full_text": text,
    }


def test_ac1_dry_run_returns_counts_and_writes_nothing(monkeypatch):
    state = {
        "total_missing": 10,
        "embeddable_missing": 7,
        "skipped_empty_total": 3,
        "candidates": [_row(1), _row(2)],
    }
    client, calls = _client(monkeypatch, state)
    r = client.post("/api/documents/reingest-missing?dry_run=true&limit=50", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["total_missing"] == 10
    assert body["embeddable_missing"] == 7
    assert body["skipped_empty_total"] == 3
    assert len(body["would_process"]) == 2
    assert body["would_process"][0]["text_len"] == len("real extracted text")
    # AC1: nothing written — ingest_text never called in dry_run.
    assert calls == []


def test_ac2_write_embeds_and_threads_keys(monkeypatch):
    state = {
        "total_missing": 3,
        "embeddable_missing": 3,
        "skipped_empty_total": 0,
        "candidates": [_row(1), _row(2), _row(3)],
        "remaining_after": 0,  # all embedded → embeddable remaining hits 0
    }
    client, calls = _client(monkeypatch, state)
    r = client.post("/api/documents/reingest-missing?dry_run=false&limit=50", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["attempted"] == 3
    assert body["embedded"] == 3
    assert body["skipped_dedup"] == 0
    assert body["failed"] == []
    assert body["remaining_after"] == 0
    # Fold 3: each call threaded documents.file_hash + document_id + matter_slug.
    assert len(calls) == 3
    for kw, row in zip(calls, state["candidates"]):
        assert kw["file_hash"] == row["file_hash"]
        assert kw["document_id"] == row["id"]
        assert kw["matter_slug"] == row["matter_slug"]
        assert kw.get("skip_dedup") in (None, False)


def test_ac3_idempotent_second_run_reports_dedup(monkeypatch):
    """AC3: re-running an already-embedded batch reports skipped_dedup, embeds nothing."""
    def _dedup(kw):
        return SimpleNamespace(
            skipped=True,
            skip_reason="Duplicate (same filename + hash already ingested)",
            chunk_count=0, point_ids=[],
        )
    state = {
        "total_missing": 2, "embeddable_missing": 2, "skipped_empty_total": 0,
        "candidates": [_row(1), _row(2)], "remaining_after": 2,
    }
    client, calls = _client(monkeypatch, state, ingest_behaviour=_dedup)
    r = client.post("/api/documents/reingest-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["embedded"] == 0
    assert body["skipped_dedup"] == 2
    assert body["failed"] == []
    assert len(calls) == 2  # idempotency handled by ingest_text dedup, not skip


def test_ac4_one_bad_row_is_caught_and_does_not_abort(monkeypatch):
    """AC4: an embed exception AND a partial_embed are both counted in `failed`
    with a reason, and remaining rows still process."""
    def _mixed(kw):
        if kw["document_id"] == 2:
            raise RuntimeError("voyage exploded")
        if kw["document_id"] == 3:
            return SimpleNamespace(skipped=True, skip_reason="partial_embed",
                                   chunk_count=5, point_ids=["p1"])
        return SimpleNamespace(skipped=False, skip_reason=None, chunk_count=3, point_ids=["a"])
    state = {
        "total_missing": 4, "embeddable_missing": 4, "skipped_empty_total": 0,
        "candidates": [_row(1), _row(2), _row(3), _row(4)], "remaining_after": 2,
    }
    client, calls = _client(monkeypatch, state, ingest_behaviour=_mixed)
    r = client.post("/api/documents/reingest-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["attempted"] == 4
    assert body["embedded"] == 2  # ids 1 and 4
    failed_ids = {f["id"] for f in body["failed"]}
    assert failed_ids == {2, 3}
    reasons = {f["id"]: f["reason"] for f in body["failed"]}
    assert "voyage exploded" in reasons[2]
    assert reasons[3] == "partial_embed"
    assert len(calls) == 4  # all rows attempted despite the bad one


def test_ac5_empty_text_row_skipped_not_embedded(monkeypatch):
    """AC5: a blank-text row that reaches the loop is counted skipped_empty and
    never embedded (defensive guard; the SQL selector already excludes empties)."""
    state = {
        "total_missing": 3, "embeddable_missing": 2, "skipped_empty_total": 1,
        "candidates": [_row(1), _row(2, text="   "), _row(3)], "remaining_after": 0,
    }
    client, calls = _client(monkeypatch, state)
    r = client.post("/api/documents/reingest-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["embedded"] == 2  # ids 1 and 3
    assert body["skipped_empty"] == 1
    assert body["skipped_empty_total"] == 1  # SQL-level empties reported
    embedded_ids = {kw["document_id"] for kw in calls}
    assert 2 not in embedded_ids, "blank-text row must not be embedded"


def test_fold2_loop_converges_despite_legacy_empties(monkeypatch):
    """Fold 2 regression: when only empties remain (embeddable=0), remaining_after
    is 0 so the resume loop terminates — even though total_missing > 0."""
    state = {
        "total_missing": 50,        # legacy filename-level backlog (mostly empties)
        "embeddable_missing": 0,    # nothing left to embed
        "skipped_empty_total": 50,
        "candidates": [],           # selector returns no embeddable rows
        "remaining_after": 0,
    }
    client, calls = _client(monkeypatch, state)
    r = client.post("/api/documents/reingest-missing?dry_run=false", headers=_HDR)
    body = r.json()
    assert body["attempted"] == 0
    assert body["embedded"] == 0
    assert body["remaining_after"] == 0  # loop terminates
    assert body["total_missing"] == 50   # legacy count still surfaced for visibility
    assert calls == []
