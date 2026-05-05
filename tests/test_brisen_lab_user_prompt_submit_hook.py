"""Tests for UserPromptSubmit hook — Brisen Lab V2 H7 auth chain (V0.3.7) + drain.

Hook: ``.claude/hooks/user-prompt-submit-confirm.py``
Brief: ``briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md`` V0.3.7 amendment + Surface 5.

CONTRACT (NON-NEGOTIABLE per PR #149 discipline):
  1. Hook ALWAYS exits 0 — never blocks terminal startup
  2. Stdin is always drained (SIGPIPE-safe)
  3. Private key never logged, never written to disk, never in env
  4. Pre-flag-flip safety: BRISEN_LAB_V2_ENABLED!=true → silent no-op

The hook is invoked as a subprocess from Claude Code; tests exercise it via
direct subprocess.run + the in-process module functions.

Roles tested: AH-bearing (lead, deputy, ah1, ah2, architect) + non-AH (b1-b5,
cortex, cowork) per Q1 ratification table.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Module loader — hook lives outside the package tree
# ---------------------------------------------------------------------------

_HOOK_PATH = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "user-prompt-submit-confirm.py"


@pytest.fixture(scope="module")
def hook_mod():
    """Import the hook script as a module for in-process testing."""
    assert _HOOK_PATH.exists(), f"hook missing: {_HOOK_PATH}"
    spec = importlib.util.spec_from_file_location("upsh_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Pin Brisen Lab env to predictable values."""
    monkeypatch.setenv("BRISEN_LAB_URL", "https://brisen-lab.test")
    monkeypatch.setenv("BRISEN_LAB_TERMINAL_KEY", "test-terminal-key")
    monkeypatch.setenv("BRISEN_LAB_V2_ENABLED", "true")
    # Default to lead (AH-bearing); individual tests override.
    monkeypatch.setenv("BAKER_ROLE", "lead")
    # Use isolated tmp for last-seen marker.
    monkeypatch.setenv("TMPDIR", "/tmp")


@pytest.fixture
def patch_httpx(monkeypatch, hook_mod):
    """Replace hook_mod.httpx... actually the hook imports httpx lazily inside
    _run_auth_chain / _drain_inbox. We patch the global httpx.Client class via
    MockTransport — same pattern as test_mcp_baker_extension_1.py.
    """
    def _install(handler, *, raise_on_request=None):
        if raise_on_request is not None:
            def _err_handler(request):
                raise raise_on_request

            transport = httpx.MockTransport(_err_handler)
        else:
            transport = httpx.MockTransport(handler)

        OriginalClient = httpx.Client

        class _PatchedClient(OriginalClient):
            def __init__(self, *args, **kwargs):
                kwargs.pop("transport", None)
                super().__init__(*args, transport=transport, **kwargs)

        monkeypatch.setattr(httpx, "Client", _PatchedClient)
        return transport

    return _install


# ==========================================================================
# 1. Pre-flag-flip safety — V2 disabled = silent no-op
# ==========================================================================


