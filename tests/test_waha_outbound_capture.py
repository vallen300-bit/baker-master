"""Tests for BRIEF_WAHA_OUTBOUND_CAPTURE_1.

Coverage:
  1. attribute_sender / is_baker_self_chat unit tests (pure)
  2. Webhook fromMe=True flow — sender re-attribution + storage
  3. Webhook Director-to-counterparty routing — PM-signal yes, RAG-question no
  4. Webhook Director-to-Baker routing — PM-signal yes, RAG-question yes
  5. RAG direction tagging — get_whatsapp_messages emits [WHATSAPP-OUTBOUND]/[INBOUND]
  6. chat_id normalization migration — @lid -> phone, idempotent
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _restore_real_store_back():
    """Some sibling tests (test_ai_head_weekly_audit.py) replace
    sys.modules['memory.store_back'] with a MagicMock and never restore it.
    Force a clean re-import for every test in this file so our monkeypatches
    land on the real module."""
    for mod in ("memory.store_back", "memory", "triggers.waha_webhook",
                "triggers", "orchestrator.pm_signal_detector"):
        sys.modules.pop(mod, None)
    importlib.import_module("memory.store_back")
    importlib.import_module("triggers.waha_webhook")
    importlib.import_module("orchestrator.pm_signal_detector")
    yield

from triggers.waha_message_utils import (
    BAKER_SELF_CHAT_CUS,
    BAKER_SELF_CHAT_IDS,
    BAKER_SELF_CHAT_JID,
    DIRECTOR_WHATSAPP_CUS,
    DIRECTOR_WHATSAPP_JID,
    attribute_sender,
    is_baker_self_chat,
)


# ----------------------------------------------------------------------------
# Class 1 — attribute_sender / is_baker_self_chat unit tests (no DB, no IO)
# ----------------------------------------------------------------------------


class TestAttributeSender:
    def test_from_me_true_attributes_to_director(self):
        sender, name, is_dir = attribute_sender("41796720083@c.us", "Julia", True)
        assert sender == DIRECTOR_WHATSAPP_CUS
        assert name == "Director"
        assert is_dir is True

    def test_from_me_false_passes_through(self):
        sender, name, is_dir = attribute_sender("41796720083@c.us", "Julia", False)
        assert sender == "41796720083@c.us"
        assert name == "Julia"
        assert is_dir is False

    def test_from_me_false_with_director_cus_marks_director(self):
        sender, name, is_dir = attribute_sender(DIRECTOR_WHATSAPP_CUS, "Dimitry", False)
        assert sender == DIRECTOR_WHATSAPP_CUS
        assert is_dir is True

    def test_from_me_false_with_director_jid_marks_director(self):
        sender, name, is_dir = attribute_sender(DIRECTOR_WHATSAPP_JID, "Dimitry", False)
        assert sender == DIRECTOR_WHATSAPP_JID
        assert is_dir is True

    def test_empty_sender_from_me_false(self):
        sender, name, is_dir = attribute_sender("", "", False)
        assert sender == ""
        assert name == ""
        assert is_dir is False


class TestIsBakerSelfChat:
    def test_cus_form(self):
        assert is_baker_self_chat(BAKER_SELF_CHAT_CUS) is True

    def test_jid_form(self):
        assert is_baker_self_chat(BAKER_SELF_CHAT_JID) is True

    def test_counterparty(self):
        assert is_baker_self_chat("41796720083@c.us") is False

    def test_none(self):
        assert is_baker_self_chat(None) is False

    def test_empty(self):
        assert is_baker_self_chat("") is False

    def test_set_membership(self):
        assert BAKER_SELF_CHAT_CUS in BAKER_SELF_CHAT_IDS
        assert BAKER_SELF_CHAT_JID in BAKER_SELF_CHAT_IDS


# ----------------------------------------------------------------------------
# Webhook integration helpers
# ----------------------------------------------------------------------------


class _FakeRequest:
    """Minimal FastAPI Request stand-in returning a fixed JSON payload."""

    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


def _run_webhook(payload: dict) -> dict:
    """Invoke triggers.waha_webhook.waha_webhook with payload, return result."""
    from triggers.waha_webhook import waha_webhook
    req = _FakeRequest(payload)
    return asyncio.run(waha_webhook(req, x_webhook_hmac=None))


def _build_payload(*, from_me: bool, to_chat: str, body: str = "hi"):
    return {
        "event": "message",
        "payload": {
            "id": f"test-msg-{from_me}-{to_chat}",
            "from": "41796720083@c.us" if not from_me else "41796720083@c.us",
            "to": to_chat,
            "chatId": to_chat if not from_me else None,
            "fromMe": from_me,
            "body": body,
            "timestamp": 1716240000,
            "hasMedia": False,
            "_data": {"notifyName": "Julia"},
        },
    }


# ----------------------------------------------------------------------------
# Class 2-4 — Webhook routing integration
# ----------------------------------------------------------------------------


class TestWebhookFromMeStorage:
    def test_from_me_re_attributes_and_stores(self, monkeypatch):
        """fromMe=True → store_whatsapp_message called with Director sender +
        is_director=True + chat_id = counterparty."""
        captured = {}

        def fake_store_whatsapp_message(**kw):
            captured.update(kw)
            return True

        fake_store = MagicMock()
        fake_store.store_whatsapp_message = fake_store_whatsapp_message
        fake_store.match_contact_by_name.return_value = None
        fake_store.link_to_trip_context = MagicMock()
        fake_store._get_conn.return_value = None  # disables auto-contact-create branch

        from memory import store_back as sb_mod
        # Set _instance directly + override classmethod — robust to whichever
        # access pattern the production code uses, and to prior test pollution
        # of the singleton cache.
        monkeypatch.setattr(sb_mod.SentinelStoreBack, "_instance", fake_store)
        monkeypatch.setattr(sb_mod.SentinelStoreBack, "_get_global_instance", classmethod(lambda cls: fake_store))

        # Block out PM-signal, deadline, youtube, action, question handlers —
        # they are pipeline-side; routing assertions live in their own tests.
        from orchestrator import pm_signal_detector as _pmd
        monkeypatch.setattr(_pmd, "detect_relevant_pms_outbound", lambda *a, **kw: [])
        monkeypatch.setattr(_pmd, "flag_pm_signal", MagicMock())

        from triggers import waha_webhook as ww
        monkeypatch.setattr(ww, "_handle_director_message", MagicMock(return_value=False))
        monkeypatch.setattr(ww, "_handle_director_question", MagicMock())

        # Director → Julia (counterparty)
        payload = _build_payload(from_me=True, to_chat="41796720083@c.us", body="see you Friday")
        _run_webhook(payload)

        assert captured["sender"] == DIRECTOR_WHATSAPP_CUS
        assert captured["sender_name"] == "Director"
        assert captured["is_director"] is True
        assert captured["chat_id"] == "41796720083@c.us"


class TestWebhookDirectorRouting:
    def _wire_mocks(self, monkeypatch):
        fake_store = MagicMock()
        fake_store.store_whatsapp_message = MagicMock(return_value=True)
        fake_store.match_contact_by_name.return_value = None
        fake_store.link_to_trip_context = MagicMock()
        fake_store._get_conn.return_value = None
        from memory import store_back as sb_mod
        # Set _instance directly + override classmethod — robust to whichever
        # access pattern the production code uses, and to prior test pollution
        # of the singleton cache.
        monkeypatch.setattr(sb_mod.SentinelStoreBack, "_instance", fake_store)
        monkeypatch.setattr(sb_mod.SentinelStoreBack, "_get_global_instance", classmethod(lambda cls: fake_store))

        pm_flag = MagicMock()
        from orchestrator import pm_signal_detector as _pmd
        monkeypatch.setattr(_pmd, "detect_relevant_pms_outbound", lambda *a, **kw: ["ao"])
        monkeypatch.setattr(_pmd, "flag_pm_signal", pm_flag)
        monkeypatch.setattr(_pmd, "detect_relevant_pms_whatsapp", lambda *a, **kw: [])

        director_q = MagicMock()
        director_m = MagicMock(return_value=False)
        from triggers import waha_webhook as ww
        monkeypatch.setattr(ww, "_handle_director_message", director_m)
        monkeypatch.setattr(ww, "_handle_director_question", director_q)
        return pm_flag, director_q, director_m

    def test_director_to_counterparty_fires_pm_signal_not_rag(self, monkeypatch):
        pm_flag, director_q, director_m = self._wire_mocks(monkeypatch)

        payload = _build_payload(from_me=True, to_chat="41796720083@c.us", body="ok see you")
        _run_webhook(payload)

        # PM-signal-outbound MUST fire (we want to capture Director's outbound).
        assert pm_flag.called, "flag_pm_signal should fire for Director->counterparty"
        # RAG-question / action handlers MUST NOT fire — counterparty replies are
        # not Director-questions for Baker.
        assert not director_q.called, "Director question handler should NOT fire for Director->counterparty"
        assert not director_m.called, "Director message handler should NOT fire for Director->counterparty"

    def test_director_to_baker_fires_pm_signal_and_rag(self, monkeypatch):
        pm_flag, director_q, director_m = self._wire_mocks(monkeypatch)

        # Director → self-chat (Baker)
        payload = _build_payload(from_me=True, to_chat=BAKER_SELF_CHAT_CUS, body="what's on for today?")
        _run_webhook(payload)

        # PM-signal-outbound fires for BOTH paths.
        assert pm_flag.called, "flag_pm_signal should fire for Director->Baker"
        # RAG / action path fires only on Director->Baker.
        assert director_m.called, "Director message handler should fire for Director->Baker"
        assert director_q.called, "Director question handler should fire for Director->Baker"


# ----------------------------------------------------------------------------
# Class 5 — RAG direction tagging (live-PG)
# ----------------------------------------------------------------------------


class TestRagDirectionTagging:
    def test_outbound_and_inbound_tags(self, needs_live_pg, monkeypatch):
        import psycopg2
        from memory.retriever import SentinelRetriever

        dsn = needs_live_pg

        # Ensure schema + seed rows
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS whatsapp_messages (
                        id TEXT PRIMARY KEY,
                        sender TEXT,
                        sender_name TEXT,
                        chat_id TEXT,
                        full_text TEXT,
                        timestamp TIMESTAMPTZ,
                        is_director BOOLEAN DEFAULT FALSE,
                        ingested_at TIMESTAMPTZ DEFAULT NOW(),
                        media_mimetype TEXT,
                        media_dropbox_path TEXT,
                        media_size_bytes INTEGER
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO whatsapp_messages (id, sender, sender_name, full_text, timestamp, is_director) "
                    "VALUES (%s, %s, %s, %s, NOW(), %s), (%s, %s, %s, %s, NOW(), %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (
                        "test-out-rag-1", DIRECTOR_WHATSAPP_CUS, "Director", "Direction tag marker OUTBOUND", True,
                        "test-in-rag-1", "41796720083@c.us", "Julia", "Direction tag marker INBOUND", False,
                    ),
                )
            conn.commit()

        # Force retriever to use the test DB
        retriever = SentinelRetriever()

        class _StubConn:
            def __init__(self, dsn):
                self._dsn = dsn
                self._real = None

            def __getattr__(self, name):
                if self._real is None:
                    self._real = psycopg2.connect(self._dsn)
                return getattr(self._real, name)

        monkeypatch.setattr(retriever, "_get_pg_conn", lambda: psycopg2.connect(dsn))
        monkeypatch.setattr(retriever, "_reset_pg_conn", lambda: None)

        contexts = retriever.get_whatsapp_messages(query="Direction tag marker", limit=10)
        contents = [c.content for c in contexts]
        assert any("[WHATSAPP-OUTBOUND]" in c and "OUTBOUND" in c for c in contents), \
            f"Expected an OUTBOUND-tagged context, got: {contents}"
        assert any("[WHATSAPP-INBOUND]" in c and "INBOUND" in c for c in contents), \
            f"Expected an INBOUND-tagged context, got: {contents}"


# ----------------------------------------------------------------------------
# Class 6 — chat_id normalization migration (live-PG + mocked resolve_lid)
# ----------------------------------------------------------------------------


class TestChatIdMigration:
    def test_lid_rows_normalized(self, needs_live_pg, monkeypatch):
        import psycopg2

        dsn = needs_live_pg

        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS whatsapp_messages (
                        id TEXT PRIMARY KEY,
                        sender TEXT,
                        sender_name TEXT,
                        chat_id TEXT,
                        full_text TEXT,
                        timestamp TIMESTAMPTZ,
                        is_director BOOLEAN DEFAULT FALSE,
                        ingested_at TIMESTAMPTZ DEFAULT NOW(),
                        media_mimetype TEXT,
                        media_dropbox_path TEXT,
                        media_size_bytes INTEGER
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO whatsapp_messages (id, sender, chat_id, full_text, timestamp) "
                    "VALUES (%s, %s, %s, %s, NOW()), (%s, %s, %s, %s, NOW()) "
                    "ON CONFLICT (id) DO UPDATE SET chat_id = EXCLUDED.chat_id",
                    (
                        "test-mig-1", "x@lid", "16462794231969@lid", "msg1",
                        "test-mig-2", "y@lid", "16462794231969@lid", "msg2",
                    ),
                )
            conn.commit()

        # Patch SentinelStoreBack._get_global_instance to use the test DSN
        # via a thin shim store that exposes _get_conn / _put_conn.
        class _ShimStore:
            def __init__(self, dsn):
                self._dsn = dsn
                self._conn = None

            def _get_conn(self):
                if self._conn is None or self._conn.closed:
                    self._conn = psycopg2.connect(self._dsn)
                return self._conn

            def _put_conn(self, conn):
                pass

        shim = _ShimStore(dsn)
        from memory import store_back as sb_mod
        monkeypatch.setattr(sb_mod.SentinelStoreBack, "_get_global_instance", classmethod(lambda cls: shim))

        # Mock resolve_lid -> phone form
        from triggers import waha_client as wc
        monkeypatch.setattr(wc, "resolve_lid", lambda lid: "41796720083@c.us")
        # Also patch in the migration script's import site
        from scripts import migrate_whatsapp_chat_id_normalize as mig
        monkeypatch.setattr(mig, "resolve_lid", lambda lid: "41796720083@c.us")

        rc = mig.main()
        assert rc == 0

        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, chat_id FROM whatsapp_messages WHERE id IN ('test-mig-1', 'test-mig-2')"
                )
                rows = dict(cur.fetchall())
        assert rows == {
            "test-mig-1": "41796720083@c.us",
            "test-mig-2": "41796720083@c.us",
        }

        # Idempotency — second run touches no rows
        rc2 = mig.main()
        assert rc2 == 0
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT chat_id FROM whatsapp_messages WHERE id IN ('test-mig-1', 'test-mig-2')"
                )
                vals = sorted(r[0] for r in cur.fetchall())
        assert vals == ["41796720083@c.us", "41796720083@c.us"]
