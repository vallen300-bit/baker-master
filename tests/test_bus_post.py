"""F2 — bus_post.{sh,py} subprocess + stub-daemon tests.

Covers:
- Director-recipient pass-through (daemon owns the safety check)
- generated registry slug validation
- BAKER_ROLE → sender-slug resolution
- 1Password CLI fetch (mocked via PATH-shim)
- HTTP error propagation
- JSON payload escaping (special chars, multi-recipient, parent_id, kind, tier)

Tests do NOT hit real network — a localhost stub HTTP daemon answers POSTs.
Tests do NOT hit real 1Password — a fake `op` shell script on PATH returns
a deterministic key string.
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BUS_POST_SH = REPO_ROOT / "scripts" / "bus_post.sh"
BUS_POST_PY = REPO_ROOT / "scripts" / "bus_post.py"


# ---------- stub HTTP daemon ----------

class _StubHandler(BaseHTTPRequestHandler):
    # Per-instance overrides set by the fixture before serving.
    _status_code = 200
    _captured: list = []
    # AGENT_BUS_IDEMPOTENT_POST_1: a per-request status SEQUENCE (e.g. [503, 503, 200])
    # to exercise the client retry-with-backoff loop. When non-empty it takes precedence
    # over _status_code; once exhausted the last element repeats. _status_idx advances
    # per request and is reset by the fixture.
    _status_sequence: list = []
    _status_idx: int = 0
    # CLIENT_STARTED_EMISSION_1: messages the GET /msg/<slug> drain returns, so the
    # started emitter's thread-resolution read has something to match. Set by the test.
    _get_messages: list = []

    def _next_status(self) -> int:
        seq = type(self)._status_sequence
        if not seq:
            return type(self)._status_code
        idx = type(self)._status_idx
        type(self)._status_idx = idx + 1
        return seq[idx] if idx < len(seq) else seq[-1]

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        # CLIENT_STARTED_EMISSION_1 thread-resolution read: GET /msg/<slug>?unread=true&
        # kind=dispatch. Returns the canned _get_messages in the daemon envelope shape.
        self._captured.append({
            "path": self.path, "method": "GET",
            "headers": {k: v for k, v in self.headers.items()},
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        out = {"messages": type(self)._get_messages, "complete": True,
               "unacked_total": len(type(self)._get_messages), "next_cursor": None}
        self.wfile.write(json.dumps(out).encode("utf-8"))

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"_raw": body}
        self._captured.append({
            "path": self.path,
            "method": "POST",
            "headers": {k: v for k, v in self.headers.items()},
            "payload": payload,
        })
        code = self._next_status()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        # 503 mirrors the real daemon's bus_busy_retry body; the client acts on the
        # HTTP code, not the body, so the shape only needs to be valid JSON.
        out = ({"detail": "bus_busy_retry"} if code == 503 else {
            "message_id": 12345,
            "thread_id": "thr-stub",
            "posted_at": "2026-05-06T00:00:00Z",
        })
        self.wfile.write(json.dumps(out).encode("utf-8"))

    def log_message(self, *_):  # silence stderr noise during tests
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def stub_daemon():
    """Start a per-test stub HTTP daemon. Yields (url, captured_list).

    Test sets _StubHandler._status_code = N before triggering subprocess
    if it wants a non-200 response.
    """
    port = _free_port()
    captured: list = []
    _StubHandler._captured = captured
    _StubHandler._status_code = 200
    _StubHandler._status_sequence = []
    _StubHandler._status_idx = 0
    _StubHandler._get_messages = []

    server = HTTPServer(("127.0.0.1", port), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (f"http://127.0.0.1:{port}", captured)
    finally:
        server.shutdown()
        server.server_close()


# ---------- fake `op` CLI shim ----------

@pytest.fixture
def fake_op_path(tmp_path):
    """Create a tmpdir holding a fake `op` shell script. Returns the dir
    so callers can prepend it to PATH for subprocess invocations.

    The fake op echoes a deterministic key string regardless of args, so
    `op read 'op://...'` returns "fake-key-<timestamp>" without needing
    real 1Password authentication.
    """
    op = tmp_path / "op"
    op.write_text("#!/usr/bin/env bash\necho fake-key-$$\n")
    op.chmod(0o755)
    return tmp_path


def _env_with(extras: dict, fake_op_dir: Path | None = None) -> dict:
    """Build subprocess env: inherit current PATH, layer extras, optionally
    prepend fake_op_dir to PATH."""
    env = os.environ.copy()
    # Strip any pre-existing BAKER_ROLE so tests start from a known state.
    env.pop("BAKER_ROLE", None)
    if fake_op_dir is not None:
        env["PATH"] = f"{fake_op_dir}:{env.get('PATH', '')}"
    env.update(extras)
    return env


def _run_sh(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(BUS_POST_SH), *args],
        env=env, capture_output=True, text=True, timeout=15,
    )


def _run_py(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUS_POST_PY), *args],
        env=env, capture_output=True, text=True, timeout=15,
    )


def _load_bus_post_module():
    spec = importlib.util.spec_from_file_location("bus_post_under_test", BUS_POST_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------- tests ----------

def test_01_sh_director_passes_through(stub_daemon, fake_op_path):
    """F2-FU-1 (BRISEN_LAB_APP_AUTOPOLL_INBOX_1): director-recipient is no
    longer script-blocked. Script POSTS to daemon; daemon enforces the
    env-gated block (covered in brisen-lab tests/test_director_recipient_block.py).
    Inverts the F2 test_01_sh_director_blocked assertion."""
    url, captured = stub_daemon
    r = _run_sh(
        ["director", "test body", "test/topic"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert any(req["path"] == "/msg/director" for req in captured), captured


def test_02_sh_unknown_slug():
    """Unknown slug → exit 1, stderr 'unknown slug'."""
    r = _run_sh(["nonexistent-slug", "x"], _env_with({"BAKER_ROLE": "AH1"}))
    assert r.returncode == 1
    assert "unknown slug" in r.stderr


def test_03_sh_no_args():
    """Missing required args → exit 2, stderr 'Usage:'."""
    r = _run_sh([], _env_with({}))
    assert r.returncode == 2
    assert "Usage:" in r.stderr


def test_04_sh_baker_role_unset():
    """BAKER_ROLE unset → exit 1, stderr 'BAKER_ROLE not set'."""
    r = _run_sh(["b2", "x"], _env_with({}))
    assert r.returncode == 1
    assert "BAKER_ROLE not set" in r.stderr


def test_05_sh_baker_role_unrecognized():
    """BAKER_ROLE garbage → exit 1, stderr 'unrecognized'."""
    r = _run_sh(["b2", "x"], _env_with({"BAKER_ROLE": "GARBAGE"}))
    assert r.returncode == 1
    assert "unrecognized" in r.stderr


def test_06_sh_post_succeeds(stub_daemon, fake_op_path):
    """Stub daemon 200 → exit 0, stdout = stub-returned JSON."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["message_id"] == 12345
    assert out["thread_id"] == "thr-stub"
    assert len(captured) == 1
    assert captured[0]["path"] == "/msg/b2"


