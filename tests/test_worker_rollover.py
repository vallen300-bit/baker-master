"""Worker rollover hook/helper tests."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "context-threshold-check.sh"
INSTALLER = REPO_ROOT / "scripts" / "install-rollover-stop-hook.py"
RESPAWN = REPO_ROOT / "scripts" / "respawn-request.sh"


def _write_transcript(tmp_path: Path, token_estimate: int) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_bytes(b"x" * token_estimate * 4)
    return path


def _run_hook(transcript: Path, *, window: int | None = None, settings: Path | None = None):
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": str(transcript),
        "cwd": str(transcript.parent),
    })
    env = os.environ.copy()
    env.pop("ROLLOVER_WINDOW_TOKENS", None)
    env.pop("ROLLOVER_SETTINGS_PATH", None)
    if window is not None:
        env["ROLLOVER_WINDOW_TOKENS"] = str(window)
    if settings is not None:
        env["ROLLOVER_SETTINGS_PATH"] = str(settings)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=8,
    )


def _additional_context(stdout: str) -> str | None:
    # Stop hooks emit a top-level `systemMessage` (not hookSpecificOutput —
    # Claude's Stop schema rejects that field); read it back the same way.
    out = stdout.strip()
    if not out:
        return None
    return json.loads(out)["systemMessage"]


def test_rollover_scripts_exist_executable_and_syntax_clean():
    for script in (HOOK, INSTALLER, RESPAWN):
        assert script.is_file()
        assert script.stat().st_mode & stat.S_IXUSR
    for script in (HOOK, RESPAWN):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    result = subprocess.run([sys.executable, "-m", "py_compile", str(INSTALLER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_context_hook_silent_below_70_percent(tmp_path):
    transcript = _write_transcript(tmp_path, 699)
    result = _run_hook(transcript, window=1000)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_context_hook_warns_at_70_percent(tmp_path):
    transcript = _write_transcript(tmp_path, 700)
    result = _run_hook(transcript, window=1000)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None
    assert "context ~70%" in ctx
    assert "Refresh the checkpoint" in ctx


def test_context_hook_hard_instruction_at_85_percent(tmp_path):
    transcript = _write_transcript(tmp_path, 850)
    result = _run_hook(transcript, window=1000)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None
    assert "context ~85%" in ctx
    assert "HARD: write or refresh" in ctx
    assert "attempt-bump commit" in ctx


def test_context_hook_reads_window_from_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"rollover_window_tokens": 1000}))
    transcript = _write_transcript(tmp_path, 700)
    result = _run_hook(transcript, settings=settings)
    assert result.returncode == 0, result.stderr
    assert "context ~70%" in _additional_context(result.stdout)


def test_context_hook_soft_percent_configurable_via_settings(tmp_path):
    # Worker seats drop soft-warn to 50%; default stays 70 when the key is absent.
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"rollover_window_tokens": 1000, "rollover_soft_percent": 50}))
    transcript = _write_transcript(tmp_path, 500)  # 50%
    result = _run_hook(transcript, settings=settings)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None
    assert "context ~50%" in ctx
    assert "Refresh the checkpoint" in ctx


def test_context_hook_silent_below_configured_soft(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"rollover_window_tokens": 1000, "rollover_soft_percent": 50}))
    transcript = _write_transcript(tmp_path, 499)  # 49% -> below configured 50
    result = _run_hook(transcript, settings=settings)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_context_hook_soft_percent_from_settings_local(tmp_path):
    # settings.local.json (per-seat, gitignored) overrides the shared base.
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({"rollover_window_tokens": 1000}))
    (claude / "settings.local.json").write_text(json.dumps({"rollover_soft_percent": 50}))
    transcript = claude.parent / "transcript.jsonl"
    transcript.write_bytes(b"x" * 500 * 4)  # 50% of a 1000-token window
    result = _run_hook(transcript)  # no env overrides -> resolves via cwd/.claude
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None
    assert "context ~50%" in ctx


def test_context_hook_hard_percent_still_default_85_with_soft_50(tmp_path):
    # Dropping soft to 50 must not move the hard block; it stays 85.
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"rollover_window_tokens": 1000, "rollover_soft_percent": 50}))
    transcript = _write_transcript(tmp_path, 850)  # 85%
    result = _run_hook(transcript, settings=settings)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None
    assert "context ~85%" in ctx
    assert "HARD: write or refresh" in ctx


def test_installer_adds_stop_hook_and_window_idempotently(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": []}]}}))

    for _ in range(2):
        result = subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--settings",
                str(settings),
                "--window-tokens",
                "1234",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        assert result.returncode == 0, result.stderr

    data = json.loads(settings.read_text())
    assert data["rollover_window_tokens"] == 1234
    stop_hooks = [
        hook
        for entry in data["hooks"]["Stop"]
        for hook in entry.get("hooks", [])
        if hook.get("command") == ".claude/hooks/context-threshold-check.sh"
    ]
    assert stop_hooks == [{
        "type": "command",
        "command": ".claude/hooks/context-threshold-check.sh",
        "timeout": 10,
    }]


def test_respawn_request_dry_run_posts_to_dispatcher_and_self():
    env = os.environ.copy()
    env["BAKER_ROLE"] = "b2"
    env["RESPAWN_REQUEST_DRY_RUN"] = "true"
    result = subprocess.run(
        [
            "bash",
            str(RESPAWN),
            "lead",
            "BRIEF_X_1",
            "briefs/_checkpoints/BRIEF_X_1.checkpoint.md",
            "2",
            "b2/brief-x-1",
            "tests green, next gate pending",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=8,
    )
    assert result.returncode == 0, result.stderr
    assert "to=lead,b2" in result.stdout
    assert "topic=rollover/BRIEF_X_1" in result.stdout
    assert "claim=attempt-bump-commit-not-ack" in result.stdout
