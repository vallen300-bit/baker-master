"""BACKFILL_GRAPH_1 unit tests — paging + dedup. Mock Graph; no live creds in CI.

kbl.attachment_store (b3 EMAIL_ATTACHMENT_STORE_1) may not be importable until
b3's lane merges — it is stubbed into sys.modules BEFORE importing the script,
so these tests are independent of merge order.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# --- stub kbl.attachment_store before the module under test imports it ------
_att_store_stub = types.ModuleType("kbl.attachment_store")
_att_store_stub.insert_attachment = MagicMock(return_value=1)
_att_store_stub.insert_attachment_meta = MagicMock(return_value=1)
sys.modules.setdefault("kbl.attachment_store", _att_store_stub)

from scripts import backfill_graph as bg  # noqa: E402


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

    def test_duplicate_returns_false(self):
        """rowcount 0 (conflict hit) reported as not-inserted."""
        conn = _fake_conn()
        conn.cursor.return_value.__enter__.return_value.rowcount = 0
        assert bg._insert_message(conn, _msg("m1")) is False

    def test_insert_failure_rolls_back_and_returns_false(self):
        conn = _fake_conn()
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = Exception("boom")
        assert bg._insert_message(conn, _msg("m1")) is False
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
        _att_store_stub.insert_attachment.reset_mock()
        with patch.object(bg, "_graph_get", return_value=page):
            n = bg._process_attachments(client, "u@x.com", "m1")
        assert n == 1
        _att_store_stub.insert_attachment.assert_called_once_with(
            "m1", "graph", "doc.pdf", "application/pdf", b"hello")

    def test_item_attachment_metadata_only_via_api(self):
        """itemAttachment routes to b3's insert_attachment_meta (bus #2765),
        meta_key = the Graph attachment id; insert_attachment untouched."""
        client = _fake_client()
        page = {"value": [{
            "@odata.type": "#microsoft.graph.itemAttachment",
            "id": "a2", "name": "fwd msg", "contentType": "message/rfc822", "size": 99,
        }]}
        _att_store_stub.insert_attachment.reset_mock()
        _att_store_stub.insert_attachment_meta.reset_mock()
        with patch.object(bg, "_graph_get", return_value=page):
            n = bg._process_attachments(client, "u@x.com", "m1")
        assert n == 1
        _att_store_stub.insert_attachment.assert_not_called()
        _att_store_stub.insert_attachment_meta.assert_called_once_with(
            "m1", "graph", "fwd msg", "message/rfc822", 99, meta_key="a2")
