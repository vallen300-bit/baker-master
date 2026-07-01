"""BACKFILL_FORWARD_PARITY_1: live pollers persist raw attachments."""
from __future__ import annotations

import base64
import json
from email.message import EmailMessage
from unittest import mock


def test_bluewin_live_poll_captures_mime_attachment(monkeypatch):
    import triggers.bluewin_poller as bluewin

    calls = []
    monkeypatch.setattr(
        bluewin,
        "_insert_live_attachment",
        lambda **kwargs: calls.append(kwargs) or 17,
    )

    msg = EmailMessage()
    msg["Message-ID"] = "<bluewin-1>"
    msg.set_content("body")
    msg.add_attachment(
        b"pdf-bytes",
        maintype="application",
        subtype="pdf",
        filename="rechnung.pdf",
    )

    assert bluewin._capture_bluewin_attachments(msg, "<bluewin-1>") == 1
    assert calls == [{
        "message_id": "bluewin-1",
        "filename": "rechnung.pdf",
        "mime_type": "application/pdf",
        "payload_bytes": b"pdf-bytes",
    }]


def test_graph_live_poll_captures_file_attachment(monkeypatch):
    import triggers.graph_mail_trigger as graph

    calls = []
    monkeypatch.setattr(
        graph,
        "_insert_live_attachment",
        lambda **kwargs: calls.append(kwargs) or 23,
    )

    client = mock.MagicMock()
    client.cfg.mail_user = "dvallen@brisengroup.com"
    client.get.return_value = {
        "value": [{
            "name": "memo.pdf",
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(b"memo-bytes").decode("ascii"),
            "isInline": False,
        }]
    }

    stored = graph._capture_graph_attachments(
        client,
        {"id": "graph-message-1", "conversationId": "graph-thread-1", "hasAttachments": True},
    )

    assert stored == 1
    client.get.assert_called_once()
    # BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1 F1: the email row is now keyed PER-MESSAGE
    # (m['id']), so the attachment MUST store under the same per-message id — NOT the
    # conversationId — or the read-path join is a false-empty surface (codex G3 HIGH).
    assert "graph-message-1" in client.get.call_args.args[0]   # fetch used the real message id
    assert calls == [{
        "message_id": "graph-message-1",                       # stored under the per-message id (== email row key)
        "filename": "memo.pdf",
        "mime_type": "application/pdf",
        "payload_bytes": b"memo-bytes",
        # M365_LARGE_ATTACHMENT_FETCH_1: routed persist now carries the Graph
        # attachment id (None here — this fixture's attachment has no 'id').
        "provider_attachment_id": None,
    }]


def test_gmail_live_poll_captures_attachment_via_existing_reader(monkeypatch):
    import triggers.email_trigger as email_trigger

    calls = []
    monkeypatch.setattr(
        email_trigger,
        "_insert_live_attachment",
        lambda **kwargs: calls.append(kwargs) or 31,
    )

    service = mock.MagicMock()
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "payload": {
            "parts": [{
                "filename": "contract.pdf",
                "mimeType": "application/pdf",
                "body": {"attachmentId": "ATT-1", "size": 9},
            }]
        }
    }

    def fake_attachment_read(args):
        assert args == {
            "message_id": "gmail-message-1",
            "filename": "contract.pdf",
            "attachment_index": 1,
            "include_bytes": True,
        }
        return json.dumps({
            "filename": "contract.pdf",
            "mime_type": "application/pdf",
            "bytes_base64": base64.b64encode(b"contract-bytes").decode("ascii"),
        })

    monkeypatch.setattr("tools.gmail._attachment_read", fake_attachment_read)

    threads = [{
        "text": "Email Thread",
        "metadata": {
            "thread_id": "gmail-thread-1",
            "message_id": "gmail-message-1",
            "all_message_ids": ["gmail-message-1"],
        },
    }]

    assert email_trigger._capture_gmail_thread_attachments(service, threads) == 1
    # BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1 F1: attachment key MUST equal the email-row
    # key, which is now the per-message id (metadata['message_id']), not thread_id.
    assert calls == [{
        "message_id": "gmail-message-1",                       # per-message id (== email row key)
        "source": "email",
        "filename": "contract.pdf",
        "mime_type": "application/pdf",
        "payload_bytes": b"contract-bytes",
    }]
