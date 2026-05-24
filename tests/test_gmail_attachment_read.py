"""Tests for tools.gmail.dispatch_gmail / _attachment_read.

12 mocked cases per BRIEF_GMAIL_ATTACHMENT_READ_2 (§Fix 2) — adapted from
the 10 READ_1 cases plus 2 new for duplicate-filename handling — plus
1 gated real-Gmail E2E test:

  1. Happy path — small PDF, text-only mode (nested-multipart payload)
  2. Happy path — include_bytes=true
  3. Missing message_id
  4. Missing filename
  5. Filename not found in message (available_filenames surfaced)
  6. Oversize attachment (size > 10 MB)
  7. Unsupported extension (.png — graceful empty text, no error)
  8. Empty Gmail data response
  9. Gmail API exception on message.get()
  10. Gmail API exception on attachments.get()
  11. Duplicate filenames — attachment_index picks the right one
  12. attachment_index out of range — error with match_count

  E2E. Real-Gmail end-to-end (skipif TEST_GMAIL_LIVE != "1")

EMAIL-ATTACH-FIX-1 nested-multipart path covered in case 1 (payload built
with two levels of `parts` nesting to exercise _collect_attachment_parts
recursion through the new tool).

The 12 mocked cases use unittest.mock.MagicMock — no real Gmail API calls.
The E2E test hits the live Gmail API and requires TEST_GMAIL_LIVE=1 plus
BAKER_GMAIL_* OAuth env vars; auto-skipped in CI.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_PDF_BYTES = b"%PDF-1.4 fake-but-plausible body content for extractor stub"
_EXTRACTED_TEXT = "extracted body text from PDF"


def _build_payload_nested_pdf(attachment_id: str = "ATT_PDF_1") -> dict:
    """Build a Gmail message payload with a PDF attachment nested two
    multipart levels deep — exercises EMAIL-ATTACH-FIX-1 recursion."""
    return {
        "parts": [
            {  # level 1: text/plain body part (no filename, skipped)
                "mimeType": "text/plain",
                "filename": "",
                "body": {"size": 100, "data": "aGVsbG8="},
            },
            {  # level 1: nested multipart wrapper (forwarded email scenario)
                "mimeType": "multipart/mixed",
                "filename": "",
                "parts": [
                    {  # level 2: the actual PDF attachment
                        "mimeType": "application/pdf",
                        "filename": "Schadensblatt-Top4.pdf",
                        "body": {
                            "size": len(_PDF_BYTES),
                            "attachmentId": attachment_id,
                        },
                    },
                ],
            },
        ],
    }


def _build_service_mock(
    *,
    message_payload: dict | None = None,
    attachment_data: str | None = None,
    message_raises: Exception | None = None,
    attachment_raises: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics the Gmail service call chain:
       service.users().messages().get(...).execute()
       service.users().messages().attachments().get(...).execute()
    """
    service = MagicMock(name="gmail_service")

    # message.get().execute()
    msg_exec = MagicMock(name="messages_get_execute")
    if message_raises is not None:
        msg_exec.execute.side_effect = message_raises
    else:
        msg_exec.execute.return_value = {
            "id": "MSG_1",
            "payload": message_payload or {},
        }
    service.users.return_value.messages.return_value.get.return_value = msg_exec

    # attachments.get().execute()
    att_exec = MagicMock(name="attachments_get_execute")
    if attachment_raises is not None:
        att_exec.execute.side_effect = attachment_raises
    else:
        att_exec.execute.return_value = {"data": attachment_data or ""}
    (
        service.users.return_value
        .messages.return_value
        .attachments.return_value
        .get.return_value
    ) = att_exec

    return service


