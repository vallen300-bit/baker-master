"""Tests for STEP2-RESOLVE-IMPL: dispatcher + 4 resolvers + Voyage client.

Uses psycopg2-shaped MagicMock for DB calls; Voyage is never reached in
CI (embed_fn is injected). A tiny fixture vault at
``tests/fixtures/resolver_vault/`` provides stored embeddings so the
transcript + scan paths can run end-to-end without touching the network.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kbl.exceptions import ResolverError, VoyageUnavailableError
from kbl.resolvers import CostInfo, ResolveResult
from kbl.resolvers import email as email_resolver
from kbl.resolvers import whatsapp as wa_resolver
from kbl.resolvers import transcript as transcript_resolver
from kbl.resolvers import scan as scan_resolver
from kbl.steps import step2_resolve
from kbl.steps.step2_resolve import resolve

VAULT = Path(__file__).parent / "fixtures" / "resolver_vault"


# ------------------------------ shared helpers ------------------------------


class _Recorder:
    """Scripted psycopg2-shaped cursor.

    Each call to ``execute`` consumes the next entry in ``script``, which
    is a list of ``(expected_sql_substr, return_rows)`` pairs. ``return_rows``
    is either a list (fetchall), a single row (fetchone), or ``None``.

    Calls are recorded onto ``.calls`` so tests can assert the SQL + params.
    """

    def __init__(self, script: list[tuple[str, Any]]):
        self.script = list(script)
        self.calls: list[tuple[str, Any]] = []
        self._last_return: Any = None

    def _match(self, sql: str) -> Any:
        for i, (needle, payload) in enumerate(self.script):
            if needle.lower() in sql.lower():
                self.script.pop(i)
                return payload
        return None

    def execute(self, sql, params=None) -> None:
        self.calls.append((sql, params))
        self._last_return = self._match(sql)

    def fetchone(self):
        v = self._last_return
        # If payload is a list of rows, fetchone returns first; else the row.
        if isinstance(v, list):
            return v[0] if v else None
        return v

    def fetchall(self):
        v = self._last_return
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]


def _mock_conn(script: list[tuple[str, Any]]) -> tuple[MagicMock, _Recorder]:
    recorder = _Recorder(script)
    conn = MagicMock()

    def _cursor_ctx(*args, **kwargs):
        ctx = MagicMock()
        ctx.__enter__.return_value = recorder
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor_ctx
    return conn, recorder


# ------------------------------ email resolver ------------------------------


def test_email_resolver_returns_vault_paths_via_message_id_graph() -> None:
    signal = {
        "id": 10,
        "source": "email",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "...",
        "payload": {
            "email_message_id": "<m3@example>",
            "in_reply_to": "<m2@example>",
            "references": ["<m1@example>", "<m2@example>"],
            "subject": "Re: Ofenheimer",
        },
    }
    rows = [
        ("wiki/hagenauer-rg7/2026-04-02_reply.md",),
        ("wiki/hagenauer-rg7/2026-04-01_open.md",),
    ]
    conn, _rec = _mock_conn([("from signal_queue", rows)])
    result = email_resolver.resolve(signal, conn)
    assert result.paths == (
        "wiki/hagenauer-rg7/2026-04-02_reply.md",
        "wiki/hagenauer-rg7/2026-04-01_open.md",
    )
    assert result.cost_info is None  # metadata-only


def test_email_resolver_falls_back_to_subject_when_no_graph_match() -> None:
    """With no message-id / in_reply_to / references the graph query is
    skipped entirely and the subject-only fallback runs."""
    signal = {
        "id": 10,
        "source": "email",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "...",
        "payload": {"subject": "Re: Re: Fwd: Ofenheimer letter"},
    }
    conn, _rec = _mock_conn(
        [
            ("from signal_queue", [("wiki/hagenauer-rg7/2026-04-02_ofenheimer.md",)]),
        ]
    )
    result = email_resolver.resolve(signal, conn)
    assert result.paths == ("wiki/hagenauer-rg7/2026-04-02_ofenheimer.md",)


def test_email_resolver_empty_matter_returns_empty() -> None:
    signal = {
        "id": 10,
        "source": "email",
        "primary_matter": None,
        "raw_content": "",
        "payload": {"email_message_id": "<x>"},
    }
    conn, _rec = _mock_conn([])
    result = email_resolver.resolve(signal, conn)
    assert result.paths == ()


def test_email_resolver_no_match_returns_empty() -> None:
    signal = {
        "id": 10,
        "source": "email",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "",
        "payload": {"email_message_id": "<m1@x>", "subject": "Greetings"},
    }
    conn, _rec = _mock_conn(
        [
            ("from signal_queue", []),
            ("from signal_queue", []),
        ]
    )
    result = email_resolver.resolve(signal, conn)
    assert result.paths == ()


def test_email_resolver_caps_at_3() -> None:
    signal = {
        "id": 10,
        "source": "email",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "",
        "payload": {
            "email_message_id": "<x>",
            "references": ["<a>", "<b>", "<c>", "<d>", "<e>"],
        },
    }
    five = [
        ("wiki/hagenauer-rg7/a.md",),
        ("wiki/hagenauer-rg7/b.md",),
        ("wiki/hagenauer-rg7/c.md",),
        ("wiki/hagenauer-rg7/d.md",),
        ("wiki/hagenauer-rg7/e.md",),
    ]
    # Even if DB returned 5 we cap internally at 3 paths.
    conn, _rec = _mock_conn([("from signal_queue", five)])
    result = email_resolver.resolve(signal, conn)
    assert len(result.paths) == 3


def test_email_resolver_deduplicates_across_graph_and_subject() -> None:
    signal = {
        "id": 10,
        "source": "email",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "",
        "payload": {"email_message_id": "<x>", "subject": "Re: Topic"},
    }
    conn, _rec = _mock_conn(
        [
            ("from signal_queue", [("wiki/hagenauer-rg7/a.md",)]),
            ("from signal_queue", [("wiki/hagenauer-rg7/a.md",), ("wiki/hagenauer-rg7/b.md",)]),
        ]
    )
    result = email_resolver.resolve(signal, conn)
    assert result.paths == (
        "wiki/hagenauer-rg7/a.md",
        "wiki/hagenauer-rg7/b.md",
    )


# ------------------------------ whatsapp resolver ------------------------------


def test_whatsapp_resolver_returns_paths_for_matching_chat() -> None:
    signal = {
        "id": 11,
        "source": "whatsapp",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "",
        "payload": {"chat_id": "12345@g.us", "sent_at": "2026-04-15T10:00:00Z"},
    }
    rows = [
        ("wiki/hagenauer-rg7/2026-04-10_update.md",),
        ("wiki/hagenauer-rg7/2026-04-05_start.md",),
    ]
    conn, rec = _mock_conn([("from signal_queue", rows)])
    result = wa_resolver.resolve(signal, conn)
    assert result.paths == (
        "wiki/hagenauer-rg7/2026-04-10_update.md",
        "wiki/hagenauer-rg7/2026-04-05_start.md",
    )
    # Sent_at anchored window (not default now()).
    _sql, params = rec.calls[0]
    assert "hagenauer-rg7" in params
    assert "12345@g.us" in params
    assert "2026-04-15T10:00:00Z" in params


def test_whatsapp_resolver_empty_chat_id_returns_empty() -> None:
    signal = {
        "id": 11,
        "source": "whatsapp",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "",
        "payload": {"chat_id": ""},
    }
    conn, _rec = _mock_conn([])
    result = wa_resolver.resolve(signal, conn)
    assert result.paths == ()
    conn.cursor.assert_not_called()


def test_whatsapp_resolver_window_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_STEP2_WA_WINDOW_DAYS", "7")
    signal = {
        "id": 11,
        "source": "whatsapp",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "",
        "payload": {"chat_id": "12345@g.us"},
    }
    conn, rec = _mock_conn([("from signal_queue", [])])
    wa_resolver.resolve(signal, conn)
    _sql, params = rec.calls[0]
    assert "7" in params


# ------------------------------ transcript resolver ------------------------------


def test_transcript_resolver_happy_path_three_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    signal = {
        "id": 12,
        "source": "meeting",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "Discussion of Ofenheimer demand letter and the Hassa reply.",
        "payload": {},
    }

    def fake_embed(text: str) -> list[float]:
        # Aligns with the stored vectors [0.9,0.1,0,0] / [0.8,0.2,0,0] etc.
        return [0.95, 0.05, 0.0, 0.0]

    result = transcript_resolver.resolve(signal, conn=None, embed_fn=fake_embed)
    assert len(result.paths) == 3
    # Ordering is by cosine similarity descending.
    assert result.paths[0] == "wiki/hagenauer-rg7/2026-04-01_ofenheimer.md"
    assert result.paths[1] == "wiki/hagenauer-rg7/2026-04-02_hassa_reply.md"
    assert result.paths[2] == "wiki/hagenauer-rg7/2026-04-03_court_notes.md"
    assert "wiki/hagenauer-rg7/2026-04-04_unrelated.md" not in result.paths
    # Cost info populated on success.
    assert result.cost_info is not None
    assert result.cost_info.model == "voyage-3"
    assert result.cost_info.success is True
    assert result.cost_info.input_tokens > 0


def test_transcript_resolver_voyage_unavailable_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    signal = {
        "id": 13,
        "source": "meeting",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "any content",
        "payload": {},
    }

    def broken_embed(text: str) -> list[float]:
        raise VoyageUnavailableError("mock 503")

    result = transcript_resolver.resolve(signal, conn=None, embed_fn=broken_embed)
    assert result.paths == ()
    # Cost ledger still written, with success=False.
    assert result.cost_info is not None
    assert result.cost_info.success is False
    assert result.cost_info.cost_usd == 0.0


def test_transcript_resolver_no_stored_embeddings_skips_voyage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If no wiki file has a stored embedding we skip the API call and
    emit no cost row — saves the Voyage charge for matters that have no
    prior context to compare against."""
    empty_vault = tmp_path / "vault"
    (empty_vault / "wiki" / "new-matter").mkdir(parents=True)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(empty_vault))
    called = []

    def should_not_be_called(text: str) -> list[float]:
        called.append(1)
        return [1.0]

    signal = {
        "id": 14,
        "source": "meeting",
        "primary_matter": "new-matter",
        "raw_content": "first signal under this matter",
        "payload": {},
    }
    result = transcript_resolver.resolve(
        signal, conn=None, embed_fn=should_not_be_called
    )
    assert result.paths == ()
    assert result.cost_info is None
    assert not called


