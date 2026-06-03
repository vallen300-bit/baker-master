"""
INGEST_SEARCH_DURABILITY_FOLLOWUPS_1 — A2: do NOT seal a partially-embedded doc.

ROOT CAUSE this guards against:
    `_embed_and_upsert` swallowed a per-batch embed failure (`logger.error; continue`)
    and returned partial point_ids. `ingest_text`/`ingest_file` then UNCONDITIONALLY
    called `log_ingestion(chunk_count=len(chunks))`, so a large doc whose batch N
    failed got logged as fully ingested → `is_duplicate` returns True on re-run →
    the missing chunks are NEVER retried → permanent half-index.

FIX under test:
    `_embed_and_upsert` returns (point_ids, failed_batches). If failed_batches is
    non-empty, the callers MUST NOT call log_ingestion and MUST return an
    IngestResult with skipped=True / skip_reason="partial_embed" — leaving the
    (filename, file_hash) absent from ingestion_log so a re-run retries the whole
    doc (deterministic point IDs → successful chunks re-upsert idempotently).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class _RateLimitError(Exception):
    """Type name contains 'RateLimit' so the retry loop treats it as rate-limited."""


def _patch_offline(monkeypatch, *, embed_raises_always=False):
    """Stub Voyage + Qdrant so pipeline runs offline; record log_ingestion calls."""
    import tools.ingest.pipeline as pipe

    class _FakeVoyage:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts, model=None, input_type=None):
            if embed_raises_always:
                raise _RateLimitError("rate limited")
            return SimpleNamespace(embeddings=[[0.1] * 8 for _ in texts])

    class _FakeQdrant:
        def __init__(self, *a, **k):
            self.upserts = []

        def upsert(self, collection_name=None, points=None):
            self.upserts.append((collection_name, points))

    logged = []
    monkeypatch.setattr(pipe, "voyageai", SimpleNamespace(Client=_FakeVoyage))
    monkeypatch.setattr(pipe, "QdrantClient", _FakeQdrant)
    monkeypatch.setattr(pipe, "ensure_collection", lambda *a, **k: None)
    monkeypatch.setattr(pipe, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(pipe, "log_ingestion", lambda *a, **k: logged.append((a, k)))
    monkeypatch.setenv("INGEST_EMBED_DELAY", "0")  # no 25s inter-batch sleep
    monkeypatch.setenv("INGEST_EMBED_BATCH", "1")  # one chunk per batch → isolate failures
    return logged


# ─── Low-level: _embed_and_upsert signals partial failure ──────────────────────


def test_embed_and_upsert_returns_tuple_with_failed_batches():
    """Signature contract: returns (point_ids, failed_batches), both lists."""
    import inspect
    import tools.ingest.pipeline as pipe

    sig = inspect.signature(pipe._embed_and_upsert)
    assert "tuple" in str(sig.return_annotation).lower()


def test_embed_and_upsert_flags_persistent_embed_failure(monkeypatch):
    """A batch that never embeds (rate-limited through all retries) lands in
    failed_batches rather than being silently dropped."""
    _patch_offline(monkeypatch, embed_raises_always=True)
    import tools.ingest.pipeline as pipe

    point_ids, failed_batches = pipe._embed_and_upsert(
        ["only chunk"], "baker-documents", "f.txt", "src/f.txt"
    )
    assert point_ids == []
    assert failed_batches == [1]


def test_embed_and_upsert_full_success_no_failed_batches(monkeypatch):
    _patch_offline(monkeypatch)
    import tools.ingest.pipeline as pipe

    point_ids, failed_batches = pipe._embed_and_upsert(
        ["chunk one", "chunk two"], "baker-documents", "f.txt", "src/f.txt"
    )
    assert len(point_ids) == 2
    assert failed_batches == []


# ─── ingest_text: no seal on partial, seal on full success ─────────────────────


def test_ingest_text_partial_does_not_seal(monkeypatch):
    logged = _patch_offline(monkeypatch)
    import tools.ingest.pipeline as pipe

    # Force a partial result regardless of embed internals.
    monkeypatch.setattr(pipe, "_embed_and_upsert", lambda *a, **k: (["p1"], [2]))

    result = pipe.ingest_text(
        full_text="some real text body here", filename="big.pdf",
        source_path="email:abc/big.pdf",
    )

    assert result.skipped is True
    assert result.skip_reason == "partial_embed"
    assert logged == [], "log_ingestion MUST NOT run on a partial embed (doc stays retryable)"


def test_ingest_text_full_success_seals(monkeypatch):
    logged = _patch_offline(monkeypatch)
    import tools.ingest.pipeline as pipe

    monkeypatch.setattr(pipe, "_embed_and_upsert", lambda *a, **k: (["p1", "p2"], []))

    result = pipe.ingest_text(
        full_text="some real text body here", filename="ok.pdf",
        source_path="email:abc/ok.pdf",
    )

    assert result.skipped is False
    assert result.skip_reason is None
    assert len(logged) == 1, "full success must seal via log_ingestion exactly once"


# ─── ingest_file: same no-seal-on-partial contract ─────────────────────────────


def test_ingest_file_partial_does_not_seal(monkeypatch, tmp_path):
    logged = _patch_offline(monkeypatch)
    import tools.ingest.pipeline as pipe

    monkeypatch.setattr(pipe, "_embed_and_upsert", lambda *a, **k: (["p1"], [3]))

    doc = tmp_path / "report.md"
    doc.write_text("# Report\n\nbody content for the partial-embed test\n")

    result = pipe.ingest_file(filepath=doc, collection="baker-documents", skip_llm=True)

    assert result.skipped is True
    assert result.skip_reason == "partial_embed"
    assert logged == [], "log_ingestion MUST NOT run on a partial embed (doc stays retryable)"


def test_ingest_file_full_success_seals(monkeypatch, tmp_path):
    logged = _patch_offline(monkeypatch)
    import tools.ingest.pipeline as pipe

    monkeypatch.setattr(pipe, "_embed_and_upsert", lambda *a, **k: (["p1", "p2"], []))

    doc = tmp_path / "report.md"
    doc.write_text("# Report\n\nbody content for the full-success test\n")

    result = pipe.ingest_file(filepath=doc, collection="baker-documents", skip_llm=True)

    assert result.skipped is False
    assert len(logged) == 1, "full success must seal via log_ingestion exactly once"
