"""BRISEN_LAB_CARD_STATE_FIX_2 Fix 1 — tests for scripts/ack_dispatch_msgs.sh.

The script orchestrates: 1Password key read → daemon GET /msg/<sender> →
filter unacked messages whose topic matches one of four prefix patterns →
single POST /msg/<id>/ack per match.

These tests run the real bash script with three external dependencies stubbed:
  - ``op`` (1Password CLI): replaced via ``BRISEN_LAB_TERMINAL_KEY_OVERRIDE``
    env-var the script honours specifically for the test path.
  - ``curl``: a fake binary placed on ``PATH`` that mimics the daemon. It
    serves the canned inbox payload on ``GET /msg/<sender>`` and records the
    ack POSTs to a log file the test inspects.
  - The Brisen Lab daemon itself: never contacted — fake-curl alone produces
    every response.

Five cases per brief §1.2:
  T1. Happy path — 3 matching messages, all acked.
  T2. Mixed — 2 matching + 1 already-acked → 2 acked, 1 skipped.
  T3. Slug not present — 0 acked, exit 0.
  T4. Key-fetch fail — exit 2.
  T5. Single-ack 4xx — script continues + final count correct.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "ack_dispatch_msgs.sh"


# ---------------------------------------------------------------------------
# Fake-curl harness
# ---------------------------------------------------------------------------


def _write_fake_curl(tmp_path: Path, *, inbox_payload: str, ack_status: int) -> Path:
    """Create a ``curl`` shim that serves a fixed inbox + records ack POSTs.

    The shim writes per-call lines to ``calls.log`` for the test to inspect.
    The shim emulates ``curl -fsS ... <URL>`` (GET) and
    ``curl -fsS ... -X POST ... -o /dev/null -w '%{http_code}' .../ack`` paths.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    calls_log = tmp_path / "calls.log"
    inbox_file = tmp_path / "inbox.json"
    inbox_file.write_text(inbox_payload)

    shim = bin_dir / "curl"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{calls_log}"\n'
        "URL=\"\"\n"
        "WRITE_OUT=\"\"\n"
        "OUTPUT_PATH=\"\"\n"
        "IS_POST=0\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  case \"$1\" in\n"
        "    -X) METHOD=\"$2\"; [[ \"$METHOD\" == \"POST\" ]] && IS_POST=1; shift 2 ;;\n"
        "    -H) shift 2 ;;\n"
        "    -o) OUTPUT_PATH=\"$2\"; shift 2 ;;\n"
        "    -w) WRITE_OUT=\"$2\"; shift 2 ;;\n"
        "    -fsS|--connect-timeout|--max-time) [[ \"$1\" == \"-fsS\" ]] && shift || shift 2 ;;\n"
        "    http*|https*) URL=\"$1\"; shift ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "case \"$URL\" in\n"
        "  *\"/ack\")\n"
        "    if [[ -n \"$OUTPUT_PATH\" ]]; then : > \"$OUTPUT_PATH\"; fi\n"
        f"    printf '%s' '{ack_status}'\n"
        "    # Without -f, real curl exits 0 on 4xx — emulate that so the\n"
        "    # script's `|| HTTP=\"000\"` fallback does NOT fire and the\n"
        "    # real HTTP code is logged.\n"
        "    exit 0\n"
        "    ;;\n"
        "  *)\n"
        f"    cat \"{inbox_file}\"\n"
        "    ;;\n"
        "esac\n"
    )
    shim.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return calls_log


def _run(tmp_path: Path, *, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    bin_dir = tmp_path / "bin"
    # Put our fake-curl FIRST on PATH but keep /usr/bin etc. for python3, bash.
    full_env["PATH"] = f"{bin_dir}:{full_env.get('PATH', '')}"
    full_env.update(env)
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=str(_REPO),
    )


def _inbox_with_messages(messages: list[dict]) -> str:
    return json.dumps({"messages": messages})


# ---------------------------------------------------------------------------
# T1 — Happy path: 3 matching messages, all acked
# ---------------------------------------------------------------------------


