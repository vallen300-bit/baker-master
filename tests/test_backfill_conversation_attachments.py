"""M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1 — conversationId-aware backfill tests.

Covers the conversationId -> messages -> attachments resolution and that the
backfill REUSES the live _capture_graph_attachments path (so attachments land
under the conversationId key, no divergent fetch/store logic).
"""
from unittest import mock

import scripts.backfill_conversation_attachments as bf
import triggers.graph_mail_trigger as gmt


def _client():
    c = mock.MagicMock(name="GraphClient")
    c.is_ready.return_value = True
    c.cfg.mail_user = "dvallen@brisengroup.com"
    return c


def _att():
    import base64
    return {
        "id": "att-1", "name": "doc.pdf", "contentType": "application/pdf",
        "size": 7, "contentBytes": base64.b64encode(b"PDFDATA").decode(), "isInline": False,
    }


def test_dry_run_needs_no_client(caplog):
    import logging
    with caplog.at_level(logging.INFO):
        rc = bf.run(["AAQkConv1=="], execute=False)
    assert rc == 0
    assert any("DRY-RUN" in r.message for r in caplog.records)


def test_no_ids_returns_error():
    assert bf.run([], execute=True) == 2


def test_resolve_filters_by_conversation_id():
    client = _client()
    client.get.return_value = {"value": [{"id": "m1", "hasAttachments": True}]}
    out = bf._resolve_messages(client, "AAQkConv'X==")     # embedded quote -> doubled
    assert out == [{"id": "m1", "hasAttachments": True}]
    params = client.get.call_args.kwargs["params"]
    assert params["$filter"] == "conversationId eq 'AAQkConv''X=='"   # OData-escaped


def test_resolve_returns_none_on_fetch_failure():
    client = _client()
    client.get.return_value = None
    assert bf._resolve_messages(client, "AAQkConv==") is None


def test_resolve_follows_nextlink_pagination():
    """G2 F2: a thread spanning >1 page is fully read via @odata.nextLink."""
    client = _client()
    client.get.return_value = {"value": [{"id": "m1"}], "@odata.nextLink": "NEXT"}
    client.get_url.return_value = {"value": [{"id": "m2"}]}        # page 2, no further link
    out = bf._resolve_messages(client, "AAQkConv==")
    assert [m["id"] for m in out] == ["m1", "m2"]                  # both pages merged
    client.get_url.assert_called_once_with("NEXT")


def test_resolve_nextlink_failure_returns_none_not_truncated():
    """Mid-pagination None is a FAILURE (None), never a silent partial list."""
    client = _client()
    client.get.return_value = {"value": [{"id": "m1"}], "@odata.nextLink": "NEXT"}
    client.get_url.return_value = None                            # page 2 fetch fails
    assert bf._resolve_messages(client, "AAQkConv==") is None


def test_backfill_stores_attachments_under_conversation_id():
    """End-to-end (mocked): resolve conv -> message with attachment -> store under conversationId."""
    client = _client()
    conv = "AAQkConv=="
    # 1st get = $filter message list; 2nd get = the message's attachments page.
    client.get.side_effect = [
        {"value": [{"id": "realMsg1", "hasAttachments": True}]},
        {"value": [_att()]},
    ]
    import kbl.graph_client as gc
    with mock.patch.object(gc, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1") as ins:
        rc = bf.run([conv], execute=True)
    assert rc == 0
    # Reused the live capture path; attachment stored under the conversationId.
    assert ins.call_args.kwargs["message_id"] == conv
    # And the attachment fetch addressed the REAL message id.
    assert "realMsg1" in client.get.call_args_list[1].args[0]


def test_backfill_surfaces_resolve_failure():
    client = _client()
    client.get.return_value = None        # conversation resolve fails
    import kbl.graph_client as gc
    with mock.patch.object(gc, "GraphClient", return_value=client):
        rc = bf.run(["AAQkConv=="], execute=True)
    assert rc == 1                        # non-zero: failure surfaced, not silent


def test_backfill_dormant_client_refuses():
    client = _client()
    client.is_ready.return_value = False
    # run() does `from kbl.graph_client import GraphClient` — patch at the source.
    import kbl.graph_client as gc
    with mock.patch.object(gc, "GraphClient", return_value=client):
        rc = bf.run(["AAQkConv=="], execute=True)
    assert rc == 3
