"""BAKER_M365_LARGE_ATTACHMENT_FETCH_1 — R2 eager-store + $value fetch tests.

Covers the build greenlit at bus #4421 (deputy-codex R2 architecture):
  F1  forward ingest — silent 'if not encoded: continue' skip replaced by a raw
      $value fetch; large fileAttachment + rfc822 itemAttachment now persist,
      referenceAttachment records metadata_only (never a silent drop).
  F2  read path — R2-stored rows resolve via object storage; metadata_only rows
      self-heal via on-demand fetch + persist-on-first-read; true-empty stays
      unavailable.
  F4  shared fetch_attachment_raw_value helper used by forward + backfill.
  store routing — >5MiB -> R2 (storage='r2', object_key), <=5MiB -> Neon inline,
      R2-failure falls back to metadata_only (fault-tolerant).
  graph_client.get_bytes — raw bytes, host-pin, no base64 inflation, 429/503
      backoff honoring Retry-After.
  backfill run_missing — message-id UPDATE-in-place, dry-run, duplicate cleanup.

All Graph + R2 + DB layers are mocked — no network, no DB, no boto3.
"""
from __future__ import annotations

import sys
import types
from unittest import mock

import pytest

import kbl.attachment_store as store
import kbl.graph_client as gc
import kbl.object_storage as obj
import triggers.graph_mail_trigger as gmt
import scripts.backfill_conversation_attachments as bf
from kbl.graph_client import GraphClient
from config.settings import GraphConfig


# ── fake DB ──────────────────────────────────────────────────────────────────
class _FakeCur:
    def __init__(self, fetch_seq=None, raise_on_execute=None):
        self._fetch = list(fetch_seq or [])
        self._raise = raise_on_execute
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._raise is not None:
            raise self._raise

    def fetchone(self):
        return self._fetch.pop(0) if self._fetch else None

    def fetchall(self):
        out, self._fetch = self._fetch, []
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = self.rolled = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_conn(monkeypatch, cur):
    monkeypatch.setattr(store, "get_conn", lambda: _FakeConn(cur))


# ── fake HTTP response for graph_client.get_bytes ────────────────────────────
class _HTTPErr(Exception):
    def __init__(self, resp):
        super().__init__(f"HTTP {resp.status_code}")
        self.response = resp


class _Resp:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.url = "https://graph.microsoft.com/v1.0/x"
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _HTTPErr(self)


def _client(ready=True, base_url="https://graph.microsoft.com/v1.0"):
    c = mock.MagicMock(name="GraphClient")
    c.is_ready.return_value = ready
    c.cfg.mail_user = "dvallen@brisengroup.com"
    c.cfg.base_url = base_url
    return c


# ══════════════════════════════════════════════════════════════════════════
# store routing — _route_storage
# ══════════════════════════════════════════════════════════════════════════
def test_route_small_goes_inline_neon():
    routed = store._route_storage("graph", b"x" * 100, "application/pdf")
    assert routed["storage"] == "db"
    assert routed["data"] == b"x" * 100
    assert routed["object_key"] is None
    assert routed["size_bytes"] == 100


def test_route_large_goes_r2(monkeypatch):
    payload = b"y" * (store.MAX_INLINE_BYTES + 10)
    calls = {}

    def fake_put(key, data, content_type):
        calls["key"] = key
        calls["ct"] = content_type
        calls["len"] = len(data)
        return {"ok": True, "key": key}

    monkeypatch.setattr(obj, "put_object", fake_put)
    routed = store._route_storage("graph", payload, "application/pdf")
    assert routed["storage"] == "r2"
    assert routed["data"] is None
    assert routed["object_key"] == calls["key"]
    # deterministic content-addressed key (hex sha) — idempotent F3
    assert routed["object_key"] == f"email-attachments/graph/{routed['sha256']}"
    assert calls["ct"] == "application/pdf"
    assert calls["len"] == len(payload)


def test_route_large_r2_failure_falls_back_metadata_only(monkeypatch):
    payload = b"z" * (store.MAX_INLINE_BYTES + 1)
    monkeypatch.setattr(obj, "put_object", lambda *a, **k: {"ok": False, "error": "disabled"})
    routed = store._route_storage("graph", payload, None)
    assert routed["storage"] == "metadata_only"
    assert routed["data"] is None
    assert routed["object_key"] is None


