"""BAKER_M365_ATTACHMENT_READ_SURFACE_1 — tests for baker_email_attachment_read.

The tool exposes the attachment BYTES that the Graph mail trigger already
persists into the email_attachments store (kbl/attachment_store.py) but which
previously had no read surface. These tests mock the store layer
(list_attachments / get_attachment) so no DB is required, and stub the gmail
text-extraction helper so no heavy office/google deps are pulled.

Coverage:
  - registration in the MCP EMAIL_TOOLS surface
  - LIST mode (enumerate a message's attachments)
  - FETCH by filename (exact, case-sensitive) + by 1-based index
  - duplicate-filename tiebreaker via attachment_index
  - include_bytes default-false / true (base64 round-trip)
  - source-aware filter passthrough
  - fail-closed error paths: missing message_id, bad index, not-found,
    out-of-range, metadata-only (>5MB), NULL/missing payload, no attachments
  - non-fatal text-extraction failure
  - dispatch routing + never-raise guard
"""
from __future__ import annotations

import base64
import json
import sys
import types

import pytest

from tools.email import EMAIL_TOOLS, EMAIL_TOOL_NAMES, dispatch_email

ATTACH_TOOL = "baker_email_attachment_read"


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _stub_extractor(monkeypatch):
    """Stub scripts.extract_gmail._extract_text_from_bytes so the text branch
    doesn't pull heavy deps. Default: echo a deterministic marker."""
    fake = types.ModuleType("scripts.extract_gmail")
    fake._extract_text_from_bytes = lambda b, fn, ext: f"TEXT[{fn}]"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.extract_gmail", fake)
    return fake


def _meta(id_, filename, *, source="graph", storage="db", size=1234,
          mime="application/pdf", sha=None):
    return {
        "id": id_, "message_id": "M1", "source": source, "filename": filename,
        "mime_type": mime, "size_bytes": size,
        "content_sha256": sha or f"sha-{id_}", "storage": storage,
    }


def _full(id_, filename, *, data=b"PDFBYTES", source="graph", storage="db",
          size=1234, mime="application/pdf", sha=None):
    return {
        "id": id_, "message_id": "M1", "source": source, "filename": filename,
        "mime_type": mime, "size_bytes": size,
        "content_sha256": sha or f"sha-{id_}", "storage": storage,
        "data": data, "created_at": None,
    }


def _call(args):
    return json.loads(dispatch_email(ATTACH_TOOL, args))


def _patch_store(monkeypatch, *, list_rows=None, full_by_id=None, list_raises=False):
    import kbl.attachment_store as store

    def fake_list(message_id, source=None):
        if list_raises:
            raise RuntimeError("boom")
        rows = list_rows if list_rows is not None else []
        if source:
            rows = [r for r in rows if r.get("source") == source]
        return rows

    def fake_get(att_id):
        return (full_by_id or {}).get(att_id)

    monkeypatch.setattr(store, "list_attachments", fake_list)
    monkeypatch.setattr(store, "get_attachment", fake_get)


# ── registration ────────────────────────────────────────────────────────────

def test_registered_in_email_surface():
    assert ATTACH_TOOL in EMAIL_TOOL_NAMES
    tool = next(t for t in EMAIL_TOOLS if t.name == ATTACH_TOOL)
    assert tool.inputSchema["required"] == ["message_id"]
    props = tool.inputSchema["properties"]
    for key in ("message_id", "filename", "attachment_index", "source", "include_bytes"):
        assert key in props


# ── input validation / fail-closed ──────────────────────────────────────────

def test_missing_message_id_errors():
    out = _call({})
    assert "error" in out and "message_id" in out["error"]


@pytest.mark.parametrize("bad", [0, -1, True, "2", 1.5])
def test_invalid_attachment_index_rejected(monkeypatch, bad):
    _patch_store(monkeypatch, list_rows=[_meta(11, "a.pdf")])
    out = _call({"message_id": "M1", "attachment_index": bad})
    assert "error" in out and "attachment_index" in out["error"]


# ── LIST mode ───────────────────────────────────────────────────────────────

def test_list_mode_enumerates(monkeypatch):
    _patch_store(monkeypatch, list_rows=[
        _meta(11, "Darlehensvertrag.pdf"),
        _meta(12, "Anlage10.pdf", size=5678),
    ])
    out = _call({"message_id": "M1"})
    assert out["attachment_count"] == 2
    assert [a["index"] for a in out["attachments"]] == [1, 2]
    assert out["attachments"][0]["filename"] == "Darlehensvertrag.pdf"
    # LIST mode never leaks bytes
    assert all("bytes_base64" not in a for a in out["attachments"])


def test_list_mode_empty(monkeypatch):
    _patch_store(monkeypatch, list_rows=[])
    out = _call({"message_id": "M1"})
    assert out["attachment_count"] == 0
    assert out["attachments"] == []


# ── FETCH by filename ───────────────────────────────────────────────────────

def test_fetch_by_filename_returns_text(monkeypatch):
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "Darlehensvertrag.pdf")],
        full_by_id={11: _full(11, "Darlehensvertrag.pdf", data=b"HELLO")},
    )
    out = _call({"message_id": "M1", "filename": "Darlehensvertrag.pdf"})
    assert out["filename"] == "Darlehensvertrag.pdf"
    assert out["text_extracted"] is True
    assert out["text"] == "TEXT[Darlehensvertrag.pdf]"
    assert out["source"] == "graph"
    assert out["match_count"] == 1
    assert "bytes_base64" not in out  # default include_bytes false


