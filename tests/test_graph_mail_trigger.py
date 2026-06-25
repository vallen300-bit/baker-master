"""M365_GRAPH_MAIL_POLL_2 — unit tests for the Graph mail poller (mocked Graph).

Covers the 6 acceptance-criteria cases:
  1. dormant (is_ready False) → fully inert (no Graph/sink/DB/health side effects)
  2. 2 delta messages → 2 thread dicts in the exact sink shape
  3. @removed tombstones skipped (and drafts skipped)
  4. returned @odata.deltaLink persisted via set_cursor
  5. @odata.nextLink pagination followed
  6. failure path: ready-but-None raises in poll; caller reports_failure and does
     NOT advance watermark/cursor (silent-success bug must not regress)
"""
from unittest import mock

import pytest

import triggers.graph_mail_trigger as gmt


def _mk_msg(mid, conv, subject, name, addr, date, body="<p>hi</p>",
            is_draft=False):
    return {
        "id": mid,
        "conversationId": conv,
        "subject": subject,
        "from": {"emailAddress": {"name": name, "address": addr}},
        "receivedDateTime": date,
        "body": {"contentType": "html", "content": body},
        "isDraft": is_draft,
    }


def _fake_client(ready=True):
    client = mock.MagicMock(name="GraphClient")
    client.is_ready.return_value = ready
    client.cfg.mail_user = "dvallen@brisengroup.com"
    return client


# ── Test 1: dormant → fully inert ────────────────────────────────────────────
def test_dormant_is_fully_inert():
    client = _fake_client(ready=False)
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "should_skip_poll") as skip, \
         mock.patch.object(gmt, "report_success") as ok, \
         mock.patch.object(gmt, "report_failure") as fail, \
         mock.patch.object(gmt.trigger_state, "set_watermark") as wm, \
         mock.patch.object(gmt.trigger_state, "set_cursor") as cur, \
         mock.patch("triggers.email_trigger._process_email_threads") as sink:
        gmt.check_new_graph_messages()

    # zero Graph HTTP
    client.get.assert_not_called()
    client.get_url.assert_not_called()
    # zero DB + health + sink side effects
    skip.assert_not_called()
    ok.assert_not_called()
    fail.assert_not_called()
    wm.assert_not_called()
    cur.assert_not_called()
    sink.assert_not_called()


def test_poll_dormant_returns_empty():
    client = _fake_client(ready=False)
    with mock.patch.object(gmt, "GraphClient", return_value=client):
        assert gmt.poll_graph_mail() == []
    client.get.assert_not_called()
    client.get_url.assert_not_called()


# ── Test 2: 2 messages → 2 thread dicts in exact shape ───────────────────────
def test_two_messages_exact_thread_shape():
    page = {
        "value": [
            _mk_msg("m1", "c1", "Subject One", "Alice", "alice@x.com",
                    "2026-06-04T10:00:00Z", body="<b>Body one</b>"),
            _mk_msg("m2", "c2", "Subject Two", "Bob", "bob@y.com",
                    "2026-06-04T10:05:00Z", body="Body two"),
        ],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?$deltatoken=abc",
    }
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        threads = gmt.poll_graph_mail()

    assert len(threads) == 2
    t0 = threads[0]
    assert set(t0.keys()) == {"text", "metadata"}
    assert set(t0["metadata"].keys()) == {
        "source", "thread_id", "subject", "primary_sender",
        "primary_sender_email", "received_date",
    }
    assert t0["metadata"] == {
        "source": "graph",
        "thread_id": "c1",
        "subject": "Subject One",
        "primary_sender": "Alice",
        "primary_sender_email": "alice@x.com",
        "received_date": "2026-06-04T10:00:00Z",
    }
    assert t0["text"].startswith("Email Thread: Subject One")
    assert "Body one" in t0["text"]
    assert "<b>" not in t0["text"]            # HTML stripped
    assert threads[1]["metadata"]["thread_id"] == "c2"


# ── Test 3: @removed tombstones + drafts skipped ─────────────────────────────
def test_removed_and_drafts_skipped():
    page = {
        "value": [
            _mk_msg("m1", "c1", "Real", "Alice", "alice@x.com",
                    "2026-06-04T10:00:00Z"),
            {"id": "m2", "@removed": {"reason": "deleted"}},
            _mk_msg("m3", "c3", "Draft", "Me", "me@x.com",
                    "2026-06-04T10:10:00Z", is_draft=True),
        ],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?$deltatoken=z",
    }
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        threads = gmt.poll_graph_mail()

    assert len(threads) == 1
    assert threads[0]["metadata"]["thread_id"] == "c1"