def test_route_never_inlines_large_into_neon(monkeypatch):
    """The whole point: a >5MiB payload must NEVER end up with data=bytes."""
    payload = b"q" * (store.MAX_INLINE_BYTES + 1)
    monkeypatch.setattr(obj, "put_object", lambda *a, **k: {"ok": True})
    routed = store._route_storage("graph", payload, "application/pdf")
    assert routed["data"] is None  # not inlined


# ══════════════════════════════════════════════════════════════════════════
# store — insert_attachment_routed (forward) + update_attachment_payload (backfill)
# ══════════════════════════════════════════════════════════════════════════
def test_insert_routed_small_inserts(monkeypatch):
    cur = _FakeCur(fetch_seq=[(42,)])
    _patch_conn(monkeypatch, cur)
    rid = store.insert_attachment_routed("M1", "graph", "a.pdf", "application/pdf", b"hi", "att-1")
    assert rid == 42
    sql, params = cur.executed[0]
    assert "INSERT INTO email_attachments" in sql
    assert "att-1" in params  # provider_attachment_id persisted


def test_update_payload_updates_row(monkeypatch):
    cur = _FakeCur(fetch_seq=[(7,)])  # UPDATE ... RETURNING id
    _patch_conn(monkeypatch, cur)
    status = store.update_attachment_payload(7, "graph", b"bytes", "application/pdf", "att-9")
    assert status == "updated"
    sql, _ = cur.executed[0]
    assert "UPDATE email_attachments" in sql
    assert "size_bytes > 0" in sql  # true-empty guard


def test_update_payload_unique_violation_is_duplicate(monkeypatch):
    cur = _FakeCur(raise_on_execute=Exception("duplicate key value violates unique constraint"))
    _patch_conn(monkeypatch, cur)
    status = store.update_attachment_payload(7, "graph", b"bytes", None, None)
    assert status == "duplicate"


def test_update_payload_skips_when_no_row(monkeypatch):
    cur = _FakeCur(fetch_seq=[])  # UPDATE matched nothing
    _patch_conn(monkeypatch, cur)
    assert store.update_attachment_payload(7, "graph", b"bytes", None, None) == "skipped"


# ══════════════════════════════════════════════════════════════════════════
# graph_client.get_bytes
# ══════════════════════════════════════════════════════════════════════════
def test_get_bytes_success(monkeypatch):
    client = GraphClient(GraphConfig())
    monkeypatch.setattr(client, "_acquire_token", lambda: "tok")
    monkeypatch.setattr(gc.requests, "get",
                        lambda *a, **k: _Resp(200, b"PDF", {"Content-Type": "application/pdf"}))
    out = client.get_bytes("/users/u/messages/m/attachments/a/$value")
    assert out == (b"PDF", "application/pdf")


def test_get_bytes_host_pin_rejects_non_graph(monkeypatch):
    client = GraphClient(GraphConfig())
    client.cfg.base_url = "https://evil.example.com/v1.0"
    tok = mock.MagicMock()
    monkeypatch.setattr(client, "_acquire_token", tok)
    monkeypatch.setattr(gc.requests, "get", mock.MagicMock())
    assert client.get_bytes("/x/$value") is None
    tok.assert_not_called()  # token never acquired for a non-Graph host


def test_get_bytes_405_reference_returns_none(monkeypatch):
    client = GraphClient(GraphConfig())
    monkeypatch.setattr(client, "_acquire_token", lambda: "tok")
    monkeypatch.setattr(gc.requests, "get", lambda *a, **k: _Resp(405))
    assert client.get_bytes("/users/u/messages/m/attachments/a/$value") is None


def test_get_bytes_429_backoff_then_success(monkeypatch):
    client = GraphClient(GraphConfig())
    monkeypatch.setattr(client, "_acquire_token", lambda: "tok")
    seq = [_Resp(429, headers={"Retry-After": "0"}), _Resp(200, b"OK", {"Content-Type": "x/y"})]
    calls = {"n": 0}

    def fake_get(*a, **k):
        r = seq[calls["n"]]
        calls["n"] += 1
        return r

    slept = []
    monkeypatch.setattr(gc.requests, "get", fake_get)
    monkeypatch.setattr(gc.time, "sleep", lambda s: slept.append(s))
    out = client.get_bytes("/users/u/messages/m/attachments/a/$value", max_retries=2)
    assert out == (b"OK", "x/y")
    assert calls["n"] == 2          # retried once
    assert slept == [0.0]           # honored Retry-After: 0


