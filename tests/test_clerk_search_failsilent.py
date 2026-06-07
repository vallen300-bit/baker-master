"""CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1 — regression tests.

Covers the two acceptance criteria from the dispatch:
  (1) a simulated backend outage SURFACES as an error, never a silent empty;
  (2) clerk's baker_search reuses the documents-search core (the path that
      actually finds the hits), so a doc present via that path is returned.

All pure unit tests — no DB / Qdrant / Voyage required (the connection layer is
monkeypatched). The live end-to-end "Peter Storer -> 43 hits" behaviour is the
POST_DEPLOY_AC.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from memory.retriever import SentinelRetriever, SearchBackendUnavailable, _is_backend_unavailable_error
from orchestrator.clerk_runtime import ClerkToolRegistry


def _bare_retriever() -> SentinelRetriever:
    """A retriever instance WITHOUT touching Qdrant/Voyage/PG in __init__."""
    r = SentinelRetriever.__new__(SentinelRetriever)
    r._pg_pool = None
    return r


# ── classifier ───────────────────────────────────────────────────────────────

def test_classifier_flags_connection_errors_only():
    import psycopg2
    assert _is_backend_unavailable_error(psycopg2.OperationalError("connection refused")) is True
    assert _is_backend_unavailable_error(OSError(111, "Connection refused")) is True
    # genuine programming/value errors are NOT backend-unavailable
    assert _is_backend_unavailable_error(ValueError("bad query")) is False
    assert _is_backend_unavailable_error(KeyError("x")) is False
    # cause-chain is walked
    wrapped = RuntimeError("wrap")
    wrapped.__cause__ = psycopg2.OperationalError("server closed")
    assert _is_backend_unavailable_error(wrapped) is True


# ── (1) backend outage surfaces as error, not empty ──────────────────────────

def test_get_email_messages_raises_backend_unavailable_not_empty():
    import psycopg2
    r = _bare_retriever()

    def boom():
        raise psycopg2.OperationalError("could not connect to server: Connection refused")

    r._get_pg_conn = boom
    with pytest.raises(SearchBackendUnavailable):
        r.get_email_messages("Peter Storer", limit=5)


def test_get_meeting_transcripts_raises_backend_unavailable_not_empty():
    import psycopg2
    r = _bare_retriever()
    r._get_pg_conn = lambda: (_ for _ in ()).throw(psycopg2.InterfaceError("connection already closed"))
    with pytest.raises(SearchBackendUnavailable):
        r.get_meeting_transcripts("Peter Storer", limit=5)


def test_get_email_messages_genuine_empty_returns_list():
    """A query that RUNS and finds nothing must still return [] (not raise)."""
    r = _bare_retriever()

    class _Cur:
        def execute(self, *a, **k):
            return None

        def fetchall(self):
            return []

        def close(self):
            return None

    class _Conn:
        def cursor(self, *a, **k):
            return _Cur()

    r._get_pg_conn = lambda: _Conn()
    assert r.get_email_messages("no-such-person-zzz", limit=5) == []


def test_get_email_messages_non_backend_error_still_returns_empty():
    """A non-connection error stays non-fatal ([]) — blast radius unchanged."""
    r = _bare_retriever()

    class _Cur:
        def execute(self, *a, **k):
            raise ValueError("malformed something")

        def close(self):
            return None

    class _Conn:
        def cursor(self, *a, **k):
            return _Cur()

    r._get_pg_conn = lambda: _Conn()
    assert r.get_email_messages("x", limit=5) == []


def test_clerk_execute_renders_backend_unavailable_not_empty():
    reg = ClerkToolRegistry()

    def boom(_args):
        raise SearchBackendUnavailable("pg connection refused")

    reg._baker_search = boom
    out = json.loads(reg.execute("baker_search", {"query": "Peter Storer"}))
    assert out.get("backend_unavailable") is True
    assert "search backend unavailable" in out.get("error", "").lower()
    # critical: it must NOT look like a successful empty result
    assert "results" not in out or not out.get("results")


def test_clerk_email_search_all_flags_backend_unavailable(monkeypatch):
    reg = ClerkToolRegistry()
    monkeypatch.setattr("orchestrator.clerk_runtime.config.qwen3.default_mail_provider", "all")

    def store_down(_q, _n):
        raise SearchBackendUnavailable("pg refused")

    monkeypatch.setattr(reg, "_graph_email_search", lambda q, n: json.dumps({"matches": []}))
    monkeypatch.setattr(reg, "_email_store_search", store_down)
    monkeypatch.setitem(sys.modules, "tools.gmail",
                        types.SimpleNamespace(dispatch_gmail=lambda *a, **k: json.dumps({"matches": []})))
    out = json.loads(reg.execute("email_search", {"query": "Peter Storer"}))
    assert out.get("backend_unavailable") is True


# ── (2) clerk baker_search reuses the documents-search core ───────────────────

def test_clerk_baker_search_reuses_documents_core(monkeypatch):
    """A doc found by search_documents_core (the /api/documents/search path) is
    returned by clerk's baker_search — proving the reroute (C)."""
    fake_payload = {
        "results": [{
            "id": 7,
            "title": "Storer-handover-letter.pdf",
            "document_type": "letter",
            "matter": "hagenauer-rg7",
            "source_path": "/vault/storer.pdf",
            "date": "2026-01-15",
            "summary": "... Peter Storer handover ...",
            "score": 0.91,
        }],
        "total": 43,
        "mode": "semantic",
    }
    captured = {}

    def fake_core(q, **kwargs):
        captured["q"] = q
        captured["kwargs"] = kwargs
        return fake_payload

    monkeypatch.setitem(sys.modules, "outputs.dashboard",
                        types.SimpleNamespace(search_documents_core=fake_core))
    reg = ClerkToolRegistry()
    out = json.loads(reg.execute("baker_search", {"query": "Peter Storer", "max_results": 8}))
    assert captured["q"] == "Peter Storer"
    assert out["channel"] == "baker_search"
    assert out["count"] == 43
    assert out["mode"] == "semantic"
    assert out["results"][0]["label"] == "Storer-handover-letter.pdf"
    assert out["results"][0]["metadata"]["id"] == 7


def test_clerk_baker_search_backend_outage_surfaces(monkeypatch):
    def core_down(*_a, **_k):
        raise SearchBackendUnavailable("pg connection unavailable")

    monkeypatch.setitem(sys.modules, "outputs.dashboard",
                        types.SimpleNamespace(search_documents_core=core_down))
    reg = ClerkToolRegistry()
    out = json.loads(reg.execute("baker_search", {"query": "Peter Storer"}))
    assert out.get("backend_unavailable") is True
    assert "search backend unavailable" in out.get("error", "").lower()