def test_happy_path_three_matching_messages(tmp_path):
    inbox = _inbox_with_messages([
        {"id": 201, "topic": "dispatch/zombie_test_1",                 "acknowledged_at": None},
        {"id": 202, "topic": "dispatch/zombie_test_1-correction-stale", "acknowledged_at": None},
        {"id": 203, "topic": "request-changes/zombie_test_1",          "acknowledged_at": None},
        {"id": 999, "topic": "dispatch/unrelated_brief_x",              "acknowledged_at": None},
    ])
    calls_log = _write_fake_curl(tmp_path, inbox_payload=inbox, ack_status=200)

    result = _run(
        tmp_path,
        args=["--brief-slug", "ZOMBIE_TEST_1"],
        env={
            "BAKER_ROLE": "b3",
            "BRISEN_LAB_TERMINAL_KEY_OVERRIDE": "fake-key",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "acked 3 of 3 messages" in result.stdout
    # Each of the 3 matching IDs MUST have been acked; the unrelated one must NOT.
    log = calls_log.read_text()
    assert "/msg/201/ack" in log
    assert "/msg/202/ack" in log
    assert "/msg/203/ack" in log
    assert "/msg/999/ack" not in log


# ---------------------------------------------------------------------------
# T2 — Mixed: 2 matching + 1 already-acked → 2 acked, 1 skipped
# ---------------------------------------------------------------------------


def test_already_acked_message_is_skipped(tmp_path):
    inbox = _inbox_with_messages([
        {"id": 301, "topic": "dispatch/zombie_test_1",                 "acknowledged_at": None},
        {"id": 302, "topic": "scope-amendment/zombie_test_1",          "acknowledged_at": None},
        {"id": 303, "topic": "dispatch/zombie_test_1",                 "acknowledged_at": "2026-05-13T08:00:00Z"},
    ])
    calls_log = _write_fake_curl(tmp_path, inbox_payload=inbox, ack_status=200)

    result = _run(
        tmp_path,
        args=["--brief-slug", "ZOMBIE_TEST_1"],
        env={
            "BAKER_ROLE": "b3",
            "BRISEN_LAB_TERMINAL_KEY_OVERRIDE": "fake-key",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "acked 2 of 2 messages" in result.stdout
    log = calls_log.read_text()
    assert "/msg/301/ack" in log
    assert "/msg/302/ack" in log
    assert "/msg/303/ack" not in log


# ---------------------------------------------------------------------------
# T3 — Slug not present: 0 acked, exit 0
# ---------------------------------------------------------------------------


def test_slug_not_present_zero_acked_exit_zero(tmp_path):
    inbox = _inbox_with_messages([
        {"id": 401, "topic": "dispatch/something_else_1",  "acknowledged_at": None},
        {"id": 402, "topic": "ship/some_other_brief-v0-1-rerun", "acknowledged_at": None},
    ])
    calls_log = _write_fake_curl(tmp_path, inbox_payload=inbox, ack_status=200)

    result = _run(
        tmp_path,
        args=["--brief-slug", "ZOMBIE_TEST_1"],
        env={
            "BAKER_ROLE": "b3",
            "BRISEN_LAB_TERMINAL_KEY_OVERRIDE": "fake-key",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "no unacked messages for slug ZOMBIE_TEST_1" in result.stdout
    log = calls_log.read_text() if calls_log.exists() else ""
    # The inbox GET hit our shim, but no /ack POSTs.
    assert "/ack" not in log


# ---------------------------------------------------------------------------
# T4 — 1Password fetch fail → exit 2
# ---------------------------------------------------------------------------


def test_key_fetch_failure_exit_2(tmp_path):
    # No BRISEN_LAB_TERMINAL_KEY_OVERRIDE → script falls back to `op read`.
    # Force `op` to fail by shimming it to exit 1.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    op_shim = bin_dir / "op"
    op_shim.write_text("#!/usr/bin/env bash\nexit 1\n")
    op_shim.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

    # Provide a curl shim too so the failure is unambiguously from `op`, not curl.
    _write_fake_curl(tmp_path, inbox_payload=_inbox_with_messages([]), ack_status=200)

    full_env = os.environ.copy()
    full_env["PATH"] = f"{bin_dir}:{full_env.get('PATH', '')}"
    full_env["BAKER_ROLE"] = "b3"
    # Belt + suspenders: clear any inherited override.
    full_env.pop("BRISEN_LAB_TERMINAL_KEY_OVERRIDE", None)

    result = subprocess.run(
        ["bash", str(_SCRIPT), "--brief-slug", "ZOMBIE_TEST_1"],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=str(_REPO),
    )

    assert result.returncode == 2
    assert "1Password fetch failed" in result.stderr


# ---------------------------------------------------------------------------
# T5 — Single-ack 4xx: script continues, final count is correct
# ---------------------------------------------------------------------------


def test_single_ack_http_error_is_non_fatal(tmp_path):
    inbox = _inbox_with_messages([
        {"id": 501, "topic": "dispatch/zombie_test_1", "acknowledged_at": None},
        {"id": 502, "topic": "dispatch/zombie_test_1", "acknowledged_at": None},
    ])
    # Force ack 403 — every ack POST fails but the script must continue + exit 0.
    _write_fake_curl(tmp_path, inbox_payload=inbox, ack_status=403)

    result = _run(
        tmp_path,
        args=["--brief-slug", "ZOMBIE_TEST_1"],
        env={
            "BAKER_ROLE": "b3",
            "BRISEN_LAB_TERMINAL_KEY_OVERRIDE": "fake-key",
        },
    )

    assert result.returncode == 0
    # 0 of 2 acked since both 403'd; the count line still prints.
    assert "acked 0 of 2 messages" in result.stdout
    # Per-message log line emitted on stderr.
    assert "HTTP 403" in result.stderr


# ---------------------------------------------------------------------------
# T6 — `op` binary absent from PATH: exit 2 with the same 1Password-fetch
# diagnostic the live path uses (BRISEN_LAB_CARD_STATE_FIX_2-v0-2 LOW).
#
# Anchor: prior tests injected an `op` shim that exited 1, but never covered
# the "command not found" case which is what a clean CI runner / Render box
# would actually produce. With set -u + pipefail and no -e, the missing-
# binary exit code (127) must still propagate through `$(op read ...) || { ... }`.
# ---------------------------------------------------------------------------


def test_op_binary_absent_from_path_exits_2(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    # Provide curl so any earlier-path failure cannot pass for the op miss.
    _write_fake_curl(tmp_path, inbox_payload=_inbox_with_messages([]), ack_status=200)

    # Minimal PATH excluding common op install dirs (/opt/homebrew/bin, /usr/local/bin).
    # Keep /usr/bin + /bin for bash, python3, sed, awk, tr.
    minimal_path = f"{bin_dir}:/usr/bin:/bin"

    full_env = {
        "PATH": minimal_path,
        "HOME": str(tmp_path),  # block ~/.config/op or similar
        "BAKER_ROLE": "b1",
        # Belt + suspenders: clear any inherited override.
    }
    full_env.pop("BRISEN_LAB_TERMINAL_KEY_OVERRIDE", None)

    result = subprocess.run(
        ["bash", str(_SCRIPT), "--brief-slug", "ZOMBIE_TEST_1"],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=str(_REPO),
    )

    assert result.returncode == 2, (
        f"expected exit 2 (1Password fetch failed); got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "1Password fetch failed" in result.stderr