def test_get_bytes_429_no_retry_when_max_zero(monkeypatch):
    client = GraphClient(GraphConfig())
    monkeypatch.setattr(client, "_acquire_token", lambda: "tok")
    monkeypatch.setattr(gc.requests, "get", lambda *a, **k: _Resp(429, headers={"Retry-After": "1"}))
    # Forward ingest passes max_retries=0 → no blocking backoff on a poll.
    assert client.get_bytes("/x/$value", max_retries=0) is None


# ══════════════════════════════════════════════════════════════════════════
# F4 + F1 — fetch_attachment_raw_value + forward ingest capture
# ══════════════════════════════════════════════════════════════════════════
def test_fetch_raw_value_builds_value_path():
    client = _client()
    client.get_bytes.return_value = (b"RAW", "application/pdf")
    out = gmt.fetch_attachment_raw_value(client, "MID/x+y", "AID/z", max_retries=3)
    assert out == (b"RAW", "application/pdf")
    path = client.get_bytes.call_args[0][0]
    assert path.endswith("/$value")
    assert "/attachments/" in path
    assert "MID%2Fx%2By" in path     # message id url-encoded
    assert client.get_bytes.call_args.kwargs["max_retries"] == 3


def test_fetch_raw_value_none_args():
    assert gmt.fetch_attachment_raw_value(_client(), "", "a") is None


def _att(att_id, name, *, inline=False, content_bytes=None, ctype="application/pdf", size=10):
    a = {"id": att_id, "name": name, "isInline": inline, "contentType": ctype, "size": size}
    if content_bytes is not None:
        a["contentBytes"] = content_bytes
    return a


def test_forward_large_attachment_no_silent_skip(monkeypatch):
    """A large fileAttachment with NO contentBytes must be fetched via $value and
    persisted — the regression the whole brief targets."""
    client = _client()
    page = {"value": [_att("A1", "big.pdf", content_bytes=None, size=9_000_000)]}
    monkeypatch.setattr(gmt, "_fetch_attachments_page", lambda c, mid: (page, False))
    monkeypatch.setattr(gmt, "fetch_attachment_raw_value",
                        lambda c, mid, aid, max_retries=0: (b"BIGDATA", "application/pdf"))
    persisted = {}
    monkeypatch.setattr(gmt, "_insert_live_attachment",
                        lambda **kw: persisted.update(kw) or 99)
    meta_called = mock.MagicMock()
    monkeypatch.setattr(gmt, "_persist_attachment_meta", meta_called)

    n = gmt._capture_graph_attachments(client, {"id": "MID", "conversationId": "C", "hasAttachments": True})
    assert n == 1
    assert persisted["payload_bytes"] == b"BIGDATA"
    assert persisted["provider_attachment_id"] == "A1"
    meta_called.assert_not_called()


def test_forward_small_attachment_uses_content_bytes(monkeypatch):
    import base64 as _b64
    client = _client()
    enc = _b64.b64encode(b"small").decode()
    page = {"value": [_att("A2", "s.pdf", content_bytes=enc, size=5)]}
    monkeypatch.setattr(gmt, "_fetch_attachments_page", lambda c, mid: (page, False))
    raw = mock.MagicMock()
    monkeypatch.setattr(gmt, "fetch_attachment_raw_value", raw)
    seen = {}
    monkeypatch.setattr(gmt, "_insert_live_attachment", lambda **kw: seen.update(kw) or 1)
    n = gmt._capture_graph_attachments(client, {"id": "MID", "hasAttachments": True})
    assert n == 1
    assert seen["payload_bytes"] == b"small"
    raw.assert_not_called()  # contentBytes present → no $value fetch


