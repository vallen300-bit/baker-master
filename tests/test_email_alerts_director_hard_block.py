"""BLOCK_BAKER_OUTBOUND_TO_DIRECTOR_1 — email env-flagged hard block.

Anchor: Director directive 2026-05-25 — recipient-based hard block at the
lowest send primitive in outputs/email_alerts.py, covering Type 4 manual
summary, Type 5 composed email, and any future caller. Companion to the
WhatsApp hard block.
"""
from unittest.mock import patch

import outputs.email_alerts as email_alerts
from outputs.email_alerts import _send_raw_full


def test_hard_block_drops_brisengroup_email(monkeypatch):
    """dvallen@brisengroup.com + flag ON → blocked, returns None, no Gmail call, audit row."""
    monkeypatch.setattr(email_alerts, "_BLOCK_EMAIL_TO_DIRECTOR", True)
    with patch.object(email_alerts, "_log_email_director_hard_blocked") as audit:
        with patch.object(email_alerts, "_get_gmail_service") as svc:
            result = _send_raw_full("dvallen@brisengroup.com", "subj", "body")
    assert result is None
    svc.assert_not_called()
    audit.assert_called_once()
    args, _ = audit.call_args
    assert args[0] == "dvallen@brisengroup.com"
    assert args[1] == "subj"


def test_hard_block_drops_personal_gmail(monkeypatch):
    """vallen300@gmail.com + flag ON → blocked same as primary."""
    monkeypatch.setattr(email_alerts, "_BLOCK_EMAIL_TO_DIRECTOR", True)
    with patch.object(email_alerts, "_log_email_director_hard_blocked") as audit:
        with patch.object(email_alerts, "_get_gmail_service") as svc:
            result = _send_raw_full("vallen300@gmail.com", "subj", "body")
    assert result is None
    svc.assert_not_called()
    audit.assert_called_once()


def test_hard_block_drops_uppercase_and_whitespace(monkeypatch):
    """`.strip().lower()` normalization catches Mixed-Case + leading/trailing whitespace."""
    monkeypatch.setattr(email_alerts, "_BLOCK_EMAIL_TO_DIRECTOR", True)
    with patch.object(email_alerts, "_log_email_director_hard_blocked") as audit:
        with patch.object(email_alerts, "_get_gmail_service") as svc:
            result = _send_raw_full(
                "  DVallen@BrisenGroup.COM  ", "subj", "body"
            )
    assert result is None
    svc.assert_not_called()
    audit.assert_called_once()


def test_hard_block_bypassed_when_env_false(monkeypatch):
    """flag OFF + Director email → Gmail API attempted."""
    monkeypatch.setattr(email_alerts, "_BLOCK_EMAIL_TO_DIRECTOR", False)
    with patch.object(email_alerts, "_log_email_director_hard_blocked") as audit:
        with patch.object(email_alerts, "_get_gmail_service") as svc:
            fake_service = svc.return_value
            fake_send = (
                fake_service.users.return_value.messages.return_value.send.return_value
            )
            fake_send.execute.return_value = {"id": "m1", "threadId": "t1"}
            result = _send_raw_full("dvallen@brisengroup.com", "subj", "body")
    assert result == {"message_id": "m1", "thread_id": "t1"}
    svc.assert_called_once()
    audit.assert_not_called()


def test_counterparty_email_unaffected(monkeypatch):
    """flag ON + non-Director recipient → Gmail API attempted, no audit."""
    monkeypatch.setattr(email_alerts, "_BLOCK_EMAIL_TO_DIRECTOR", True)
    with patch.object(email_alerts, "_log_email_director_hard_blocked") as audit:
        with patch.object(email_alerts, "_get_gmail_service") as svc:
            fake_service = svc.return_value
            fake_send = (
                fake_service.users.return_value.messages.return_value.send.return_value
            )
            fake_send.execute.return_value = {"id": "m2", "threadId": "t2"}
            result = _send_raw_full("counsel@example.com", "subj", "body")
    assert result == {"message_id": "m2", "thread_id": "t2"}
    svc.assert_called_once()
    audit.assert_not_called()
