"""Tests for scripts/brisen_lab_terminal_key.sh cache-first lookup."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "brisen_lab_terminal_key.sh"


def _make_op(bin_dir: Path, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    op = bin_dir / "op"
    op.write_text(body)
    op.chmod(0o755)


def _run_read_key(tmp_path: Path, bin_dir: Path, *, env_value: str = "") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    if env_value:
        env["BRISEN_LAB_TERMINAL_KEY"] = env_value
    else:
        env.pop("BRISEN_LAB_TERMINAL_KEY", None)
    return subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; . "$1"; brisen_lab_read_terminal_key lead "${BRISEN_LAB_TERMINAL_KEY:-}"',
            "bash",
            str(HELPER),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_literal_env_beats_cache_and_op(tmp_path):
    cache_dir = tmp_path / ".brisen-lab" / "keys"
    cache_dir.mkdir(parents=True)
    (cache_dir / "lead").write_text("cache-key\n")
    bin_dir = tmp_path / "bin"
    sentinel = tmp_path / "op-called"
    _make_op(bin_dir, f"#!/usr/bin/env bash\ntouch {sentinel}\nexit 99\n")

    result = _run_read_key(tmp_path, bin_dir, env_value="env-key")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "env-key"
    assert not sentinel.exists(), "op must not run when literal env is set"


def test_cache_beats_op_ref_env(tmp_path):
    cache_dir = tmp_path / ".brisen-lab" / "keys"
    cache_dir.mkdir(parents=True)
    (cache_dir / "lead").write_text("cache-key\n")
    bin_dir = tmp_path / "bin"
    sentinel = tmp_path / "op-called"
    _make_op(bin_dir, f"#!/usr/bin/env bash\ntouch {sentinel}\nexit 99\n")

    result = _run_read_key(
        tmp_path,
        bin_dir,
        env_value="op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "cache-key"
    assert not sentinel.exists(), "op must not run when cache is populated"


def test_op_fallback_writes_cache_file_0600(tmp_path):
    bin_dir = tmp_path / "bin"
    _make_op(bin_dir, "#!/usr/bin/env bash\necho op-key\n")

    result = _run_read_key(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "op-key"
    cache_file = tmp_path / ".brisen-lab" / "keys" / "lead"
    assert cache_file.read_text().strip() == "op-key"
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache_file.parent.stat().st_mode) == 0o700
