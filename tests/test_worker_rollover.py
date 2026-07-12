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


def _usage_line(*, input_tokens: int = 0, cache_read: int = 0, cache_creation: int = 0, output: int = 50) -> str:
    # A transcript assistant turn as Claude Code writes it: the running context is
    # input_tokens + cache_read_input_tokens + cache_creation_input_tokens.
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "usage": {
            "input_tokens": input_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_creation,
            "output_tokens": output,
        }},
    })


def _write_usage_transcript(tmp_path: Path, *context_tokens: int, pad_tokens: int = 0) -> Path:
    # Build a transcript whose on-disk bytes are dominated by a usage-free junk
    # line (a stand-in for tool-result dumps), so bytes/4 would read very high
    # while the real per-turn usage is whatever we assert. Emits one usage line
    # per value in `context_tokens`, in order (the LAST is the live context).
    path = tmp_path / "transcript.jsonl"
    lines = []
    if pad_tokens:
        lines.append(json.dumps({"type": "tool_result", "content": "x" * (pad_tokens * 4)}))
    for total in context_tokens:
        lines.append(_usage_line(input_tokens=2, cache_read=total - 2))
    path.write_text("\n".join(lines) + "\n")
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


def _decision(stdout: str) -> str | None:
    # `decision: block` is what forces the session to keep running; its absence
    # is what lets the session exit. Block-at-most-once turns on the presence of
    # this field across successive Stops.
    out = stdout.strip()
    if not out:
        return None
    return json.loads(out).get("decision")


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


def test_context_hook_hard_first_fire_blocks_and_writes_marker(tmp_path):
    # First Stop over the hard band blocks (forces the checkpoint) and records a
    # per-session marker keyed to transcript_path.
    transcript = _write_transcript(tmp_path, 850)  # 85%
    result = _run_hook(transcript, window=1000)
    assert result.returncode == 0, result.stderr
    assert _decision(result.stdout) == "block"
    assert "HARD: write or refresh" in _additional_context(result.stdout)
    marker = Path(str(transcript) + ".rollover-blocked")
    assert marker.exists(), "first hard fire must persist the block-once marker"


def test_context_hook_hard_second_fire_does_not_block(tmp_path):
    # The doom-loop regression: with the marker present, a second (or Nth) Stop
    # over the hard band must NOT block, so the session can actually exit.
    transcript = _write_transcript(tmp_path, 850)
    first = _run_hook(transcript, window=1000)
    assert _decision(first.stdout) == "block"

    # Grow the transcript further (as a blocked turn would) and fire again.
    transcript.write_bytes(b"x" * 950 * 4)  # 95%
    second = _run_hook(transcript, window=1000)
    assert second.returncode == 0, second.stderr
    assert _decision(second.stdout) is None, "must not block again — that is the loop"
    ctx = _additional_context(second.stdout)
    assert ctx is not None and "exit now" in ctx


def test_context_hook_hard_marker_is_keyed_to_transcript(tmp_path):
    # A different session (different transcript_path) blocks on its own first
    # fire even though another session already has a marker.
    first_t = _write_transcript(tmp_path, 850)
    _run_hook(first_t, window=1000)  # writes first_t marker

    other = tmp_path / "other.jsonl"
    other.write_bytes(b"x" * 850 * 4)
    result = _run_hook(other, window=1000)
    assert _decision(result.stdout) == "block", "second session must still block once"


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


def test_context_hook_uses_transcript_usage_not_bytes(tmp_path):
    # CONTEXT_METER_FIX_1: the estimator must read the transcript's own API-reported
    # usage, not bytes/4. Here usage = 750k (75% of 1M -> soft band) while the file's
    # bytes/4 would be ~950k (95% -> hard band). The hook must report ~75%, soft.
    transcript = _write_usage_transcript(tmp_path, 750_000, pad_tokens=950_000)
    assert transcript.stat().st_size // 4 > 900_000, "junk pad must make bytes/4 read hard-band"
    result = _run_hook(transcript, window=1_000_000)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None
    assert "context ~75%" in ctx, ctx
    assert "Refresh the checkpoint" in ctx      # soft path, not the bytes/4 hard path
    assert "HARD: write or refresh" not in ctx
    assert _decision(result.stdout) is None      # 75% usage must not block


def test_context_hook_takes_last_usage_as_live_context(tmp_path):
    # Context shrinks on compaction: an earlier 900k turn then a later 200k turn
    # (post-compaction) must read as the LATEST (20%), not the peak.
    transcript = _write_usage_transcript(tmp_path, 900_000, 200_000)
    result = _run_hook(transcript, window=1_000_000)
    assert result.returncode == 0, result.stderr
    # 20% is below the default soft band -> silent (healthy seat, not force-checkpointed).
    assert result.stdout.strip() == "", result.stdout


def test_context_hook_fresh_seat_reads_below_5_percent(tmp_path):
    # AC: a fresh seat reads <5%. Tiny usage (30k = 3%) even with a large byte pad
    # (bytes/4 would be ~60%). Force emit with soft=1 so we can read the percent back.
    transcript = _write_usage_transcript(tmp_path, 30_000, pad_tokens=600_000)
    result = _run_hook(transcript, window=1_000_000)
    assert result.returncode == 0, result.stderr
    # default soft 70 -> a 3% seat is silent (would NOT be force-rolled).
    assert result.stdout.strip() == "", result.stdout
    # And when surfaced with soft=1, the reported percent is < 5.
    env = os.environ.copy()
    env["ROLLOVER_WINDOW_TOKENS"] = "1000000"
    env["ROLLOVER_SOFT_PERCENT"] = "1"
    env["ROLLOVER_HARD_PERCENT"] = "85"
    env.pop("ROLLOVER_SETTINGS_PATH", None)
    payload = json.dumps({"hook_event_name": "Stop", "transcript_path": str(transcript), "cwd": str(transcript.parent)})
    surfaced = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True, env=env, timeout=8)
    ctx = _additional_context(surfaced.stdout)
    assert ctx is not None
    import re
    pct = int(re.search(r"context ~(\d+)%", ctx).group(1))
    assert pct < 5, ctx


def test_context_hook_falls_back_to_bytes4_without_usage(tmp_path):
    # A transcript with no usage field (non-Claude / empty / malformed) must keep
    # the legacy bytes/4 behavior so nothing regresses for those seats.
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps({"type": "tool_result", "content": "x" * 400}) for _ in range(7)) + "\n")
    # ~7 lines of ~430 bytes -> tune to land at/above 70% of a small window.
    size = path.stat().st_size
    window = int((size / 4) / 0.70)  # so bytes/4 ~= 70% of window
    result = _run_hook(path, window=window)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None
    # Fell back to bytes/4 and warned in the soft band (no usage present).
    assert "Refresh the checkpoint" in ctx or "HARD: write or refresh" in ctx


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