def test_transcript_resolver_threshold_env_excludes_low_similarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    monkeypatch.setenv("KBL_STEP2_RESOLVE_THRESHOLD", "0.9999")
    signal = {
        "id": 15,
        "source": "meeting",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "abc",
        "payload": {},
    }

    def fake_embed(text: str) -> list[float]:
        return [0.95, 0.05, 0.0, 0.0]

    result = transcript_resolver.resolve(signal, conn=None, embed_fn=fake_embed)
    # At 0.9999 threshold even the tight-cluster stored vectors don't qualify.
    assert result.paths == ()


def test_transcript_resolver_empty_matter_short_circuits() -> None:
    signal = {
        "id": 16,
        "source": "meeting",
        "primary_matter": None,
        "raw_content": "content",
        "payload": {},
    }
    called = []
    result = transcript_resolver.resolve(
        signal, conn=None, embed_fn=lambda t: called.append(1) or [1.0]
    )
    assert result.paths == ()
    assert result.cost_info is None
    assert not called


def test_transcript_resolver_vault_unset_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    signal = {
        "id": 17,
        "source": "meeting",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "content",
        "payload": {},
    }
    called = []
    result = transcript_resolver.resolve(
        signal, conn=None, embed_fn=lambda t: called.append(1) or [1.0]
    )
    assert result.paths == ()
    assert result.cost_info is None
    assert not called