# ── Test 4: deltaLink persisted via set_cursor ───────────────────────────────
def test_deltalink_persisted():
    delta = "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=persist-me"
    page = {"value": [], "@odata.deltaLink": delta}
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor:
        threads = gmt.poll_graph_mail()

    assert threads == []
    set_cursor.assert_called_once_with("graph_mail_poll", delta)


def test_stored_cursor_followed_via_get_url():
    """First-run cursor present → followed via get_url (host-pin), not get()."""
    stored = "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=stored"
    page = {"value": [], "@odata.deltaLink": stored + "-next"}
    client = _fake_client(ready=True)
    client.get_url.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=stored), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        gmt.poll_graph_mail()

    client.get_url.assert_called_once_with(stored)
    client.get.assert_not_called()


# ── Test 5: nextLink pagination followed ─────────────────────────────────────
def test_nextlink_pagination_followed():
    next_url = "https://graph.microsoft.com/v1.0/me/delta?$skiptoken=page2"
    delta = "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=final"
    page1 = {
        "value": [_mk_msg("m1", "c1", "P1", "A", "a@x.com",
                          "2026-06-04T10:00:00Z")],
        "@odata.nextLink": next_url,
    }
    page2 = {
        "value": [_mk_msg("m2", "c2", "P2", "B", "b@x.com",
                          "2026-06-04T10:05:00Z")],
        "@odata.deltaLink": delta,
    }
    client = _fake_client(ready=True)
    client.get.return_value = page1
    client.get_url.return_value = page2
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor:
        threads = gmt.poll_graph_mail()

    client.get_url.assert_called_once_with(next_url)
    assert [t["metadata"]["thread_id"] for t in threads] == ["c1", "c2"]
    set_cursor.assert_called_once_with("graph_mail_poll", delta)


# ── Test 6: failure path — ready-but-None raises; no silent success ──────────
def test_ready_but_none_raises():
    client = _fake_client(ready=True)
    client.get.return_value = None
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None):
        with pytest.raises(RuntimeError):
            gmt.poll_graph_mail()


def test_nextlink_none_mid_pagination_raises():
    next_url = "https://graph.microsoft.com/v1.0/me/delta?$skiptoken=page2"
    page1 = {"value": [], "@odata.nextLink": next_url}
    client = _fake_client(ready=True)
    client.get.return_value = page1
    client.get_url.return_value = None
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor:
        with pytest.raises(RuntimeError):
            gmt.poll_graph_mail()
    set_cursor.assert_not_called()     # no partial cursor persisted


def test_check_failure_reports_and_does_not_advance():
    client = _fake_client(ready=True)
    client.get.return_value = None     # ready-but-None → poll raises
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "should_skip_poll", return_value=False), \
         mock.patch.object(gmt, "report_success") as ok, \
         mock.patch.object(gmt, "report_failure") as fail, \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor, \
         mock.patch.object(gmt.trigger_state, "set_watermark") as set_wm:
        gmt.check_new_graph_messages()    # must NOT raise to scheduler

    fail.assert_called_once()
    assert fail.call_args[0][0] == "graph_mail"
    ok.assert_not_called()
    set_wm.assert_not_called()         # watermark NOT advanced on failure
    set_cursor.assert_not_called()     # cursor NOT advanced on failure


def test_check_success_advances_watermark_and_calls_sink():
    page = {
        "value": [_mk_msg("m1", "c1", "S", "A", "a@x.com",
                          "2026-06-04T10:00:00Z")],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=ok",
    }
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "should_skip_poll", return_value=False), \
         mock.patch.object(gmt, "report_success") as ok, \
         mock.patch.object(gmt, "report_failure") as fail, \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"), \
         mock.patch.object(gmt.trigger_state, "set_watermark") as set_wm, \
         mock.patch("triggers.email_trigger._process_email_threads") as sink:
        gmt.check_new_graph_messages()

    sink.assert_called_once()
    assert len(sink.call_args[0][0]) == 1     # one thread handed to sink
    set_wm.assert_called_once()
    ok.assert_called_once_with("graph_mail")
    fail.assert_not_called()


