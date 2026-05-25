"""Tests for tools.gmail.dispatch_gmail — three MCP tools:

  baker_gmail_attachment_read  — 12 mocked cases + 1 gated E2E (from READ_2)
  baker_gmail_search           —  6 mocked cases + 1 gated E2E (this brief)
  baker_gmail_read_message     —  6 mocked cases + 1 gated E2E (this brief)

The 24 mocked cases use unittest.mock.MagicMock — no real Gmail API calls.
The 3 E2E tests hit live Gmail and require TEST_GMAIL_LIVE=1 plus
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
    # baker_gmail_search wiring:
    list_response: dict | None = None,
    list_raises: Exception | None = None,
    metadata_responses: dict | None = None,        # {msg_id: metadata_dict}
    metadata_raises: dict | None = None,           # {msg_id: Exception}
    # baker_gmail_read_message wiring:
    full_message_response: dict | None = None,
    full_message_raises: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics the Gmail service call chains:
       service.users().messages().get(...).execute()                          [attachment_read]
       service.users().messages().attachments().get(...).execute()            [attachment_read]
       service.users().messages().list(...).execute()                         [search]
       service.users().messages().get(format='metadata', ...).execute()       [search]
       service.users().messages().get(format='full', id=X, ...).execute()     [read_message]
    """
    service = MagicMock(name="gmail_service")

    # messages().list() chain — for baker_gmail_search.
    list_exec = MagicMock(name="messages_list_execute")
    if list_raises is not None:
        list_exec.execute.side_effect = list_raises
    else:
        list_exec.execute.return_value = list_response or {"messages": [], "resultSizeEstimate": 0}
    service.users.return_value.messages.return_value.list.return_value = list_exec

    # messages().get() — format-aware router. Routes on `format` + `id` kwargs.
    # Legacy callers (baker_gmail_attachment_read tests) pass message_payload
    # without a `format=` and hit the fallback branch.
    def _route_messages_get(**kwargs):
        fmt = kwargs.get("format", "")
        msg_id = kwargs.get("id", "")
        exec_mock = MagicMock(name=f"messages_get_execute(format={fmt},id={msg_id})")
        if fmt == "metadata":
            if metadata_raises and msg_id in metadata_raises:
                exec_mock.execute.side_effect = metadata_raises[msg_id]
            else:
                md = (metadata_responses or {}).get(msg_id, {})
                exec_mock.execute.return_value = md
        elif fmt == "full" and (full_message_response is not None or full_message_raises is not None):
            if full_message_raises is not None:
                exec_mock.execute.side_effect = full_message_raises
            else:
                exec_mock.execute.return_value = full_message_response
        else:
            # Legacy fallback for baker_gmail_attachment_read tests that pass
            # `message_payload=` via this factory.
            if message_raises is not None:
                exec_mock.execute.side_effect = message_raises
            else:
                exec_mock.execute.return_value = {
                    "id": msg_id or "MSG_1",
                    "payload": message_payload or {},
                }
        return exec_mock

    service.users.return_value.messages.return_value.get.side_effect = _route_messages_get

    # attachments().get() chain — for baker_gmail_attachment_read.
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


