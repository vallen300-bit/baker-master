"""BACKFILL_GRAPH_1 unit tests — paging + dedup. Mock Graph; no live creds in CI.

kbl.attachment_store (b3 EMAIL_ATTACHMENT_STORE_1) is on main — imported for
real; insert_attachment / insert_attachment_meta are monkeypatched per-test
(no sys.modules stub, so other test files see the genuine module — codex
re-gate #2807).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts import backfill_graph as bg


# ------------------------------------------------------------------ fixtures

def _msg(mid: str, has_att: bool = False, draft: bool = False) -> dict:
    return {
        "id": mid,
        "conversationId": f"conv-{mid}",
        "subject": f"subj {mid}",
        "from": {"emailAddress": {"name": "Mario Spanyi", "address": "m.spanyi@eh.at"}},
        "receivedDateTime": "2026-06-06T17:59:00Z",
        "body": {"content": "<p>hello <b>world</b></p>"},
        "isDraft": draft,
        "hasAttachments": has_att,
    }


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.cfg.mail_user = "dvallen@brisengroup.com"
    client.cfg.base_url = "https://graph.microsoft.com/v1.0"
    client._acquire_token.return_value = "tok"
    return client


def _fake_conn() -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    cur.rowcount = 1
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


# ------------------------------------------------------------------- paging

class TestPaging:
    def test_follows_next_link_until_exhausted(self):
        """Two pages chained by @odata.nextLink — both pages' messages processed."""
        client = _fake_client()
        conn = _fake_conn()
        page1 = {"value": [_msg("m1"), _msg("m2")],
                 "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page-2"}
        page2 = {"value": [_msg("m3")]}

        with patch.object(bg, "_graph_get", side_effect=[page1, page2]) as gg, \
             patch.object(bg, "_get_progress", return_value=(None, 0)), \
             patch.object(bg, "_set_progress") as sp, \
             patch.object(bg, "_folder_total", return_value=3), \
             patch.object(bg, "_insert_message", return_value=True) as im, \
             patch.object(bg.time, "sleep"):
            stats = bg.backfill_folder(conn, client, "Inbox")

        assert im.call_count == 3
        assert stats["inserted"] == 3
        # second _graph_get call followed the nextLink verbatim
        assert gg.call_args_list[1].args[1] == "https://graph.microsoft.com/v1.0/next-page-2"
        # final progress write marks the folder DONE
        final = sp.call_args_list[-1].args
        assert final[2] == bg.DONE_SENTINEL

    def test_cursor_persisted_per_page_for_resume(self):
        """After page 1 the saved cursor is page 2's nextLink (kill-safe resume)."""
        client = _fake_client()
        conn = _fake_conn()
        nxt = "https://graph.microsoft.com/v1.0/next-page-2"
        page1 = {"value": [_msg("m1")], "@odata.nextLink": nxt}
        page2 = {"value": [_msg("m2")]}

        with patch.object(bg, "_graph_get", side_effect=[page1, page2]), \
             patch.object(bg, "_get_progress", return_value=(None, 0)), \
             patch.object(bg, "_set_progress") as sp, \
             patch.object(bg, "_folder_total", return_value=2), \
             patch.object(bg, "_insert_message", return_value=True), \
             patch.object(bg.time, "sleep"):
            bg.backfill_folder(conn, client, "Inbox")

        # progress writes: fresh-start row, then page1 (cursor=nextLink), then DONE
        cursors = [c.args[2] for c in sp.call_args_list]
        assert nxt in cursors

    def test_resume_starts_from_saved_cursor(self):
        """A saved cursor is fetched directly — no fresh folder listing."""
        client = _fake_client()
        conn = _fake_conn()
        saved = "https://graph.microsoft.com/v1.0/saved-cursor"

        with patch.object(bg, "_graph_get", return_value={"value": [_msg("m9")]}) as gg, \
             patch.object(bg, "_get_progress", return_value=(saved, 100)), \
             patch.object(bg, "_set_progress"), \
             patch.object(bg, "_folder_total") as ft, \
             patch.object(bg, "_insert_message", return_value=True), \
             patch.object(bg.time, "sleep"):
            bg.backfill_folder(conn, client, "Inbox")

        assert gg.call_args_list[0].args[1] == saved
        ft.assert_not_called()

    def test_done_sentinel_skips_folder(self):
        client = _fake_client()
        conn = _fake_conn()
        with patch.object(bg, "_graph_get") as gg, \
             patch.object(bg, "_get_progress", return_value=(bg.DONE_SENTINEL, 500)):
            stats = bg.backfill_folder(conn, client, "Inbox")
        gg.assert_not_called()
        assert stats == {"inserted": 0, "skipped": 0, "attachments": 0}

    def test_done_sentinel_self_heals_heartbeat(self):
        # PY39_UNION_IMPORT_SWEEP_1: a folder already at DONE_SENTINEL must still
        # emit a DONE heartbeat on skip, so an already-complete folder self-heals
        # job_heartbeats without a manual reconciliation beat (mirrors bluewin).
        client = _fake_client()
        conn = _fake_conn()
        with patch.object(bg, "_graph_get") as gg, \
             patch.object(bg, "_hb") as hb, \
             patch.object(bg, "_get_progress", return_value=(bg.DONE_SENTINEL, 500)):
            stats = bg.backfill_folder(conn, client, "Inbox")
        gg.assert_not_called()
        hb.assert_called_once_with("Inbox", 500, "DONE")
        assert stats == {"inserted": 0, "skipped": 0, "attachments": 0}

    def test_limit_stops_with_cursor_saved(self):
        """--limit halts after the page that crosses it; cursor stays resumable."""
        client = _fake_client()
        conn = _fake_conn()
        nxt = "https://graph.microsoft.com/v1.0/next-page-2"
        page1 = {"value": [_msg(f"m{i}") for i in range(3)], "@odata.nextLink": nxt}

        with patch.object(bg, "_graph_get", side_effect=[page1]) as gg, \
             patch.object(bg, "_get_progress", return_value=(None, 0)), \
             patch.object(bg, "_set_progress") as sp, \
             patch.object(bg, "_folder_total", return_value=999), \
             patch.object(bg, "_insert_message", return_value=True), \
             patch.object(bg.time, "sleep"):
            bg.backfill_folder(conn, client, "Inbox", limit=2)

        assert gg.call_count == 1                       # never fetched page 2
        assert sp.call_args_list[-1].args[2] == nxt     # cursor saved, NOT DONE

    def test_drafts_skipped(self):
        client = _fake_client()
        conn = _fake_conn()
        page = {"value": [_msg("m1", draft=True), _msg("m2")]}
        with patch.object(bg, "_graph_get", return_value=page), \
             patch.object(bg, "_get_progress", return_value=(None, 0)), \
             patch.object(bg, "_set_progress"), \
             patch.object(bg, "_folder_total", return_value=2), \
             patch.object(bg, "_insert_message", return_value=True) as im, \
             patch.object(bg.time, "sleep"):
            bg.backfill_folder(conn, client, "Inbox")
        assert im.call_count == 1
        assert im.call_args.args[1]["id"] == "m2"


