import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.settings import Qwen3Config
from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkGuardrails,
    ClerkRuntimeError,
    ClerkToolRegistry,
    Qwen3ToolClient,
    _TextBlock,
    _ToolResponse,
    _ToolUseBlock,
    _CLERK_SYSTEM_PROMPT,
)


class _FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("no fake response left")
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


class _RaisingMessages:
    def __init__(self, exc):
        self.exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise self.exc


class _RaisingClient:
    def __init__(self, exc):
        self.messages = _RaisingMessages(exc)


class _FakeRegistry:
    tools = [
        {
            "name": "file_save",
            "description": "save",
            "input_schema": {"type": "object"},
        }
    ]

    def __init__(self):
        self.calls = []

    def execute(self, name, args):
        self.calls.append((name, args))
        return json.dumps({"status": "ready", "path": "/Baker-Feed/Clerk-Workbench/out.md"})


def _cfg(max_steps=12, timeout=180):
    return Qwen3Config(
        base_url="https://qwen.example/v1",
        api_key="test-key",
        model="qwen3-coder",
        backend="qwen3_hosted",
        max_steps=max_steps,
        task_timeout_s=timeout,
    )


def test_tool_round_trip_with_mock_qwen_client():
    registry = _FakeRegistry()
    client = _FakeClient([
        _ToolResponse([
            _ToolUseBlock("call_1", "file_save", {"content": "hello", "filename": "out.md"})
        ], "tool_use", 10, 5),
        _ToolResponse([
            _TextBlock("Ready: /Baker-Feed/Clerk-Workbench/out.md / Source: test")
        ], "end_turn", 8, 4),
    ])

    result = ClerkAgent(model_client=client, registry=registry, cfg=_cfg()).run("convert and save")

    assert result["status"] == "ready"
    assert "Ready:" in result["answer"]
    assert registry.calls == [("file_save", {"content": "hello", "filename": "out.md"})]
    assert result["usage"]["input_tokens"] == 18
    assert result["usage"]["output_tokens"] == 9
    assert result["usage"]["prompt_tokens"] == 18
    assert result["usage"]["completion_tokens"] == 9
    assert result["usage"]["total_tokens"] == 27
    assert result["usage"]["context_window_used"] == 10


def test_malformed_tool_output_retries_once_then_escalates():
    registry = _FakeRegistry()
    qwen = _FakeClient([
        _ToolResponse([_ToolUseBlock("bad_1", "file_save", {"__malformed_json": "{"})], "tool_use", 11, 5, cost=0.001),
        _ToolResponse([_ToolUseBlock("bad_2", "file_save", {"__malformed_json": "{"})], "tool_use", 13, 7, cost=0.002),
    ])
    gemini = _FakeClient([
        _ToolResponse([_TextBlock("Ready: escalated")], "end_turn", 3, 2)
    ])

    result = ClerkAgent(
        model_client=qwen,
        escalation_client=gemini,
        registry=registry,
        cfg=_cfg(),
    ).run("fetch and save")

    assert result["status"] == "ready"
    assert result["escalated"] is True
    assert "repeated schema/tool failure" in result["reason"]
    assert len(qwen.messages.calls) == 2
    assert len(gemini.messages.calls) == 1
    assert result["usage"]["prompt_tokens"] == 24
    assert result["usage"]["completion_tokens"] == 12
    assert result["usage"]["total_tokens"] == 36
    assert result["usage"]["context_window_used"] == 13
    assert result["usage"]["session_cost_usd"] == pytest.approx(0.003)


def test_tool_input_guardrail_preserves_usage_before_approval_exit():
    registry = _FakeRegistry()
    client = _FakeClient([
        _ToolResponse(
            [_ToolUseBlock("call_1", "file_save", {"content": "delete this email", "filename": "out.md"})],
            "tool_use",
            17,
            6,
            total_tokens=25,
            cost=0.0042,
        )
    ])

    result = ClerkAgent(model_client=client, registry=registry, cfg=_cfg()).run("save the note")

    assert result["status"] == "pending_approval"
    assert result["denylist_item"] == 5
    assert registry.calls == []
    assert result["usage"]["prompt_tokens"] == 17
    assert result["usage"]["completion_tokens"] == 6
    assert result["usage"]["total_tokens"] == 25
    assert result["usage"]["context_window_used"] == 17
    assert result["usage"]["session_cost_usd"] == pytest.approx(0.0042)


