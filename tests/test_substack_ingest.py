"""Tests for SUBSTACK_NATE_INGEST_1."""
from __future__ import annotations

import base64
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from triggers.substack_ingest import (  # noqa: E402
    _detect_paid_tier,
    _extract_html_body,
    _extract_post_url,
    _html_to_markdown,
    _slugify,
    fetch_full_message,
    ingest,
    is_substack_nate,
    is_substack_nate_sender,
)


# --- Fixtures ---


@pytest.fixture
def nate_headers():
    return [
        {"name": "From", "value": "Nate from Nate's Newsletter <nate@natesnewsletter.substack.com>"},
        {"name": "Subject", "value": "How to evaluate an agent — the wrong way and the right way"},
        {"name": "List-Id", "value": "post.natesnewsletter.substack.com <a8b9c0d1.list-id.substack.com>"},
    ]


@pytest.fixture
def non_nate_headers():
    return [
        {"name": "From", "value": "noreply@github.com"},
        {"name": "Subject", "value": "PR #100 opened"},
    ]


@pytest.fixture
def fake_html_payload():
    html = """
    <html><body>
    <h1>How to evaluate an agent</h1>
    <p>Some content here.</p>
    <a href="https://natesnewsletter.substack.com/p/how-to-evaluate-an-agent?utm_source=email">Read in app</a>
    </body></html>
    """
    b64 = base64.urlsafe_b64encode(html.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": ""}},
            {"mimeType": "text/html", "body": {"data": b64}},
        ],
    }


# --- Classifier ---


def test_is_substack_nate_matches_list_id(nate_headers):
    assert is_substack_nate(nate_headers, "nate@natesnewsletter.substack.com") is True


def test_is_substack_nate_falls_back_to_sender(nate_headers):
    h = [x for x in nate_headers if x["name"] != "List-Id"]
    assert is_substack_nate(h, "nate@natesnewsletter.substack.com") is True


def test_is_substack_nate_rejects_non_substack(non_nate_headers):
    assert is_substack_nate(non_nate_headers, "noreply@github.com") is False


def test_is_substack_nate_handles_empty_inputs():
    assert is_substack_nate([], None) is False
    assert is_substack_nate(None, None) is False


def test_is_substack_nate_sender_matches_substring():
    assert is_substack_nate_sender("nate@natesnewsletter.substack.com") is True
    assert is_substack_nate_sender("Nate <nate@NatesNewsletter.SUBSTACK.com>") is True


def test_is_substack_nate_sender_rejects_other():
    assert is_substack_nate_sender(None) is False
    assert is_substack_nate_sender("") is False
    assert is_substack_nate_sender("noreply@github.com") is False


# --- Parser ---


def test_extract_html_body_walks_parts(fake_html_payload):
    html = _extract_html_body(fake_html_payload)
    assert html and "How to evaluate an agent" in html


def test_extract_post_url_strips_tracking(fake_html_payload):
    html = _extract_html_body(fake_html_payload)
    assert _extract_post_url(html) == "https://natesnewsletter.substack.com/p/how-to-evaluate-an-agent"


def test_detect_paid_tier_marker():
    html_paid = "<p>This post is for paying subscribers.</p>"
    html_free = "<p>Read on.</p>"
    assert _detect_paid_tier(html_paid) is True
    assert _detect_paid_tier(html_free) is False


def test_html_to_markdown_basic():
    md = _html_to_markdown("<h1>Hi</h1><p>One <b>two</b> three.</p>")
    assert "# Hi" in md
    assert "**two**" in md


def test_slugify_handles_punctuation():
    assert _slugify("How to evaluate — the right way?") == "how-to-evaluate-the-right-way"
    assert _slugify("") == "untitled"


# --- Idempotency + write ---