# -------------------------------------------------------------------- dedup

class TestDedup:
    def test_insert_uses_on_conflict_do_nothing(self):
        """Historical insert must be DO NOTHING (never clobber live-poller rows)."""
        conn = _fake_conn()
        bg._insert_message(conn, _msg("m1"))
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "ON CONFLICT (message_id) DO NOTHING" in sql
        assert "DO UPDATE" not in sql

    def test_priority_null_source_graph(self):
        """No LLM on historical rows: priority literal NULL, source literal 'graph'."""
        conn = _fake_conn()
        bg._insert_message(conn, _msg("m1"))
        cur = conn.cursor.return_value.__enter__.return_value
        sql = cur.execute.call_args.args[0]
        params = cur.execute.call_args.args[1]
        assert "NULL, 'graph'" in sql
        assert len(params) == 7          # priority/source are literals, not params

    def test_nul_bytes_stripped(self):
        """psycopg2 ValueError on 0x00 — hit live on historical Outlook HTML
        (dry-run 2026-06-10). All text params must be NUL-free."""
        conn = _fake_conn()
        m = _msg("m1")
        m["subject"] = "bad\x00subject"
        m["body"]["content"] = "<p>nul\x00body</p>"
        m["from"]["emailAddress"]["name"] = "Na\x00me"
        bg._insert_message(conn, m)
        params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[1]
        assert not any("\x00" in p for p in params if isinstance(p, str))

    def test_duplicate_returns_false(self):
        """rowcount 0 (conflict hit) reported as not-inserted."""
        conn = _fake_conn()
        conn.cursor.return_value.__enter__.return_value.rowcount = 0
        assert bg._insert_message(conn, _msg("m1")) is False

    def test_insert_db_error_retries_then_raises(self):
        """DB error ≠ dup (bus #2775): bounded retry, rollback each time, then
        loud RuntimeError carrying the message id — never a silent False."""
        conn = _fake_conn()
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = Exception("boom")
        with patch.object(bg.time, "sleep"):
            with pytest.raises(RuntimeError, match="message_id=m1"):
                bg._insert_message(conn, _msg("m1"))
        assert conn.rollback.call_count == bg.STORE_RETRIES

    def test_insert_db_error_recovers_on_retry(self):
        """Transient failure on attempt 1, success on attempt 2 — no raise."""
        conn = _fake_conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.execute.side_effect = [Exception("blip"), None]
        cur.rowcount = 1
        with patch.object(bg.time, "sleep"):
            assert bg._insert_message(conn, _msg("m1")) is True
        conn.rollback.assert_called_once()


