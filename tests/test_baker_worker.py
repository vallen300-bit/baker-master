"""Tests for scripts/baker_worker.py — the per-cycle B-code self-wake worker.

WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

Coverage (8 cases):
  1. Kill switch off  -> exit 0, no work
  2. Lock alive        -> exit 0, no claude invoke
  3. Breaker tripped   -> exit 0
  4. Rate cap reached  -> exit 0
  5. Cost cap reached  -> exit 0 + one Slack push, no repeat same day
  6. No new messages   -> exit 0, no claude invoke, consecutive_fails reset
  7. New messages full flow -> claude invoked, acks, state advances, audit posted
  8. Claude exit != 0 three times -> breaker trips on 3rd

Approach: load baker_worker as a module, run main() with monkeypatched env +
patched network/subprocess primitives. Avoids forking subprocess for speed.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKER_PATH = REPO_ROOT / "scripts" / "baker_worker.py"


@pytest.fixture()
def worker_module():
    """Load scripts/baker_worker.py as a module under test."""
    spec = importlib.util.spec_from_file_location("baker_worker", str(WORKER_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def workdir(tmp_path, monkeypatch):
    """Per-test state dir + picker dir + minimal env."""
    state = tmp_path / "state"
    picker = tmp_path / "picker"
    state.mkdir()
    picker.mkdir()
    (state / "key").write_text("test-terminal-key")

    monkeypatch.setenv("BAKER_WORKER_SLUG", "b1")
    monkeypatch.setenv("BAKER_WORKER_ENABLED", "true")
    monkeypatch.setenv("BAKER_WORKER_STATE_DIR", str(state))
    monkeypatch.setenv("BAKER_WORKER_PICKER_DIR", str(picker))
    monkeypatch.setenv("BRISEN_LAB_DAEMON_URL", "https://lab.test")
    monkeypatch.setenv("BAKER_MASTER_URL", "https://master.test")
    monkeypatch.setenv("BAKER_KEY", "test-baker-key")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.test/webhook")
    return state, picker


def _write_state(state_dir: Path, **overrides) -> dict:
    base = {
        "cursor": "1970-01-01T00:00:00Z",
        "processed_ids": [],
        "tokens_today": 0,
        "tokens_today_date": time.strftime("%Y-%m-%d", time.gmtime()),
        "recent_wakes_60min": [],
        "consecutive_fails": 0,
        "breaker": {"tripped": False, "trip_ts": None, "reason": None},
        "cost_cap_hit_today": False,
    }
    base.update(overrides)
    (state_dir / "state.json").write_text(json.dumps(base, indent=2))
    return base


def _read_state(state_dir: Path) -> dict:
    return json.loads((state_dir / "state.json").read_text())


# ---------------------------------------------------------------------------
# 1. Kill switch off → exit 0, nothing called
# ---------------------------------------------------------------------------

def test_kill_switch_off_short_circuits(worker_module, workdir, monkeypatch):
    monkeypatch.setenv("BAKER_WORKER_ENABLED", "false")
    state_dir, _ = workdir
    poll_calls = MagicMock()
    with patch.object(worker_module, "_poll_bus", poll_calls), \
         pytest.raises(SystemExit) as exc:
        worker_module.main()
    assert exc.value.code == 0
    poll_calls.assert_not_called()
    # No state.json should be written either
    assert not (state_dir / "state.json").exists()


# ---------------------------------------------------------------------------
# 2. Live lock → exit 0, no claude invoke
# ---------------------------------------------------------------------------

def test_lock_alive_skips_cycle(worker_module, workdir):
    state_dir, _ = workdir
    # Forge a lock for the current process — definitely alive
    (state_dir / "wake.lock").write_text(json.dumps({
        "pid": os.getpid(),
        "start_ts": time.time(),
        "source": "test-fixture",
    }))
    poll = MagicMock()
    invoke = MagicMock()
    with patch.object(worker_module, "_poll_bus", poll), \
         patch.object(worker_module, "_invoke_claude", invoke), \
         pytest.raises(SystemExit) as exc:
        worker_module.main()
    assert exc.value.code == 0
    poll.assert_not_called()
    invoke.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Breaker tripped → exit 0
# ---------------------------------------------------------------------------

def test_breaker_tripped_skips(worker_module, workdir):
    state_dir, _ = workdir
    _write_state(state_dir, breaker={"tripped": True, "trip_ts": "...", "reason": "manual"})
    poll = MagicMock()
    with patch.object(worker_module, "_poll_bus", poll), \
         pytest.raises(SystemExit) as exc:
        worker_module.main()
    assert exc.value.code == 0
    poll.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Rate cap reached → exit 0
# ---------------------------------------------------------------------------

def test_rate_cap_reached_skips(worker_module, workdir):
    state_dir, _ = workdir
    now = time.time()
    _write_state(state_dir, recent_wakes_60min=[now - 600, now - 400, now - 200, now - 100])
    poll = MagicMock()
    with patch.object(worker_module, "_poll_bus", poll), \
         pytest.raises(SystemExit) as exc:
        worker_module.main()
    assert exc.value.code == 0
    poll.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Cost cap reached → exit 0, slack push once, second wake same day silent
# ---------------------------------------------------------------------------

def test_cost_cap_reached_pushes_slack_once(worker_module, workdir):
    state_dir, _ = workdir
    _write_state(state_dir, tokens_today=worker_module.COST_CAP_TOKENS_PER_DAY + 1,
                 cost_cap_hit_today=False)
    slack = MagicMock()
    poll = MagicMock()
    with patch.object(worker_module, "_slack", slack), \
         patch.object(worker_module, "_poll_bus", poll), \
         pytest.raises(SystemExit) as exc:
        worker_module.main()
    assert exc.value.code == 0
    poll.assert_not_called()
    assert slack.call_count == 1
    # After first hit, state has cost_cap_hit_today=True; second main() must not push
    state = _read_state(state_dir)
    assert state["cost_cap_hit_today"] is True

    slack.reset_mock()
    with patch.object(worker_module, "_slack", slack), \
         patch.object(worker_module, "_poll_bus", poll), \
         pytest.raises(SystemExit):
        worker_module.main()
    slack.assert_not_called()


# ---------------------------------------------------------------------------
# 6. No new messages → exit 0, no claude invoke, consecutive_fails reset
# ---------------------------------------------------------------------------

def test_no_new_messages_quiet_exit(worker_module, workdir):
    state_dir, _ = workdir
    _write_state(state_dir, consecutive_fails=2)
    with patch.object(worker_module, "_poll_bus", return_value=[]), \
         patch.object(worker_module, "_invoke_claude") as invoke, \
         pytest.raises(SystemExit) as exc:
        worker_module.main()
    assert exc.value.code == 0
    invoke.assert_not_called()
    assert _read_state(state_dir)["consecutive_fails"] == 0


# ---------------------------------------------------------------------------
# 7. New messages → claude invoked, acks fired, audit posted, state updated
# ---------------------------------------------------------------------------

def test_new_messages_full_flow(worker_module, workdir):
    state_dir, _ = workdir
    _write_state(state_dir)
    msgs = [
        {"id": 101, "created_at": "2026-05-15T01:00:00+00:00"},
        {"id": 102, "created_at": "2026-05-15T01:00:05+00:00"},
    ]
    # Claude returns a valid --output-format=json blob with usage
    stdout_json = json.dumps({
        "type": "result",
        "modelUsage": {"claude-opus-4-7[1m]": {
            "inputTokens": 100, "outputTokens": 200,
            "cacheReadInputTokens": 50, "cacheCreationInputTokens": 25,
        }},
    })
    ack = MagicMock(return_value=True)
    audit = MagicMock()
    with patch.object(worker_module, "_poll_bus", return_value=msgs), \
         patch.object(worker_module, "_invoke_claude", return_value=(0, stdout_json, "", 2.5)), \
         patch.object(worker_module, "_ack_message", ack), \
         patch.object(worker_module, "_audit_log", audit):
        # Normal completion path returns; no SystemExit raised (sys.exit only on
        # early-skip branches). launchd treats natural return as exit 0.
        worker_module.main()
    # Both messages acked
    assert ack.call_count == 2
    # Audit posted
    assert audit.call_count == 1
    audit_payload = audit.call_args[0][2]
    assert audit_payload["worker_slug"] == "b1"
    assert audit_payload["messages_drained"] == 2
    assert audit_payload["message_ids"] == [101, 102]
    assert audit_payload["claude_exit_code"] == 0
    assert audit_payload["claude_stdout_tokens"] == 375  # 100+200+50+25
    # State advanced: cursor + processed_ids + recent_wakes appended
    state = _read_state(state_dir)
    assert state["cursor"] == "2026-05-15T01:00:05+00:00"
    assert 101 in state["processed_ids"] and 102 in state["processed_ids"]
    assert len(state["recent_wakes_60min"]) == 1
    assert state["consecutive_fails"] == 0
    assert state["tokens_today"] == 375
    # Lock should be cleaned up post-cycle
    assert not (state_dir / "wake.lock").exists()


# ---------------------------------------------------------------------------
# 8. Claude exit != 0 three consecutive times → breaker trips on 3rd
# ---------------------------------------------------------------------------

def test_breaker_trips_after_three_consecutive_claude_failures(worker_module, workdir):
    state_dir, _ = workdir
    slack = MagicMock()

    # Each iteration receives a fresh message so we keep entering the
    # "got work" path. Different IDs avoid the processed_ids filter.
    def _msg(i: int) -> list[dict]:
        return [{"id": 1000 + i, "created_at": f"2026-05-15T01:00:0{i}+00:00"}]

    for i in range(1, 4):
        _write_state(
            state_dir,
            consecutive_fails=i - 1,
            recent_wakes_60min=[],   # reset rate cap window each tick
        )
        with patch.object(worker_module, "_poll_bus", return_value=_msg(i)), \
             patch.object(worker_module, "_invoke_claude", return_value=(1, "{}", "boom", 0.1)), \
             patch.object(worker_module, "_ack_message", return_value=True), \
             patch.object(worker_module, "_audit_log"), \
             patch.object(worker_module, "_slack", slack):
            worker_module.main()
        state = _read_state(state_dir)
        if i < 3:
            assert state["breaker"]["tripped"] is False, f"breaker tripped early at iter {i}"
            assert state["consecutive_fails"] == i
        else:
            assert state["breaker"]["tripped"] is True
            assert "claude exit 1" in (state["breaker"]["reason"] or "")
            # Slack push fired at least once on the trip
            assert slack.call_count >= 1
