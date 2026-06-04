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
