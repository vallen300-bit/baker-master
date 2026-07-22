import json
import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).parents[1] / ".claude" / "statusline.sh"
MIGRATE_SCRIPT = Path(__file__).parents[1] / "scripts" / "migrate_context_band_slugs.sh"


def run_statusline(
    tmp_path,
    *,
    window_tokens,
    used_percentage,
    model_display="Opus 4.8",
    role="lead",
    forge_terminal=None,
):
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
    env.pop("FORGE_TERMINAL", None)
    env.update(
        {
            "BAKER_ROLE": role,
            "CONTEXT_BAND_DIR": str(tmp_path),
            "CONTEXT_BAND_THROTTLE_S": "0",
        }
    )
    if forge_terminal is not None:
        env["FORGE_TERMINAL"] = forge_terminal
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    raw_alias = forge_terminal if forge_terminal is not None else role
    alias = {
        "lead": "lead",
        "movie_desk": "movie-desk",
        "baden_baden_desk": "baden-baden-desk",
    }.get(raw_alias, raw_alias)
    record = json.loads((tmp_path / f"{alias}.current").read_text(encoding="utf-8"))
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
    env.pop("FORGE_TERMINAL", None)
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


def test_statusline_normalizes_underscore_role_to_canonical_slug(tmp_path):
    record, _ = run_statusline(
        tmp_path,
        window_tokens=1_000_000,
        used_percentage=16,
        role="movie_desk",
    )

    assert record["context_percent"] == 16
    assert (tmp_path / "movie-desk.current").is_symlink()
    assert not (tmp_path / "movie_desk.current").exists()


def test_statusline_normalizes_underscore_forge_terminal_to_canonical_slug(tmp_path):
    record, _ = run_statusline(
        tmp_path,
        window_tokens=1_000_000,
        used_percentage=18,
        role="lead",
        forge_terminal="movie_desk",
    )

    assert record["context_percent"] == 18
    assert (tmp_path / "movie-desk.current").is_symlink()
    assert not (tmp_path / "movie_desk.current").exists()


def test_context_band_migration_relinks_symlink_and_moves_regular_file(tmp_path):
    target = tmp_path / "movie-session.json"
    target.write_text(json.dumps({"session_id": "movie-1"}), encoding="utf-8")
    (tmp_path / "movie_desk.current").symlink_to(target.name)
    (tmp_path / "origination_desk.current").write_text(
        json.dumps({"context_percent": 12}),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(MIGRATE_SCRIPT)],
        text=True,
        capture_output=True,
        env={**os.environ, "CONTEXT_BAND_DIR": str(tmp_path)},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "movie-desk.current").is_symlink()
    assert (tmp_path / "movie-desk.current").readlink() == Path(target.name)
    assert json.loads(
        (tmp_path / "origination-desk.current").read_text(encoding="utf-8")
    ) == {"context_percent": 12}
    assert not (tmp_path / "movie_desk.current").exists()
    assert not (tmp_path / "origination_desk.current").exists()


def test_context_band_migration_does_not_overwrite_existing_canonical_file(tmp_path):
    canonical = tmp_path / "movie-desk.current"
    legacy = tmp_path / "movie_desk.current"
    canonical.write_text(
        json.dumps({"context_percent": 99}),
        encoding="utf-8",
    )
    legacy.write_text(
        json.dumps({"context_percent": 18}),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(MIGRATE_SCRIPT)],
        text=True,
        capture_output=True,
        env={**os.environ, "CONTEXT_BAND_DIR": str(tmp_path)},
        check=False,
    )

    assert result.returncode != 0
    assert "canonical target already exists" in result.stderr
    assert json.loads(canonical.read_text(encoding="utf-8")) == {
        "context_percent": 99
    }
    assert json.loads(legacy.read_text(encoding="utf-8")) == {
        "context_percent": 18
    }
