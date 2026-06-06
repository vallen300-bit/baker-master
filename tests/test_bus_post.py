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

import json
import os
import socket
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
