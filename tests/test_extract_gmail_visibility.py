"""Visibility-patch regression test for scripts/extract_gmail.py.

Asserts that when _extract_text_from_bytes raises, a WARNING log line
is emitted carrying `err_type=` so production logs can name the actual
exception class from a single grep.

Anchor: BRIEF_GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 (Director-ratified 2026-05-25).
"""
from __future__ import annotations

import base64
import logging
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _fake_gmail_part_inline():
    """A Gmail attachment part where data is inline (not behind attachmentId)."""
    return {
        "filename": "test.pdf",
        "body": {
            "data": base64.urlsafe_b64encode(b"%PDF-1.4 fake-bytes").decode(),
            "size": 100,
        },
    }


def test_extract_text_from_bytes_failure_emits_warning_with_err_type(caplog):
    """When the extractor raises, _extract_text_from_bytes must log WARNING with err_type=."""
    from scripts import extract_gmail

    with patch("tools.ingest.extractors.extract", side_effect=ValueError("boom-test")):
        with caplog.at_level(logging.WARNING, logger="sentinel.gmail"):
            result = extract_gmail._extract_text_from_bytes(
                file_bytes=b"%PDF-1.4 fake-bytes",
                filename="test.pdf",
                ext=".pdf",
            )

    assert result is None, "_extract_text_from_bytes must return None on extractor failure"
    matching = [
        r for r in caplog.records
        if r.name == "sentinel.gmail" and r.levelno == logging.WARNING
        and "err_type=ValueError" in r.message
        and "_extract_text_from_bytes FAILED" in r.message
    ]
    assert len(matching) == 1, (
        f"Expected exactly 1 WARNING with err_type=ValueError, got {len(matching)}. "
        f"All sentinel.gmail records: {[(r.levelname, r.message) for r in caplog.records if r.name == 'sentinel.gmail']}"
    )


def test_format_thread_swallow_emits_warning_with_err_type(caplog, _fake_gmail_part_inline):
    """format_thread's wholesale except block must log WARNING with err_type= when called downstream raises."""
    from scripts import extract_gmail

    # Force the per-thread service binding to a non-None value so the attachment path runs.
    extract_gmail._gmail_service = MagicMock()
    # Force extract_attachments_text to raise.
    with patch.object(extract_gmail, "extract_attachments_text", side_effect=RuntimeError("boom-thread")):
        thread_data = {"id": "thr_test", "messages": []}
        messages = [{
            "id": "mid_test",
            "payload": {
                "headers": [
                    {"name": "From", "value": "test@example.com"},
                    {"name": "Subject", "value": "Subject test"},
                    {"name": "Date", "value": "Mon, 25 May 2026 10:00:00 +0000"},
                ],
                "body": {"data": base64.urlsafe_b64encode(("x" * 200).encode()).decode()},
            },
        }]

        with caplog.at_level(logging.WARNING, logger="sentinel.gmail"):
            try:
                extract_gmail.format_thread(thread_data, messages)
            except Exception:
                # format_thread may legitimately return None or partial; we care only about the log.
                pass

    matching = [
        r for r in caplog.records
        if r.name == "sentinel.gmail" and r.levelno == logging.WARNING
        and "err_type=RuntimeError" in r.message
        and "format_thread: extract_attachments_text raised" in r.message
    ]
    assert len(matching) == 1, (
        f"Expected exactly 1 WARNING with err_type=RuntimeError for format_thread swallow, got {len(matching)}. "
        f"All sentinel.gmail records: {[(r.levelname, r.message) for r in caplog.records if r.name == 'sentinel.gmail']}"
    )


def test_extract_attachments_text_unsupported_ext_emits_info_skip(caplog):
    """When attachment has unsupported extension, INFO log must fire with reason=unsupported_ext."""
    from scripts import extract_gmail

    # Build a message payload with one .xyz attachment (unsupported)
    message = {
        "id": "mid_unsupp",
        "payload": {
            "parts": [
                {
                    "filename": "presentation.xyz",
                    "mimeType": "application/octet-stream",
                    "body": {"size": 1000, "attachmentId": "ATT_X"},
                },
            ],
        },
    }
    service = MagicMock()

    with caplog.at_level(logging.INFO, logger="sentinel.gmail"):
        result = extract_gmail.extract_attachments_text(service, message)

    assert result == []
    matching = [
        r for r in caplog.records
        if r.name == "sentinel.gmail" and r.levelno == logging.INFO
        and "SKIP" in r.message and "reason=unsupported_ext" in r.message
        and "mid=mid_unsupp" in r.message and "presentation.xyz" in r.message
    ]
    assert len(matching) == 1, (
        f"Expected exactly 1 INFO SKIP with reason=unsupported_ext, got {len(matching)}. "
        f"All sentinel.gmail records: {[(r.levelname, r.message) for r in caplog.records if r.name == 'sentinel.gmail']}"
    )
