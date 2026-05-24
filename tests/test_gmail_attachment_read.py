"""Tests for tools.gmail.dispatch_gmail / _attachment_read.

10 cases per BRIEF_GMAIL_ATTACHMENT_READ_1 (§Fix/Feature 2):

  1. Happy path — small PDF, text-only mode
  2. Happy path — include_bytes=true
  3. Missing message_id
  4. Missing attachment_id
  5. attachment_id not found in message
  6. Oversize attachment (size > 10 MB)
  7. Unsupported extension (.png — graceful empty text, no error)
  8. Empty Gmail data response
  9. Gmail API exception on message.get()
  10. Gmail API exception on attachments.get()

EMAIL-ATTACH-FIX-1 nested-multipart path covered in case 1 (payload built
with two levels of `parts` nesting to exercise _collect_attachment_parts
recursion through the new tool).

No real Gmail API calls. All mocked via unittest.mock.MagicMock. Local
fixtures only (no conftest.py modifications) — mirrors existing test
patterns (tests/test_grok_client.py).
"""
from __future__ import annotations

import base64
import json
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


@pytest.fixture(autouse=True)
def _patch_gmail_service(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Default: every test injects its own service via the `set_service`
    callback returned in this fixture's dict. Tests that don't override
    get a service that raises on call (forces explicit setup)."""
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


@pytest.fixture(autouse=True)
def _patch_extractor(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub _extract_text_from_bytes — returns _EXTRACTED_TEXT for the
    fake PDF bytes; tests can override via the returned dict."""
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
        {"message_id": "MSG_1", "attachment_id": "ATT_PDF_1"},
    )
    result = json.loads(raw)

    assert "error" not in result
    assert result["filename"] == "Schadensblatt-Top4.pdf"
    assert result["text"] == _EXTRACTED_TEXT
    assert result["text_extracted"] is True
    assert "bytes_base64" not in result
    assert result["mime_type"] == "application/pdf"
    assert result["size"] == len(_PDF_BYTES)
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
        {"message_id": "MSG_1", "attachment_id": "ATT_PDF_1", "include_bytes": True},
    )
    result = json.loads(raw)

    assert "error" not in result
    assert result["text"] == _EXTRACTED_TEXT
    assert "bytes_base64" in result
    decoded = base64.standard_b64decode(result["bytes_base64"])
    assert decoded == _PDF_BYTES


def test_missing_message_id(_patch_gmail_service):
    """Case 3: empty message_id → error response, no Gmail call attempted."""
    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "", "attachment_id": "ATT_PDF_1"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "message_id" in result["error"]


def test_missing_attachment_id(_patch_gmail_service):
    """Case 4: empty attachment_id → error response, no Gmail call attempted."""
    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "attachment_id": ""},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "attachment_id" in result["error"]


def test_attachment_id_not_found(_patch_gmail_service, _patch_extractor):
    """Case 5: attachment_id not in any part → error 'attachment_id not found'."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(attachment_id="DIFFERENT_ID"),
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "attachment_id": "ATT_PDF_1"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "attachment_id not found" in result["error"]


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
        {"message_id": "MSG_1", "attachment_id": "ATT_BIG"},
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
        {"message_id": "MSG_1", "attachment_id": "ATT_PNG"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["text"] == ""
    assert result["text_extracted"] is False
    assert result["filename"] == "photo.png"
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
        {"message_id": "MSG_1", "attachment_id": "ATT_PDF_1"},
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
        {"message_id": "MSG_1", "attachment_id": "ATT_PDF_1"},
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
        {"message_id": "MSG_1", "attachment_id": "ATT_PDF_1"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "download failed" in result["error"]
    assert result["filename"] == "Schadensblatt-Top4.pdf"