@pytest.mark.parametrize(
    ("task", "status", "item"),
    [
        ("please wire money to this counterparty", "blocked", 1),
        ("act as Dimitry and approve this note", "blocked", 2),
        ("deploy production after changing code", "blocked", 3),
        ("create matter slug new-project", "blocked", 4),
        ("delete this email after reading", "pending_approval", 5),
        ("purge the message", "pending_approval", 5),
        ("remove this email", "pending_approval", 5),
        ("send external email to person@example.com", "pending_approval", 6),
        ("email the invoice to a@b.com", "pending_approval", 6),
        ("forward this to a@b.com", "pending_approval", 6),
        ("reply to X with the file", "pending_approval", 6),
        ("permanently finalize transaction", "pending_approval", 7),
        ("pay the supplier 5000 EUR", "blocked", 1),
        ("wire 10k to vendor", "blocked", 1),
    ],
)
def test_denylist_enforced_before_model_call(task, status, item):
    client = _FakeClient([_ToolResponse([_TextBlock("should not run")], "end_turn")])

    result = ClerkAgent(model_client=client, registry=_FakeRegistry(), cfg=_cfg()).run(task)

    assert result["status"] == status
    assert result["denylist_item"] == item
    assert client.messages.calls == []


def test_approval_required_items_cannot_be_unlocked_by_phase1_token():
    client = _FakeClient([_ToolResponse([_TextBlock("Ready: draft")], "end_turn")])

    result = ClerkAgent(model_client=client, registry=_FakeRegistry(), cfg=_cfg()).run("delete this email after reading")

    assert result["status"] == "pending_approval"
    assert client.messages.calls == []


def test_internal_bus_reply_task_is_allowed_not_external_send():
    task = "reply on the bus to lead with a one-line ack"
    client = _FakeClient([_ToolResponse([_TextBlock("Ack: received")], "end_turn")])

    result = ClerkAgent(model_client=client, registry=_FakeRegistry(), cfg=_cfg()).run(task)

    assert ClerkGuardrails().check(task).allowed is True
    assert result["status"] == "ready"
    assert result["answer"] == "Ack: received"
    assert len(client.messages.calls) == 1
    assert "internal Brisen agent bus" in client.messages.calls[0]["system"]
    assert "not an external send" in " ".join(_CLERK_SYSTEM_PROMPT.split())


def test_email_search_defaults_to_all_provider_and_merges_mailboxes(monkeypatch):
    monkeypatch.setattr("orchestrator.clerk_runtime.config.qwen3.default_mail_provider", "all")
    registry = ClerkToolRegistry()
    calls = []

    def fake_graph_search(query, max_results):
        calls.append(("search", query, max_results))
        return json.dumps({"provider": "graph", "match_count": 1, "matches": [{"subject": "graph"}]})

    def fake_store_search(query, max_results):
        calls.append(("store", query, max_results))
        return json.dumps({"channel": "email_store", "count": 1, "results": [{"subject": "store"}]})

    def fake_dispatch(tool_name, payload):
        calls.append(("gmail", tool_name, payload))
        return json.dumps({"messages": [{"subject": "gmail"}]})

    monkeypatch.setattr(registry, "_graph_email_search", fake_graph_search)
    monkeypatch.setattr(registry, "_email_store_search", fake_store_search)
    monkeypatch.setitem(sys.modules, "tools.gmail", SimpleNamespace(dispatch_gmail=fake_dispatch))

    search_tool = next(tool for tool in registry.tools if tool["name"] == "email_search")
    download_tool = next(tool for tool in registry.tools if tool["name"] == "email_download")
    assert search_tool["input_schema"]["properties"]["provider"]["default"] == "all"
    assert download_tool["input_schema"]["properties"]["provider"]["default"] == "all"

    search = json.loads(registry.execute("email_search", {"query": "from:peter"}))

    assert search["provider"] == "all"
    assert search["match_count"] == 3
    assert set(search["results"]) == {"graph", "gmail", "store"}
    assert calls == [
        ("search", "from:peter", 10),
        ("gmail", "baker_gmail_search", {"query": "from:peter", "max_results": 10}),
        ("store", "from:peter", 10),
    ]