def test_attachment_read_happy_path_text_only(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_happy_path_include_bytes(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_missing_message_id(_patch_gmail_service):
    """Case 3: empty message_id → error response, no Gmail call attempted."""
    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "", "filename": "Schadensblatt-Top4.pdf"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "message_id" in result["error"]


def test_attachment_read_missing_filename(_patch_gmail_service):
    """Case 4: empty filename → error response, no Gmail call attempted."""
    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": ""},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "filename" in result["error"]


def test_attachment_read_filename_not_found(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_oversize(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_unsupported_extension(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_empty_gmail_data(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_message_fetch_exception(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_download_exception(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_duplicate_filenames_with_index(_patch_gmail_service, _patch_extractor):
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


def test_attachment_read_index_out_of_range(_patch_gmail_service, _patch_extractor):
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
# baker_gmail_search — 6 mocked cases                                         #
# --------------------------------------------------------------------------- #


def _metadata_payload(*, from_addr: str, to_addr: str, subject: str, date: str,
                       snippet: str, thread_id: str, label_ids: list[str] | None = None) -> dict:
    """Build a realistic format='metadata' Gmail response payload."""
    return {
        "id": "X",  # routed mock overrides with real id
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": label_ids or ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "To", "value": to_addr},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ],
        },
    }


def test_search_empty_query_rejected(_patch_gmail_service):
    """Case 1: empty query → error, no Gmail call attempted."""
    import tools.gmail as gmail_mod

    # No service needed — short-circuit before Gmail call.
    raw = gmail_mod.dispatch_gmail("baker_gmail_search", {"query": ""})
    result = json.loads(raw)
    assert "error" in result
    assert "query" in result["error"]


def test_search_no_matches(_patch_gmail_service):
    """Case 2: list returns 0 messages → match_count=0, no metadata calls."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        list_response={"messages": [], "resultSizeEstimate": 0},
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_search",
        {"query": "from:nobody@example.com"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["match_count"] == 0
    assert result["matches"] == []
    assert result["result_size_estimate"] == 0
    # No metadata calls should have been made — list returned 0 stubs.
    # Verify get was never invoked (only list was).
    service.users.return_value.messages.return_value.get.assert_not_called()


def test_search_happy_path_three_matches(_patch_gmail_service):
    """Case 3: 3 matches with realistic headers + snippet → all fields populated."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        list_response={
            "messages": [
                {"id": "M1", "threadId": "T1"},
                {"id": "M2", "threadId": "T2"},
                {"id": "M3", "threadId": "T3"},
            ],
            "resultSizeEstimate": 3,
        },
        metadata_responses={
            "M1": _metadata_payload(
                from_addr="alice@example.com",
                to_addr="me@brisengroup.com",
                subject="Filing update",
                date="Mon, 25 May 2026 09:00:00 +0000",
                snippet="First match snippet",
                thread_id="T1",
                label_ids=["INBOX", "Baker"],
            ),
            "M2": _metadata_payload(
                from_addr="bob@example.com",
                to_addr="me@brisengroup.com",
                subject="Re: Filing update",
                date="Mon, 25 May 2026 09:15:00 +0000",
                snippet="Second match snippet",
                thread_id="T2",
            ),
            "M3": _metadata_payload(
                from_addr="carol@example.com",
                to_addr="me@brisengroup.com",
                subject="Filing — final",
                date="Mon, 25 May 2026 09:30:00 +0000",
                snippet="Third match snippet",
                thread_id="T3",
            ),
        },
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_search",
        {"query": "subject:filing", "max_results": 3},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["match_count"] == 3
    assert result["result_size_estimate"] == 3
    ids = [m["id"] for m in result["matches"]]
    assert ids == ["M1", "M2", "M3"]
    for m in result["matches"]:
        assert "error" not in m
        assert m["from"]
        assert m["to"] == "me@brisengroup.com"
        assert m["subject"]
        assert m["date"]
        assert m["snippet"]
        assert isinstance(m["label_ids"], list)
    assert "Baker" in result["matches"][0]["label_ids"]


def test_search_metadata_fetch_partial_failure(_patch_gmail_service):
    """Case 4: M2 metadata raises → M2 has error field, M1/M3 normal. NON-FATAL."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        list_response={
            "messages": [
                {"id": "M1", "threadId": "T1"},
                {"id": "M2", "threadId": "T2"},
                {"id": "M3", "threadId": "T3"},
            ],
            "resultSizeEstimate": 3,
        },
        metadata_responses={
            "M1": _metadata_payload(
                from_addr="alice@example.com",
                to_addr="me@brisengroup.com",
                subject="A",
                date="Mon, 25 May 2026 09:00:00 +0000",
                snippet="ok",
                thread_id="T1",
            ),
            "M3": _metadata_payload(
                from_addr="carol@example.com",
                to_addr="me@brisengroup.com",
                subject="C",
                date="Mon, 25 May 2026 09:30:00 +0000",
                snippet="ok3",
                thread_id="T3",
            ),
        },
        metadata_raises={"M2": RuntimeError("rate limited")},
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_search",
        {"query": "anything", "max_results": 3},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["match_count"] == 3
    by_id = {m["id"]: m for m in result["matches"]}
    assert "error" in by_id["M2"]
    assert "rate limited" in by_id["M2"]["error"]
    assert by_id["M2"]["thread_id"] == "T2"
    assert "error" not in by_id["M1"]
    assert "error" not in by_id["M3"]
    assert by_id["M1"]["subject"] == "A"
    assert by_id["M3"]["subject"] == "C"


def test_search_max_results_clamped(_patch_gmail_service):
    """Case 5: max_results=100 → server-side clamp to 50 in list() call."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        list_response={"messages": [], "resultSizeEstimate": 0},
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_search",
        {"query": "x", "max_results": 100},
    )
    result = json.loads(raw)
    assert "error" not in result
    list_mock = service.users.return_value.messages.return_value.list
    assert list_mock.called
    call_kwargs = list_mock.call_args.kwargs
    assert call_kwargs.get("maxResults") == 50
    assert call_kwargs.get("q") == "x"


def test_search_pagination_passthrough(_patch_gmail_service):
    """Case 6: next_page_token surfaced; page_token=PT_PRIOR passed to list()."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        list_response={
            "messages": [{"id": "M1", "threadId": "T1"}],
            "nextPageToken": "PT_42",
            "resultSizeEstimate": 100,
        },
        metadata_responses={
            "M1": _metadata_payload(
                from_addr="a@b.com",
                to_addr="me@brisengroup.com",
                subject="S",
                date="Mon, 25 May 2026 09:00:00 +0000",
                snippet="snip",
                thread_id="T1",
            ),
        },
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_search",
        {"query": "x", "max_results": 1, "page_token": "PT_PRIOR"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["next_page_token"] == "PT_42"
    list_mock = service.users.return_value.messages.return_value.list
    assert list_mock.call_args.kwargs.get("pageToken") == "PT_PRIOR"


# --------------------------------------------------------------------------- #
# baker_gmail_read_message — 6 mocked cases                                   #
# --------------------------------------------------------------------------- #


def _full_message_text_plain(
    *,
    body_text: str = "Hello, this is a test body.",
    attachments: list[tuple[str, int, str]] | None = None,
    headers_extra: list[dict] | None = None,
    msg_id: str = "MSG_R1",
    thread_id: str = "T_R1",
) -> dict:
    """Build a format='full' Gmail message with text/plain body + N attachments."""
    import base64 as _b64
    body_data = _b64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ascii")
    parts: list[dict] = [
        {
            "mimeType": "text/plain",
            "filename": "",
            "body": {"size": len(body_text), "data": body_data},
        },
    ]
    for fname, size, att_id in attachments or []:
        parts.append({
            "mimeType": "application/octet-stream",
            "filename": fname,
            "body": {"size": size, "attachmentId": att_id},
        })
    headers = [
        {"name": "From", "value": "sender@example.com"},
        {"name": "To", "value": "me@brisengroup.com"},
        {"name": "Subject", "value": "Test subject"},
        {"name": "Date", "value": "Mon, 25 May 2026 10:00:00 +0000"},
    ] + (headers_extra or [])
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": body_text[:50],
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": headers,
            "parts": parts,
        },
    }


def test_read_missing_message_id(_patch_gmail_service):
    """Case 1: empty message_id → error, no Gmail call."""
    import tools.gmail as gmail_mod

    raw = gmail_mod.dispatch_gmail("baker_gmail_read_message", {"message_id": ""})
    result = json.loads(raw)
    assert "error" in result
    assert "message_id" in result["error"]


def test_read_happy_path_text_plain_body(_patch_gmail_service):
    """Case 2: text/plain body + 2 attachments → body_text + 2 attachment entries."""
    import tools.gmail as gmail_mod

    full = _full_message_text_plain(
        body_text="This is the message body content.",
        attachments=[
            ("contract.pdf", 12345, "ATT_C"),
            ("invoice.xlsx", 6789, "ATT_I"),
        ],
        headers_extra=[{"name": "Cc", "value": "cc@brisengroup.com"}],
    )
    service = _build_service_mock(full_message_response=full)
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_read_message",
        {"message_id": "MSG_R1"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["message_id"] == "MSG_R1"
    assert result["thread_id"] == "T_R1"
    assert result["from"] == "sender@example.com"
    assert result["to"] == "me@brisengroup.com"
    assert result["cc"] == "cc@brisengroup.com"
    assert result["subject"] == "Test subject"
    assert "message body content" in result["body_text"]
    assert result["body_truncated"] is False
    assert len(result["attachments"]) == 2
    by_name = {a["filename"]: a for a in result["attachments"]}
    assert by_name["contract.pdf"]["size"] == 12345
    assert by_name["contract.pdf"]["mime_type"] == "application/pdf"
    assert by_name["invoice.xlsx"]["size"] == 6789
    assert "spreadsheet" in by_name["invoice.xlsx"]["mime_type"] or by_name["invoice.xlsx"]["mime_type"].endswith("xlsx")


def test_read_html_only_body_stripped(_patch_gmail_service):
    """Case 3: html-only body → stripped text returned (no tags, entities decoded)."""
    import tools.gmail as gmail_mod

    html_body = "<html><body><p>Hello &amp; goodbye <b>world</b></p></body></html>"
    html_data = base64.urlsafe_b64encode(html_body.encode("utf-8")).decode("ascii")
    full = {
        "id": "MSG_HTML",
        "threadId": "T_HTML",
        "snippet": "Hello",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/html",
            "filename": "",
            "headers": [
                {"name": "From", "value": "h@example.com"},
                {"name": "To", "value": "me@brisengroup.com"},
                {"name": "Subject", "value": "html-only"},
                {"name": "Date", "value": "Mon, 25 May 2026 11:00:00 +0000"},
            ],
            "body": {"size": len(html_body), "data": html_data},
        },
    }
    service = _build_service_mock(full_message_response=full)
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_read_message",
        {"message_id": "MSG_HTML"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert "<" not in result["body_text"]
    assert ">" not in result["body_text"]
    assert "Hello" in result["body_text"]
    assert "world" in result["body_text"]
    assert "&amp;" not in result["body_text"]
    assert "&" in result["body_text"]
    assert result["body_truncated"] is False
    assert result["attachments"] == []


def test_read_body_truncation(_patch_gmail_service):
    """Case 4: 60,000-char body → truncated to 50,000 + marker, body_truncated=True."""
    import tools.gmail as gmail_mod
    from tools.gmail import _BODY_TEXT_CAP_CHARS, _BODY_TRUNCATION_MARKER

    long_body = "x" * 60_000
    full = _full_message_text_plain(body_text=long_body, msg_id="MSG_LONG")
    service = _build_service_mock(full_message_response=full)
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_read_message",
        {"message_id": "MSG_LONG"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["body_truncated"] is True
    assert result["body_text"].endswith(_BODY_TRUNCATION_MARKER)
    assert len(result["body_text"]) == _BODY_TEXT_CAP_CHARS + len(_BODY_TRUNCATION_MARKER)


def test_read_message_fetch_exception(_patch_gmail_service):
    """Case 5: messages.get(format='full') raises → error 'message fetch failed'."""
    import tools.gmail as gmail_mod

    service = _build_service_mock(
        full_message_raises=RuntimeError("gmail down"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_read_message",
        {"message_id": "MSG_FAIL"},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "message fetch failed" in result["error"]


def test_read_no_attachments(_patch_gmail_service):
    """Case 6: only text/plain part, no attachment parts → attachments == []."""
    import tools.gmail as gmail_mod

    full = _full_message_text_plain(body_text="Plain body, no attachments.", msg_id="MSG_NOATT")
    service = _build_service_mock(full_message_response=full)
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_read_message",
        {"message_id": "MSG_NOATT"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["attachments"] == []
    assert result["body_truncated"] is False
    assert "Plain body" in result["body_text"]


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


@pytest.mark.skipif(
    os.getenv("TEST_GMAIL_LIVE") != "1",
    reason="Real-Gmail E2E. Set TEST_GMAIL_LIVE=1 + BAKER_GMAIL_* env vars to run.",
)
def test_e2e_real_gmail_search():
    """E2E: search for a known-stable query. Asserts no error + valid shape."""
    import tools.gmail as gmail_mod

    # 'from:me' always matches something in baker's mailbox (baker sends daily).
    # E2E_GMAIL_SEARCH_QUERY overrides for ad-hoc local testing.
    query = os.getenv("E2E_GMAIL_SEARCH_QUERY", "from:me")

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_search",
        {"query": query, "max_results": 3},
    )
    result = json.loads(raw)

    assert "error" not in result, f"E2E search returned error: {result}"
    assert "matches" in result
    assert isinstance(result["matches"], list)
    if result["match_count"] > 0:
        first = result["matches"][0]
        assert "id" in first
        assert "thread_id" in first
        if "error" not in first:
            assert "snippet" in first
            assert "from" in first


@pytest.mark.skipif(
    os.getenv("TEST_GMAIL_LIVE") != "1",
    reason="Real-Gmail E2E. Set TEST_GMAIL_LIVE=1 + BAKER_GMAIL_* env vars to run.",
)
def test_e2e_real_gmail_read_message():
    """E2E: read a known-stable message body. Uses E2E_GMAIL_MESSAGE_ID fixture."""
    import tools.gmail as gmail_mod

    fixture_message_id = os.getenv("E2E_GMAIL_MESSAGE_ID", "")
    if not fixture_message_id:
        pytest.skip("E2E fixture env var E2E_GMAIL_MESSAGE_ID not set")

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_read_message",
        {"message_id": fixture_message_id},
    )
    result = json.loads(raw)

    assert "error" not in result, f"E2E read returned error: {result}"
    assert result["message_id"] == fixture_message_id
    assert "from" in result
    assert "subject" in result
    assert "body_text" in result
    assert "attachments" in result
    assert isinstance(result["attachments"], list)