# ------------------------------ scan resolver ------------------------------


def test_scan_resolver_uses_director_context_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    captured = {}

    def fake_embed(text: str) -> list[float]:
        captured["text"] = text
        return [0.95, 0.05, 0.0, 0.0]

    signal = {
        "id": 20,
        "source": "scan",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "short",
        "payload": {
            "director_context_hint": "Ofenheimer demand letter status, Hassa reply open"
        },
    }
    result = scan_resolver.resolve(signal, conn=None, embed_fn=fake_embed)
    assert captured["text"].startswith("Ofenheimer")
    assert len(result.paths) == 3
    assert result.cost_info is not None
    assert result.cost_info.success is True


def test_scan_resolver_falls_back_to_raw_content_when_no_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    captured = {}

    def fake_embed(text: str) -> list[float]:
        captured["text"] = text
        return [0.95, 0.05, 0.0, 0.0]

    signal = {
        "id": 21,
        "source": "scan",
        "primary_matter": "hagenauer-rg7",
        "raw_content": "Director asks for Ofenheimer + Hassa status summary",
        "payload": {},
    }
    scan_resolver.resolve(signal, conn=None, embed_fn=fake_embed)
    assert captured["text"].startswith("Director asks")


# ------------------------------ dispatcher ------------------------------


def _dispatch_conn(signal: dict[str, Any]) -> tuple[MagicMock, _Recorder]:
    """Conn that serves SELECT signal_queue, UPDATE status, UPDATE result,
    INSERT kbl_cost_ledger in order."""
    payload = signal.get("payload") or {}
    row = (
        signal["id"],
        signal["source"],
        signal["primary_matter"],
        signal.get("raw_content") or "",
        payload,
    )
    script: list[tuple[str, Any]] = [
        ("select id, source, primary_matter", row),
        ("update signal_queue set status = %s where id", None),
        # The resolver's own queries (if any) are claimed next — but
        # email/wa resolvers go through their own cursor() calls via
        # the same _Recorder; provide those rows ahead of the final
        # UPDATE for the result. For tests we patch the resolver itself.
        ("update signal_queue set", None),
    ]
    return _mock_conn(script)


