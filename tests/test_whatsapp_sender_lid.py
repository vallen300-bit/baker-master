"""Tests for outputs/whatsapp_sender.py LID resolution + audit logging.

Why this test exists: 2026-05-05 — sends to Kira (46761387271@c.us) silently
failed because her active WhatsApp chat had migrated to @lid. Sender now
resolves @c.us → @lid via whatsapp_lid_map and audits every attempt.
"""
from unittest.mock import MagicMock, patch

import outputs.whatsapp_sender as sender


def _mock_store(lookup_row):
    """Build a SentinelStoreBack mock whose cursor returns lookup_row."""
    cur = MagicMock()
    cur.fetchone.return_value = lookup_row
    conn = MagicMock()
    conn.cursor.return_value = cur
    store = MagicMock()
    store._get_conn.return_value = conn
    store._put_conn = MagicMock()
    return store, conn, cur


def test_resolve_returns_lid_when_phone_has_mapping():
    store, _, cur = _mock_store(("10110470463618@lid",))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id("46761387271@c.us")
    assert result == "10110470463618@lid"
    cur.execute.assert_called_once()
    sql_arg, params = cur.execute.call_args.args
    assert "FROM whatsapp_messages" in sql_arg
    assert "ORDER BY timestamp DESC" in sql_arg
    assert params == ("46761387271@c.us",)


def test_resolve_returns_input_when_no_mapping():
    store, _, _ = _mock_store(None)
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id("99999999999@c.us")
    assert result == "99999999999@c.us"


def test_resolve_passes_through_non_cus_chat_ids():
    # Already an @lid or @s.whatsapp.net — no mapping needed
    assert sender._resolve_to_active_chat_id("10110470463618@lid") == "10110470463618@lid"
    assert sender._resolve_to_active_chat_id("") == ""


def test_resolve_fails_open_on_db_error():
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("db down")
    store = MagicMock()
    store._get_conn.return_value = conn
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id("46761387271@c.us")
    assert result == "46761387271@c.us"


def test_send_uses_resolved_chat_id_in_waha_call():
    store, _, _ = _mock_store(("10110470463618@lid",))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_log_send_to_baker_actions"):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = True
                resp.status_code = 200
                client_inst.post.return_value = resp
                ok = sender.send_whatsapp(text="hi", chat_id="46761387271@c.us")
    assert ok is True
    posted = client_inst.post.call_args
    assert posted.kwargs["json"]["chatId"] == "10110470463618@lid"


def test_send_audits_failure_with_response_body():
    store, _, _ = _mock_store(None)  # no LID mapping for this number
    captured = {}

    def fake_log(**kwargs):
        captured.update(kwargs)

    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_log_send_to_baker_actions", side_effect=fake_log):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = False
                resp.status_code = 422
                resp.text = '{"error":"chat not found"}'
                client_inst.post.return_value = resp
                ok = sender.send_whatsapp(text="hi", chat_id="99999999999@c.us")
    assert ok is False
    assert captured["success"] is False
    assert captured["http_status"] == 422
    assert "chat not found" in captured["error_message"]