def test_email_search_keeps_explicit_gmail_provider_selectable(monkeypatch):
    monkeypatch.setattr("orchestrator.clerk_runtime.config.qwen3.default_mail_provider", "graph")
    calls = []

    def fake_dispatch(tool_name, payload):
        calls.append((tool_name, payload))
        return json.dumps({"provider": "gmail", "payload": payload})

    monkeypatch.setitem(sys.modules, "tools.gmail", SimpleNamespace(dispatch_gmail=fake_dispatch))
    registry = ClerkToolRegistry()

    result = json.loads(registry.execute("email_search", {"provider": "gmail", "query": "from:peter"}))

    assert result["provider"] == "gmail"
    assert calls == [("baker_gmail_search", {"query": "from:peter", "max_results": 10})]


def test_email_search_rewrites_fabricated_from_address_to_all_name_search(monkeypatch, caplog):
    registry = ClerkToolRegistry()
    calls = []

    def fake_graph_search(query, max_results):
        calls.append(("graph", query, max_results))
        return json.dumps({"provider": "graph", "match_count": 0, "matches": []})

    def fake_store_search(query, max_results):
        calls.append(("store", query, max_results))
        return json.dumps({"channel": "email_store", "count": 1, "results": [{"sender": "pestorer@nvidia.com"}]})

    def fake_dispatch(tool_name, payload):
        calls.append(("gmail", tool_name, payload))
        return json.dumps({"messages": []})

    monkeypatch.setattr(registry, "_graph_email_search", fake_graph_search)
    monkeypatch.setattr(registry, "_email_store_search", fake_store_search)
    monkeypatch.setitem(sys.modules, "tools.gmail", SimpleNamespace(dispatch_gmail=fake_dispatch))
    caplog.set_level("INFO", logger="baker.clerk_runtime")

    result = json.loads(registry.execute(
        "email_search",
        {"provider": "graph", "query": "private-extra from:peter.storer@example.com", "max_results": 1},
    ))

    assert result["provider"] == "all"
    assert result["query"] == "peter storer"
    assert result["query_guard"]["reason"] == "fabricated_placeholder_address"
    assert result["query_guard"]["original_provider"] == "graph"
    serialized = json.dumps(result) + json.dumps(calls) + caplog.text
    assert "example.com" not in serialized
    assert "private-extra" not in serialized
    assert calls == [
        ("graph", "peter storer", 10),
        ("gmail", "baker_gmail_search", {"query": "peter storer", "max_results": 10}),
        ("store", "peter storer", 10),
    ]


def test_email_search_placeholder_without_name_does_not_broaden_to_recent_mail(monkeypatch):
    registry = ClerkToolRegistry()
    calls = []

    monkeypatch.setattr(registry, "_graph_email_search", lambda *args: calls.append(("graph", args)) or "{}")
    monkeypatch.setattr(registry, "_email_store_search", lambda *args: calls.append(("store", args)) or "{}")
    monkeypatch.setitem(
        sys.modules,
        "tools.gmail",
        SimpleNamespace(dispatch_gmail=lambda *args: calls.append(("gmail", args)) or "{}"),
    )

    result = json.loads(registry.execute(
        "email_search",
        {"provider": "graph", "query": "from:foo@bar", "max_results": 1},
    ))

    assert result["status"] == "blocked"
    assert result["match_count"] == 0
    assert result["query_guard"]["status"] == "blocked"
    assert "query" not in result
    assert calls == []


def test_email_search_prompt_and_description_forbid_synthesized_addresses():
    registry = ClerkToolRegistry()
    search_tool = next(tool for tool in registry.tools if tool["name"] == "email_search")
    description = search_tool["description"]
    prompt = " ".join(_CLERK_SYSTEM_PROMPT.split())

    assert "person's name" in description
    assert "Default provider is all" in description
    assert "Do not synthesize or guess an address" in description
    assert "search by the name itself" in prompt
    assert "Never invent, guess, or fabricate email addresses" in prompt
    assert "example.com" in prompt
    assert "plain text only" in prompt
    assert "Do not use markdown syntax" in prompt