def test_dispatcher_routes_email_to_email_resolver() -> None:
    signal = {
        "id": 1,
        "source": "email",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    with patch.object(
        email_resolver,
        "resolve",
        return_value=ResolveResult(paths=("wiki/movie/a.md",)),
    ) as m_email, patch.object(wa_resolver, "resolve") as m_wa, patch.object(
        transcript_resolver, "resolve"
    ) as m_transcript, patch.object(scan_resolver, "resolve") as m_scan:
        out = resolve(1, conn)
    assert out == ["wiki/movie/a.md"]
    m_email.assert_called_once()
    m_wa.assert_not_called()
    m_transcript.assert_not_called()
    m_scan.assert_not_called()


def test_dispatcher_routes_whatsapp() -> None:
    signal = {
        "id": 2,
        "source": "whatsapp",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {"chat_id": "x@g.us"},
    }
    conn, _ = _dispatch_conn(signal)
    with patch.object(
        wa_resolver, "resolve", return_value=ResolveResult(paths=("wiki/movie/b.md",))
    ) as m_wa:
        out = resolve(2, conn)
    assert out == ["wiki/movie/b.md"]
    m_wa.assert_called_once()


def test_dispatcher_routes_meeting_to_transcript() -> None:
    signal = {
        "id": 3,
        "source": "meeting",
        "primary_matter": "movie",
        "raw_content": "transcript",
        "payload": {},
    }
    conn, _ = _dispatch_conn(signal)
    cost = CostInfo(model="voyage-3", input_tokens=10, cost_usd=0.00001, success=True)
    with patch.object(
        transcript_resolver,
        "resolve",
        return_value=ResolveResult(paths=("wiki/movie/c.md",), cost_info=cost),
    ) as m_t:
        out = resolve(3, conn)
    assert out == ["wiki/movie/c.md"]
    m_t.assert_called_once()


def test_dispatcher_routes_scan() -> None:
    signal = {
        "id": 4,
        "source": "scan",
        "primary_matter": "movie",
        "raw_content": "q",
        "payload": {},
    }
    conn, _ = _dispatch_conn(signal)
    with patch.object(
        scan_resolver, "resolve", return_value=ResolveResult(paths=())
    ) as m_s:
        resolve(4, conn)
    m_s.assert_called_once()


def test_dispatcher_writes_result_as_jsonb_array() -> None:
    signal = {
        "id": 1,
        "source": "email",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    with patch.object(
        email_resolver,
        "resolve",
        return_value=ResolveResult(paths=("wiki/movie/a.md",)),
    ):
        resolve(1, conn)
    # The final UPDATE must serialize the paths as a JSON array.
    update_calls = [c for c in rec.calls if "resolved_thread_paths" in c[0]]
    assert update_calls
    _sql, params = update_calls[0]
    assert params[0] == json.dumps(["wiki/movie/a.md"])
    assert params[1] == "awaiting_extract"


def test_dispatcher_writes_empty_array_on_no_match() -> None:
    signal = {
        "id": 1,
        "source": "email",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    with patch.object(email_resolver, "resolve", return_value=ResolveResult()):
        out = resolve(1, conn)
    assert out == []
    update_calls = [c for c in rec.calls if "resolved_thread_paths" in c[0]]
    _sql, params = update_calls[0]
    assert params[0] == "[]"


def test_dispatcher_writes_cost_ledger_only_for_embedding_resolvers() -> None:
    signal = {
        "id": 1,
        "source": "meeting",
        "primary_matter": "movie",
        "raw_content": "t",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    cost = CostInfo(model="voyage-3", input_tokens=50, cost_usd=0.00001, success=True)
    with patch.object(
        transcript_resolver,
        "resolve",
        return_value=ResolveResult(paths=(), cost_info=cost),
    ):
        resolve(1, conn)
    cost_calls = [c for c in rec.calls if "kbl_cost_ledger" in c[0]]
    assert cost_calls
    _sql, params = cost_calls[0]
    assert "voyage-3" in params
    assert 50 in params
    assert True in params


def test_dispatcher_no_cost_ledger_for_metadata_resolvers() -> None:
    signal = {
        "id": 1,
        "source": "email",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    with patch.object(
        email_resolver,
        "resolve",
        return_value=ResolveResult(paths=("wiki/movie/a.md",)),
    ):
        resolve(1, conn)
    assert not any("kbl_cost_ledger" in c[0] for c in rec.calls)


def test_dispatcher_marks_failed_when_resolver_raises_unexpected() -> None:
    signal = {
        "id": 1,
        "source": "email",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    with patch.object(
        email_resolver, "resolve", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(ResolverError, match="boom"):
            resolve(1, conn)
    # Must have transitioned the signal to resolve_failed before re-raising.
    failed_calls = [
        c for c in rec.calls if "resolved_thread_paths" in c[0]
    ]
    assert failed_calls
    _sql, params = failed_calls[0]
    assert params[1] == "resolve_failed"


def test_dispatcher_lookup_error_when_signal_missing() -> None:
    conn, _rec = _mock_conn([("select id, source, primary_matter", None)])
    with pytest.raises(LookupError, match="row not found"):
        resolve(9999, conn)


def test_dispatcher_invariant_paths_always_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4.3 invariant: resolved_thread_paths is never NULL and always an array."""
    signal = {
        "id": 1,
        "source": "email",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    with patch.object(email_resolver, "resolve", return_value=ResolveResult()):
        resolve(1, conn)
    update_calls = [c for c in rec.calls if "resolved_thread_paths" in c[0]]
    _sql, params = update_calls[0]
    assert json.loads(params[0]) == []


def test_dispatcher_invariant_paths_vault_relative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4.3 invariant: every path starts with wiki/. Non-compliant entries
    are dropped with a WARN log rather than failing the signal."""
    signal = {
        "id": 1,
        "source": "email",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    with patch.object(
        email_resolver,
        "resolve",
        return_value=ResolveResult(
            paths=("wiki/movie/ok.md", "/abs/not-allowed.md", "wrong/prefix.md")
        ),
    ):
        out = resolve(1, conn)
    assert out == ["wiki/movie/ok.md"]


def test_dispatcher_unknown_source_gives_empty_arc() -> None:
    signal = {
        "id": 1,
        "source": "rss_feed",
        "primary_matter": "movie",
        "raw_content": "",
        "payload": {},
    }
    conn, rec = _dispatch_conn(signal)
    out = resolve(1, conn)
    assert out == []
    update_calls = [c for c in rec.calls if "resolved_thread_paths" in c[0]]
    _sql, params = update_calls[0]
    # Dispatches to no resolver and advances to awaiting_extract (not failed).
    assert params[1] == "awaiting_extract"


# ------------------------------ module surface ------------------------------


def test_module_public_surface() -> None:
    assert hasattr(step2_resolve, "resolve")
    assert hasattr(email_resolver, "resolve")
    assert hasattr(wa_resolver, "resolve")
    assert hasattr(transcript_resolver, "resolve")
    assert hasattr(scan_resolver, "resolve")