@pytest.fixture
def _patch_gmail_service(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Each test injects its own service via the `set_service` callback
    returned in this fixture's dict. Tests that don't override get a
    service that raises on call (forces explicit setup).

    Not autouse — the E2E test must NOT receive a stubbed service.
    """
    container: dict[str, Any] = {"service": None}

    def _fake_get_service():
        svc = container["service"]
        if svc is None:
            raise RuntimeError("test did not call set_service()")
        return svc

    monkeypatch.setattr(
        "triggers.email_trigger._get_gmail_service",
        _fake_get_service,
    )

    def _set_service(svc: Any) -> None:
        container["service"] = svc

    container["set_service"] = _set_service
    return container


@pytest.fixture
def _patch_extractor(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub _extract_text_from_bytes — returns _EXTRACTED_TEXT for the
    fake PDF bytes; tests can override via the returned dict.

    Not autouse — the E2E test must NOT receive a stubbed extractor.
    """
    container: dict[str, Any] = {"calls": [], "return_value": _EXTRACTED_TEXT}

    def _fake_extract(file_bytes: bytes, filename: str, ext: str) -> str | None:
        container["calls"].append((file_bytes, filename, ext))
        rv = container["return_value"]
        if isinstance(rv, Exception):
            raise rv
        return rv

    monkeypatch.setattr(
        "scripts.extract_gmail._extract_text_from_bytes",
        _fake_extract,
    )
    return container


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_happy_path_text_only(_patch_gmail_service, _patch_extractor):
    """Case 1: small PDF, text-only mode → text non-empty, no bytes_base64,
    nested-multipart payload (EMAIL-ATTACH-FIX-1 path)."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(),
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf"},
    )
    result = json.loads(raw)

    assert "error" not in result
    assert result["filename"] == "Schadensblatt-Top4.pdf"
    assert result["text"] == _EXTRACTED_TEXT
    assert result["text_extracted"] is True
    assert "bytes_base64" not in result
    assert result["mime_type"] == "application/pdf"
    assert result["size"] == len(_PDF_BYTES)
    assert result["match_count"] == 1
    assert result["attachment_index"] == 1
    # extractor invoked with the decoded bytes
    assert len(_patch_extractor["calls"]) == 1
    assert _patch_extractor["calls"][0][0] == _PDF_BYTES


def test_happy_path_include_bytes(_patch_gmail_service, _patch_extractor):
    """Case 2: include_bytes=true → bytes_base64 present, decodes to original."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(),
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf", "include_bytes": True},
    )
    result = json.loads(raw)

    assert "error" not in result
    assert result["text"] == _EXTRACTED_TEXT
    assert "bytes_base64" in result
    decoded = base64.standard_b64decode(result["bytes_base64"])
    assert decoded == _PDF_BYTES
    assert result["match_count"] == 1
    assert result["attachment_index"] == 1


def test_missing_message_id(_patch_gmail_service):
    """Case 3: empty message_id → error response, no Gmail call attempted."""
    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "", "filename": "Schadensblatt-Top4.pdf"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "message_id" in result["error"]


def test_missing_filename(_patch_gmail_service):
    """Case 4: empty filename → error response, no Gmail call attempted."""
    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": ""},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "filename" in result["error"]


def test_filename_not_found(_patch_gmail_service, _patch_extractor):
    """Case 5: filename not in any part → error + available_filenames listed."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(),
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "NotInMessage.pdf"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "filename not found in message" in result["error"]
    assert "available_filenames" in result
    assert "Schadensblatt-Top4.pdf" in result["available_filenames"]


def test_oversize_attachment(_patch_gmail_service, _patch_extractor):
    """Case 6: size > _MAX_ATTACHMENT_SIZE → error 'attachment too large'."""
    import tools.gmail as gmail_mod
    from scripts.extract_gmail import _MAX_ATTACHMENT_SIZE

    huge = _MAX_ATTACHMENT_SIZE + 1
    payload = {
        "parts": [
            {
                "filename": "huge.pdf",
                "body": {"size": huge, "attachmentId": "ATT_BIG"},
            },
        ],
    }
    service = _build_service_mock(message_payload=payload)
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "huge.pdf"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "too large" in result["error"]
    assert result["size"] == huge
    assert result["filename"] == "huge.pdf"


def test_unsupported_extension(_patch_gmail_service, _patch_extractor):
    """Case 7: .png — out of v1 scope. Text empty, no error (graceful)."""
    import tools.gmail as gmail_mod

    png_bytes = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    payload = {
        "parts": [
            {
                "filename": "photo.png",
                "body": {"size": len(png_bytes), "attachmentId": "ATT_PNG"},
            },
        ],
    }
    service = _build_service_mock(
        message_payload=payload,
        attachment_data=base64.urlsafe_b64encode(png_bytes).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "photo.png"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["text"] == ""
    assert result["text_extracted"] is False
    assert result["filename"] == "photo.png"
    assert result["match_count"] == 1
    assert result["attachment_index"] == 1
    # extractor must NOT have been called for unsupported extension
    assert _patch_extractor["calls"] == []


def test_empty_gmail_data_response(_patch_gmail_service, _patch_extractor):
    """Case 8: attachments.get() returns {data: ''} → error 'gmail returned empty'."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(),
        attachment_data="",  # empty data
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "gmail returned empty" in result["error"]
    assert result["filename"] == "Schadensblatt-Top4.pdf"


