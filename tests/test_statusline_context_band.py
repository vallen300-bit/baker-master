import json
import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).parents[1] / ".claude" / "statusline.sh"


def run_statusline(tmp_path, *, window_tokens, used_percentage, model_display="Opus 4.8"):
    payload = {
        "model": {
            "display_name": model_display,
            "id": "claude-opus-4-8",
        },
        "context_window": {
            "used_percentage": used_percentage,
            "context_window_size": window_tokens,
            "total_input_tokens": 1200,
            "total_output_tokens": 300,
        },
    }
    env = os.environ.copy()
    env.update(
        {
            "BAKER_ROLE": "lead",
            "CONTEXT_BAND_DIR": str(tmp_path),
            "CONTEXT_BAND_THROTTLE_S": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    record = json.loads((tmp_path / "lead.current").read_text(encoding="utf-8"))
    return record, result.stdout


def test_statusline_uses_live_context_window_size(tmp_path):
    record, output = run_statusline(
        tmp_path,
        window_tokens=1_000_000,
        used_percentage=12.4,
    )

    assert record == {
        "context_percent": 12,
        "band": "ok",
        "measured": True,
        "window_tokens": 1_000_000,
    }
    assert "Opus" in output
    assert "12%" in output


def test_live_context_window_size_wins_over_model_text_fallback(tmp_path):
    record, _ = run_statusline(
        tmp_path,
        window_tokens=200_000,
        used_percentage=42,
        model_display="Opus 4.8 1M",
    )

    assert record["window_tokens"] == 200_000
    assert record["context_percent"] == 42


def test_invalid_live_window_uses_existing_model_fallback(tmp_path):
    payload = {
        "model": {"display_name": "Opus 4.8 1M", "id": "claude-opus-4-8"},
        "context_window": {
            "used_percentage": 86,
            "context_window_size": "unknown",
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        },
    }
    env = os.environ.copy()
    env.update(
        {
            "BAKER_ROLE": "lead",
            "CONTEXT_BAND_DIR": str(tmp_path),
            "CONTEXT_BAND_THROTTLE_S": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    record = json.loads((tmp_path / "lead.current").read_text(encoding="utf-8"))
    assert record["window_tokens"] == 1_000_000
    assert record["band"] == "hard"


def test_statusline_updates_symlink_target_without_replacing_current_link(tmp_path):
    target = tmp_path / "session.json"
    target.write_text(
        json.dumps({
            "session_id": "sess-1",
            "metadata": {"source": "context-threshold-check"},
            "context_percent": 1,
        }),
        encoding="utf-8",
    )
    current = tmp_path / "lead.current"
    current.symlink_to(target.name)

    record, _ = run_statusline(
        tmp_path,
        window_tokens=200_000,
        used_percentage=67,
    )

    assert current.is_symlink()
    assert current.readlink() == Path("session.json")
    assert record["context_percent"] == 67
    updated = json.loads(target.read_text(encoding="utf-8"))
    assert updated["context_percent"] == 67
    assert updated["session_id"] == "sess-1"
    assert updated["metadata"] == {"source": "context-threshold-check"}