def test_forward_reference_attachment_records_metadata_not_silent(monkeypatch):
    client = _client()
    page = {"value": [_att("A3", "ref.pdf", content_bytes=None, size=12)]}
    monkeypatch.setattr(gmt, "_fetch_attachments_page", lambda c, mid: (page, False))
    monkeypatch.setattr(gmt, "fetch_attachment_raw_value",
                        lambda c, mid, aid, max_retries=0: None)  # $value 405
    meta = {}
    monkeypatch.setattr(gmt, "_persist_attachment_meta", lambda **kw: meta.update(kw) or 1)
    routed = mock.MagicMock()
    monkeypatch.setattr(gmt, "_insert_live_attachment", routed)
    n = gmt._capture_graph_attachments(client, {"id": "MID", "hasAttachments": True})
    assert n == 0                       # nothing byte-stored
    assert meta["provider_attachment_id"] == "A3"  # but recorded, not dropped
    routed.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# object_storage.get_object
# ══════════════════════════════════════════════════════════════════════════
def test_get_object_disabled_when_unconfigured(monkeypatch):
    for k in obj._REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    res = obj.get_object("email-attachments/graph/abc")
    assert res["ok"] is False
    assert res["error"] == "disabled"


def test_get_object_success(monkeypatch):
    for k in obj._REQUIRED_ENV:
        monkeypatch.setenv(k, "set")

    class _Body:
        def read(self):
            return b"OBJDATA"

    fake_client = mock.MagicMock()
    fake_client.get_object.return_value = {"Body": _Body(), "ContentType": "application/pdf"}
    monkeypatch.setattr(obj, "_client", lambda: fake_client)
    res = obj.get_object("email-attachments/graph/abc")
    assert res["ok"] is True
    assert res["data"] == b"OBJDATA"
    assert res["content_type"] == "application/pdf"


# ══════════════════════════════════════════════════════════════════════════
# F2 read path — tools/email._attachment_read
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def _email_mod(monkeypatch):
    import tools.email as em
    fake = types.ModuleType("scripts.extract_gmail")
    fake._extract_text_from_bytes = lambda b, fn, ext: f"TEXT[{fn}]"
    monkeypatch.setitem(sys.modules, "scripts.extract_gmail", fake)
    return em


def _row(**kw):
    base = {"id": 1, "message_id": "M1", "source": "graph", "filename": "d.pdf",
            "mime_type": "application/pdf", "size_bytes": 100, "content_sha256": "s",
            "storage": "db", "object_key": None}
    base.update(kw)
    return base


def test_read_r2_row_downloads_and_extracts(monkeypatch, _email_mod):
    monkeypatch.setattr(store, "list_attachments",
                        lambda mid, src=None: [_row(storage="r2", object_key="email-attachments/graph/s")])
    monkeypatch.setattr(_email_mod, "_r2_get_bytes", lambda key: b"R2BYTES")
    import json
    out = json.loads(_email_mod.dispatch_email("baker_email_attachment_read",
                                                {"message_id": "M1", "filename": "d.pdf"}))
    assert out["storage"] == "r2"
    assert out["text"] == "TEXT[d.pdf]"
    assert out["text_extracted"] is True


def test_read_metadata_only_ondemand_self_heals(monkeypatch, _email_mod):
    monkeypatch.setattr(store, "list_attachments",
                        lambda mid, src=None: [_row(storage="metadata_only", size_bytes=9_000_000)])
    monkeypatch.setattr(_email_mod, "_ondemand_fetch_and_persist", lambda target, mid: b"HEALED")
    import json
    out = json.loads(_email_mod.dispatch_email("baker_email_attachment_read",
                                                {"message_id": "M1", "filename": "d.pdf"}))
    assert out["text"] == "TEXT[d.pdf]"


def test_read_true_empty_unavailable(monkeypatch, _email_mod):
    # size 0 -> on-demand short-circuits (no heavy Graph import) -> unavailable.
    monkeypatch.setattr(store, "list_attachments",
                        lambda mid, src=None: [_row(storage="db", size_bytes=0)])
    monkeypatch.setattr(store, "get_attachment_read", lambda i: _row(storage="db", size_bytes=0, data=None) if False else None)
    import json
    out = json.loads(_email_mod.dispatch_email("baker_email_attachment_read",
                                                {"message_id": "M1", "filename": "d.pdf"}))
    assert "unavailable" in out["error"]


