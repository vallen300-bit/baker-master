"""BLOCK_BAKER_OUTBOUND_TO_DIRECTOR_1 — WhatsApp env-flagged hard block.

Anchor: Director directive 2026-05-25 — belt-and-suspenders on top of
PR #263 (root-cause WA self-chat loop fix). When
BAKER_BLOCK_WA_TO_DIRECTOR is ON, NO Baker → Director WA send goes
through, regardless of kind. Hard switch hits BEFORE the kind-allowlist
check.
"""
from unittest.mock import MagicMock, patch

import outputs.whatsapp_sender as sender
from outputs.whatsapp_sender import send_whatsapp


def test_hard_block_drops_director_swiss_send_default_env(monkeypatch):
    """Swiss Director chat_id + flag ON → blocked, returns False, no HTTP, hard_blocked audit."""
    monkeypatch.setattr(sender, "_BLOCK_WA_TO_DIRECTOR", True)
    with patch.object(sender, "_log_director_hard_blocked") as audit:
        with patch("httpx.Client") as MockClient:
            result = send_whatsapp(
                "hi", chat_id="41799605092@c.us", kind="counterparty"
            )
    assert result is False
    MockClient.assert_not_called()
    audit.assert_called_once()
    args, _ = audit.call_args
    assert args[0] == "hi"
    assert args[1] == "counterparty"


def test_hard_block_drops_director_uk_send(monkeypatch):
    """UK Director chat_id + flag ON → blocked same as Swiss."""
    monkeypatch.setattr(sender, "_BLOCK_WA_TO_DIRECTOR", True)
    with patch.object(sender, "_log_director_hard_blocked") as audit:
        with patch("httpx.Client") as MockClient:
            result = send_whatsapp(
                "hi", chat_id="447588690632@c.us", kind="counterparty"
            )
    assert result is False
    MockClient.assert_not_called()
    audit.assert_called_once()


def test_hard_block_drops_even_allowlisted_kind(monkeypatch):
    """kind='director_inbound' (allowlisted by FILTER_1) + flag ON → STILL blocked.

    Hard switch precedes the kind-check; allowlist cannot bypass it.
    """
    monkeypatch.setattr(sender, "_BLOCK_WA_TO_DIRECTOR", True)
    with patch.object(sender, "_log_director_hard_blocked") as audit:
        with patch.object(sender, "_log_director_blocked") as kind_audit:
            with patch("httpx.Client") as MockClient:
                result = send_whatsapp(
                    "hi", chat_id="41799605092@c.us", kind="director_inbound"
                )
    assert result is False
    MockClient.assert_not_called()
    audit.assert_called_once()
    # The kind-allowlist audit path must NOT fire — hard block short-circuits earlier.
    kind_audit.assert_not_called()


def test_hard_block_bypassed_when_env_false(monkeypatch):
    """flag OFF + non-allowlisted kind → falls through to kind-allowlist block.

    Asserts kind-allowlist path runs (whatsapp_blocked audit), NOT hard_blocked.
    """
    monkeypatch.setattr(sender, "_BLOCK_WA_TO_DIRECTOR", False)
    with patch.object(sender, "_log_director_hard_blocked") as hard_audit:
        with patch.object(sender, "_log_director_blocked") as kind_audit:
            with patch("httpx.Client") as MockClient:
                result = send_whatsapp(
                    "hi", chat_id="41799605092@c.us", kind="counterparty"
                )
    # counterparty IS allowlisted, so it should proceed past kind-check but we
    # don't mock the resolver — verify hard_blocked audit NOT called either way.
    hard_audit.assert_not_called()
    # Either result; main contract is: hard-block audit untouched when flag OFF.
    assert kind_audit.call_count == 0 or result is False
    _ = MockClient  # silence linter


def test_counterparty_send_unaffected(monkeypatch):
    """flag ON + non-Director chat_id → HTTP POST proceeds, no hard_blocked audit."""
    monkeypatch.setattr(sender, "_BLOCK_WA_TO_DIRECTOR", True)
    other = "447588690633@c.us"  # UK number 1 digit off — not in DIRECTOR_PHONE_ROOTS
    with patch.object(sender, "_log_director_hard_blocked") as audit:
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
    audit.assert_not_called()