# ---------------------------------------------------------------------------
# M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1 — AAQk immutable-id attachment-skip fix.
#
# Root cause (b2 bus #4257): messages whose id is immutable-form (base64url,
# '-'/'_') had attachments silently dropped because the by-id Graph attachment
# fetch was issued WITHOUT Prefer: IdType="ImmutableId". Fix: detect id form,
# set the header for immutable ids, and surface any fetch failure loudly.
# ---------------------------------------------------------------------------

# A real immutable-id-form id (base64url: contains '-' and '_') and a standard
# (base64) id (uses '+' and '/'), mirroring the AAQk vs AAMk forms in the brief.
_IMMUTABLE_ID = "AAQkAGI2T-Hg_x9Q1Zr0nBcVg8w=="
_STANDARD_ID = "AAMkAGI2THg+x9Q/1Zr0nBcVg8w=="


@pytest.fixture(autouse=True)
def _reset_attachment_counter():
    gmt._attachment_fetch_failures = 0
    yield
    gmt._attachment_fetch_failures = 0


def _att(name="doc.pdf", ctype="application/pdf", content=b"PDFDATA", inline=False):
    import base64 as _b64
    return {
        "id": "att-1",
        "name": name,
        "contentType": ctype,
        "size": len(content),
        "contentBytes": _b64.b64encode(content).decode(),
        "isInline": inline,
    }


def test_id_form_discriminator():
    # base64url chars => immutable; base64 (+,/) => standard.
    assert gmt._is_immutable_message_id(_IMMUTABLE_ID) is True
    assert gmt._is_immutable_message_id(_STANDARD_ID) is False


def test_immutable_id_sets_prefer_header_and_persists():
    """AC1 (test-shaped): immutable-id message -> Prefer header sent, attachment persists."""
    client = _fake_client()
    client.get.return_value = {"value": [_att()]}
    m = {"id": _IMMUTABLE_ID, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1") as ins:
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 1
    ins.assert_called_once()
    # The by-id attachment fetch MUST carry Prefer: IdType="ImmutableId".
    assert client.get.call_args.kwargs.get("extra_headers") == {"Prefer": 'IdType="ImmutableId"'}
    assert gmt.attachment_fetch_failures() == 0


def test_standard_id_no_prefer_header():
    """No regression: standard (AAMk) id fetched WITHOUT the immutable header."""
    client = _fake_client()
    client.get.return_value = {"value": [_att()]}
    m = {"id": _STANDARD_ID, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1"):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 1
    assert client.get.call_args.kwargs.get("extra_headers") is None


def test_failed_fetch_is_surfaced_not_silent(caplog):
    """AC2: a None (failed) by-id fetch on hasAttachments=true is surfaced, never silent."""
    client = _fake_client()
    client.get.return_value = None            # simulate AAQk by-id failure
    m = {"id": _IMMUTABLE_ID, "hasAttachments": True}
    import logging
    with caplog.at_level(logging.ERROR):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 0
    assert gmt.attachment_fetch_failures() == 1            # surfaced via counter
    assert any("FAILED" in r.message for r in caplog.records)   # surfaced via ERROR log


def test_exception_during_capture_is_surfaced(caplog):
    """AC2: an exception mid-capture also counts + logs, never silently returns 0."""
    client = _fake_client()
    client.get.side_effect = RuntimeError("boom")
    m = {"id": _IMMUTABLE_ID, "hasAttachments": True}
    import logging
    with caplog.at_level(logging.ERROR):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 0
    assert gmt.attachment_fetch_failures() == 1


def test_all_inline_is_benign_no_failure_count(caplog):
    """Successful fetch, only inline parts -> 0 stored, surfaced as WARNING, NOT a failure."""
    client = _fake_client()
    client.get.return_value = {"value": [_att(inline=True)]}
    m = {"id": _IMMUTABLE_ID, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1"):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 0
    assert gmt.attachment_fetch_failures() == 0            # benign, not a failure


def test_no_attachments_flag_skips_fetch():
    """hasAttachments=false -> no Graph call at all."""
    client = _fake_client()
    m = {"id": _IMMUTABLE_ID, "hasAttachments": False}
    assert gmt._capture_graph_attachments(client, m) == 0
    client.get.assert_not_called()