def test_07_sh_post_503_retries_then_fails_loud(stub_daemon, fake_op_path):
    """AGENT_BUS_IDEMPOTENT_POST_1: a PERSISTENT 503 now retries to the attempt budget,
    then exits 1 (fail loud, exit code unchanged). Every attempt reuses ONE
    idempotency_key so the daemon would replay, not duplicate, any that committed."""
    _StubHandler._status_code = 503
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url,
                   "BUS_POST_BACKOFF_BASE": "0"},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 1
    assert "HTTP 503" in r.stderr
    assert "after 4 attempt(s)" in r.stderr
    assert len(captured) == 4  # default MAX_ATTEMPTS
    keys = {req["payload"]["idempotency_key"] for req in captured}
    assert len(keys) == 1, f"one key must be reused across the storm, got {keys}"


def test_08_sh_post_unreachable(fake_op_path):
    """Bad URL (connection failure = retryable) → retry to the budget, then exit 1."""
    r = _run_sh(
        ["b2", "hello"],
        _env_with(
            {"BAKER_ROLE": "AH1",
             "BRISEN_LAB_DAEMON_URL": "http://127.0.0.1:1",
             "BUS_POST_BACKOFF_BASE": "0"},
            fake_op_dir=fake_op_path,
        ),
    )
    # curl returns non-zero on connection failure, retried to the budget then fails loud.
    assert r.returncode == 1
    assert ("HTTP" in r.stderr) or ("curl" in r.stderr.lower())
    assert "after 4 attempt(s)" in r.stderr


