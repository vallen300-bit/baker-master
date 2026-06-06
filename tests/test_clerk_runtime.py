import json
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
    assert result["usage"] == {"input_tokens": 18, "output_tokens": 9}


def test_malformed_tool_output_retries_once_then_escalates():
    registry = _FakeRegistry()
    qwen = _FakeClient([
        _ToolResponse([_ToolUseBlock("bad_1", "file_save", {"__malformed_json": "{"})], "tool_use"),
        _ToolResponse([_ToolUseBlock("bad_2", "file_save", {"__malformed_json": "{"})], "tool_use"),
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