def test_email_store_search_fuzzy_fallback_resolves_name_typo(monkeypatch):
    class FakeRetriever:
        def get_email_messages(self, query, limit):
            assert query == "Petzer Storer"
            assert limit == 10
            return []

    class FakeSentinelRetriever:
        @staticmethod
        def _get_global_instance():
            return FakeRetriever()

    registry = ClerkToolRegistry()
    query_calls = []

    def fake_query_rows(sql, params):
        query_calls.append((sql, params))
        return [{
            "message_id": "msg-1",
            "thread_id": "thread-1",
            "sender_name": "Peter Storer",
            "sender_email": "pestorer@nvidia.com",
            "subject": "NVIDIA status",
            "body_preview": "Latest note",
            "received_date": "2026-06-06T10:00:00Z",
            "priority": None,
            "ingested_at": "2026-06-06T10:01:00Z",
        }]

    monkeypatch.setitem(sys.modules, "memory.retriever", SimpleNamespace(SentinelRetriever=FakeSentinelRetriever))
    monkeypatch.setattr(registry, "_query_rows", fake_query_rows)

    result = json.loads(registry.execute("email_search", {"provider": "store", "query": "Petzer Storer"}))

    assert result["channel"] == "email_store"
    assert result["count"] == 1
    assert result["results"][0]["sender_email"] == "pestorer@nvidia.com"
    assert result["fuzzy"]["triggered"] is True
    assert result["fuzzy"]["interpreted"] == {"Petzer": "Peter"}
    assert "interpreted 'Petzer' as 'Peter'" in result["fuzzy"]["note"]
    assert query_calls
    assert query_calls[0][1] == (8000, 1000)