def test_ondemand_self_heal_addresses_real_message_id_for_conv_keyed_row(monkeypatch, _email_mod):
    """G3 F1 #4473: a forward-ingest row keyed (message_id) by a conversationId
    (AAQk) must self-heal by addressing Graph with the stored real_message_id
    (AAMk) + provider_attachment_id — NOT the conversationId store key."""
    em = _email_mod
    monkeypatch.setattr(gc, "GraphClient", lambda *a, **k: _client(ready=True))
    seen = {}

    def fake_raw(c, real_msg, att_id, max_retries=0):
        seen["real_msg"] = real_msg
        seen["att_id"] = att_id
        return (b"HEALED", "application/pdf")

    monkeypatch.setattr(gmt, "fetch_attachment_raw_value", fake_raw)
    listed = mock.MagicMock()
    monkeypatch.setattr(gmt, "_fetch_attachments_page", listed)  # must NOT be called
    monkeypatch.setattr(store, "update_attachment_payload", lambda *a, **k: "updated")
    target = {
        "id": 5, "source": "graph", "filename": "d.pdf", "mime_type": "application/pdf",
        "size_bytes": 9_000_000, "storage": "metadata_only",
        "message_id": "AAQkConversationId==",       # store key = conversationId
        "real_message_id": "AAMkRealMessageId==",    # the addressable id
        "provider_attachment_id": "ATT-9",
    }
    out = em._ondemand_fetch_and_persist(target, "AAQkConversationId==")
    assert out == b"HEALED"
    assert seen["real_msg"] == "AAMkRealMessageId=="   # addressed by REAL id, not conversationId
    assert seen["att_id"] == "ATT-9"
    listed.assert_not_called()                         # direct $value fetch, no listing


def test_ondemand_self_heal_lists_for_aamk_row_without_att_id(monkeypatch, _email_mod):
    """Existing 2,618 rows: message_id IS the AAMk id, no provider_attachment_id —
    self-heal lists by that message_id and matches by filename (the fallback)."""
    em = _email_mod
    monkeypatch.setattr(gc, "GraphClient", lambda *a, **k: _client(ready=True))
    page = {"value": [_att("ATT-1", "d.pdf", content_bytes=None, size=9_000_000)]}
    listed = {}

    def fake_list(c, mid):
        listed["mid"] = mid
        return page, False

    monkeypatch.setattr(gmt, "_fetch_attachments_page", fake_list)
    seen = {}
    monkeypatch.setattr(
        gmt, "fetch_attachment_raw_value",
        lambda c, real_msg, att_id, max_retries=0: seen.update(real_msg=real_msg, att_id=att_id) or (b"OK", "x/y"),
    )
    monkeypatch.setattr(store, "update_attachment_payload", lambda *a, **k: "updated")
    target = {
        "id": 1, "source": "graph", "filename": "d.pdf", "mime_type": "application/pdf",
        "size_bytes": 9_000_000, "storage": "metadata_only",
        "message_id": "AAMkRealId==", "real_message_id": None, "provider_attachment_id": None,
    }
    out = em._ondemand_fetch_and_persist(target, "AAMkRealId==")
    assert out == b"OK"
    assert listed["mid"] == "AAMkRealId=="     # listed by the AAMk message_id (fallback)
    assert seen["att_id"] == "ATT-1"


# ══════════════════════════════════════════════════════════════════════════
# backfill run_missing — message-id UPDATE-in-place mode
# ══════════════════════════════════════════════════════════════════════════
def test_run_missing_dry_run_no_writes(monkeypatch):
    monkeypatch.setattr(bf, "_load_byte_empty_rows",
                        lambda *a, **k: [{"id": 1, "message_id": "MID", "filename": "a.pdf",
                                          "mime_type": "application/pdf", "size_bytes": 10}])
    # dry-run must not touch GraphClient
    assert bf.run_missing(execute=False) == 0


