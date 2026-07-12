"""Shared context-band computation tests — CASE_ONE_P0_CONTEXT_METERING_1.

Rubric #1: ONE band computation, no drift. These tests prove `context_meter`
is correct in isolation AND that the Stop hook, which imports it, reports the
same band for the same transcript on both the measured-usage path and the
bytes/4 fallback path. Lead #9733: the identical-band test lands BEFORE the
heartbeat band-file emitter.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "context-threshold-check.sh"
METER_PATH = REPO_ROOT / ".claude" / "hooks" / "context_meter.py"

# Load context_meter by path (it lives in .claude/hooks, not on the package path).
_spec = importlib.util.spec_from_file_location("context_meter", METER_PATH)
context_meter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(context_meter)


# --- transcript builders (mirror the hook's real input shape) ----------------

def _usage_line(total: int) -> str:
    # input_tokens + cache_read_input_tokens + cache_creation_input_tokens == total.
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "usage": {
            "input_tokens": 2,
            "cache_read_input_tokens": total - 2,
            "cache_creation_input_tokens": 0,
            "output_tokens": 50,
        }},
    })


def _usage_transcript(tmp_path: Path, total: int, *, pad_tokens: int = 0) -> Path:
    path = tmp_path / "usage.jsonl"
    lines = []
    if pad_tokens:
        lines.append(json.dumps({"type": "tool_result", "content": "x" * (pad_tokens * 4)}))
    lines.append(_usage_line(total))
    path.write_text("\n".join(lines) + "\n")
    return path


def _bytes_transcript(tmp_path: Path, token_estimate: int) -> Path:
    # No usage field -> the meter must fall back to bytes/4.
    path = tmp_path / "bytes.jsonl"
    path.write_bytes(b"x" * token_estimate * 4)
    return path


# --- module-level correctness ------------------------------------------------

def test_band_boundaries():
    assert context_meter.band_for(0, 70, 85) == "ok"
    assert context_meter.band_for(69, 70, 85) == "ok"
    assert context_meter.band_for(70, 70, 85) == "soft"   # soft is inclusive
    assert context_meter.band_for(84, 70, 85) == "soft"
    assert context_meter.band_for(85, 70, 85) == "hard"   # hard is inclusive
    assert context_meter.band_for(200, 70, 85) == "hard"  # over 100 stays hard


def test_compute_measured_true_from_usage(tmp_path):
    t = _usage_transcript(tmp_path, 750_000, pad_tokens=900_000)  # bytes/4 would read hard
    m = context_meter.compute(t, 1_000_000, 70, 85)
    assert m["measured"] is True
    assert m["context_percent"] == 75  # from usage, not the junk pad
    assert m["band"] == "soft"
    assert m["window_tokens"] == 1_000_000


def test_compute_measured_false_bytes_fallback(tmp_path):
    t = _bytes_transcript(tmp_path, 900_000)  # 900k est tokens of a 1M window
    m = context_meter.compute(t, 1_000_000, 70, 85)
    assert m["measured"] is False
    assert m["context_percent"] == 90
    assert m["band"] == "hard"


def test_compute_none_on_unset_window(tmp_path):
    t = _bytes_transcript(tmp_path, 100)
    assert context_meter.compute(t, 0, 70, 85) is None


def test_compute_none_on_unreadable_transcript(tmp_path):
    missing = tmp_path / "does-not-exist.jsonl"
    assert context_meter.compute(missing, 1_000_000, 70, 85) is None


# --- no-drift: the hook reports the SAME band the module computes ------------

def _run_hook(transcript: Path, *, window: int, soft: int, hard: int):
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": str(transcript),
        "cwd": str(transcript.parent),
    })
    env = os.environ.copy()
    env.pop("ROLLOVER_SETTINGS_PATH", None)
    env["ROLLOVER_WINDOW_TOKENS"] = str(window)
    env["ROLLOVER_SOFT_PERCENT"] = str(soft)
    env["ROLLOVER_HARD_PERCENT"] = str(hard)
    return subprocess.run(
        ["bash", str(HOOK)], input=payload, capture_output=True, text=True, env=env, timeout=8,
    )


def _hook_percent_and_band(stdout: str, soft: int, hard: int):
    """Parse the percent the hook reported and classify it with the SAME band
    cutoffs, so we can assert the hook agrees with context_meter."""
    out = stdout.strip()
    if not out:
        return None, None  # silent -> below soft -> band ok
    msg = json.loads(out)["systemMessage"]
    m = re.search(r"context ~(\d+)%", msg)
    assert m, f"no percent in hook message: {msg!r}"
    pct = int(m.group(1))
    return pct, context_meter.band_for(pct, soft, hard)


def test_hook_and_meter_agree_measured_path(tmp_path):
    # soft=1 forces the hook to surface the percent even for a healthy seat.
    t = _usage_transcript(tmp_path, 750_000, pad_tokens=900_000)
    meter = context_meter.compute(t, 1_000_000, 1, 85)
    result = _run_hook(t, window=1_000_000, soft=1, hard=85)
    hook_pct, hook_band = _hook_percent_and_band(result.stdout, 1, 85)
    assert hook_pct == meter["context_percent"] == 75
    assert hook_band == meter["band"] == "soft"


def test_hook_and_meter_agree_bytes_fallback_path(tmp_path):
    t = _bytes_transcript(tmp_path, 900_000)
    meter = context_meter.compute(t, 1_000_000, 70, 85)
    result = _run_hook(t, window=1_000_000, soft=70, hard=85)
    hook_pct, hook_band = _hook_percent_and_band(result.stdout, 70, 85)
    assert hook_pct == meter["context_percent"] == 90
    assert hook_band == meter["band"] == "hard"


def test_hook_and_meter_agree_ok_band_is_silent(tmp_path):
    # 20% -> ok band -> the hook stays silent (below default soft). The module
    # must independently classify the same transcript as ok.
    t = _usage_transcript(tmp_path, 200_000)
    meter = context_meter.compute(t, 1_000_000, 70, 85)
    assert meter["band"] == "ok"
    result = _run_hook(t, window=1_000_000, soft=70, hard=85)
    assert result.stdout.strip() == "", "ok band must produce no warning"


# --- P0.1 emit: the Stop hook writes the machine band file -------------------

def _run_hook_with_band(transcript: Path, *, window: int, soft: int, hard: int,
                        session_id: str | None, band_dir: Path):
    payload = {
        "hook_event_name": "Stop",
        "transcript_path": str(transcript),
        "cwd": str(transcript.parent),
    }
    if session_id is not None:
        payload["session_id"] = session_id
    env = os.environ.copy()
    env.pop("ROLLOVER_SETTINGS_PATH", None)
    env["ROLLOVER_WINDOW_TOKENS"] = str(window)
    env["ROLLOVER_SOFT_PERCENT"] = str(soft)
    env["ROLLOVER_HARD_PERCENT"] = str(hard)
    env["CONTEXT_BAND_DIR"] = str(band_dir)
    return subprocess.run(
        ["bash", str(HOOK)], input=json.dumps(payload), capture_output=True,
        text=True, env=env, timeout=8,
    )


def test_band_file_written_for_ok_seat(tmp_path):
    # A fresh healthy seat (20%, ok band, below soft -> silent warning) MUST still
    # emit its band so the dispatcher sees it as ok (retires E16 false alarm).
    band_dir = tmp_path / "band"
    t = _usage_transcript(tmp_path, 200_000)
    result = _run_hook_with_band(t, window=1_000_000, soft=70, hard=85,
                                 session_id="sess-ok-1", band_dir=band_dir)
    assert result.stdout.strip() == "", "ok seat still silent to the human"
    rec = json.loads((band_dir / "sess-ok-1.json").read_text())
    assert rec["band"] == "ok"
    assert rec["context_percent"] == 20
    assert rec["measured"] is True
    assert rec["window_tokens"] == 1_000_000
    assert rec["session_id"] == "sess-ok-1"


def test_band_file_written_for_hard_seat_matches_hook(tmp_path):
    band_dir = tmp_path / "band"
    t = _bytes_transcript(tmp_path, 900_000)  # bytes/4 -> 90% -> hard, measured=false
    result = _run_hook_with_band(t, window=1_000_000, soft=70, hard=85,
                                 session_id="sess-hard-1", band_dir=band_dir)
    hook_pct, hook_band = _hook_percent_and_band(result.stdout, 70, 85)
    rec = json.loads((band_dir / "sess-hard-1.json").read_text())
    assert rec["band"] == hook_band == "hard"
    assert rec["context_percent"] == hook_pct == 90
    assert rec["measured"] is False


def test_band_file_skipped_without_session_id(tmp_path):
    band_dir = tmp_path / "band"
    t = _usage_transcript(tmp_path, 200_000)
    _run_hook_with_band(t, window=1_000_000, soft=70, hard=85,
                        session_id=None, band_dir=band_dir)
    assert not band_dir.exists() or not any(band_dir.iterdir()), \
        "no session_id -> no band file (nothing to key it on)"


def test_band_file_atomic_no_tmp_left(tmp_path):
    band_dir = tmp_path / "band"
    t = _usage_transcript(tmp_path, 800_000)
    _run_hook_with_band(t, window=1_000_000, soft=70, hard=85,
                        session_id="sess-atomic", band_dir=band_dir)
    assert (band_dir / "sess-atomic.json").exists()
    assert not list(band_dir.glob("*.tmp")), "temp file must be swapped away"