def test_email_store_fuzzy_query_uses_real_email_message_columns(monkeypatch):
    registry = ClerkToolRegistry()
    captured = {}

    def fake_query_rows(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(registry, "_query_rows", fake_query_rows)

    result = json.loads(registry._email_store_fuzzy_search("Petzer Storer", 10))

    assert result == {"channel": "email_store", "count": 0, "results": []}
    assert "body_preview" not in captured["sql"].split("FROM email_messages", 1)[1]
    assert "LEFT(full_body, %s) AS body_preview" in captured["sql"]
    assert "WHERE sender_name IS NOT NULL OR sender_email IS NOT NULL" in " ".join(captured["sql"].split())
    assert captured["params"] == (8000, 1000)


def test_email_store_fuzzy_person_single_token_does_not_match_subject_substring(monkeypatch):
    registry = ClerkToolRegistry()

    monkeypatch.setattr(registry, "_query_rows", lambda *args: [{
        "message_id": "msg-annual",
        "thread_id": "thread-annual",
        "sender_name": "Finance Bot",
        "sender_email": "finance@example.com",
        "subject": "Annual budget update",
        "body_preview": "Annual plan",
        "received_date": "2026-06-06T10:00:00Z",
        "priority": None,
        "ingested_at": "2026-06-06T10:01:00Z",
    }])

    result = json.loads(registry._email_store_fuzzy_search("person:Ann", 10))

    assert result == {"channel": "email_store", "count": 0, "results": []}


def test_email_store_fuzzy_fallback_does_not_fire_for_single_keyword(monkeypatch):
    class FakeRetriever:
        def get_email_messages(self, query, limit):
            return []

    class FakeSentinelRetriever:
        @staticmethod
        def _get_global_instance():
            return FakeRetriever()

    registry = ClerkToolRegistry()
    query_calls = []

    monkeypatch.setitem(sys.modules, "memory.retriever", SimpleNamespace(SentinelRetriever=FakeSentinelRetriever))
    monkeypatch.setattr(registry, "_query_rows", lambda *args: query_calls.append(args) or [])

    result = json.loads(registry.execute("email_search", {"provider": "store", "query": "NVIDIA"}))

    assert result == {"channel": "email_store", "count": 0, "results": []}
    assert query_calls == []


def test_baker_search_reuses_documents_search_core(monkeypatch):
    # CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1 (C): baker_search no longer calls
    # SentinelRetriever.search_all_collections (the Qdrant path that returned 0
    # for "Peter Storer"); it reuses search_documents_core — the SAME PG
    # documents semantic+ILIKE retrieval GET /api/documents/search uses (43 hits).
    calls = []

    def fake_core(query, **kwargs):
        calls.append((query, kwargs))
        return {
            "results": [{
                "id": 11,
                "title": "storer.pdf",
                "document_type": "letter",
                "matter": "hagenauer-rg7",
                "source_path": "/v/storer.pdf",
                "date": "2026-06-07",
                "summary": "Peter Storer ...",
                "score": 0.91,
            }],
            "total": 43,
            "mode": "semantic",
        }

    monkeypatch.setitem(sys.modules, "outputs.dashboard", SimpleNamespace(search_documents_core=fake_core))
    registry = ClerkToolRegistry()

    result = json.loads(registry.execute("baker_search", {"query": "Peter Storer", "max_results": 4}))

    assert result["channel"] == "baker_search"
    assert result["count"] == 43
    assert result["results"][0]["label"] == "storer.pdf"
    assert calls and calls[0][0] == "Peter Storer" and calls[0][1].get("limit") == 4


def test_channel_search_slack_and_rss_use_read_only_sql(monkeypatch):
    registry = ClerkToolRegistry()
    calls = []

    def fake_query_rows(sql, params):
        calls.append((sql, params))
        if "FROM slack_messages" in sql:
            return [{"id": "slack-1", "channel_name": "cockpit", "full_text": "Peter update"}]
        if "FROM rss_articles" in sql:
            return [{"id": 7, "title": "NVIDIA", "feed_title": "Tech", "summary": "GPU news"}]
        raise AssertionError(sql)

    monkeypatch.setattr(registry, "_query_rows", fake_query_rows)

    slack = json.loads(registry.execute("channel_search", {"channel": "slack", "query": "Peter"}))
    rss = json.loads(registry.execute("channel_search", {"channel": "rss", "query": "NVIDIA"}))

    assert slack == {"channel": "slack", "count": 1, "results": [{"id": "slack-1", "channel_name": "cockpit", "full_text": "Peter update"}]}
    assert rss["channel"] == "rss"
    assert rss["results"][0]["title"] == "NVIDIA"
    assert all("INSERT " not in sql and "UPDATE " not in sql and "DELETE " not in sql for sql, _ in calls)


def test_transcripts_by_matter_filters_existing_transcript_table(monkeypatch):
    registry = ClerkToolRegistry()
    seen = {}

    def fake_query_rows(sql, params):
        seen["sql"] = sql
        seen["params"] = params
        return [{"id": "mtg-1", "title": "Hag meeting", "matter_slug": "hagenauer-rg7", "transcript": "body"}]

    monkeypatch.setattr(registry, "_query_rows", fake_query_rows)

    result = json.loads(registry.execute(
        "transcripts_by_matter",
        {"matter_slug": "hagenauer-rg7", "query": "court", "max_results": 3},
    ))

    assert result["channel"] == "transcripts_by_matter"
    assert result["results"][0]["matter_slug"] == "hagenauer-rg7"
    assert "FROM meeting_transcripts" in seen["sql"]
    assert "%hagenauer-rg7%" in seen["params"]


def test_step_cap_stops_unbounded_loop():
    registry = _FakeRegistry()
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("call_1", "file_save", {"content": "a", "filename": "a.md"})], "tool_use"),
        _ToolResponse([_ToolUseBlock("call_2", "file_save", {"content": "b", "filename": "b.md"})], "tool_use"),
    ])

    result = ClerkAgent(model_client=client, registry=registry, cfg=_cfg(max_steps=2)).run("keep looping")

    assert result["status"] == "blocked"
    assert result["reason"] == "max_steps exceeded"
    assert len(registry.calls) == 2


def test_timeout_stops_before_model_call():
    ticks = iter([0, 2])
    client = _FakeClient([_ToolResponse([_TextBlock("should not run")], "end_turn")])

    result = ClerkAgent(
        model_client=client,
        registry=_FakeRegistry(),
        cfg=_cfg(timeout=1),
        clock=lambda: next(ticks),
    ).run("slow task")

    assert result["status"] == "timeout"
    assert client.messages.calls == []


