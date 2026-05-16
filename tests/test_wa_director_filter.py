"""BAKER_WA_DIRECTOR_FILTER_1 — Director-bound WA send rejection.

Anchor: Director directive 2026-05-15 — "Baker NEVER WhatsApps me about its
own internal infrastructure." Chokepoint at outputs/whatsapp_sender.py
requires Director-bound calls to pass an allowlisted kind= or get blocked
before any WAHA HTTP call.
"""
from unittest.mock import MagicMock, patch

import outputs.whatsapp_sender as sender
from outputs.whatsapp_sender import (
    DIRECTOR_WA_ALLOWED_KINDS,
    DIRECTOR_WHATSAPP,
    send_whatsapp,
)


def test_director_send_without_kind_blocked():
    """No kind= + Director chat_id → blocked, returns False, no HTTP call."""
    with patch.object(sender, "_log_director_blocked") as audit:
        with patch("httpx.Client") as MockClient:
            result = send_whatsapp("test alert", chat_id=DIRECTOR_WHATSAPP)
    assert result is False
    MockClient.assert_not_called()
    audit.assert_called_once()
    args, kwargs = audit.call_args
    assert args[0] == "test alert"
    assert args[1] is None


def test_director_send_with_infra_kind_blocked():
    """kind='scheduler' (not in allowlist) + Director chat_id → blocked."""
    with patch.object(sender, "_log_director_blocked") as audit:
        with patch("httpx.Client") as MockClient:
            result = send_whatsapp("test", chat_id=DIRECTOR_WHATSAPP, kind="scheduler")
    assert result is False
    MockClient.assert_not_called()
    audit.assert_called_once()
    assert audit.call_args.args[1] == "scheduler"


def test_director_send_with_allowlisted_kind_allowed():
    """kind='counterparty' + Director chat_id → reaches the WAHA HTTP call."""
    # Patch the LID resolver to short-circuit (return same chat_id) and the
    # baker_actions audit emitter so we don't need a DB. Patch httpx.Client to
    # verify a POST is actually issued.
    with patch.object(sender, "_resolve_to_active_chat_id", side_effect=lambda c: c):
        with patch.object(sender, "_log_send_to_baker_actions"):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = True
                resp.status_code = 200
                client_inst.post.return_value = resp
                result = send_whatsapp(
                    "AO sent a thing",
                    chat_id=DIRECTOR_WHATSAPP,
                    kind="counterparty",
                )
    assert result is True
    client_inst.post.assert_called_once()
    posted = client_inst.post.call_args
    assert posted.kwargs["json"]["chatId"] == DIRECTOR_WHATSAPP
    assert posted.kwargs["json"]["text"] == "AO sent a thing"


def test_non_director_chat_id_kind_optional():
    """Non-Director chat_id → kind not required; call proceeds to WAHA."""
    other = "41XXXXXXXXX@c.us"
    with patch.object(sender, "_resolve_to_active_chat_id", side_effect=lambda c: c):
        with patch.object(sender, "_log_send_to_baker_actions"):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = True
                resp.status_code = 200
                client_inst.post.return_value = resp
                result = send_whatsapp("hi", chat_id=other)
    assert result is True
    client_inst.post.assert_called_once()


def test_allowlist_contents():
    """Allowlist contains exactly the 7 Director-ratified kinds.

    Added `kbl_critical` post-REQUEST_CHANGES on PR #208 (AH1 2026-05-16):
    KBL CRITICAL alerts (Anthropic circuit / KBL cost cap) are
    Director-actionable infra and must pass the chokepoint. See
    kbl/logging.py:169.
    """
    assert DIRECTOR_WA_ALLOWED_KINDS == frozenset({
        "counterparty",
        "legal_threat",
        "deadline",
        "vip_signal",
        "financial",
        "director_inbound",
        "kbl_critical",
    })


def test_director_send_with_kbl_critical_kind_allowed():
    """kind='kbl_critical' + Director chat_id → reaches the WAHA HTTP call."""
    with patch.object(sender, "_resolve_to_active_chat_id", side_effect=lambda c: c):
        with patch.object(sender, "_log_send_to_baker_actions"):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = True
                resp.status_code = 200
                client_inst.post.return_value = resp
                result = send_whatsapp(
                    "[KBL CRITICAL] anthropic_client: circuit opened",
                    chat_id=DIRECTOR_WHATSAPP,
                    kind="kbl_critical",
                )
    assert result is True
    client_inst.post.assert_called_once()