def test_fetch_include_bytes_roundtrip(monkeypatch):
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "doc.pdf")],
        full_by_id={11: _full(11, "doc.pdf", data=b"RAWBYTES\x00\x01")},
    )
    out = _call({"message_id": "M1", "filename": "doc.pdf", "include_bytes": True})
    assert base64.b64decode(out["bytes_base64"]) == b"RAWBYTES\x00\x01"


def test_fetch_filename_case_sensitive_not_found(monkeypatch):
    _patch_store(monkeypatch, list_rows=[_meta(11, "Doc.pdf")])
    out = _call({"message_id": "M1", "filename": "doc.pdf"})
    assert "error" in out
    assert out["available_filenames"] == ["Doc.pdf"]


def test_duplicate_filename_tiebreaker(monkeypatch):
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "dup.pdf"), _meta(12, "dup.pdf")],
        full_by_id={11: _full(11, "dup.pdf", data=b"first"),
                    12: _full(12, "dup.pdf", data=b"second")},
    )
    out = _call({"message_id": "M1", "filename": "dup.pdf",
                 "attachment_index": 2, "include_bytes": True})
    assert base64.b64decode(out["bytes_base64"]) == b"second"
    assert out["match_count"] == 2


def test_filename_index_out_of_range(monkeypatch):
    _patch_store(monkeypatch, list_rows=[_meta(11, "dup.pdf")])
    out = _call({"message_id": "M1", "filename": "dup.pdf", "attachment_index": 2})
    assert "error" in out and "out of range" in out["error"]


# ── FETCH by index (no filename) ────────────────────────────────────────────

def test_fetch_by_index_selects_nth(monkeypatch):
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "first.pdf"), _meta(12, "second.pdf")],
        full_by_id={12: _full(12, "second.pdf", data=b"two")},
    )
    out = _call({"message_id": "M1", "attachment_index": 2, "include_bytes": True})
    assert out["filename"] == "second.pdf"
    assert base64.b64decode(out["bytes_base64"]) == b"two"


def test_index_only_out_of_range(monkeypatch):
    _patch_store(monkeypatch, list_rows=[_meta(11, "a.pdf")])
    out = _call({"message_id": "M1", "attachment_index": 3})
    assert "error" in out and "out of range" in out["error"]


def test_fetch_no_attachments_on_message(monkeypatch):
    _patch_store(monkeypatch, list_rows=[])
    out = _call({"message_id": "M1", "filename": "x.pdf"})
    assert "error" in out and "no attachments" in out["error"]


# ── metadata-only (>5MB) + payload gaps ─────────────────────────────────────

def test_metadata_only_bytes_unavailable(monkeypatch):
    # get_attachment must NOT be consulted for a metadata_only row.
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "huge.pdf", storage="metadata_only", size=99_000_000)],
        full_by_id={},
    )
    out = _call({"message_id": "M1", "filename": "huge.pdf", "include_bytes": True})
    assert out["storage"] == "metadata_only"
    assert "bytes_base64" not in out
    assert "metadata-only" in out["error"]


def test_payload_null_data(monkeypatch):
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "doc.pdf")],
        full_by_id={11: _full(11, "doc.pdf", data=None)},
    )
    out = _call({"message_id": "M1", "filename": "doc.pdf"})
    assert "error" in out and "unavailable" in out["error"]


def test_payload_store_miss(monkeypatch):
    _patch_store(monkeypatch, list_rows=[_meta(11, "doc.pdf")], full_by_id={})
    out = _call({"message_id": "M1", "filename": "doc.pdf"})
    assert "error" in out and "unavailable" in out["error"]


# ── source-aware ────────────────────────────────────────────────────────────

def test_source_filter_passthrough(monkeypatch):
    _patch_store(monkeypatch, list_rows=[
        _meta(11, "g.pdf", source="graph"),
        _meta(21, "b.pdf", source="bluewin"),
    ])
    out = _call({"message_id": "M1", "source": "graph"})
    names = [a["filename"] for a in out["attachments"]]
    assert names == ["g.pdf"]


# ── non-fatal extraction failure ────────────────────────────────────────────

def test_extraction_failure_is_nonfatal(monkeypatch):
    def boom(b, fn, ext):
        raise ValueError("corrupt pdf")
    sys.modules["scripts.extract_gmail"]._extract_text_from_bytes = boom  # type: ignore[attr-defined]
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "bad.pdf")],
        full_by_id={11: _full(11, "bad.pdf", data=b"x")},
    )
    out = _call({"message_id": "M1", "filename": "bad.pdf"})
    assert out["text"] == ""
    assert out["text_extracted"] is False
    assert "text_error" in out


def test_non_text_extension_skips_extraction(monkeypatch):
    _patch_store(
        monkeypatch,
        list_rows=[_meta(11, "image.png", mime="image/png")],
        full_by_id={11: _full(11, "image.png", data=b"\x89PNG", mime="image/png")},
    )
    out = _call({"message_id": "M1", "filename": "image.png", "include_bytes": True})
    assert out["text"] == ""
    assert out["text_extracted"] is False
    assert base64.b64decode(out["bytes_base64"]) == b"\x89PNG"


# ── dispatch routing + never-raise ──────────────────────────────────────────

def test_dispatch_routes_to_attachment_read(monkeypatch):
    _patch_store(monkeypatch, list_rows=[_meta(11, "a.pdf")])
    out = _call({"message_id": "M1"})
    assert "attachment_count" in out


def test_dispatch_never_raises_on_store_error(monkeypatch):
    _patch_store(monkeypatch, list_raises=True)
    out = _call({"message_id": "M1"})
    assert "error" in out  # surfaced as JSON, not an exception