def test_qwen_host_guard_for_hosted_and_local_backends():
    with pytest.raises(ClerkRuntimeError, match="local/private/reserved"):
        Qwen3ToolClient(Qwen3Config(
            base_url="https://localhost:11434/v1",
            api_key="x",
            model="qwen3-coder",
            backend="qwen3_hosted",
        ), http_client=SimpleNamespace())

    with pytest.raises(ClerkRuntimeError, match="local/private/reserved"):
        Qwen3ToolClient(Qwen3Config(
            base_url="https://169.254.169.254/v1",
            api_key="x",
            model="qwen3-coder",
            backend="qwen3_hosted",
        ), http_client=SimpleNamespace())

    with pytest.raises(ClerkRuntimeError, match="local/private/reserved"):
        Qwen3ToolClient(Qwen3Config(
            base_url="https://10.0.0.5/v1",
            api_key="x",
            model="qwen3-coder",
            backend="qwen3_hosted",
        ), http_client=SimpleNamespace())

    with pytest.raises(ClerkRuntimeError, match="local/private/reserved"):
        Qwen3ToolClient(Qwen3Config(
            base_url="https://127.1/v1",
            api_key="x",
            model="qwen3-coder",
            backend="qwen3_hosted",
        ), http_client=SimpleNamespace())

    with pytest.raises(ClerkRuntimeError, match="only permits localhost"):
        Qwen3ToolClient(Qwen3Config(
            base_url="https://8.8.8.8/v1",
            api_key="",
            model="qwen3-coder",
            backend="qwen3_ollama_local",
        ), http_client=SimpleNamespace())

    hosted = Qwen3ToolClient(Qwen3Config(
        base_url="https://8.8.8.8/v1",
        api_key="x",
        model="qwen3-coder",
        backend="qwen3_hosted",
    ), http_client=SimpleNamespace())
    assert hosted.base_url == "https://8.8.8.8/v1"

    client = Qwen3ToolClient(Qwen3Config(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen3-coder",
        backend="qwen3_ollama_local",
    ), http_client=SimpleNamespace())
    assert client.base_url == "http://localhost:11434/v1"


def test_qwen_client_parses_openrouter_usage_cost():
    class HTTP:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "choices": [{"message": {"content": "Ready"}}],
                    "usage": {
                        "prompt_tokens": 12000,
                        "completion_tokens": 345,
                        "total_tokens": 12345,
                        "cost": 0.0042,
                    },
                },
            )

    http = HTTP()
    client = Qwen3ToolClient(Qwen3Config(
        base_url="https://8.8.8.8/v1",
        api_key="x",
        model="qwen3-coder",
        backend="qwen3_hosted",
    ), http_client=http)

    resp = client.messages.create(model="qwen3-coder", messages=[{"role": "user", "content": "hi"}])

    assert http.calls[0][0] == "https://8.8.8.8/v1/chat/completions"
    assert "usage" not in http.calls[0][1]["json"]
    assert resp.usage.prompt_tokens == 12000
    assert resp.usage.completion_tokens == 345
    assert resp.usage.total_tokens == 12345
    assert resp.usage.cost == 0.0042


def test_qwen_client_preserves_missing_usage_as_unknown():
    class HTTP:
        def post(self, url, **kwargs):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"choices": [{"message": {"content": "Ready"}}]},
            )

    client = Qwen3ToolClient(Qwen3Config(
        base_url="https://8.8.8.8/v1",
        api_key="x",
        model="qwen3-coder",
        backend="qwen3_hosted",
    ), http_client=HTTP())

    resp = client.messages.create(model="qwen3-coder", messages=[{"role": "user", "content": "hi"}])

    assert resp.usage.prompt_tokens is None
    assert resp.usage.completion_tokens is None
    assert resp.usage.total_tokens is None
    assert resp.usage.cost is None
    assert resp.usage.input_tokens == 0
    assert resp.usage.output_tokens == 0


def test_agent_computes_cost_only_from_configured_prices_when_api_cost_absent():
    cfg = Qwen3Config(
        base_url="https://qwen.example/v1",
        api_key="test-key",
        model="qwen3-coder",
        backend="qwen3_hosted",
        max_steps=12,
        task_timeout_s=180,
        context_window_max=1000000,
        prompt_price_per_m=0.3,
        completion_price_per_m=0.8,
    )
    client = _FakeClient([
        _ToolResponse([_TextBlock("Ready")], "end_turn", 1000, 2000),
    ])

    result = ClerkAgent(model_client=client, registry=_FakeRegistry(), cfg=cfg).run("draft")

    assert result["usage"]["context_window_max"] == 1000000
    assert result["usage"]["context_window_used"] == 1000
    assert result["usage"]["total_tokens"] == 3000
    assert result["usage"]["session_cost_usd"] == pytest.approx(0.0019)