def test_09_sh_payload_escapes_special_chars(stub_daemon, fake_op_path):
    """Body with quotes + $vars must round-trip JSON-encoded correctly."""
    url, captured = stub_daemon
    body = 'hello with "quotes" + $vars'
    r = _run_sh(
        ["b2", body],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["body"] == body


def test_10_sh_payload_includes_topic(stub_daemon, fake_op_path):
    """Topic with slashes round-trips into JSON payload field."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/with/slashes"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["topic"] == "topic/with/slashes"


def test_11_py_multi_recipient(stub_daemon, fake_op_path):
    """--to lead,deputy → payload.to == ['lead','deputy'] (not single)."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "lead,deputy", "--body", "broadcast hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["to"] == ["lead", "deputy"]


def test_12_py_director_passes_through(stub_daemon, fake_op_path):
    """F2-FU-1 (BRISEN_LAB_APP_AUTOPOLL_INBOX_1): py: --to director passes
    through to daemon (no script-side reject). Daemon enforces the env-gated
    block. Inverts the F2 test_12_py_director_blocked assertion."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "director", "--body", "x"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert any(req["path"] == "/msg/director" for req in captured), captured


def test_13_py_payload_includes_parent_id(stub_daemon, fake_op_path):
    """--parent-id 42 → payload.parent_id == 42."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "b2", "--body", "x", "--parent-id", "42"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["parent_id"] == 42


def test_14_py_kind_broadcast_tier_a(stub_daemon, fake_op_path):
    """--kind broadcast --tier A → payload.kind / tier_required round-trip."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "b2", "--body", "x", "--kind", "broadcast", "--tier", "A"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["kind"] == "broadcast"
    assert captured[0]["payload"]["tier_required"] == "A"


def test_15_py_baker_role_missing():
    """py: BAKER_ROLE absent → sys.exit with 'BAKER_ROLE not set'."""
    r = _run_py(
        ["--to", "b2", "--body", "x"],
        _env_with({}),  # BAKER_ROLE explicitly not set
    )
    assert r.returncode != 0
    assert "BAKER_ROLE not set" in r.stderr


def test_16_clerk_haiku_recipient_and_sender(stub_daemon, fake_op_path):
    """clerk-haiku is generated as both legal recipient and legal sender."""
    url, captured = stub_daemon
    r = _run_sh(
        ["clerk-haiku", "hello clerk chat", "dispatch/clerk-haiku-smoke"],
        _env_with({"BAKER_ROLE": "clerk-haiku", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["path"] == "/msg/clerk-haiku"
    assert captured[0]["payload"]["to"] == ["clerk-haiku"]


def test_17_sh_agent_id_recipient_and_sender(stub_daemon, fake_op_path):
    """sh: AG-id sender/recipient inputs canonicalize to bus slugs."""
    url, captured = stub_daemon
    r = _run_sh(
        ["AG-203", "hello architect", "dispatch/ag-id-smoke"],
        _env_with({"BAKER_ROLE": "AG-001", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["path"] == "/msg/codex-arch"
    assert captured[0]["payload"]["to"] == ["codex-arch"]


def test_18_py_agent_id_recipients(stub_daemon, fake_op_path):
    """py: AG-id recipients canonicalize before path and payload are built."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "AG-203,AG-004", "--body", "hello ids"],
        _env_with({"BAKER_ROLE": "AG-001", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["path"] == "/msg/codex-arch"
    assert captured[0]["payload"]["to"] == ["codex-arch", "deputy-codex"]


def test_19_sh_cache_key_beats_op_ref(stub_daemon, tmp_path):
    """sh: op:// env + populated cache must POST without invoking op."""
    url, captured = stub_daemon
    cache_dir = tmp_path / ".brisen-lab" / "keys"
    cache_dir.mkdir(parents=True)
    (cache_dir / "lead").write_text("cache-key\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    op_sentinel = tmp_path / "op-called"
    op = bin_dir / "op"
    op.write_text(f"#!/usr/bin/env bash\ntouch {op_sentinel}\nexit 99\n")
    op.chmod(0o755)

    r = _run_sh(
        ["b2", "hello from cache"],
        _env_with(
            {
                "HOME": str(tmp_path),
                "BAKER_ROLE": "AH1",
                "BRISEN_LAB_DAEMON_URL": url,
                "BRISEN_LAB_TERMINAL_KEY":
                    "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential",
            },
            fake_op_dir=bin_dir,
        ),
    )

    assert r.returncode == 0, r.stderr
    assert captured[0]["headers"].get("X-Terminal-Key") == "cache-key"
    assert not op_sentinel.exists(), "op must not run when cache is populated"


def test_20_py_cache_key_beats_op_ref(stub_daemon, tmp_path):
    """py: op:// env + populated cache must POST without invoking op."""
    url, captured = stub_daemon
    cache_dir = tmp_path / ".brisen-lab" / "keys"
    cache_dir.mkdir(parents=True)
    (cache_dir / "lead").write_text("cache-key\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    op_sentinel = tmp_path / "op-called"
    op = bin_dir / "op"
    op.write_text(f"#!/usr/bin/env bash\ntouch {op_sentinel}\nexit 99\n")
    op.chmod(0o755)

    r = _run_py(
        ["--to", "b2", "--body", "hello from cache"],
        _env_with(
            {
                "HOME": str(tmp_path),
                "BAKER_ROLE": "AH1",
                "BRISEN_LAB_DAEMON_URL": url,
                "BRISEN_LAB_TERMINAL_KEY":
                    "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential",
            },
            fake_op_dir=bin_dir,
        ),
    )

    assert r.returncode == 0, r.stderr
    assert captured[0]["headers"].get("X-Terminal-Key") == "cache-key"
    assert not op_sentinel.exists(), "op must not run when cache is populated"


def test_21_py_op_fallback_cache_seed_uses_0600_create_mode(monkeypatch, tmp_path):
    """py: op fallback must create the temp key file as 0600, not chmod after."""
    mod = _load_bus_post_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("BRISEN_LAB_TERMINAL_KEY", raising=False)

    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *_, **__: subprocess.CompletedProcess(
            ["op", "read", "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential"],
            0,
            stdout="op-key\n",
            stderr="",
        ),
    )

    real_open = os.open
    create_modes: list[int] = []

    def recording_open(path, flags, mode=0o777, *args, **kwargs):
        create_modes.append(mode)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(mod.os, "open", recording_open)

    assert mod._fetch_key("lead") == "op-key"
    assert create_modes == [0o600]
    cache_file = tmp_path / ".brisen-lab" / "keys" / "lead"
    assert cache_file.read_text().strip() == "op-key"
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600


# ---------- BUS_POST_THREADING_ARG_1: --parent / --thread ----------

def test_22_sh_parent_flag_sets_parent_id(stub_daemon, fake_op_path):
    """--parent 42 (after positionals) -> payload.parent_id == 42, no thread_id."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent", "42"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["parent_id"] == 42
    assert "thread_id" not in captured[0]["payload"]


def test_23_sh_thread_flag_sets_thread_id(stub_daemon, fake_op_path):
    """--parent 42 --thread <uuid> -> parent_id + thread_id both round-trip
    (the daemon does not auto-inherit thread from parent_id alone)."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent", "42", "--thread", "thr-abc-123"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["parent_id"] == 42
    assert captured[0]["payload"]["thread_id"] == "thr-abc-123"


def test_24_sh_unflagged_omits_threading_keys(stub_daemon, fake_op_path):
    """Un-flagged post carries NO parent_id/thread_id keys. It DOES now carry a single
    always-present idempotency_key (AGENT_BUS_IDEMPOTENT_POST_1) inserted right after the
    core fields — the only wire-shape change vs pre-change."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    payload = captured[0]["payload"]
    assert "parent_id" not in payload
    assert "thread_id" not in payload
    # exact key set + order that today's callers put on the wire
    assert list(payload.keys()) == [
        "kind", "body", "to", "tier_required", "idempotency_key", "topic"]
    assert payload["idempotency_key"]  # non-empty (auto-minted)


def test_25_sh_parent_non_integer_rejected(fake_op_path):
    """--parent must be an integer message id (fail-loud) -> exit 2."""
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent", "not-a-number"],
        _env_with({"BAKER_ROLE": "AH1"}, fake_op_dir=fake_op_path),
    )
    assert r.returncode == 2
    assert "integer" in r.stderr


def test_26_sh_parent_equals_form(stub_daemon, fake_op_path):
    """--parent=42 equals-form is accepted too."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent=42"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["payload"]["parent_id"] == 42


def test_27_sh_parent_flag_before_positionals(stub_daemon, fake_op_path):
    """Flags may precede the positionals; recipient/body/topic still resolve."""
    url, captured = stub_daemon
    r = _run_sh(
        ["--parent", "42", "b2", "x", "topic/x"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert captured[0]["path"] == "/msg/b2"
    assert captured[0]["payload"]["parent_id"] == 42
    assert captured[0]["payload"]["topic"] == "topic/x"


def test_28_sh_parent_empty_equals_rejected(stub_daemon, fake_op_path):
    """--parent= (empty value) must FAIL LOUD, never silently post unthreaded
    (codex G3 F1: an empty-expanded parent var stranded the check-in). Exit 2,
    and the daemon must NOT be hit."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent="],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 2
    assert "non-empty" in r.stderr
    assert captured == []  # never posted


def test_29_sh_parent_empty_next_arg_rejected(stub_daemon, fake_op_path):
    """--parent '' (empty next arg, e.g. from an unset shell var) must fail loud."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent", ""],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 2
    assert "non-empty" in r.stderr
    assert captured == []


def test_30_sh_thread_empty_equals_rejected(stub_daemon, fake_op_path):
    """--thread= (empty value) must fail loud."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent", "42", "--thread="],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 2
    assert "non-empty" in r.stderr
    assert captured == []


def test_31_sh_thread_empty_next_arg_rejected(stub_daemon, fake_op_path):
    """--thread '' (empty next arg) must fail loud."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--parent", "42", "--thread", ""],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 2
    assert "non-empty" in r.stderr
    assert captured == []


# ---- AGENT_BUS_IDEMPOTENT_POST_1: internal retry-backoff + idempotency key (AC3) ----

def test_32_sh_internal_retry_storm_reuses_one_key(stub_daemon, fake_op_path):
    """AC3: an internal-retry storm (503, 503, 200) succeeds on the 3rd attempt and
    reuses ONE minted key across all 3 — so the daemon collapses any that committed to a
    single row. This is the failure mode that dup'd b1's stand-down confirm tonight."""
    _StubHandler._status_sequence = [503, 503, 200]
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url,
                   "BUS_POST_BACKOFF_BASE": "0"},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["message_id"] == 12345
    assert len(captured) == 3  # two 503s then the 200
    keys = {req["payload"]["idempotency_key"] for req in captured}
    assert len(keys) == 1, f"one key must be reused across the storm, got {keys}"


def test_33_sh_auto_mint_key_present(stub_daemon, fake_op_path):
    """No key supplied → a non-empty key is auto-minted and sent."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    key = captured[0]["payload"]["idempotency_key"]
    assert isinstance(key, str) and len(key) >= 8


def test_34_sh_passthrough_key_survives_reinvocation(stub_daemon, fake_op_path):
    """AC3: a caller-managed loop that re-invokes the script across a kill/rerun passes
    ONE key; both invocations send the SAME key so the daemon dedupes them to one row.
    Flag (--idempotency-key) and env (BUS_IDEMPOTENCY_KEY) forms both honored."""
    url, captured = stub_daemon
    K = "caller-managed-key-0001"
    r1 = _run_sh(
        ["b2", "hello", "topic/x", "--idempotency-key", K],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    r2 = _run_sh(
        ["b2", "hello", "topic/x"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url,
                   "BUS_IDEMPOTENCY_KEY": K},
                  fake_op_dir=fake_op_path),
    )
    assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)
    assert captured[0]["payload"]["idempotency_key"] == K   # flag form
    assert captured[1]["payload"]["idempotency_key"] == K   # env form


def test_35_sh_empty_idempotency_key_flag_rejected(stub_daemon, fake_op_path):
    """--idempotency-key '' (empty) must fail loud, never silently auto-mint over a
    caller's intent — mirrors the --parent/--thread empty-value guards."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "x", "topic/x", "--idempotency-key", ""],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 2
    assert "non-empty" in r.stderr
    assert captured == []


def test_36_py_internal_retry_storm_reuses_one_key(stub_daemon, fake_op_path):
    """AC3 (py): internal-retry storm (503,503,200) reuses ONE key across all attempts."""
    _StubHandler._status_sequence = [503, 503, 200]
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "b2", "--body", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url,
                   "BUS_POST_BACKOFF_BASE": "0"},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["message_id"] == 12345
    assert len(captured) == 3
    keys = {req["payload"]["idempotency_key"] for req in captured}
    assert len(keys) == 1, f"one key must be reused across the storm, got {keys}"


def test_37_py_passthrough_key_and_persistent_503(stub_daemon, fake_op_path):
    """py: --idempotency-key round-trips; a persistent 503 retries to the budget then
    exits non-zero (fail loud), reusing the passed key on every attempt."""
    _StubHandler._status_code = 503
    url, captured = stub_daemon
    K = "py-caller-key-0002"
    r = _run_py(
        ["--to", "b2", "--body", "hello", "--idempotency-key", K],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url,
                   "BUS_POST_BACKOFF_BASE": "0"},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode != 0
    assert "after 4 attempt(s)" in r.stderr
    assert len(captured) == 4
    assert all(req["payload"]["idempotency_key"] == K for req in captured)


def test_38_py_auto_mint_key_present(stub_daemon, fake_op_path):
    """py: no key supplied → a non-empty key is auto-minted and sent."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "b2", "--body", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    key = captured[0]["payload"]["idempotency_key"]
    assert isinstance(key, str) and len(key) >= 8


# ---- codex #8373 fixes: read-timeout retry (P1) + empty-key fail-loud (P2) ----

class _FakeResp:
    """Minimal context-manager stand-in for a urlopen() response."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_39_py_post_retries_on_read_timeout(monkeypatch):
    """codex #8373 P1: a READ timeout raises a bare socket.timeout (NOT urllib URLError).
    _post must RETRY it (reusing the one key) — two timeouts then a 200 → success on the
    3rd attempt. Regression: before the fix this escaped uncaught after exactly 1 call."""
    import socket as _socket
    mod = _load_bus_post_module()
    monkeypatch.setenv("BUS_POST_BACKOFF_BASE", "0")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _socket.timeout("timed out")
        return _FakeResp(b'{"message_id": 999, "deduped": false}')

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    result = mod._post("b2", {"body": "x", "idempotency_key": "k1"}, "key")
    assert calls["n"] == 3             # retried past both read timeouts
    assert result["message_id"] == 999


def test_40_py_post_read_timeout_exhausts_then_fails_loud(monkeypatch):
    """codex #8373 P1: a PERSISTENT read timeout retries to the budget then exits
    non-zero (fail loud), not an uncaught socket.timeout traceback."""
    import socket as _socket
    mod = _load_bus_post_module()
    monkeypatch.setenv("BUS_POST_BACKOFF_BASE", "0")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise _socket.timeout("timed out")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit):
        mod._post("b2", {"body": "x", "idempotency_key": "k1"}, "key")
    assert calls["n"] == 4             # default MAX_ATTEMPTS, all retried


def test_41_py_empty_idempotency_key_flag_fails_loud(stub_daemon, fake_op_path):
    """codex #8373 P2: an explicitly empty --idempotency-key must fail loud and never
    post (parity with the sh guard test_35), not silently auto-mint a fresh key."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "b2", "--body", "x", "--idempotency-key", ""],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode != 0
    assert "non-empty" in r.stderr
    assert captured == []              # never posted


def test_42_py_whitespace_idempotency_key_flag_fails_loud(stub_daemon, fake_op_path):
    """codex #8373 P2 edge: a whitespace-only --idempotency-key is also a caller error."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "b2", "--body", "x", "--idempotency-key", "   "],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode != 0
    assert "non-empty" in r.stderr
    assert captured == []


# ---- codex #8385: shell-side whitespace-key parity (matches py test_42) ----

def test_43_sh_whitespace_idempotency_key_flag_fails_loud(stub_daemon, fake_op_path):
    """codex #8385: sh must reject a whitespace-only --idempotency-key (not just empty).
    The daemon strips the key before insert, so a blank key silently becomes keyless and
    never dedupes — fail loud + never post instead (parity with py test_42)."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "hello", "topic/x", "--idempotency-key", "   "],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 2
    assert "non-empty" in r.stderr
    assert captured == []              # never posted


def test_44_sh_whitespace_env_key_mints_not_posts_blank(stub_daemon, fake_op_path):
    """codex #8385: a whitespace-only BUS_IDEMPOTENCY_KEY env is treated as UNSET -> a
    real key is minted (never the blank), so dedupe still works (parity with py .strip())."""
    url, captured = stub_daemon
    r = _run_sh(
        ["b2", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url,
                   "BUS_IDEMPOTENCY_KEY": "   "},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    key = captured[0]["payload"]["idempotency_key"]
    assert key.strip(), f"minted key must be non-blank, got {key!r}"
    assert key != "   "


# ---- CLIENT_STARTED_EMISSION_1 — rubric 5: client `started` emission ----
# A recipient's FIRST NON-ACK reply to a dispatch optimistically fires
# POST /msg/<id>/started via the shared emitter scripts/emit_started.py. The endpoint is
# the authoritative gate (brisen-lab tests/test_case_one_p5_delivery_confirmation.py);
# here we assert the CLIENT wiring: it fires when (and only when) the reply threads onto a
# dispatch — target resolved by --parent (primary) OR by --thread (bounded unread read;
# topic-match dropped per lead #11216 collision hazard) — it is TOTAL best-effort (any
# miss, incl. a generic OSError, never changes the post's exit code), the kill switch
# suppresses it, and an ack post never emits.

def test_45_sh_started_emitted_on_parent_reply(stub_daemon, fake_op_path):
    """--parent 42 → after the main post lands, a best-effort POST /msg/42/started fires.
    Two requests captured, in order: the reply, then the started signal. Exit 0."""
    url, captured = stub_daemon
    r = _run_sh(
        ["lead", "on it", "heartbeat/x", "--parent", "42"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    paths = [req["path"] for req in captured]
    assert paths == ["/msg/lead", "/msg/42/started"], paths
    # The started POST carries the sender's terminal key and an empty body.
    started = captured[1]
    assert "X-Terminal-Key" in started["headers"]
    assert started["payload"] == {}


def test_46_sh_no_started_without_parent(stub_daemon, fake_op_path):
    """A non-reply post (no --parent) never fires a started signal — exactly one POST."""
    url, captured = stub_daemon
    r = _run_sh(
        ["lead", "fyi", "note/x"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    paths = [req["path"] for req in captured]
    assert paths == ["/msg/lead"], paths
    assert not any(p.endswith("/started") for p in paths)


def test_47_sh_started_kill_switch_suppresses(stub_daemon, fake_op_path):
    """BAKER_STARTED_EMISSION_DISABLED=1 suppresses the started fire even with --parent."""
    url, captured = stub_daemon
    r = _run_sh(
        ["lead", "on it", "heartbeat/x", "--parent", "42"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url,
                   "BAKER_STARTED_EMISSION_DISABLED": "1"},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    paths = [req["path"] for req in captured]
    assert paths == ["/msg/lead"], paths


def test_48_sh_started_miss_never_alters_exit_code(stub_daemon, fake_op_path):
    """Best-effort: the main post lands 200, but the started signal gets a 404 (e.g. the
    parent is not a dispatch / the sender is not a recipient). The post's exit code stays
    0 and a one-line best-effort note is logged to stderr. Sequence [200, 404]: the reply
    is request 1 (200), the started is request 2 (404)."""
    _StubHandler._status_sequence = [200, 404]
    url, captured = stub_daemon
    r = _run_sh(
        ["lead", "on it", "heartbeat/x", "--parent", "42"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    paths = [req["path"] for req in captured]
    assert paths == ["/msg/lead", "/msg/42/started"], paths
    assert "started-emit best-effort miss" in r.stderr
    assert "target=42" in r.stderr


def test_49_py_started_emitted_on_parent_reply(stub_daemon, fake_op_path):
    """bus_post.py parity: --parent-id 42 on a dispatch reply fires POST /msg/42/started."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "lead", "--body", "on it", "--parent-id", "42"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    paths = [req["path"] for req in captured]
    assert paths == ["/msg/lead", "/msg/42/started"], paths


def test_50_py_started_not_emitted_on_ack(stub_daemon, fake_op_path):
    """bus_post.py: an ack post (kind=ack) NEVER emits started, even threaded on a parent —
    ack alone is not a start (E22). Exactly one POST, no /started."""
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "lead", "--body", "ack", "--kind", "ack", "--parent-id", "42"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    paths = [req["path"] for req in captured]
    assert paths == ["/msg/lead"], paths
    assert not any(p.endswith("/started") for p in paths)


# ---- CLIENT_STARTED_EMISSION_1 — parent-OR-thread match + TOTAL best-effort guard ----

EMIT_STARTED_PY = REPO_ROOT / "scripts" / "emit_started.py"


def _load_emit_started_module():
    spec = importlib.util.spec_from_file_location("emit_started_under_test",
                                                  EMIT_STARTED_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_51_sh_started_via_thread_resolution(stub_daemon, fake_op_path):
    """No --parent, but --thread <T>: the emitter resolves the dispatch in that thread via
    the bounded unread read (GET /msg/<sender>?unread=true&kind=dispatch) and fires
    /started for the resolved id. Stub returns a dispatch id=99 in thread T addressed to
    the sender b1."""
    _StubHandler._get_messages = [
        {"id": 99, "thread_id": "T-uuid", "kind": "dispatch",
         "execute_obligation": True, "to_terminals": ["b1"]},
    ]
    url, captured = stub_daemon
    r = _run_sh(
        ["lead", "on it", "note/x", "--thread", "T-uuid"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    # The main post, then a GET resolution read, then the started POST for the resolved id.
    assert captured[0]["path"] == "/msg/lead"
    gets = [c for c in captured if c.get("method") == "GET"]
    assert gets and gets[0]["path"].startswith("/msg/b1?"), captured
    assert any(c["path"] == "/msg/99/started" for c in captured), captured


def test_52_sh_thread_no_match_no_started(stub_daemon, fake_op_path):
    """--thread <T> but no dispatch in the drain matches that thread → the emitter resolves
    nothing and fires NO started. The resolution read may happen, but no /started POST."""
    _StubHandler._get_messages = [
        {"id": 77, "thread_id": "OTHER", "kind": "dispatch",
         "execute_obligation": True, "to_terminals": ["b1"]},
    ]
    url, captured = stub_daemon
    r = _run_sh(
        ["lead", "on it", "note/x", "--thread", "T-uuid"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert not any(c["path"].endswith("/started") for c in captured), captured


def test_53_py_started_via_thread_resolution(stub_daemon, fake_op_path):
    """bus_post.py parity: --thread-id <T> with no --parent-id resolves the dispatch and
    fires /started for it."""
    _StubHandler._get_messages = [
        {"id": 99, "thread_id": "T-uuid", "kind": "dispatch",
         "execute_obligation": True, "to_terminals": ["b1"]},
    ]
    url, captured = stub_daemon
    r = _run_py(
        ["--to", "lead", "--body", "on it", "--thread-id", "T-uuid"],
        _env_with({"BAKER_ROLE": "b1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 0, r.stderr
    assert any(c["path"] == "/msg/99/started" for c in captured), captured


def test_54_emit_started_total_guard_unreachable_exits_zero():
    """The shared emitter is TOTAL best-effort: pointed at an unreachable daemon with a
    --parent target, it logs a miss and STILL exits 0 (a connection failure is an
    OSError/URLError — must never propagate to the caller)."""
    r = subprocess.run(
        [sys.executable, str(EMIT_STARTED_PY),
         "--daemon", "http://127.0.0.1:1", "--key", "k", "--sender", "b1",
         "--parent", "42"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0, r.stderr
    assert "best-effort" in r.stderr


def test_55_emit_started_total_guard_swallows_generic_oserror(monkeypatch):
    """codex #11216 (1): a generic OSError raised inside the resolution path must be
    swallowed by the TOTAL outer guard — resolve_and_emit returns normally, never raises.
    Force the thread-resolution read to raise a bare OSError."""
    mod = _load_emit_started_module()

    def _boom(*_a, **_k):
        raise OSError("simulated low-level socket error")
    monkeypatch.setattr(mod, "_resolve_thread_dispatch", _boom)
    # No exception must escape (thread path triggers _resolve_thread_dispatch → OSError).
    mod.resolve_and_emit("http://127.0.0.1:1", "k", "b1", None, "T-uuid")
