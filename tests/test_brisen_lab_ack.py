"""deputy F2 (lead #12428, ops/bus-health-wake-503) — tests for
scripts/brisen_lab_ack.sh, the idempotent ack retry-with-backoff helper.

The helper POSTs /msg/<id>/ack and retries transient/infra HTTP codes (503 flap,
000 network, etc.) with exponential backoff, but never retries a permanent 4xx.
The ack endpoint is idempotent, so retrying a transient failure is always safe.

External dependency stubbed: ``curl`` — a fake binary on ``PATH`` that returns a
*scripted sequence* of HTTP codes (one per invocation, advanced via a counter
file) so we can drive the retry loop deterministically. ``BRISEN_LAB_ACK_NO_SLEEP=1``
removes the real sleeps so the suite stays fast.

Cases:
  T1. 200 first try            -> exit 0, one call.
  T2. 503,503,200              -> retries twice then succeeds, exit 0, 3 calls.
  T3. persistent 503, cap 3    -> exhausts attempts, exit 3, exactly 3 calls.
  T4. 404 permanent            -> NO retry, exit 3, exactly 1 call.
  T5. 000 network then 200     -> transient network retried, exit 0, 2 calls.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "brisen_lab_ack.sh"


def _write_sequence_curl(tmp_path: Path, codes: list[str]) -> tuple[Path, Path]:
    """Fake curl that returns ``codes[i]`` on the i-th call (clamped to last).

    Records one line per call to ``calls.log``; advances ``counter`` each call.
    Emulates the helper's ``curl ... -o /dev/null -w '%{http_code}' ...`` shape:
    prints the scripted code to stdout and exits 0 (real curl exits 0 on 4xx/5xx
    too — only a hard network failure is non-zero, which we model as code 000).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    calls_log = tmp_path / "calls.log"
    counter = tmp_path / "counter"
    counter.write_text("0")
    codes_file = tmp_path / "codes"
    codes_file.write_text("\n".join(codes) + "\n")

    # NB: macOS system bash is 3.2 (no `mapfile`), so read the scripted code
    # for this call via `sed -n Np` (1-indexed), clamped to the last line.
    shim = bin_dir / "curl"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{calls_log}"\n'
        f'i="$(cat "{counter}")"\n'
        f'n="$(grep -c . "{codes_file}")"\n'
        'line=$(( i + 1 ))\n'
        '(( line > n )) && line="$n"\n'
        f'code="$(sed -n "${{line}}p" "{codes_file}")"\n'
        f'echo $(( i + 1 )) > "{counter}"\n'
        # 000 models a hard network failure: real curl writes 000 to -w AND
        # exits non-zero, which the helper maps via `|| http=000`.
        'if [[ "$code" == "000" ]]; then printf "000"; exit 7; fi\n'
        'printf "%s" "$code"\n'
        "exit 0\n"
    )
    shim.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return calls_log, counter


def _run(tmp_path: Path, *, codes: list[str], msg_id: str = "555",
         extra_env: dict | None = None) -> tuple[subprocess.CompletedProcess, Path]:
    calls_log, _ = _write_sequence_curl(tmp_path, codes)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'bin'}:{env.get('PATH', '')}"
    env["BRISEN_LAB_ACK_NO_SLEEP"] = "1"
    # Key is injected via env (the resolver's literal-key precedence), NOT argv:
    # the helper deliberately has no --key flag (codex PR #595 P2). BAKER_ROLE
    # drives the internal slug resolution.
    env["BAKER_ROLE"] = "deputy"
    env["BRISEN_LAB_TERMINAL_KEY"] = "fake-key"
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        ["bash", str(_SCRIPT), msg_id],
        env=env, capture_output=True, text=True, cwd=str(_REPO),
    )
    return proc, calls_log


def _call_count(calls_log: Path) -> int:
    return len(calls_log.read_text().splitlines()) if calls_log.exists() else 0


def test_success_first_try(tmp_path):
    proc, log = _run(tmp_path, codes=["200"])
    assert proc.returncode == 0, proc.stderr
    assert "ack #555 → 200" in proc.stdout
    assert _call_count(log) == 1


def test_retries_transient_503_then_succeeds(tmp_path):
    proc, log = _run(tmp_path, codes=["503", "503", "200"])
    assert proc.returncode == 0, proc.stderr
    assert "ack #555 → 200" in proc.stdout
    assert _call_count(log) == 3


def test_persistent_503_exhausts_attempts(tmp_path):
    proc, log = _run(
        tmp_path, codes=["503"],
        extra_env={"BRISEN_LAB_ACK_MAX_ATTEMPTS": "3"},
    )
    assert proc.returncode == 3
    assert "FAILED → HTTP 503" in proc.stderr
    assert _call_count(log) == 3  # first attempt + 2 retries, then give up


def test_permanent_404_is_not_retried(tmp_path):
    proc, log = _run(
        tmp_path, codes=["404", "200"],  # a 200 is queued but must never be reached
        extra_env={"BRISEN_LAB_ACK_MAX_ATTEMPTS": "5"},
    )
    assert proc.returncode == 3
    assert "FAILED → HTTP 404" in proc.stderr
    assert _call_count(log) == 1  # exactly one call — no retry on permanent error


def test_network_failure_is_retried(tmp_path):
    proc, log = _run(tmp_path, codes=["000", "200"])
    assert proc.returncode == 0, proc.stderr
    assert "ack #555 → 200" in proc.stdout
    assert _call_count(log) == 2


def test_rejects_non_numeric_msg_id(tmp_path):
    proc, _ = _run(tmp_path, codes=["200"], msg_id="not-a-number")
    assert proc.returncode == 2
    assert "must be numeric" in proc.stderr


# --- P2 security regressions (codex PR #595) --------------------------------

def test_no_key_flag_on_argv(tmp_path):
    """`--key` must NOT be a key path — a terminal key on argv leaks via `ps`.

    Passing `--key foo` should be treated as an unexpected non-numeric arg and
    rejected (exit 2), never accepted as a credential.
    """
    calls_log, _ = _write_sequence_curl(tmp_path, ["200"])
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'bin'}:{env.get('PATH', '')}"
    env["BRISEN_LAB_ACK_NO_SLEEP"] = "1"
    env["BAKER_ROLE"] = "deputy"
    env["BRISEN_LAB_TERMINAL_KEY"] = "fake-key"
    proc = subprocess.run(
        ["bash", str(_SCRIPT), "--key", "should-not-be-accepted", "555"],
        env=env, capture_output=True, text=True, cwd=str(_REPO),
    )
    assert proc.returncode == 2
    # It bailed before any network call — no ack POST leaked the "key".
    assert not calls_log.exists() or "/ack" not in calls_log.read_text()


def test_daemon_url_is_hard_pinned(tmp_path):
    """BRISEN_LAB_DAEMON_URL must NOT redirect the key — the host is hard-pinned.

    Even with a hostile override in the env, the ack POST must hit
    brisen-lab.onrender.com and never the attacker host.
    """
    proc, log = _run(
        tmp_path, codes=["200"],
        extra_env={"BRISEN_LAB_DAEMON_URL": "https://evil.example.test"},
    )
    assert proc.returncode == 0, proc.stderr
    logged = log.read_text()
    assert "brisen-lab.onrender.com/msg/555/ack" in logged
    assert "evil.example.test" not in logged