def test_ingest_writes_file_and_is_idempotent(tmp_path, fake_html_payload, nate_headers):
    received = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    out1 = ingest(
        gmail_message_id="abc123",
        headers=nate_headers,
        sender_email="nate@natesnewsletter.substack.com",
        subject="How to evaluate an agent",
        received_date=received,
        raw_payload=fake_html_payload,
        nate_dir=tmp_path,
    )
    assert out1 is not None and out1.exists()
    assert out1.name == "2026-05-23-how-to-evaluate-an-agent.md"

    content = out1.read_text(encoding="utf-8")
    assert "source: nate_substack" in content
    assert "paid_tier: false" in content
    assert "url: https://natesnewsletter.substack.com/p/how-to-evaluate-an-agent" in content
    assert "# How to evaluate an agent" in content

    out2 = ingest(
        gmail_message_id="abc123",
        headers=nate_headers,
        sender_email="nate@natesnewsletter.substack.com",
        subject="How to evaluate an agent",
        received_date=received,
        raw_payload=fake_html_payload,
        nate_dir=tmp_path,
    )
    assert out2 is None


def test_ingest_handles_mixed_quote_subject(tmp_path, fake_html_payload, nate_headers):
    """Mixed-quote subjects must yield YAML-valid frontmatter (json.dumps escaping).

    Pre-fix: `subject: {subject!r}` produced repr() output that emits single-quoted
    strings with embedded `"` unescaped (or vice versa for double-quoted strings
    with embedded `'`), which yaml.safe_load then rejects as invalid syntax.
    Fix: json.dumps always emits a double-quoted string with `"` + `\\` properly
    backslash-escaped — valid YAML by spec (YAML 1.2 §7.3.1 is a JSON superset).
    """
    received = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    subject = """Why "agents" can't reason about Nate's "tools" yet"""
    out = ingest(
        gmail_message_id="mixedq",
        headers=nate_headers,
        sender_email="nate@natesnewsletter.substack.com",
        subject=subject,
        received_date=received,
        raw_payload=fake_html_payload,
        nate_dir=tmp_path,
    )
    assert out is not None and out.exists()

    text = out.read_text(encoding="utf-8")
    fm_match = text.split("---\n", 2)
    assert len(fm_match) >= 3, "frontmatter block missing"
    parsed = yaml.safe_load(fm_match[1])
    assert parsed["subject"] == subject, (
        f"YAML round-trip failed: expected {subject!r}, got {parsed.get('subject')!r}"
    )


def test_ingest_handles_missing_html_part(tmp_path, nate_headers):
    """No HTML part → return None, do not crash."""
    received = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    out = ingest(
        gmail_message_id="abc123",
        headers=nate_headers,
        sender_email="nate@natesnewsletter.substack.com",
        subject="Missing HTML",
        received_date=received,
        raw_payload={"mimeType": "text/plain", "parts": []},
        nate_dir=tmp_path,
    )
    assert out is None
    assert list(tmp_path.iterdir()) == []


# --- fetch_full_message (Gmail round-trip helper) ---


def test_fetch_full_message_returns_none_when_service_unset(monkeypatch):
    """When _get_substack_service() returns None, helper returns None (does not raise)."""
    import triggers.substack_ingest as si
    monkeypatch.setattr(si, "_get_substack_service", lambda: None)
    assert fetch_full_message("anything") is None


def test_fetch_full_message_returns_payload_when_service_set(monkeypatch):
    """When substack svc is available, helper calls users().messages().get(...).execute()."""
    import triggers.substack_ingest as si
    expected = {"id": "m1", "payload": {"headers": [{"name": "List-Id", "value": "x"}]}}
    svc = MagicMock()
    svc.users.return_value.messages.return_value.get.return_value.execute.return_value = expected
    monkeypatch.setattr(si, "_get_substack_service", lambda: svc)

    assert fetch_full_message("m1") == expected
    svc.users.return_value.messages.return_value.get.assert_called_once_with(
        userId="me", id="m1", format="full",
    )


# --- SUBSTACK_NATE_PATCH_1 — defect patches ---


def test_fetch_full_message_returns_none_on_timeout(monkeypatch):
    """Fix 1: socket.timeout from httplib2-wrapped execute() → fetch_full_message returns None.

    Architecture-honest: under the new pattern, `_get_substack_service()` builds
    a Gmail service wrapped in `httplib2.Http(timeout=10)`. When the underlying
    socket exceeds the timeout, httplib2 raises `socket.timeout` from execute().
    No thread, no ThreadPoolExecutor shutdown wait — the exception unwinds the
    stack directly. Test stubs the failure path explicitly + asserts the
    `_safe_report_failure` audit fires.
    """
    import socket
    import triggers.substack_ingest as si

    svc = MagicMock()
    svc.users.return_value.messages.return_value.get.return_value.execute.side_effect = (
        socket.timeout("simulated httplib2 timeout")
    )
    monkeypatch.setattr(si, "_get_substack_service", lambda: svc)
    reported = []
    monkeypatch.setattr(
        si, "_safe_report_failure",
        lambda source, error: reported.append((source, error)),
    )

    result = fetch_full_message("hung_msg")
    assert result is None
    assert reported == [("substack_ingest", "fetch_full_message socket.timeout")], (
        f"expected exactly one socket.timeout audit row; got {reported}"
    )


