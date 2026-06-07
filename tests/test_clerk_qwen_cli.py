from __future__ import annotations

import io
import json
import subprocess
import urllib.error
import urllib.request

import clerk_qwen


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_run_wait_uses_clerk_endpoints_and_prints_pending_approval(monkeypatch, capsys):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        url = req.full_url
        assert "/api/client-config" not in url
        if url == "https://baker.test/api/clerk/run":
            assert req.get_method() == "POST"
            assert req.headers["X-baker-key"] == "test-key"
            assert json.loads(req.data.decode("utf-8")) == {"task": "send external email"}
            return _FakeResponse({"session_id": "sess-1", "status": "running"})
        if url == "https://baker.test/api/clerk/session/sess-1":
            return _FakeResponse({
                "session_id": "sess-1",
                "status": "pending_approval",
                "result": {"reason": "external email requires Director approval"},
            })
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main([
        "run",
        "--base-url",
        "https://baker.test",
        "--api-key",
        "test-key",
        "--wait",
        "--interval-s",
        "0",
        "send",
        "external",
        "email",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert len(calls) == 2
    assert "Status: pending_approval" in out
    assert "PENDING APPROVAL" in out
    assert "Session for approval: sess-1" in out
    assert "https://baker.test/clerk/edit/sess-1" in out


def test_chat_sends_plain_english_line_and_prints_real_footer(monkeypatch, capsys):
    calls = []
    inputs = iter(["find emails from Peter in my Outlook", "exit"])

    def fake_input(prompt):
        assert prompt == "clerk> "
        return next(inputs)

    def fake_urlopen(req, timeout):
        calls.append(req)
        url = req.full_url
        if url == "https://baker.test/api/clerk/run":
            assert req.get_method() == "POST"
            assert json.loads(req.data.decode("utf-8")) == {"task": "find emails from Peter in my Outlook"}
            return _FakeResponse({"session_id": "sess-chat", "status": "running"})
        if url == "https://baker.test/api/clerk/session/sess-chat":
            return _FakeResponse({
                "session_id": "sess-chat",
                "status": "ready",
                "result": {
                    "status": "ready",
                    "answer": "Ready: /Baker-Feed/Clerk-Workbench/peter.md / Source: Outlook",
                },
                "draft_content": "Latest email from Peter Storer: status note about the hotel asset.",
                "draft_path": "/Baker-Feed/Clerk-Workbench/peter.md",
                "context_window_used": 12000,
                "context_window_max": 1000000,
                "total_tokens": 12345,
                "session_cost_usd": 0.0042,
                "model": "qwen/qwen3-coder-plus",
            })
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main([
        "chat",
        "--base-url",
        "https://baker.test",
        "--api-key",
        "test-key",
        "--interval-s",
        "0",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert len(calls) == 2
    assert 'Clerk Qwen3 (Brisen doc clerk) - type a task; "help" for reach/limits; exit to quit.' in out
    assert "Reach:" not in out
    assert "Limits:" not in out
    assert "Ready: /Baker-Feed/Clerk-Workbench/peter.md / Source: Outlook" in out
    assert "Draft preview:" in out
    assert "Latest email from Peter Storer: status note about the hotel asset." in out
    assert "Ready path: /Baker-Feed/Clerk-Workbench/peter.md" in out
    assert "Status: ready" in out
    assert "Qwen3 Plus │ ░░░░░░░░░░ 1% │ $0.0042" in out
    assert '  ⏵⏵ read-only clerk · action-guardrails on · "help" for reach' in out
    assert "12345 tok" not in out
    assert out.index("Ready: /Baker-Feed/Clerk-Workbench/peter.md") < out.index("Status: ready")
    assert out.index("Status: ready") < out.index("Qwen3 Plus │")


def test_chat_prints_blocked_reason_inline(monkeypatch, capsys):
    calls = []
    inputs = iter(["wire money", "exit"])

    def fake_input(prompt):
        assert prompt == "clerk> "
        return next(inputs)

    def fake_urlopen(req, timeout):
        calls.append(req)
        url = req.full_url
        if url == "https://baker.test/api/clerk/run":
            return _FakeResponse({"session_id": "sess-blocked", "status": "running"})
        if url == "https://baker.test/api/clerk/session/sess-blocked":
            return _FakeResponse({
                "session_id": "sess-blocked",
                "status": "blocked",
                "result": {"status": "blocked", "reason": "money/payment action"},
            })
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main([
        "chat",
        "--base-url",
        "https://baker.test",
        "--api-key",
        "test-key",
        "--interval-s",
        "0",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert len(calls) == 2
    assert "Blocked: money/payment action" in out
    assert "Status: blocked" in out
    assert "Qwen3 Coder │ ░░░░░░░░░░ --% │ $n/a" in out


def test_chat_help_prints_reach_limits_without_api_call(monkeypatch, capsys):
    inputs = iter(["help", "exit"])

    def fake_input(prompt):
        assert prompt == "clerk> "
        return next(inputs)

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("help must not call the Clerk API")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    code = clerk_qwen.main([
        "chat",
        "--base-url",
        "https://baker.test",
        "--api-key",
        "test-key",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert out.count("Clerk Qwen3 (Brisen doc clerk)") == 1
    assert "Reach: Gmail, Outlook/Graph" in out
    assert "Limits: no money, no external sends" in out
    assert "Usage: type a task." in out


def test_chat_prints_escalation_reason_and_answer(monkeypatch, capsys):
    calls = []
    inputs = iter(["summarize difficult document", "exit"])

    def fake_input(prompt):
        assert prompt == "clerk> "
        return next(inputs)

    def fake_urlopen(req, timeout):
        calls.append(req)
        url = req.full_url
        if url == "https://baker.test/api/clerk/run":
            return _FakeResponse({"session_id": "sess-escalated", "status": "running"})
        if url == "https://baker.test/api/clerk/session/sess-escalated":
            return _FakeResponse({
                "session_id": "sess-escalated",
                "status": "ready",
                "result": {
                    "status": "ready",
                    "escalated": True,
                    "reason": "repeated schema/tool failure: tool arguments were malformed JSON",
                    "answer": "Ready: escalated",
                },
            })
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main([
        "chat",
        "--base-url",
        "https://baker.test",
        "--api-key",
        "test-key",
        "--interval-s",
        "0",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert len(calls) == 2
    assert "Escalated: repeated schema/tool failure: tool arguments were malformed JSON" in out
    assert "Ready: escalated" in out
    assert out.index("Escalated: repeated schema/tool failure") < out.index("Ready: escalated")
    assert "Status: ready" in out


def test_chat_draft_preview_truncates_to_readable_size(capsys):
    long_text = "x" * 650
    session = {
        "session_id": "sess-long",
        "status": "ready",
        "result": {"answer": "Ready: /Baker-Feed/Clerk-Workbench/long.md"},
        "draft_content": long_text,
        "draft_path": "/Baker-Feed/Clerk-Workbench/long.md",
    }

    clerk_qwen._print_chat_result(session)

    out = capsys.readouterr().out
    assert ("x" * 600) + "..." in out
    assert ("x" * 601) not in out


def test_chat_footer_renders_na_for_missing_telemetry():
    assert clerk_qwen._telemetry_footer({"status": "ready"}) == (
        'Qwen3 Coder │ ░░░░░░░░░░ --% │ $n/a\n'
        '  ⏵⏵ read-only clerk · action-guardrails on · "help" for reach'
    )


def test_chat_footer_bar_tracks_pct_and_model_label_maps():
    footer = clerk_qwen._telemetry_footer({
        "status": "ready",
        "model": "qwen/qwen3-coder-plus",
        "context_window_used": 340000,
        "context_window_max": 1000000,
        "session_cost_usd": 0.006919,
    })

    first_line, second_line = footer.splitlines()
    assert first_line == "Qwen3 Plus │ ▓▓▓░░░░░░░ 34% │ $0.006919"
    assert len("▓▓▓░░░░░░░") == 10
    assert second_line == '  ⏵⏵ read-only clerk · action-guardrails on · "help" for reach'
    assert clerk_qwen._model_label("qwen/qwen3-coder") == "Qwen3 Coder"
    assert clerk_qwen._model_label("qwen/qwen3-coder-flash") == "Qwen3 Flash"


def test_chat_footer_uses_model_env_when_session_omits_model(monkeypatch):
    monkeypatch.setenv("CLERK_QWEN_MODEL", "qwen/qwen3-coder-plus")

    assert clerk_qwen._telemetry_footer({
        "status": "ready",
        "context_window_used": 990000,
        "context_window_max": 1000000,
        "session_cost_usd": 0.1,
    }).splitlines()[0] == "Qwen3 Plus │ ▓▓▓▓▓▓▓▓▓▓ 99% │ $0.1"


def test_no_args_defaults_to_chat(monkeypatch, capsys):
    monkeypatch.setenv("BAKER_API_KEY", "env-key")
    monkeypatch.setattr("builtins.input", lambda prompt: "exit")

    code = clerk_qwen.main([])

    out = capsys.readouterr().out
    assert code == 0
    assert "Clerk Qwen3 (Brisen doc clerk)" in out


def test_status_uses_env_key_without_1password(monkeypatch, capsys):
    monkeypatch.setenv("BAKER_API_KEY", "env-key")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("1Password should not be called when env key is present")

    def fake_urlopen(req, timeout):
        assert req.headers["X-baker-key"] == "env-key"
        assert req.full_url == "https://baker.test/api/clerk/session/sess-env"
        return _FakeResponse({"session_id": "sess-env", "status": "ready", "draft_path": "/Baker-Feed/Clerk-Workbench/out.md"})

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main(["status", "--base-url", "https://baker.test", "sess-env"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Status: ready" in out
    assert "Draft path: /Baker-Feed/Clerk-Workbench/out.md" in out


def test_missing_api_key_degrades_cleanly_when_1password_absent(monkeypatch, capsys):
    monkeypatch.delenv("BAKER_API_KEY", raising=False)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "", "item not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    code = clerk_qwen.main(["list", "--base-url", "https://baker.test"])

    err = capsys.readouterr().err
    assert code == 2
    assert "Baker API key missing" in err
    assert "1Password item 'API Baker'" in err


def test_1password_fallback_reads_api_baker_item(monkeypatch, capsys):
    monkeypatch.delenv("BAKER_API_KEY", raising=False)
    op_calls = []

    def fake_run(args, **kwargs):
        op_calls.append(args)
        return subprocess.CompletedProcess(args, 0, "one-password-key\n", "")

    def fake_urlopen(req, timeout):
        assert req.headers["X-baker-key"] == "one-password-key"
        return _FakeResponse({"session_id": "sess-op", "status": "ready"})

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main(["status", "--base-url", "https://baker.test", "sess-op"])

    assert code == 0
    assert op_calls == [["op", "read", "op://Baker API Keys/API Baker/credential"]]
    assert "Status: ready" in capsys.readouterr().out


def test_list_json_outputs_payload(monkeypatch, capsys):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://baker.test/api/clerk/sessions?limit=2"
        return _FakeResponse({"sessions": [{"session_id": "sess-a", "status": "ready"}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main([
        "list",
        "--base-url",
        "https://baker.test",
        "--api-key",
        "test-key",
        "--limit",
        "2",
        "--json",
    ])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["sessions"][0]["session_id"] == "sess-a"


def test_http_error_message_is_clean(monkeypatch, capsys):
    def fake_urlopen(req, timeout):
        body = json.dumps({"detail": {"status": "pending_approval", "reason": "target path requires Director approval"}}).encode()
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    code = clerk_qwen.main(["status", "--base-url", "https://baker.test", "--api-key", "test-key", "sess-403"])

    err = capsys.readouterr().err
    assert code == 2
    assert "target path requires Director approval" in err