def test_agent_accumulates_api_provided_cost():
    client = _FakeClient([
        _ToolResponse([_TextBlock("Ready")], "end_turn", 12000, 345, total_tokens=12345, cost=0.0042),
    ])

    result = ClerkAgent(model_client=client, registry=_FakeRegistry(), cfg=_cfg()).run("draft")

    assert result["usage"]["prompt_tokens"] == 12000
    assert result["usage"]["completion_tokens"] == 345
    assert result["usage"]["total_tokens"] == 12345
    assert result["usage"]["session_cost_usd"] == pytest.approx(0.0042)


def test_agent_leaves_cost_unknown_when_api_and_prices_are_absent():
    client = _FakeClient([
        _ToolResponse([_TextBlock("Ready")], "end_turn", 1000, 2000),
    ])

    result = ClerkAgent(model_client=client, registry=_FakeRegistry(), cfg=_cfg()).run("draft")

    assert result["usage"]["session_cost_usd"] is None


def test_file_save_uses_dropbox_upload_file_signature():
    class Dropbox:
        def __init__(self):
            self.calls = []

        def upload_file(self, local_path, dropbox_path):
            assert Path(local_path).exists()
            self.calls.append((local_path, dropbox_path))
            return {"path_display": dropbox_path, "size": 5}

    dropbox = Dropbox()
    registry = ClerkToolRegistry(dropbox_client=dropbox)

    raw = registry.execute("file_save", {"content": "hello", "filename": "out.md"})

    parsed = json.loads(raw)
    assert parsed["status"] == "ready"
    assert parsed["path"] == "/Baker-Feed/Clerk-Workbench/out.md"
    assert dropbox.calls[0][1] == "/Baker-Feed/Clerk-Workbench/out.md"


def test_file_save_outside_working_folder_blocks_even_if_model_sets_approved_path():
    calls = []
    registry = ClerkToolRegistry(dropbox_client=SimpleNamespace(upload_file=lambda *args: calls.append(args) or {}))

    raw = registry.execute(
        "file_save",
        {
            "content": "hello",
            "filename": "out.md",
            "dropbox_path": "/Director-Private/exfil.md",
            "approved_path": True,
        },
    )

    parsed = json.loads(raw)
    assert parsed["status"] == "blocked"
    assert calls == []


def test_file_save_allows_caller_side_exact_approved_path():
    calls = []
    target = "/Baker-Feed/Approved/out.md"
    registry = ClerkToolRegistry(
        dropbox_client=SimpleNamespace(upload_file=lambda *args: calls.append(args) or {"path_display": target}),
        approved_save_paths={target},
    )

    raw = registry.execute(
        "file_save",
        {
            "content": "hello",
            "filename": "out.md",
            "dropbox_path": target,
        },
    )

    parsed = json.loads(raw)
    assert parsed["status"] == "ready"
    assert parsed["path"] == target
    assert calls[0][1] == target


def test_registry_execute_catches_system_exit_as_controlled_error():
    class Registry(ClerkToolRegistry):
        def _file_save(self, args):
            raise SystemExit("gmail credentials missing")

    raw = Registry().execute("file_save", {"content": "hello", "filename": "out.md"})

    parsed = json.loads(raw)
    assert parsed == {"error": "file_save failed: SystemExit"}


def test_file_save_path_boundary_blocks_prefix_smuggling():
    calls = []
    registry = ClerkToolRegistry(dropbox_client=SimpleNamespace(upload_file=lambda *args: calls.append(args) or {}))

    raw = registry.execute(
        "file_save",
        {
            "content": "hello",
            "filename": "out.md",
            "dropbox_path": "/Baker-Feed/Clerk-Workbench-Evil/out.md",
        },
    )

    parsed = json.loads(raw)
    assert parsed["status"] == "blocked"
    assert calls == []


def test_file_save_schema_does_not_expose_approved_path_to_model():
    registry = ClerkToolRegistry()
    file_save = next(tool for tool in registry.tools if tool["name"] == "file_save")

    assert "approved_path" not in file_save["input_schema"]["properties"]


def test_format_convert_reuses_extractors_signature(tmp_path, monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="clerk_doc_"))
    target = root / "doc.md"
    target.write_text("hello", encoding="utf-8")
    seen = {}

    def fake_extract(path):
        seen["path"] = path
        return path.read_text(encoding="utf-8").upper()

    monkeypatch.setattr("tools.ingest.extractors.extract", fake_extract)
    registry = ClerkToolRegistry()

    raw = registry.execute("format_convert", {"local_path": str(target), "target_format": "markdown"})

    parsed = json.loads(raw)
    assert parsed["text"] == "HELLO"
    assert seen["path"] == target