def test_backfill_max_pages_guards_runaway_pagination(monkeypatch, caplog):
    """Fix 2: when Gmail returns infinite nextPageToken loop, MAX_PAGES breaks early.

    With MAX_PAGES now at module scope, monkeypatch it down to 3 for a fast
    deterministic test — no 200-iteration synthetic loop needed.
    """
    import logging as _logging
    import sys as _sys
    import types as _types

    # Stub googleapiclient.discovery + scripts.extract_gmail so the backfill
    # module can be imported in test envs where neither dep is installed
    # (prod ships with both). Import the real `scripts` package first to
    # avoid shadowing it with an empty stub.
    import scripts as _scripts_pkg  # noqa: F401 — ensures real package in sys.modules

    if "googleapiclient.discovery" not in _sys.modules:
        gapi_pkg = _sys.modules.get("googleapiclient") or _types.ModuleType("googleapiclient")
        gapi_disc = _types.ModuleType("googleapiclient.discovery")
        gapi_disc.build = lambda *a, **kw: None
        monkeypatch.setitem(_sys.modules, "googleapiclient", gapi_pkg)
        monkeypatch.setitem(_sys.modules, "googleapiclient.discovery", gapi_disc)
    if "scripts.extract_gmail" not in _sys.modules:
        eg_stub = _types.ModuleType("scripts.extract_gmail")
        eg_stub.authenticate = lambda: None
        eg_stub._gmail_service = None
        monkeypatch.setitem(_sys.modules, "scripts.extract_gmail", eg_stub)

    from scripts import backfill_nate_substack as backfill

    svc = MagicMock()
    svc.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "nextPageToken": "x",
        "messages": [],
    }
    monkeypatch.setattr(backfill, "authenticate", lambda: None)
    monkeypatch.setattr(backfill, "build", lambda *a, **kw: svc)
    monkeypatch.setattr(backfill, "MAX_PAGES", 3)

    with caplog.at_level(_logging.WARNING, logger="substack_backfill"):
        written = backfill.run(days=30, dry_run=True)

    assert written == 0
    list_calls = svc.users.return_value.messages.return_value.list.call_count
    assert list_calls == 3, f"expected exactly MAX_PAGES=3 list() calls; got {list_calls}"
    assert any("MAX_PAGES" in rec.message for rec in caplog.records), (
        "expected MAX_PAGES warning in caplog"
    )


def test_is_substack_nate_rejects_substring_spoofing():
    """Fix 3: tightened _LIST_ID_RE rejects substring-match from third-party Substack.

    Adversary List-Id `foo.substack.com <id> (re: natesnewsletter.substack.com)`
    must NOT pass — the canonical `post.natesnewsletter.substack.com` prefix is
    required.
    """
    spoof_headers = [
        {"name": "From", "value": "attacker@foo.substack.com"},
        {"name": "List-Id", "value": "foo.substack.com <id> (re: natesnewsletter.substack.com)"},
    ]
    assert is_substack_nate(spoof_headers, "attacker@foo.substack.com") is False


def test_is_substack_nate_accepts_canonical_list_id():
    """Positive coverage: canonical Nate List-Id still matches under tightened regex.

    Belt-and-braces — if a future regex tighten silently breaks the happy path,
    this test fails loud instead of letting Nate Substack ingest go quiet.
    """
    canonical_headers = [
        {"name": "From", "value": "nate@natesnewsletter.substack.com"},
        {"name": "List-Id", "value": "post.natesnewsletter.substack.com <a8b9c0d1.list-id.substack.com>"},
    ]
    assert is_substack_nate(canonical_headers, "nate@natesnewsletter.substack.com") is True
