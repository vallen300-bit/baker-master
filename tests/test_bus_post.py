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

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"_raw": body}
        self._captured.append({
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "payload": payload,
        })
        self.send_response(self._status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "message_id": 12345,
            "thread_id": "thr-stub",
            "posted_at": "2026-05-06T00:00:00Z",
        }).encode("utf-8"))

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


def test_07_sh_post_503(stub_daemon, fake_op_path):
    """Stub daemon 503 → exit 1, stderr 'HTTP 503'."""
    _StubHandler._status_code = 503
    url, _ = stub_daemon
    r = _run_sh(
        ["b2", "hello"],
        _env_with({"BAKER_ROLE": "AH1", "BRISEN_LAB_DAEMON_URL": url},
                  fake_op_dir=fake_op_path),
    )
    assert r.returncode == 1
    assert "HTTP 503" in r.stderr


def test_08_sh_post_unreachable(fake_op_path):
    """Bad URL → exit non-zero with curl error in stderr."""
    r = _run_sh(
        ["b2", "hello"],
        _env_with(
            {"BAKER_ROLE": "AH1",
             "BRISEN_LAB_DAEMON_URL": "http://127.0.0.1:1"},
            fake_op_dir=fake_op_path,
        ),
    )
    # curl returns 000 on connection failure, script's HTTP != 200 path fires.
    assert r.returncode == 1
    assert ("HTTP" in r.stderr) or ("curl" in r.stderr.lower())


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
    """Un-flagged post must carry NO parent_id/thread_id keys — byte-identical
    to the pre-change request body (AC2)."""
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
    assert list(payload.keys()) == ["kind", "body", "to", "tier_required", "topic"]


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