def test_run_missing_executes_update(monkeypatch):
    rows = [{"id": 5, "message_id": "MID", "filename": "a.pdf",
             "mime_type": "application/pdf", "size_bytes": 7_000_000}]
    monkeypatch.setattr(bf, "_load_byte_empty_rows", lambda *a, **k: rows)

    client = _client(ready=True)
    monkeypatch.setattr(gc, "GraphClient", lambda *a, **k: client)
    page = {"value": [_att("A1", "a.pdf", content_bytes=None, size=7_000_000)]}
    monkeypatch.setattr(gmt, "_fetch_attachments_page", lambda c, mid: (page, False))
    monkeypatch.setattr(gmt, "fetch_attachment_raw_value",
                        lambda c, mid, aid, max_retries=0: (b"BYTES", "application/pdf"))
    updates = []
    monkeypatch.setattr(store, "update_attachment_payload",
                        lambda *a, **k: updates.append(a) or "updated")
    rc = bf.run_missing(execute=True)
    assert rc == 0
    assert len(updates) == 1
    assert updates[0][0] == 5          # updated the exact row id


def test_run_missing_duplicate_deletes_empty(monkeypatch):
    rows = [{"id": 9, "message_id": "MID", "filename": "dup.pdf",
             "mime_type": "application/pdf", "size_bytes": 100}]
    monkeypatch.setattr(bf, "_load_byte_empty_rows", lambda *a, **k: rows)
    client = _client(ready=True)
    monkeypatch.setattr(gc, "GraphClient", lambda *a, **k: client)
    page = {"value": [_att("A1", "dup.pdf", content_bytes=None, size=100)]}
    monkeypatch.setattr(gmt, "_fetch_attachments_page", lambda c, mid: (page, False))
    monkeypatch.setattr(gmt, "fetch_attachment_raw_value",
                        lambda c, mid, aid, max_retries=0: (b"BYTES", "application/pdf"))
    monkeypatch.setattr(store, "update_attachment_payload", lambda *a, **k: "duplicate")
    deleted = []
    monkeypatch.setattr(store, "delete_empty_attachment", lambda i: deleted.append(i) or True)
    bf.run_missing(execute=True)
    assert deleted == [9]


def test_run_missing_per_row_byte_budget_stops_at_boundary(monkeypatch):
    """G2 F1 #4465: budget enforced PER ROW (before fetch, by known size), so a
    multi-row message can't overshoot. 3x100B rows, budget 150 -> only the first
    row is fetched (first-row progress), the second trips the gate and stops."""
    rows = [
        {"id": 1, "message_id": "MID", "filename": "a.pdf", "mime_type": "application/pdf", "size_bytes": 100},
        {"id": 2, "message_id": "MID", "filename": "b.pdf", "mime_type": "application/pdf", "size_bytes": 100},
        {"id": 3, "message_id": "MID", "filename": "c.pdf", "mime_type": "application/pdf", "size_bytes": 100},
    ]
    monkeypatch.setattr(bf, "_load_byte_empty_rows", lambda *a, **k: rows)
    client = _client(ready=True)
    monkeypatch.setattr(gc, "GraphClient", lambda *a, **k: client)
    page = {"value": [_att("A1", "a.pdf", content_bytes=None, size=100),
                      _att("A2", "b.pdf", content_bytes=None, size=100),
                      _att("A3", "c.pdf", content_bytes=None, size=100)]}
    monkeypatch.setattr(gmt, "_fetch_attachments_page", lambda c, mid: (page, False))
    fetched = []
    monkeypatch.setattr(gmt, "fetch_attachment_raw_value",
                        lambda c, mid, aid, max_retries=0: fetched.append(aid) or (b"x" * 100, "application/pdf"))
    updates = []
    monkeypatch.setattr(store, "update_attachment_payload",
                        lambda *a, **k: updates.append(a[0]) or "updated")
    bf.run_missing(execute=True, byte_budget=150)
    # Stopped at the boundary: only row 1 fetched+updated, NOT all three (200B+ overshoot).
    assert fetched == ["A1"]
    assert updates == [1]


def test_run_missing_dormant_client_aborts(monkeypatch):
    monkeypatch.setattr(bf, "_load_byte_empty_rows",
                        lambda *a, **k: [{"id": 1, "message_id": "MID", "filename": "a.pdf",
                                          "mime_type": "application/pdf", "size_bytes": 10}])
    monkeypatch.setattr(gc, "GraphClient", lambda *a, **k: _client(ready=False))
    assert bf.run_missing(execute=True) == 3
