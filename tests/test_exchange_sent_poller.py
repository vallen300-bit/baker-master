"""
BAKER_CAPTURE_BLINDSPOTS_1: Tests for Exchange Sent-folder sibling poller.
"""

from __future__ import annotations

import email
from datetime import datetime, timezone
from unittest import mock

import pytest

from triggers import exchange_poller


# ---- _detect_sent_folder -----------------------------------------------------


def _make_list_response(*folder_names: str):
    """Build a fake IMAP LIST tuple shaped (status, [b'(...) "/" "<name>"', ...])."""
    rows = [
        f'(\\HasNoChildren) "/" "{name}"'.encode("utf-8") for name in folder_names
    ]
    return ("OK", rows)


def test_detect_sent_folder_finds_sent_items():
    conn = mock.Mock()
    conn.list.return_value = _make_list_response("INBOX", "Drafts", "Sent Items", "Trash")
    assert exchange_poller._detect_sent_folder(conn) == "Sent Items"


def test_detect_sent_folder_prefers_first_candidate():
    """Candidate order is Sent Items > Sent > INBOX.Sent."""
    conn = mock.Mock()
    conn.list.return_value = _make_list_response("INBOX", "Sent", "Sent Items")
    assert exchange_poller._detect_sent_folder(conn) == "Sent Items"


def test_detect_sent_folder_returns_none_when_absent():
    conn = mock.Mock()
    conn.list.return_value = _make_list_response("INBOX", "Drafts", "Trash")
    assert exchange_poller._detect_sent_folder(conn) is None


def test_detect_sent_folder_swallows_list_failure():
    conn = mock.Mock()
    conn.list.return_value = ("NO", [])
    assert exchange_poller._detect_sent_folder(conn) is None


def test_detect_sent_folder_handles_unquoted_names():
    """AH2 review bus #1350 MEDIUM: some Exchange configs return bare folder
    names without quotes (RFC-3501 atom form). Without the unquoted fallback
    the Sent poll silently disables on those servers."""
    conn = mock.Mock()
    conn.list.return_value = (
        "OK",
        [
            b"(\\HasNoChildren) / INBOX",
            b"(\\HasNoChildren) / Drafts",
            b"(\\HasNoChildren) / Sent",
            b"(\\HasNoChildren) / Trash",
        ],
    )
    assert exchange_poller._detect_sent_folder(conn) == "Sent"


def test_detect_sent_folder_mixed_quoted_and_unquoted():
    conn = mock.Mock()
    conn.list.return_value = (
        "OK",
        [
            b'(\\HasNoChildren) "/" "INBOX"',
            b"(\\HasNoChildren) / Sent",
        ],
    )
    assert exchange_poller._detect_sent_folder(conn) == "Sent"


# ---- poll_exchange_sent ------------------------------------------------------


def _bypass_retirement(monkeypatch):
    """RETIRE_DEAD_EVOK_SENTINELS_1: poll_exchange_sent() now short-circuits via
    should_skip_poll('exchange_sent') -> True. The IMAP mechanics below still
    exist (lead kept the shared code), so bypass the retirement guard to keep
    that logic under test. poll_exchange_sent imports the symbol at call time,
    so patching it on the source module takes effect."""
    monkeypatch.setattr("triggers.sentinel_health.should_skip_poll", lambda s: False)


def test_poll_exchange_sent_retired_short_circuits(monkeypatch):
    """The Evok Sent source is retired: even with a password + a working mock
    connection, the poller returns [] without touching IMAP."""
    monkeypatch.setattr(exchange_poller, "EXCHANGE_PASS", "secret")
    with mock.patch("triggers.exchange_poller.imaplib.IMAP4_SSL") as imap:
        assert exchange_poller.poll_exchange_sent() == []
        imap.assert_not_called()


def test_poll_exchange_sent_skips_when_no_password(monkeypatch):
    _bypass_retirement(monkeypatch)
    monkeypatch.setattr(exchange_poller, "EXCHANGE_PASS", "")
    assert exchange_poller.poll_exchange_sent() == []


