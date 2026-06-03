"""
ATTACHMENT_TWO_WRITE_PARITY_1 — attachments must reach BOTH stores.

THE RULE this guards (Lesson #8 / #86 — green-but-broken):
    Content is fully covered only if it reaches BOTH
      - Postgres `documents`      (Documents UI + GET /api/documents/search)
      - Qdrant `baker-documents`  (chat / Cortex semantic RAG)
    Email live attachments already became first-class `documents` rows
    (SPECIALIST-UPGRADE-1B) but were NEVER embedded into Qdrant — invisible to
    semantic RAG. WhatsApp media text was inline-only. This change adds the
    missing Qdrant half via a shared two-write helper + a reusable text→Qdrant
    path (ingest_text) that does NOT re-extract from a filepath (the temp file is
    already deleted post-extraction — calling ingest_file there is a contract bug).

These tests assert (1) ingest_text embeds already-extracted text with a DURABLE
source_path, (2) the promote helper drives both halves and is non-fatal, (3) the
live sites use the helper, and (4) parent inline email/WA text is untouched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Source-level checks (always run, even on Py3.9) ──────────────────────────


def test_gmail_live_path_uses_promote_helper():
    """Email live attachments must promote via the two-write helper (adds Qdrant),
    not the old store_document_full-only block."""
    src = Path("scripts/extract_gmail.py").read_text()
    assert "promote_attachment_text_to_document_and_qdrant(" in src, (
        "extract_gmail must route live attachments through the two-write helper "
        "so they reach Qdrant baker-documents, not just the documents table"
    )
    assert "source_path=f\"email:{message_id}/{att['filename']}\"" in src


def test_waha_media_uses_promote_helper_with_durable_source_path():
    """WA media must promote via the helper using a DURABLE source_path (Dropbox
    path or whatsapp:<id>/ fallback) — never the deleted local temp filepath."""
    src = Path("triggers/waha_webhook.py").read_text()
    assert "promote_attachment_text_to_document_and_qdrant(" in src
    assert "media_dropbox_path" in src
    assert 'f"whatsapp:{msg_id}/' in src, "needs the deterministic durable fallback path"
    # Regression guard: the parent inline two-write must remain.
    assert "store_whatsapp_message(" in src
    assert "combined_body" in src


def test_backfill_email_attachments_adds_qdrant_half():
    """The email-attachment backfill must embed into Qdrant (ingest_text), not
    only write the documents row."""
    src = Path("scripts/backfill_email_attachments.py").read_text()
    assert "ingest_text(" in src
    assert "store_document_full(" in src  # Postgres half preserved


def test_no_ingest_file_at_text_only_sites():
    """The foot-gun: ingest_file re-extracts from a filepath. It must NOT be called
    at the already-extracted-text attachment sites."""
    for path in ("tools/ingest/attachments.py",
                 "triggers/waha_webhook.py",
                 "scripts/extract_gmail.py"):
        src = Path(path).read_text()
        assert "ingest_file(" not in src, f"{path} must not call ingest_file (re-extracts)"


# ─── ingest_text unit tests (Voyage + Qdrant mocked; no network/DB) ───────────


_SENTINEL = "PARITY_SENTINEL_TOKEN_b3a91c"


def _patch_pipeline(monkeypatch):
    """Stub Voyage + Qdrant so ingest_text runs offline; capture upserts."""
    import tools.ingest.pipeline as pipe

    class _FakeVoyage:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts, model=None, input_type=None):
            return SimpleNamespace(embeddings=[[0.1] * 8 for _ in texts])

    class _FakeQdrant:
        instances = []

        def __init__(self, *a, **k):
            self.upserts = []
            _FakeQdrant.instances.append(self)

        def upsert(self, collection_name=None, points=None):
            self.upserts.append((collection_name, points))

    _FakeQdrant.instances = []
    monkeypatch.setattr(pipe, "voyageai", SimpleNamespace(Client=_FakeVoyage))
    monkeypatch.setattr(pipe, "QdrantClient", _FakeQdrant)
    monkeypatch.setattr(pipe, "ensure_collection", lambda *a, **k: None)
    monkeypatch.setattr(pipe, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(pipe, "log_ingestion", lambda *a, **k: None)
    monkeypatch.setenv("INGEST_EMBED_DELAY", "0")
    monkeypatch.setenv("INGEST_EMBED_BATCH", "50")
    return _FakeQdrant


def test_ingest_text_embeds_already_extracted_text(monkeypatch):
    """ingest_text chunks+embeds text WITHOUT a filepath and returns chunks+ids."""
    fake_qdrant = _patch_pipeline(monkeypatch)
    from tools.ingest.pipeline import ingest_text

    r = ingest_text(
        full_text=f"Attachment body carrying {_SENTINEL} for RAG.",
        filename="invoice.pdf",
        source_path="email:abc123/invoice.pdf",
        collection="baker-documents",
    )

    assert not r.skipped
    assert r.chunk_count >= 1
    assert len(r.point_ids) >= 1
    assert r.collection == "baker-documents"
    # Something was actually upserted into Qdrant.
    assert fake_qdrant.instances and fake_qdrant.instances[0].upserts


def test_ingest_text_uses_durable_source_path_in_payload(monkeypatch):
    """The Qdrant payload must carry the DURABLE source_path the caller passed —
    NOT a temp filepath."""
    fake_qdrant = _patch_pipeline(monkeypatch)
    from tools.ingest.pipeline import ingest_text

    durable = "email:mid999/contract.pdf"
    ingest_text(full_text=f"x {_SENTINEL} y", filename="contract.pdf",
                source_path=durable, collection="baker-documents")

    points = fake_qdrant.instances[0].upserts[0][1]
    assert points, "expected at least one upserted point"
    payload = points[0].payload
    assert payload["source_path"] == durable
    assert payload["source_file"] == "contract.pdf"
    assert not payload["source_path"].startswith("/"), "must not be a local temp path"


def test_ingest_text_empty_text_is_skipped(monkeypatch):
    _patch_pipeline(monkeypatch)
    from tools.ingest.pipeline import ingest_text

    r = ingest_text(full_text="   ", filename="empty.txt", source_path="email:x/empty.txt")
    assert r.skipped
    assert r.chunk_count == 0


def test_ingest_text_dedup_short_circuits(monkeypatch):
    """If ingestion_log already has (filename, hash), ingest_text must skip without
    re-embedding."""
    import tools.ingest.pipeline as pipe
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(pipe, "is_duplicate", lambda *a, **k: True)
    from tools.ingest.pipeline import ingest_text

    r = ingest_text(full_text=f"dup {_SENTINEL}", filename="dup.pdf",
                    source_path="email:x/dup.pdf")
    assert r.skipped
    assert "Duplicate" in (r.skip_reason or "")


def test_ingest_text_idempotent_point_ids(monkeypatch):
    """Re-running on identical text yields identical (deterministic) point IDs, so
    re-upsert overwrites rather than duplicating."""
    _patch_pipeline(monkeypatch)
    from tools.ingest.pipeline import ingest_text

    kw = dict(full_text=f"idem {_SENTINEL} body", filename="idem.pdf",
              source_path="email:x/idem.pdf", collection="baker-documents")
    r1 = ingest_text(**kw)
    r2 = ingest_text(**kw)
    assert r1.point_ids == r2.point_ids
    assert r1.point_ids  # non-empty


# ─── promote helper unit tests (store + ingest_text stubbed) ──────────────────


def _patch_helper(monkeypatch, store=None, raise_in_store=False, raise_in_qdrant=False):
    """Stub SentinelStoreBack + ingest_text + queue_extraction for the helper."""
    import memory.store_back as sb
    import tools.ingest.pipeline as pipe
    import tools.document_pipeline as dp

    calls = {"store": [], "qdrant": [], "queue": []}

    class _Store:
        def store_document_full(self, source_path, filename, file_hash, full_text,
                                token_count=0, owner="shared"):
            calls["store"].append({
                "source_path": source_path, "filename": filename,
                "file_hash": file_hash, "full_text": full_text, "owner": owner,
            })
            if raise_in_store:
                raise RuntimeError("postgres down")
            return 4242

    monkeypatch.setattr(sb.SentinelStoreBack, "_get_global_instance",
                        classmethod(lambda cls: _Store()))

    from tools.ingest.models import IngestResult

    def _fake_ingest_text(full_text, filename, source_path, collection="baker-documents",
                          file_hash=None, **kw):
        calls["qdrant"].append({
            "source_path": source_path, "filename": filename,
            "file_hash": file_hash, "collection": collection,
        })
        if raise_in_qdrant:
            raise RuntimeError("qdrant down")
        return IngestResult(filename=filename, file_hash=file_hash or "h",
                            file_size_bytes=1, collection=collection, chunk_count=3)

    monkeypatch.setattr(pipe, "ingest_text", _fake_ingest_text)
    monkeypatch.setattr(dp, "queue_extraction", lambda doc_id: calls["queue"].append(doc_id))
    return calls


def test_promote_drives_both_halves_with_aligned_hash(monkeypatch):
    """Both stores called, with the SAME file_hash + source_path → aligned dedup."""
    calls = _patch_helper(monkeypatch)
    from tools.ingest.attachments import promote_attachment_text_to_document_and_qdrant

    res = promote_attachment_text_to_document_and_qdrant(
        source_path="whatsapp:msg1/photo.jpg",
        filename="photo.jpg",
        full_text=f"WA media OCR {_SENTINEL}",
    )

    assert len(calls["store"]) == 1
    assert len(calls["qdrant"]) == 1
    s, q = calls["store"][0], calls["qdrant"][0]
    assert s["source_path"] == q["source_path"] == "whatsapp:msg1/photo.jpg"
    assert s["file_hash"] == q["file_hash"]  # same hash → dedup keys aligned
    assert res["doc_id"] == 4242
    assert res["chunk_count"] == 3
    assert calls["queue"] == [4242]  # extraction queued for the doc


def test_promote_empty_text_is_noop(monkeypatch):
    calls = _patch_helper(monkeypatch)
    from tools.ingest.attachments import promote_attachment_text_to_document_and_qdrant

    res = promote_attachment_text_to_document_and_qdrant(
        source_path="email:x/blank.txt", filename="blank.txt", full_text="  ")
    assert res == {"doc_id": None, "chunk_count": 0}
    assert calls["store"] == [] and calls["qdrant"] == []


def test_promote_non_fatal_when_postgres_fails(monkeypatch):
    """A Postgres failure must NOT block the Qdrant half and must NOT raise."""
    calls = _patch_helper(monkeypatch, raise_in_store=True)
    from tools.ingest.attachments import promote_attachment_text_to_document_and_qdrant

    res = promote_attachment_text_to_document_and_qdrant(
        source_path="email:x/a.pdf", filename="a.pdf", full_text=f"body {_SENTINEL}")
    assert res["doc_id"] is None        # store failed
    assert res["chunk_count"] == 3      # but Qdrant half still ran
    assert len(calls["qdrant"]) == 1


def test_promote_non_fatal_when_qdrant_fails(monkeypatch):
    """A Qdrant failure must NOT raise and must NOT lose the documents row."""
    calls = _patch_helper(monkeypatch, raise_in_qdrant=True)
    from tools.ingest.attachments import promote_attachment_text_to_document_and_qdrant

    res = promote_attachment_text_to_document_and_qdrant(
        source_path="email:x/b.pdf", filename="b.pdf", full_text=f"body {_SENTINEL}")
    assert res["doc_id"] == 4242        # store succeeded
    assert res["chunk_count"] == 0      # qdrant failed, reported as 0
    assert len(calls["store"]) == 1