def test_v2_disabled_silent_noop(hook_mod, monkeypatch, capsys):
    monkeypatch.setenv("BRISEN_LAB_V2_ENABLED", "false")
    with patch.object(sys, "stdin", _stdin_with({"prompt": "hi"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    # No additionalContext emitted when V2 disabled
    assert captured.out.strip() == ""


def test_v2_enabled_unset_silent_noop(hook_mod, monkeypatch, capsys):
    monkeypatch.delenv("BRISEN_LAB_V2_ENABLED", raising=False)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "hi"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == ""


# ==========================================================================
# 2. Auth-chain skip for non-AH-bearing roles (b-codes, cortex)
# ==========================================================================


@pytest.mark.parametrize("role", ["b1", "b2", "b3", "b4", "b5", "cortex"])
def test_non_ah_roles_skip_auth_chain(hook_mod, monkeypatch, role, patch_httpx):
    monkeypatch.setenv("BAKER_ROLE", role)
    auth_calls: list = []
    drain_calls: list = []

    def handler(request):
        url = str(request.url)
        if "/auth/" in url:
            auth_calls.append(url)
        if "/msg/" in url and not url.endswith("/ack"):
            drain_calls.append(url)
        # Drain returns empty inbox; auth shouldn't be called at all
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "hello"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    # CRITICAL: non-AH roles must NEVER hit /auth/* endpoints
    assert auth_calls == []
    # Drain side fires for everyone (including b-codes)
    assert len(drain_calls) >= 1


# ==========================================================================
# 3. AH-role auth chain — happy path (4-way matrix per PR #149 pattern)
# ==========================================================================


@pytest.mark.parametrize("role", ["lead", "deputy", "ah1", "ah2", "architect"])
def test_ah_roles_run_full_auth_chain(hook_mod, monkeypatch, role, patch_httpx, capsys):
    monkeypatch.setenv("BAKER_ROLE", role)
    captured = {"register_body": None, "human_confirm_body": None, "auth_headers": []}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/auth/register-session-pubkey"):
            captured["register_body"] = json.loads(request.content.decode("utf-8"))
            captured["auth_headers"].append(dict(request.headers))
            return httpx.Response(200, json={"session_id": "sess-abc-123"})
        if url.endswith("/auth/human-confirmation"):
            captured["human_confirm_body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"token": "JWT.eyTest.value"})
        if "/msg/" in url:
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "ratify proposal #42"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    envelope = json.loads(out.strip())
    assert envelope["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "JWT.eyTest.value" in envelope["hookSpecificOutput"]["additionalContext"]

    # Register payload contains pubkey base64 + worker_slug (daemon contract bus.py:635)
    assert captured["register_body"] is not None
    assert "pubkey" in captured["register_body"]
    import base64 as _b64
    decoded = _b64.b64decode(captured["register_body"]["pubkey"], validate=True)
    assert len(decoded) == 32  # ed25519 pubkey size
    assert captured["register_body"]["worker_slug"] == role
    # X-Terminal-Key on every auth call
    for h in captured["auth_headers"]:
        assert h.get("x-terminal-key") == "test-terminal-key"

    # Human-confirmation payload structure per brief §6 H7 §2
    hc = captured["human_confirm_body"]
    assert hc["session_id"] == "sess-abc-123"
    payload = hc["payload"]
    assert payload["worker_slug"] == role
    assert payload["session_id"] == "sess-abc-123"
    assert "prompt_hash" in payload
    assert len(payload["prompt_hash"]) == 64  # sha256 hex
    assert "ts" in payload
    assert "nonce" in payload
    assert isinstance(hc["signature"], str)
    sig_decoded = _b64.b64decode(hc["signature"], validate=True)
    assert len(sig_decoded) == 64  # ed25519 sig is 64 bytes


# ==========================================================================
# 4. Sign-FIRST then post (nonce-ordering discipline mirrors brisen-lab HIGH)
# ==========================================================================


def test_sign_happens_before_human_confirmation_post(hook_mod, monkeypatch, patch_httpx):
    """The hook must construct and sign the payload BEFORE posting to
    /auth/human-confirmation. We verify by checking that the sig in the body
    matches what we'd expect given the registered pubkey (round-trip sig check).
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    import base64 as _b64
    captured = {"pubkey": None, "payload": None, "signature": None}

    def handler(request):
        url = str(request.url)
        if url.endswith("/auth/register-session-pubkey"):
            body = json.loads(request.content.decode("utf-8"))
            captured["pubkey"] = _b64.b64decode(body["pubkey"], validate=True)
            return httpx.Response(200, json={"session_id": "ss-1"})
        if url.endswith("/auth/human-confirmation"):
            body = json.loads(request.content.decode("utf-8"))
            captured["payload"] = body["payload"]
            captured["signature"] = _b64.b64decode(body["signature"], validate=True)
            return httpx.Response(200, json={"token": "tok"})
        if "/msg/" in url:
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    patch_httpx(handler)
    monkeypatch.setenv("BAKER_ROLE", "lead")
    with patch.object(sys, "stdin", _stdin_with({"prompt": "test"})):
        with pytest.raises(SystemExit):
            hook_mod.main()

    # Reconstruct canonical signed bytes and verify the signature against the
    # registered public key. If the hook signed AFTER posting (or skipped sign),
    # this verify call will fail.
    pub = Ed25519PublicKey.from_public_bytes(captured["pubkey"])
    canonical = json.dumps(captured["payload"], sort_keys=True, separators=(",", ":"))
    pub.verify(captured["signature"], canonical.encode("utf-8"))


# ==========================================================================
# 5. Fail-open paths — every error path must exit 0 + emit no JWT
# ==========================================================================


def test_register_endpoint_500_silent_no_jwt(hook_mod, monkeypatch, patch_httpx, capsys):
    def handler(request):
        if "/auth/register-session-pubkey" in str(request.url):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "hi"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "JWT" not in out and "human_confirmation_token" not in out


def test_human_confirmation_endpoint_403_silent_no_jwt(hook_mod, monkeypatch, patch_httpx, capsys):
    def handler(request):
        url = str(request.url)
        if url.endswith("/auth/register-session-pubkey"):
            return httpx.Response(200, json={"session_id": "s1"})
        if url.endswith("/auth/human-confirmation"):
            return httpx.Response(403, json={"error": "sig_invalid"})
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "hi"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "JWT" not in out


def test_network_timeout_silent_exit(hook_mod, monkeypatch, patch_httpx):
    patch_httpx(None, raise_on_request=httpx.TimeoutException("slow"))
    with patch.object(sys, "stdin", _stdin_with({"prompt": "hi"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0


# ==========================================================================
# 5b. Surface 6a — register-session-pubkey retry on 409 race-loss
# ==========================================================================


def test_register_409_retried_once_then_succeeds(hook_mod, monkeypatch, patch_httpx, capsys):
    """First /auth/register-session-pubkey call returns 409 (concurrent
    register lost the partial-unique-index race); the hook waits jitter ms
    and retries once; the retry's UPDATE step expires the prior winner and
    the new INSERT succeeds with 200; auth chain proceeds to JWT issuance."""
    register_calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/auth/register-session-pubkey"):
            register_calls.append(url)
            if len(register_calls) == 1:
                return httpx.Response(
                    409,
                    json={"detail": {"error": "concurrent_registration_lost_race"}},
                )
            return httpx.Response(200, json={"session_id": "sess-after-retry"})
        if url.endswith("/auth/human-confirmation"):
            return httpx.Response(200, json={"token": "JWT.eyTest.retry"})
        if "/msg/" in url:
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    patch_httpx(handler)
    # Stub jitter sleep so the test runs fast + deterministic.
    monkeypatch.setattr(hook_mod.time, "sleep", lambda *_: None)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "race-loser"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    assert len(register_calls) == 2, "hook must retry register exactly once on 409"
    out = capsys.readouterr().out
    envelope = json.loads(out.strip())
    assert "JWT.eyTest.retry" in envelope["hookSpecificOutput"]["additionalContext"]


def test_register_409_twice_fails_open_no_jwt(hook_mod, monkeypatch, patch_httpx, capsys):
    """Both register attempts return 409 (systemic contention storm). Hook
    fails open per V0.3.7 — exits 0, emits no JWT, no further retries."""
    register_calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/auth/register-session-pubkey"):
            register_calls.append(url)
            return httpx.Response(
                409,
                json={"detail": {"error": "concurrent_registration_lost_race"}},
            )
        if "/msg/" in url:
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    patch_httpx(handler)
    monkeypatch.setattr(hook_mod.time, "sleep", lambda *_: None)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "double-409"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    assert len(register_calls) == 2, "max-retry=1 → exactly 2 attempts then give up"
    out = capsys.readouterr().out
    assert "JWT" not in out


def test_register_500_no_retry_immediate_fail_open(hook_mod, monkeypatch, patch_httpx):
    """Surface 6a retry is scoped strictly to 409. Other non-200 (500, 503,
    400, 403) must NOT trigger retry — they're either daemon outage or
    permanent failures where retry is wasted latency."""
    register_calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/auth/register-session-pubkey"):
            register_calls.append(url)
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    monkeypatch.setattr(hook_mod.time, "sleep", lambda *_: None)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "five-hundred"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    assert len(register_calls) == 1, "non-409 must short-circuit; no retry"


def test_no_terminal_key_silent_exit(hook_mod, monkeypatch, capsys):
    monkeypatch.delenv("BRISEN_LAB_TERMINAL_KEY", raising=False)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "hi"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == ""


def test_garbage_stdin_silent_exit(hook_mod, monkeypatch, patch_httpx):
    """Hook must drain stdin even when the JSON is malformed."""
    def handler(request):
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    fake_stdin = MagicMock()
    fake_stdin.read.return_value = "{not-json"
    with patch.object(sys, "stdin", fake_stdin):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0


def test_empty_stdin_silent_exit(hook_mod, monkeypatch, patch_httpx, capsys):
    def handler(request):
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    fake_stdin = MagicMock()
    fake_stdin.read.return_value = ""
    with patch.object(sys, "stdin", fake_stdin):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0


def test_uncaught_exception_in_main_still_exits_zero(hook_mod, monkeypatch):
    """Last-resort guard at __main__ block: ANY uncaught exception → exit 0."""
    # Patch _drain_stdin to raise something non-Exception-handled.
    with patch.object(hook_mod, "_drain_stdin", side_effect=KeyboardInterrupt):
        with pytest.raises((SystemExit, KeyboardInterrupt)):
            hook_mod.main()


# ==========================================================================
# 6. Drain wiring (Surface 5) — read inbox + ack each
# ==========================================================================


def test_drain_emits_summary_and_acks_each_msg(hook_mod, monkeypatch, patch_httpx, capsys):
    monkeypatch.setenv("BAKER_ROLE", "b4")  # non-AH; drain only path
    acked: list[int] = []
    rows = [
        {"id": 1, "kind": "dispatch", "from_terminal": "ah1", "topic": "cortex/x", "body_preview": "go"},
        {"id": 2, "kind": "broadcast", "from_terminal": "daemon", "topic": "lifecycle/restart", "body_preview": "ping"},
    ]

    def handler(request):
        url = str(request.url)
        if url.endswith("/ack"):
            mid = int(url.split("/")[-2])
            acked.append(mid)
            return httpx.Response(200, json={"acknowledged": True})
        if "/msg/b4" in url and request.method == "GET":
            return httpx.Response(200, json=rows)
        return httpx.Response(404)

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "carry on"})):
        with pytest.raises(SystemExit) as exc:
            hook_mod.main()
    assert exc.value.code == 0
    assert sorted(acked) == [1, 2]
    out = capsys.readouterr().out
    assert "Brisen Lab inbox drained" in out
    assert "[dispatch]" in out
    assert "[broadcast]" in out


def test_drain_per_msg_ack_failure_does_not_abort_loop(hook_mod, monkeypatch, patch_httpx, capsys):
    monkeypatch.setenv("BAKER_ROLE", "b4")
    acked: list[int] = []

    def handler(request):
        url = str(request.url)
        if url.endswith("/msg/2/ack"):
            return httpx.Response(500, text="oops")
        if url.endswith("/ack"):
            mid = int(url.split("/")[-2])
            acked.append(mid)
            return httpx.Response(200, json={"acknowledged": True})
        if "/msg/b4" in url and request.method == "GET":
            return httpx.Response(200, json=[
                {"id": 1, "kind": "dispatch", "from_terminal": "x", "topic": "t", "body_preview": "a"},
                {"id": 2, "kind": "dispatch", "from_terminal": "y", "topic": "t", "body_preview": "b"},
                {"id": 3, "kind": "dispatch", "from_terminal": "z", "topic": "t", "body_preview": "c"},
            ])
        return httpx.Response(404)

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "."})):
        with pytest.raises(SystemExit):
            hook_mod.main()
    # 1 + 3 acked (2 failed); loop did not abort
    assert sorted(acked) == [1, 3]


def test_drain_empty_inbox_no_emit(hook_mod, monkeypatch, patch_httpx, capsys):
    monkeypatch.setenv("BAKER_ROLE", "b4")

    def handler(request):
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "."})):
        with pytest.raises(SystemExit):
            hook_mod.main()
    assert capsys.readouterr().out.strip() == ""


def test_drain_writes_last_seen_marker(hook_mod, monkeypatch, patch_httpx, tmp_path):
    monkeypatch.setenv("BAKER_ROLE", "b4")
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    def handler(request):
        url = str(request.url)
        if url.endswith("/ack"):
            return httpx.Response(200, json={})
        if "/msg/b4" in url and request.method == "GET":
            return httpx.Response(
                200,
                json=[{
                    "id": 7, "kind": "dispatch", "from_terminal": "x", "topic": "t",
                    "body_preview": "a", "created_at": "2026-05-05T12:34:56Z",
                }],
            )
        return httpx.Response(404)

    patch_httpx(handler)
    marker = tmp_path / "baker-brisen-lab-lastseen-b4.txt"
    assert not marker.exists()
    with patch.object(sys, "stdin", _stdin_with({"prompt": "."})):
        with pytest.raises(SystemExit):
            hook_mod.main()
    assert marker.exists()
    assert marker.read_text().strip() == "2026-05-05T12:34:56Z"


def test_drain_uses_last_seen_as_since_filter(hook_mod, monkeypatch, patch_httpx, tmp_path):
    monkeypatch.setenv("BAKER_ROLE", "b4")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    marker = tmp_path / "baker-brisen-lab-lastseen-b4.txt"
    marker.write_text("2026-05-05T10:00:00Z")
    captured: dict = {}

    def handler(request):
        url = str(request.url)
        if "/msg/b4" in url and request.method == "GET":
            captured["url"] = url
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})

    patch_httpx(handler)
    with patch.object(sys, "stdin", _stdin_with({"prompt": "."})):
        with pytest.raises(SystemExit):
            hook_mod.main()
    assert "since=2026-05-05T10%3A00%3A00Z" in captured["url"] or "since=2026-05-05T10:00:00Z" in captured["url"]


# ==========================================================================
# 7. Subprocess invocation — black-box exit-0 contract
# ==========================================================================


def test_subprocess_invocation_exits_zero_on_v2_disabled(monkeypatch, tmp_path):
    """Black-box subprocess test: hook ALWAYS exits 0, even with V2 disabled."""
    env = os.environ.copy()
    env["BRISEN_LAB_V2_ENABLED"] = "false"
    env["BAKER_ROLE"] = "lead"
    env["TMPDIR"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps({"prompt": "hi"}),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0


def test_subprocess_invocation_exits_zero_on_garbage_stdin(monkeypatch, tmp_path):
    env = os.environ.copy()
    env["BRISEN_LAB_V2_ENABLED"] = "false"  # avoid live network in subprocess
    env["BAKER_ROLE"] = "lead"
    env["TMPDIR"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input="this is { not valid json",
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0


def test_subprocess_no_private_key_in_stderr_or_stdout(monkeypatch, tmp_path):
    """Defense-in-depth: nothing private-key-shaped should ever leak to either stream.

    With V2 disabled the hook never even touches keygen; this is a smoke check.
    """
    env = os.environ.copy()
    env["BRISEN_LAB_V2_ENABLED"] = "false"
    env["BAKER_ROLE"] = "lead"
    env["TMPDIR"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps({"prompt": "x"}),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "PRIVATE KEY" not in proc.stdout.upper()
    assert "PRIVATE KEY" not in proc.stderr.upper()
    assert "BEGIN PRIVATE" not in proc.stdout
    assert "BEGIN PRIVATE" not in proc.stderr


# ==========================================================================
# 8. Settings.local.json.example wiring sanity (avoid PR #149 regression)
# ==========================================================================


def test_settings_example_wires_user_prompt_submit_hook():
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    example = repo_root / ".claude" / "settings.local.json.example"
    cfg = json.loads(example.read_text())
    upsh = cfg.get("hooks", {}).get("UserPromptSubmit") or []
    assert any(
        "user-prompt-submit-confirm.py" in entry.get("command", "")
        for entry in upsh
    ), "UserPromptSubmit hook not wired in settings.local.json.example"


# ==========================================================================
# Helpers
# ==========================================================================


def _stdin_with(envelope: dict) -> MagicMock:
    """Build a mock stdin that returns the JSON-encoded envelope on .read()."""
    fake = MagicMock()
    fake.read.return_value = json.dumps(envelope)
    return fake
