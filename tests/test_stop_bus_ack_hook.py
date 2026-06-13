"""Tests for the Stop-hook bus auto-ack (V2 — ack-only-what-renders).

Fix for PINNED §OPEN-2 (2026-06-10 incident): V1 acked ALL unacked messages at
turn end, including 6 ship reports the agent never saw. V2 acks ONLY message
ids present in the rendered-ID ledger ~/.brisen-lab-bus-rendered-<slug>.txt
(written by session-start-bus-drain.sh + check-<slug>-inbox.sh).

Hook lives at tests/fixtures/stop-bus-ack.sh (canonical), deployed user-global
at ~/.claude/hooks/stop-bus-ack.sh. Drift detection at the bottom.

The hook talks to the daemon via urllib (not curl), so tests spin up a real
local HTTP server recording GET /msg/<slug> and POST /msg/<id>/ack calls.
`op` is stubbed via PATH.

Coverage:
  1. No ledger file → no fetch, no acks (fail-safe default).
  2. Rendered subset → ONLY ledgered+unacked ids acked; unseen ids untouched.
  3. Ledger pruned after successful acks (acked + already-acked ids drop out).
  4. Non-orchestrator role (b2) → silent no-op even with a populated ledger.
  5. Daemon fetch failure → no acks, ledger left intact for next turn.
  6. Drift: deployed user-global hook matches the repo fixture.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "stop-bus-ack.sh"
USER_GLOBAL_HOOK = Path.home() / ".claude" / "hooks" / "stop-bus-ack.sh"


def _make_stub(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _msg(mid: int, acked: bool = False) -> dict:
    return {
        "id": mid,
        "from_terminal": "b3",
        "to_terminals": ["lead"],
        "topic": "t",
        "kind": "dispatch",
        "body_preview": f"msg {mid}",
        "created_at": f"2026-06-11T01:{mid:02d}:00+00:00",
        "acknowledged_at": "2026-06-11T02:00:00+00:00" if acked else None,
    }


class _DaemonHandler(BaseHTTPRequestHandler):
    """Records ack POSTs; serves a canned inbox on GET /msg/<slug>."""

    inbox: list = []
    acked: list = []
    fail_get: bool = False

    def do_GET(self):  # noqa: N802
        if type(self).fail_get:
            self.send_response(502)
            self.end_headers()
            return
        body = json.dumps({"messages": type(self).inbox}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        # /msg/<id>/ack
        parts = self.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "msg" and parts[2] == "ack":
            type(self).acked.append(int(parts[1]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture
def daemon():
    _DaemonHandler.inbox = []
    _DaemonHandler.acked = []
    _DaemonHandler.fail_get = False
    srv = HTTPServer(("127.0.0.1", 0), _DaemonHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}", _DaemonHandler
    srv.shutdown()


@pytest.fixture
def stubs_dir(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    _make_stub(d / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    return d


def _run_hook(tmp_path: Path, stubs_dir: Path, daemon_url: str, role: str = "lead"):
    env = {
        "PATH": f"{stubs_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path),
        "BRISEN_LAB_DAEMON_URL": daemon_url,
        "BAKER_ROLE": role,
    }
    return subprocess.run(
        ["bash", str(HOOK_FIXTURE)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def test_no_ledger_no_acks(tmp_path, stubs_dir, daemon):
    """No ledger file → hook exits without acking anything (fail-safe)."""
    url, handler = daemon
    handler.inbox = [_msg(1), _msg(2)]

    result = _run_hook(tmp_path, stubs_dir, url)

    assert result.returncode == 0, result.stderr
    assert handler.acked == [], "nothing rendered → nothing may be acked"


def test_acks_only_rendered_ids(tmp_path, stubs_dir, daemon):
    """Core §OPEN-2 fix: unacked-but-unrendered ids must NOT be acked."""
    url, handler = daemon
    handler.inbox = [_msg(10), _msg(11), _msg(12)]  # all unacked
    ledger = tmp_path / ".brisen-lab-bus-rendered-lead.txt"
    ledger.write_text("10\n11\n")  # 12 arrived mid-session, never rendered

    result = _run_hook(tmp_path, stubs_dir, url)

    assert result.returncode == 0, result.stderr
    assert sorted(handler.acked) == [10, 11]
    assert 12 not in handler.acked, "unseen ship report must stay unacked"


def test_cache_key_skips_op_fetch(tmp_path, stubs_dir, daemon):
    """Populated ~/.brisen-lab/keys/<slug> means Stop hook never calls op."""
    url, handler = daemon
    handler.inbox = [_msg(13)]
    (tmp_path / ".brisen-lab" / "keys").mkdir(parents=True)
    (tmp_path / ".brisen-lab" / "keys" / "lead").write_text("cache-key\n")
    (tmp_path / ".brisen-lab-bus-rendered-lead.txt").write_text("13\n")
    op_sentinel = tmp_path / "op-called"
    _make_stub(stubs_dir / "op", f"#!/bin/bash\ntouch {op_sentinel}\nexit 99\n")

    result = _run_hook(tmp_path, stubs_dir, url)

    assert result.returncode == 0, result.stderr
    assert handler.acked == [13]
    assert not op_sentinel.exists(), "op must not run when cache is populated"


def test_ledger_pruned_after_acks(tmp_path, stubs_dir, daemon):
    """Acked ids + ids already acked elsewhere drop out of the ledger."""
    url, handler = daemon
    handler.inbox = [_msg(20), _msg(21, acked=True)]
    ledger = tmp_path / ".brisen-lab-bus-rendered-lead.txt"
    ledger.write_text("20\n21\n999\n")  # 999 expired/absent from inbox

    result = _run_hook(tmp_path, stubs_dir, url)

    assert result.returncode == 0, result.stderr
    assert handler.acked == [20], "only the still-unacked rendered id is POSTed"
    assert ledger.read_text() == "", "ledger fully pruned after successful run"


def test_non_orchestrator_role_noop(tmp_path, stubs_dir, daemon):
    """b2 (worker) → silent no-op even with a populated ledger (claim-gated)."""
    url, handler = daemon
    handler.inbox = [_msg(30)]
    (tmp_path / ".brisen-lab-bus-rendered-b2.txt").write_text("30\n")

    result = _run_hook(tmp_path, stubs_dir, url, role="b2")

    assert result.returncode == 0, result.stderr
    assert handler.acked == []


def test_fetch_failure_leaves_ledger_intact(tmp_path, stubs_dir, daemon):
    """Daemon 502 on GET → no acks, ledger untouched (retry next turn)."""
    url, handler = daemon
    handler.fail_get = True
    ledger = tmp_path / ".brisen-lab-bus-rendered-lead.txt"
    ledger.write_text("40\n41\n")

    result = _run_hook(tmp_path, stubs_dir, url)

    assert result.returncode == 0, result.stderr
    assert handler.acked == []
    assert ledger.read_text() == "40\n41\n"


def test_user_global_matches_repo():
    if not USER_GLOBAL_HOOK.exists():
        pytest.skip(
            f"user-global hook not deployed at {USER_GLOBAL_HOOK} "
            "(expected on CI; deploy via cp pre-merge)"
        )
    assert HOOK_FIXTURE.read_bytes() == USER_GLOBAL_HOOK.read_bytes(), (
        "drift detected: ~/.claude/hooks/stop-bus-ack.sh differs from "
        "tests/fixtures/stop-bus-ack.sh — re-run "
        "`cp tests/fixtures/stop-bus-ack.sh ~/.claude/hooks/stop-bus-ack.sh`"
    )