# ---------------------------------------------------------------- throttling

class TestThrottle:
    def test_429_honors_retry_after(self):
        client = _fake_client()
        throttled = MagicMock(status_code=429, headers={"Retry-After": "7"})
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"value": []}
        with patch.object(bg.requests, "get", side_effect=[throttled, ok]), \
             patch.object(bg.time, "sleep") as slp:
            out = bg._graph_get(client, "https://graph.microsoft.com/v1.0/x")
        assert out == {"value": []}
        slp.assert_any_call(7)

    def test_non_graph_url_rejected(self):
        client = _fake_client()
        with pytest.raises(RuntimeError, match="non-Graph URL"):
            bg._graph_get(client, "https://evil.example.com/steal")
        client._acquire_token.assert_not_called()


# -------------------------------------------------------------- attachments

class TestAttachments:
    def test_file_attachment_decoded_and_stored(self):
        client = _fake_client()
        import base64 as b64
        page = {"value": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "a1", "name": "doc.pdf", "contentType": "application/pdf",
            "size": 5, "contentBytes": b64.b64encode(b"hello").decode(),
        }]}
        ins = MagicMock(return_value=1)
        with patch.object(bg, "_graph_get", return_value=page), \
             patch.object(bg, "insert_attachment", ins):
            n = bg._process_attachments(client, "u@x.com", "m1")
        assert n == 1
        ins.assert_called_once_with(
            "m1", "graph", "doc.pdf", "application/pdf", b"hello")

    def test_item_attachment_metadata_only_via_api(self):
        """itemAttachment routes to b3's insert_attachment_meta (bus #2765),
        meta_key = the Graph attachment id; insert_attachment untouched."""
        client = _fake_client()
        page = {"value": [{
            "@odata.type": "#microsoft.graph.itemAttachment",
            "id": "a2", "name": "fwd msg", "contentType": "message/rfc822", "size": 99,
        }]}
        ins = MagicMock(return_value=1)
        ins_meta = MagicMock(return_value=1)
        with patch.object(bg, "_graph_get", return_value=page), \
             patch.object(bg, "insert_attachment", ins), \
             patch.object(bg, "insert_attachment_meta", ins_meta):
            n = bg._process_attachments(client, "u@x.com", "m1")
        assert n == 1
        ins.assert_not_called()
        ins_meta.assert_called_once_with(
            "m1", "graph", "fwd msg", "message/rfc822", 99, meta_key="a2")

    def test_store_none_retries_then_raises(self):
        """bus #2775 class: store returning None must NOT count as stored —
        bounded retry, then loud RuntimeError with the message id."""
        client = _fake_client()
        import base64 as b64
        page = {"value": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "a1", "name": "doc.pdf", "contentType": "application/pdf",
            "size": 5, "contentBytes": b64.b64encode(b"hello").decode(),
        }]}
        ins = MagicMock(return_value=None)
        with patch.object(bg, "_graph_get", return_value=page), \
             patch.object(bg, "insert_attachment", ins), \
             patch.object(bg.time, "sleep"):
            with pytest.raises(RuntimeError, match="m1"):
                bg._process_attachments(client, "u@x.com", "m1")
        assert ins.call_count == bg.STORE_RETRIES

    def test_store_none_recovers_on_retry(self):
        client = _fake_client()
        import base64 as b64
        page = {"value": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "a1", "name": "doc.pdf", "contentType": "application/pdf",
            "size": 5, "contentBytes": b64.b64encode(b"hello").decode(),
        }]}
        ins = MagicMock(side_effect=[None, 7])
        with patch.object(bg, "_graph_get", return_value=page), \
             patch.object(bg, "insert_attachment", ins), \
             patch.object(bg.time, "sleep"):
            n = bg._process_attachments(client, "u@x.com", "m1")
        assert n == 1

    def test_store_failure_blocks_cursor_advance(self):
        """End-to-end (bus #2775): a store failure inside a page must abort
        backfill_folder BEFORE _set_progress persists that page's nextLink."""
        client = _fake_client()
        conn = _fake_conn()
        page = {"value": [_msg("m1", has_att=True)],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page-2"}
        with patch.object(bg, "_graph_get", return_value=page), \
             patch.object(bg, "_get_progress", return_value=(None, 0)), \
             patch.object(bg, "_set_progress") as sp, \
             patch.object(bg, "_folder_total", return_value=1), \
             patch.object(bg, "_insert_message", return_value=True), \
             patch.object(bg, "_process_attachments",
                          side_effect=RuntimeError("attachment store failure: m1")), \
             patch.object(bg.time, "sleep"):
            with pytest.raises(RuntimeError, match="m1"):
                bg.backfill_folder(conn, client, "Inbox")
        # only the fresh-start progress row was written — the failed page's
        # cursor was never persisted
        cursors = [c.args[2] for c in sp.call_args_list]
        assert "https://graph.microsoft.com/v1.0/next-page-2" not in cursors
        assert bg.DONE_SENTINEL not in cursors

    def test_message_db_error_blocks_cursor_advance(self):
        """End-to-end S1a (codex G3 #2781): a message-store DB error must abort
        backfill_folder BEFORE _set_progress persists that page's nextLink."""
        client = _fake_client()
        conn = _fake_conn()
        page = {"value": [_msg("m1")],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page-2"}
        with patch.object(bg, "_graph_get", return_value=page), \
             patch.object(bg, "_get_progress", return_value=(None, 0)), \
             patch.object(bg, "_set_progress") as sp, \
             patch.object(bg, "_folder_total", return_value=1), \
             patch.object(bg, "_insert_message",
                          side_effect=RuntimeError("message store failure: message_id=m1")), \
             patch.object(bg.time, "sleep"):
            with pytest.raises(RuntimeError, match="message_id=m1"):
                bg.backfill_folder(conn, client, "Inbox")
        cursors = [c.args[2] for c in sp.call_args_list]
        assert "https://graph.microsoft.com/v1.0/next-page-2" not in cursors
        assert bg.DONE_SENTINEL not in cursors