def test_format_convert_blocks_arbitrary_local_file(tmp_path):
    target = tmp_path / "secret.md"
    target.write_text("secret", encoding="utf-8")
    registry = ClerkToolRegistry()

    raw = registry.execute("format_convert", {"local_path": str(target), "target_format": "markdown"})

    parsed = json.loads(raw)
    assert parsed["status"] == "blocked"


def test_document_fetch_returns_persistent_local_path(tmp_path, monkeypatch):
    class Dropbox:
        def download_file(self, path, dest_dir):
            out = dest_dir / Path(path).name
            out.write_text("body", encoding="utf-8")
            return out

    monkeypatch.setattr("tools.ingest.extractors.extract", lambda path: path.read_text(encoding="utf-8"))
    registry = ClerkToolRegistry(dropbox_client=Dropbox())

    raw = registry.execute("document_fetch", {"path": "/Baker-Feed/source.md"})

    parsed = json.loads(raw)
    assert parsed["text"] == "body"
    assert Path(parsed["local_path"]).exists()


def test_document_fetch_blocks_private_dropbox_paths():
    registry = ClerkToolRegistry(dropbox_client=SimpleNamespace(download_file=lambda *_: (_ for _ in ()).throw(AssertionError("no download"))))

    raw = registry.execute("document_fetch", {"path": "/Director-Private/secret.pdf"})

    parsed = json.loads(raw)
    assert parsed["status"] == "blocked"


def test_document_fetch_blocks_prefix_smuggling():
    registry = ClerkToolRegistry(dropbox_client=SimpleNamespace(download_file=lambda *_: (_ for _ in ()).throw(AssertionError("no download"))))

    raw = registry.execute("document_fetch", {"path": "/Baker-Feed-Evil/source.md"})

    parsed = json.loads(raw)
    assert parsed["status"] == "blocked"


def test_forbidden_tool_capability_rejected_before_execution():
    agent = ClerkAgent(model_client=_FakeClient([]), registry=_FakeRegistry(), cfg=_cfg())

    valid, error = agent._validate_tool_use(SimpleNamespace(name="send_email", input={}))

    assert valid is False
    assert "forbidden tool capability" in error


def test_escalation_path_cannot_upload_outside_working_folder():
    class Dropbox:
        def __init__(self):
            self.calls = []

        def upload_file(self, *args):
            self.calls.append(args)
            return {"path_display": args[1]}

    dropbox = Dropbox()
    registry = ClerkToolRegistry(dropbox_client=dropbox)
    qwen = _FakeClient([
        _ToolResponse([_ToolUseBlock("bad_1", "file_save", {"__malformed_json": "{"})], "tool_use"),
        _ToolResponse([_ToolUseBlock("bad_2", "file_save", {"__malformed_json": "{"})], "tool_use"),
    ])
    gemini = _FakeClient([
        _ToolResponse([
            _ToolUseBlock(
                "esc_1",
                "file_save",
                {"content": "x", "filename": "x.md", "dropbox_path": "/Somewhere/x.md", "approved_path": True},
            )
        ], "tool_use")
    ])

    result = ClerkAgent(model_client=qwen, escalation_client=gemini, registry=registry, cfg=_cfg()).run("fetch")

    assert result["status"] == "ready"
    assert "blocked" in result["answer"]
    assert dropbox.calls == []


def test_model_transport_exception_returns_controlled_blocked_result():
    client = _RaisingClient(TimeoutError("slow model"))

    result = ClerkAgent(model_client=client, registry=_FakeRegistry(), cfg=_cfg()).run("fetch")

    assert result["status"] == "blocked"
    assert result["reason"] == "model call failed"
    assert result["error_type"] == "TimeoutError"


def test_model_call_receives_remaining_task_timeout():
    ticks = iter([0.0, 0.25])
    client = _FakeClient([_ToolResponse([_TextBlock("Ready")], "end_turn")])

    result = ClerkAgent(
        model_client=client,
        registry=_FakeRegistry(),
        cfg=_cfg(timeout=1),
        clock=lambda: next(ticks),
    ).run("fetch")

    assert result["status"] == "ready"
    assert client.messages.calls[0]["timeout"] == pytest.approx(0.75)
