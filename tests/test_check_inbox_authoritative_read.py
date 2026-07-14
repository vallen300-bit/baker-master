"""CLIENT_AUTHORITATIVE_READ_CONTRACT_1 (E27 recurrence, lead #10901).

Load-bearing regression for the E27 false-empty *recurrence*: the daemon read
path (#130) fail-closes a degraded read to HTTP 503 `bus_busy_retry`, but the
client `check_inbox.sh` ran `curl -sS` (no status check) and then
`data.get("messages", [])`, so a 503 body — which has no `messages` key — became
`[]` and printed "no unacked messages": a FALSE all-clear over a genuinely-unacked
dispatch (the 05:48Z 2026-07-14 incident, diagnosed in
briefs/_reports/B1_E27_RECURRENCE_DIAGNOSIS_20260714.md).

The fix makes the client authoritative: capture the HTTP status; any non-200 is a
LOUD error (never empty); claim "no unacked" ONLY on 200 AND complete:true.

Method mirrors test_bus_drain_hook.py — stub `curl` on PATH so the script exercises
real bash + python3 + JSON parsing without network. The stub honors the fix's
`-w '\\n%{http_code}'` by emitting `<body>\\n<status>`; retries are made instant via
CHECK_INBOX_RETRY_SLEEP=0 / CHECK_INBOX_RETRY_MAX=1.
"""
from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_inbox.sh"


def _make_curl_stub(bin_dir: Path, body: str, status: str) -> None:
    """A curl stub that ignores argv and emits `<body>\\n<status>` (the -w shape)."""
    stub = bin_dir / "curl"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s' {body!r}\n"
        f"printf '\\n%s' {status!r}\n"
        "exit 0\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_curl_transport_fail(bin_dir: Path) -> None:
    stub = bin_dir / "curl"
    stub.write_text("#!/usr/bin/env bash\nexit 7\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    import os

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "BAKER_ROLE": "researcher",
        "BRISEN_LAB_TERMINAL_KEY": "dummy-test-key",
        "CHECK_INBOX_RETRY_SLEEP": "0",
        "CHECK_INBOX_RETRY_MAX": "1",
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture()
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    return d


def test_503_busy_is_loud_never_empty(tmp_path, bin_dir):
    """THE regression: a 503 bus_busy_retry must NOT read as 'no unacked messages'."""
    _make_curl_stub(bin_dir, '{"detail":"bus_busy_retry"}', "503")
    r = _run(tmp_path)
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"503 must fail loud, got rc=0. out={out!r}"
    assert "no unacked messages" not in out, f"503 leaked a false all-clear: {out!r}"
    assert "503" in out or "bus_busy_retry" in out, f"503 not surfaced: {out!r}"


def test_4xx_error_body_is_loud_never_empty(tmp_path, bin_dir):
    _make_curl_stub(bin_dir, '{"detail":"not_recipient"}', "403")
    r = _run(tmp_path)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "no unacked messages" not in out


def test_transport_failure_is_loud_never_empty(tmp_path, bin_dir):
    _make_curl_transport_fail(bin_dir)
    r = _run(tmp_path)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "no unacked messages" not in out
    assert "unreachable" in out


def test_200_complete_empty_is_all_clear(tmp_path, bin_dir):
    """The ONLY authoritative all-clear: 200 + complete:true + no unacked."""
    _make_curl_stub(bin_dir, '{"messages":[],"complete":true,"unacked_total":0}', "200")
    r = _run(tmp_path)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"clean empty should pass: {out!r}"
    assert "no unacked messages" in out


def test_200_incomplete_empty_is_not_all_clear(tmp_path, bin_dir):
    """200 with complete:false is a PARTIAL page — must NOT claim all-clear."""
    _make_curl_stub(bin_dir, '{"messages":[],"complete":false,"next_cursor":"x"}', "200")
    r = _run(tmp_path)
    out = r.stdout + r.stderr
    assert "no unacked messages" not in out, f"partial read lied as all-clear: {out!r}"
    assert "PARTIAL" in out


def test_200_with_unacked_renders(tmp_path, bin_dir):
    body = (
        '{"messages":[{"id":10860,"from_terminal":"codex","to_terminals":["researcher"],'
        '"topic":"review/pr-136","acknowledged_at":null,"created_at":"2026-07-14T03:22:00Z",'
        '"body_preview":"codex verdict"}],"complete":true,"unacked_total":1}'
    )
    _make_curl_stub(bin_dir, body, "200")
    r = _run(tmp_path)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "1 unacked" in out
    assert "#10860" in out
