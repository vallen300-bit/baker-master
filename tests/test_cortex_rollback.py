"""Smoke test for scripts/cortex_rollback_v1.sh — CORTEX_3T_FORMALIZE_1C.

Source-level + bash-syntax assertions. We do NOT actually fire the
rollback (it is Director-only and depends on live 1Password CLI + Render
API). Quality Checkpoints #5 + #6 are verified via static inspection:
  * `set -euo pipefail` present
  * 4 explicit ISO timestamps (start, env-update, redeploy, end)
  * `confirm` arg requirement enforced
  * usage banner printed when arg is missing
  * file is executable
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/cortex_rollback_v1.sh")


def test_rollback_script_exists():
    assert SCRIPT.is_file()


def test_rollback_script_is_executable():
    assert os.access(SCRIPT, os.X_OK), "script must have +x bit set"


def test_rollback_script_has_strict_mode():
    """Quality Checkpoint #5 — `set -euo pipefail`."""
    text = SCRIPT.read_text()
    assert "set -euo pipefail" in text


def test_rollback_script_requires_confirm_arg():
    text = SCRIPT.read_text()
    assert '"${1:-}" != "confirm"' in text


def test_rollback_script_has_4_explicit_timestamps():
    """Quality Checkpoint #6 — 4 explicit ISO timestamps."""
    text = SCRIPT.read_text()
    matches = re.findall(r"\$\(date -u \+%Y-%m-%dT%H:%M:%SZ\)", text)
    assert len(matches) >= 4, (
        f"expected ≥4 ISO timestamps, found {len(matches)}"
    )


def test_rollback_script_calls_render_env_var_patch():
    text = SCRIPT.read_text()
    assert "api.render.com/v1/services" in text
    assert "/env-vars" in text


def test_rollback_script_disables_cortex_pipeline_flags():
    text = SCRIPT.read_text()
    # Both AO_SIGNAL_DETECTOR_ENABLED + CORTEX_LIVE_PIPELINE must be touched
    assert '"AO_SIGNAL_DETECTOR_ENABLED"' in text
    assert '"CORTEX_LIVE_PIPELINE"' in text
    assert '"CORTEX_PIPELINE_ENABLED"' in text


def test_rollback_script_renames_frozen_table():
    text = SCRIPT.read_text()
    assert "ao_project_state_legacy_frozen_" in text
    assert "RENAME TO ao_project_state" in text


def test_rollback_script_posts_director_dm():
    text = SCRIPT.read_text()
    assert "/api/slack/dm-director" in text
    assert "rollback executed" in text.lower()


def test_rollback_script_bash_parses_cleanly():
    """`bash -n` should parse the script without syntax errors."""
    if shutil.which("bash") is None:
        pytest.skip("bash unavailable")
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True,
    )
    assert result.returncode == 0, (
        f"bash -n failed:\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_rollback_no_arg_prints_usage_and_exits_nonzero():
    """Without `confirm`, must exit 1 and print usage banner."""
    if shutil.which("bash") is None:
        pytest.skip("bash unavailable")
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, timeout=10,
    )
    assert result.returncode == 1
    out = result.stdout.decode("utf-8", "replace")
    assert "Usage:" in out
    assert "confirm" in out


def test_rollback_destructive_warning_in_usage():
    text = SCRIPT.read_text()
    assert "DESTRUCTIVE" in text


def test_rollback_5min_rto_target_documented():
    text = SCRIPT.read_text()
    assert "5 min" in text or "<5 min" in text