def _fake_state(monkeypatch, *, wm_dt: datetime | None, watermark_sink: list):
    """Patch triggers.state.TriggerState so the poller uses a controllable stub."""

    class _StubState:
        def get_watermark(self, source):
            return wm_dt

        def set_watermark(self, source, timestamp):
            watermark_sink.append((source, timestamp))

        def is_processed(self, source, source_id):
            return False

        def mark_processed(self, source, source_id):
            pass

    import triggers.state as state_module

    monkeypatch.setattr(state_module, "TriggerState", lambda: _StubState())


def _build_raw_email(message_id: str, subject: str, body: str, date_hdr: str) -> bytes:
    msg = email.message.EmailMessage()
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = "Dimitry Vallen <dvallen@brisengroup.com>"
    msg["To"] = "peter@example.com"
    msg["Date"] = date_hdr
    msg.set_content(body)
    return msg.as_bytes()


def test_poll_exchange_sent_returns_outbound_and_advances_watermark(monkeypatch):
    _bypass_retirement(monkeypatch)
    monkeypatch.setattr(exchange_poller, "EXCHANGE_PASS", "secret")

    watermark_sink: list = []
    _fake_state(
        monkeypatch,
        wm_dt=datetime(2026, 5, 25, tzinfo=timezone.utc),
        watermark_sink=watermark_sink,
    )

    raw_email = _build_raw_email(
        message_id="<sent-1@brisengroup.com>",
        subject="Test outbound",
        body="Hello Peter, the deck is attached.",
        date_hdr="Fri, 29 May 2026 14:23:01 +0000",
    )

    conn = mock.Mock()
    conn.login.return_value = ("OK", [b"Logged in"])
    conn.list.return_value = _make_list_response("INBOX", "Sent Items")
    conn.select.return_value = ("OK", [b"1"])
    conn.search.return_value = ("OK", [b"42"])
    conn.fetch.return_value = ("OK", [(b"42 (RFC822 {123}", raw_email), b")"])

    with mock.patch("triggers.exchange_poller.imaplib.IMAP4_SSL", return_value=conn):
        results = exchange_poller.poll_exchange_sent()

    assert len(results) == 1
    row = results[0]
    assert row["metadata"]["source"] == exchange_poller.SOURCE_TYPE_SENT
    assert row["metadata"]["primary_sender_email"] == "dvallen@brisengroup.com"
    assert row["metadata"]["thread_id"] == "sent-1@brisengroup.com"
    assert "Test outbound" in row["text"]

    # Watermark advanced to the message's received_dt.
    assert len(watermark_sink) == 1
    src, ts = watermark_sink[0]
    assert src == exchange_poller.WATERMARK_KEY_SENT
    assert ts.year == 2026 and ts.month == 5 and ts.day == 29

    # Sent folder was selected, not INBOX.
    conn.select.assert_called_once()
    assert conn.select.call_args[0][0] == '"Sent Items"'


def test_poll_exchange_sent_returns_empty_when_sent_folder_missing(monkeypatch):
    _bypass_retirement(monkeypatch)
    monkeypatch.setattr(exchange_poller, "EXCHANGE_PASS", "secret")

    watermark_sink: list = []
    _fake_state(
        monkeypatch,
        wm_dt=datetime(2026, 5, 25, tzinfo=timezone.utc),
        watermark_sink=watermark_sink,
    )

    conn = mock.Mock()
    conn.login.return_value = ("OK", [b"Logged in"])
    conn.list.return_value = _make_list_response("INBOX", "Drafts", "Trash")

    with mock.patch("triggers.exchange_poller.imaplib.IMAP4_SSL", return_value=conn):
        results = exchange_poller.poll_exchange_sent()

    assert results == []
    conn.select.assert_not_called()
    assert watermark_sink == []  # no watermark advance on no-folder path