def test_message_fetch_exception(_patch_gmail_service, _patch_extractor):
    """Case 9: service.users().messages().get(...).execute() raises → error."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_raises=RuntimeError("gmail 500 backend error"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "message fetch failed" in result["error"]


def test_attachment_download_exception(_patch_gmail_service, _patch_extractor):
    """Case 10: attachments.get().execute() raises → error 'download failed'."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(),
        attachment_raises=RuntimeError("network unreachable"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "download failed" in result["error"]
    assert result["filename"] == "Schadensblatt-Top4.pdf"


def test_duplicate_filenames_with_index(_patch_gmail_service, _patch_extractor):
    """Case 11: two attachments share filename → caller picks via attachment_index.

    Both calls must succeed; the tool resolves each call's session-valid
    attachmentId internally (ATT_INV_A then ATT_INV_B) via depth-first walk
    order of _collect_attachment_parts."""
    import tools.gmail as gmail_mod

    payload = {
        "parts": [
            {
                "filename": "invoice.pdf",
                "body": {"size": len(_PDF_BYTES), "attachmentId": "ATT_INV_A"},
            },
            {
                "filename": "invoice.pdf",
                "body": {"size": len(_PDF_BYTES), "attachmentId": "ATT_INV_B"},
            },
        ],
    }
    service = _build_service_mock(
        message_payload=payload,
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    # Default index=1 → first match
    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "invoice.pdf"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["match_count"] == 2
    assert result["attachment_index"] == 1

    # Explicit index=2 → second match (different attachmentId resolved internally)
    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "invoice.pdf", "attachment_index": 2},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["match_count"] == 2
    assert result["attachment_index"] == 2


def test_attachment_index_out_of_range(_patch_gmail_service, _patch_extractor):
    """Case 12: attachment_index > match_count → error listing match_count."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(),
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf", "attachment_index": 5},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "out of range" in result["error"]
    assert result["match_count"] == 1


# --------------------------------------------------------------------------- #
# E2E (gated)                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    os.getenv("TEST_GMAIL_LIVE") != "1",
    reason="Real-Gmail E2E. Set TEST_GMAIL_LIVE=1 + BAKER_GMAIL_* env vars to run.",
)
def test_e2e_real_gmail_attachment_read():
    """End-to-end test against the real Gmail API using baker's OAuth creds.

    Fixture: a known-stable poll-indexed message + attachment from baker's
    documents table. Selected by querying:
        SELECT source_path FROM documents
        WHERE source_path LIKE 'email:%/%.pdf'
        ORDER BY ingested_at DESC LIMIT 1
    Extract the Gmail message_id (the substring between 'email:' and '/').

    Gated on TEST_GMAIL_LIVE=1 to avoid hitting the live API in CI.
    Must NOT be part of the standard pytest run.
    """
    fixture_message_id = os.getenv("E2E_GMAIL_MESSAGE_ID", "")
    fixture_filename = os.getenv("E2E_GMAIL_FILENAME", "")
    if not fixture_message_id or not fixture_filename:
        pytest.skip("E2E fixture env vars E2E_GMAIL_MESSAGE_ID / E2E_GMAIL_FILENAME not set")

    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": fixture_message_id, "filename": fixture_filename},
    )
    result = json.loads(raw)

    assert "error" not in result, f"E2E call returned error: {result}"
    assert result["filename"] == fixture_filename
    assert result["size"] > 0
    assert result["match_count"] >= 1
    # PDF/DOCX/etc. should extract text; raw bytes path also valid.
    # Skip text non-empty assertion — depends on fixture file content.
