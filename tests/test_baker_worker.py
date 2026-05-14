"""Tests for scripts/baker_worker.py — BRIEF_WORKER_SELFWAKE_PHASE_1.

The worker is invoked once per launchd cycle. Tests drive `_run_cycle()`
directly with monkey-patched env + state + urllib + subprocess so each
branch (kill switch / lock / breaker / rate cap / cost cap / no-msgs /
new-msgs / claude-fail / breaker-trip-on-3rd) can be exercised in
isolation.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (avoids importing scripts/ as a package)
# ---------------------------------------------------------------------------

_WORKER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "baker_worker.py"


@pytest.fixture
def worker(tmp_path, monkeypatch):
    """Load baker_worker as a fresh module + wire env to a tmp state dir.

    Yields the module object so tests can call `worker._run_cycle()` and patch
    helper functions directly. Env vars set here are reset by monkeypatch
    teardown.
    """
    spec = importlib.util.spec_from_file_location("baker_worker_under_test", _WORKER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["baker_worker_under_test"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    state_dir = tmp_path / "worker-b1"
    picker_dir = tmp_path / "bm-b1"
    state_dir.mkdir()
    picker_dir.mkdir()
    (state_dir / "key").write_text("dummy-terminal-key\n")

    monkeypatch.setenv("BAKER_WORKER_SLUG", "b1")
    monkeypatch.setenv("BAKER_WORKER_ENABLED", "true")
    monkeypatch.setenv("BAKER_WORKER_STATE_DIR", str(state_dir))
    monkeypatch.setenv("BAKER_WORKER_PICKER_DIR", str(picker_dir))
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setenv("BRISEN_LAB_DAEMON_URL", "https://example.invalid/lab")
    monkeypatch.setenv("BAKER_MASTER_URL", "https://example.invalid/master")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "")

    yield types_namespace(mod=mod, state_dir=state_dir, picker_dir=picker_dir)


class types_namespace:
    """Tiny fixture container so tests can read .mod / .state_dir / .picker_dir."""
    def __init__(self, mod, state_dir, picker_dir):
        self.mod = mod
        self.state_dir = state_dir
        self.picker_dir = picker_dir
    @property
    def state_file(self):
        return self.state_dir / "state.json"
    @property
    def lock_file(self):
        return self.state_dir / "wake.lock"


def _seed_state(state_file: Path, **overrides) -> None:
    """Seed state.json. Defaults `tokens_today_date` to today (UTC) so the
    daily-reset branch in `_maybe_reset_daily_cost` doesn't wipe seeded
    counters mid-test."""
    from datetime import datetime, timezone
    base = {
        "cursor": "1970-01-01T00:00:00Z",
        "processed_ids": [],
        "tokens_today": 0,
        "tokens_today_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "recent_wakes_60min": [],
        "consecutive_fails": 0,
        "breaker": {"tripped": False, "trip_ts": None, "reason": None},
        "cost_cap_hit_today": False,
    }
    base.update(overrides)
    state_file.write_text(json.dumps(base))


# ---------------------------------------------------------------------------
# Behavior tests — one per branch of the per-cycle flow
# ---------------------------------------------------------------------------

def test_kill_switch_off_exits_silently(worker, monkeypatch):
    """BAKER_WORKER_ENABLED!='true' → exit 0, no bus poll, no claude."""
    monkeypatch.setenv("BAKER_WORKER_ENABLED", "false")
    poll_calls = []
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: poll_calls.append(a) or ([], 200))
    rc = worker.mod._run_cycle()
    assert rc == 0
    assert poll_calls == []   # never reached


def test_lock_alive_blocks_cycle(worker, monkeypatch):
    """wake.lock with current PID → skip cycle."""
    worker.lock_file.write_text(json.dumps({"pid": os.getpid(), "start_ts": time.time()}))
    poll_calls = []
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: poll_calls.append(a) or ([], 200))
    rc = worker.mod._run_cycle()
    assert rc == 0
    assert poll_calls == []
    # Lock should still exist (we did NOT enter the wake path, so we don't delete it).
    assert worker.lock_file.exists()


def test_breaker_tripped_blocks_cycle(worker, monkeypatch):
    _seed_state(worker.state_file, breaker={"tripped": True, "trip_ts": "2026-05-15", "reason": "test"})
    poll_calls = []
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: poll_calls.append(a) or ([], 200))
    rc = worker.mod._run_cycle()
    assert rc == 0
    assert poll_calls == []


def test_rate_cap_skips_after_4_wakes(worker, monkeypatch):
    """4 wakes within last 60min → skip; pruning leaves the recent ones."""
    now = time.time()
    _seed_state(worker.state_file, recent_wakes_60min=[now - 600, now - 400, now - 200, now - 60])
    poll_calls = []
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: poll_calls.append(a) or ([], 200))
    rc = worker.mod._run_cycle()
    assert rc == 0
    assert poll_calls == []


def test_cost_cap_pushes_slack_first_hit_then_silent(worker, monkeypatch):
    """tokens_today >= cap → exit 0, Slack push only on first hit of the day."""
    _seed_state(worker.state_file, tokens_today=200_000, cost_cap_hit_today=False)
    slack_calls = []
    monkeypatch.setattr(worker.mod, "_slack", lambda webhook, text: slack_calls.append(text))
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: ([], 200))
    rc = worker.mod._run_cycle()
    assert rc == 0
    assert len(slack_calls) == 1 and "daily token cap" in slack_calls[0]
    # Second cycle: cost_cap_hit_today now True; Slack must NOT push again.
    rc2 = worker.mod._run_cycle()
    assert rc2 == 0
    assert len(slack_calls) == 1


def test_no_new_messages_no_op(worker, monkeypatch):
    """Bus returns no msgs → cycle exits cleanly without invoking claude."""
    _seed_state(worker.state_file)
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: ([], 200))
    invocations = []
    monkeypatch.setattr(worker.mod, "_invoke_claude", lambda picker: invocations.append(picker) or (0, "", "", 0.0))
    rc = worker.mod._run_cycle()
    assert rc == 0
    assert invocations == []
    assert not worker.lock_file.exists()


def test_new_messages_invoke_claude_ack_audit_state(worker, monkeypatch):
    """Happy path: 2 new msgs → claude invoked → both acked → state updated → audit POSTed."""
    _seed_state(worker.state_file, processed_ids=[1])
    msgs = [
        {"id": 100, "created_at": "2026-05-15T00:00:01Z", "body": "hi"},
        {"id": 101, "created_at": "2026-05-15T00:00:02Z", "body": "hi2"},
    ]
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: (msgs, 200))

    sample_json = (
        '{"type":"result","is_error":false,'
        '"usage":{"input_tokens":10,"output_tokens":20,'
        '"cache_creation_input_tokens":1000,"cache_read_input_tokens":0},'
        '"total_cost_usd":0.123}'
    )
    monkeypatch.setattr(worker.mod, "_invoke_claude", lambda picker: (0, sample_json, "", 1.5))

    acked = []
    monkeypatch.setattr(worker.mod, "_ack_message", lambda base, mid, key: acked.append(mid) or True)

    audit_payloads = []
    monkeypatch.setattr(worker.mod, "_audit_log", lambda url, key, payload: audit_payloads.append(payload) or True)

    rc = worker.mod._run_cycle()
    assert rc == 0
    assert sorted(acked) == [100, 101]

    # State updates persisted.
    state = json.loads(worker.state_file.read_text())
    assert state["cursor"] == "2026-05-15T00:00:02Z"
    assert state["tokens_today"] == 10 + 20 + 1000 + 0
    assert 100 in state["processed_ids"] and 101 in state["processed_ids"]
    assert state["consecutive_fails"] == 0
    assert state["breaker"]["tripped"] is False
    assert len(state["recent_wakes_60min"]) == 1

    # Audit payload shape.
    assert len(audit_payloads) == 1
    p = audit_payloads[0]
    assert p["worker_slug"] == "b1"
    assert p["messages_drained"] == 2
    assert p["message_ids"] == [100, 101]
    assert p["claude_exit_code"] == 0
    assert p["claude_stdout_tokens"] == 1030
    assert abs(p["cost_eur_est"] - round(0.123 * worker.mod.USD_TO_EUR_FALLBACK, 4)) < 1e-9

    # Lock removed.
    assert not worker.lock_file.exists()


def test_claude_fail_increments_then_trips_breaker_on_3rd(worker, monkeypatch):
    """3 consecutive non-zero claude exits → breaker trips + Slack push."""
    msgs = [{"id": 200, "created_at": "2026-05-15T00:00:00Z", "body": "x"}]
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: (msgs, 200))
    monkeypatch.setattr(worker.mod, "_invoke_claude", lambda picker: (1, "", "boom", 0.5))
    monkeypatch.setattr(worker.mod, "_ack_message", lambda *a, **k: True)
    monkeypatch.setattr(worker.mod, "_audit_log", lambda *a, **k: True)
    slack_pushes = []
    monkeypatch.setattr(worker.mod, "_slack", lambda webhook, text: slack_pushes.append(text))

    # Each cycle re-finds msg 200 (id not in processed_ids until claude succeeds);
    # we re-seed cursor each time so the message keeps being "new".
    for cycle_idx in range(3):
        _seed_state(
            worker.state_file,
            consecutive_fails=cycle_idx,
            recent_wakes_60min=[],
            processed_ids=[],   # force the message to re-qualify each cycle
        )
        rc = worker.mod._run_cycle()
        assert rc == 0

    state = json.loads(worker.state_file.read_text())
    assert state["breaker"]["tripped"] is True
    assert "claude exit 1" in state["breaker"]["reason"]
    assert any(":rotating_light:" in s and "TRIPPED" in s for s in slack_pushes), slack_pushes


def test_claude_success_resets_consecutive_fails(worker, monkeypatch):
    """Successful wake clears consecutive_fails counter."""
    _seed_state(worker.state_file, consecutive_fails=2)
    msgs = [{"id": 300, "created_at": "2026-05-15T01:00:00Z", "body": "ok"}]
    monkeypatch.setattr(worker.mod, "_poll_bus", lambda *a, **k: (msgs, 200))
    monkeypatch.setattr(worker.mod, "_invoke_claude", lambda picker: (0, '{"usage":{"input_tokens":1,"output_tokens":1}}', "", 0.1))
    monkeypatch.setattr(worker.mod, "_ack_message", lambda *a, **k: True)
    monkeypatch.setattr(worker.mod, "_audit_log", lambda *a, **k: True)

    rc = worker.mod._run_cycle()
    assert rc == 0
    state = json.loads(worker.state_file.read_text())
    assert state["consecutive_fails"] == 0
    assert state["breaker"]["tripped"] is False


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------

def test_parse_usage_extracts_tokens_and_cost(worker):
    sample = (
        '{"type":"result","is_error":false,'
        '"usage":{"input_tokens":6,"cache_creation_input_tokens":42508,'
        '"cache_read_input_tokens":0,"output_tokens":13},'
        '"total_cost_usd":0.26603}'
    )
    tokens, cost = worker.mod._parse_usage(sample)
    assert tokens == 6 + 42508 + 0 + 13
    assert cost == pytest.approx(0.26603)


def test_parse_usage_returns_zero_on_garbage(worker):
    assert worker.mod._parse_usage("") == (0, None)
    assert worker.mod._parse_usage("not json\nstill not json") == (0, None)
    # Valid JSON but no usage key → (0, None).
    assert worker.mod._parse_usage('{"foo": 1}') == (0, None)


def test_parse_usage_tolerates_pre_roll_lines(worker):
    """Pre-roll noise lines must NOT break parse — last non-empty line wins."""
    out = "starting...\nstill warming up\n\n" + '{"usage":{"input_tokens":7,"output_tokens":8}}'
    tokens, cost = worker.mod._parse_usage(out)
    assert tokens == 15
    assert cost is None


def test_lock_alive_keeps_long_session_with_live_pid(worker):
    """Long-running picker session: stale-aged but live PID → lock remains alive.

    PID check is authoritative; the stale window only matters when the
    writer is gone. Without this, 4h+ Director picker sessions would race
    against worker wakes after the 14400s window.
    """
    worker.lock_file.write_text(json.dumps({
        "pid": os.getpid(),
        "start_ts": time.time() - (worker.mod.LOCK_STALE_S + 60),
    }))
    assert worker.mod._lock_alive(worker.lock_file) is True
    assert worker.lock_file.exists()


def test_lock_alive_reclaims_stale_orphan_with_dead_pid(worker):
    """Dead PID + age > LOCK_STALE_S → lock reclaimed (orphan from prior crash)."""
    worker.lock_file.write_text(json.dumps({
        "pid": 999_999,
        "start_ts": time.time() - (worker.mod.LOCK_STALE_S + 60),
    }))
    assert worker.mod._lock_alive(worker.lock_file) is False
    assert not worker.lock_file.exists()


def test_lock_alive_dead_pid_recent_holds(worker):
    """Dead PID but recent start_ts → conservative hold (SessionEnd race window)."""
    worker.lock_file.write_text(json.dumps({"pid": 999_999, "start_ts": time.time()}))
    assert worker.mod._lock_alive(worker.lock_file) is True
    assert worker.lock_file.exists()


def test_lock_alive_corrupted_payload_reclaimed(worker):
    """Garbage in the lock file → reclaim (writer crashed mid-write)."""
    worker.lock_file.write_text("not json")
    assert worker.mod._lock_alive(worker.lock_file) is False
    assert not worker.lock_file.exists()


def test_state_save_is_atomic(worker):
    """_save_state writes via .tmp + replace so a crash never half-writes."""
    worker.mod._save_state(worker.state_file, {"cursor": "x", "processed_ids": []})
    assert worker.state_file.exists()
    # No leftover .tmp file.
    assert not worker.state_dir.joinpath("state.json.tmp").exists()
    parsed = json.loads(worker.state_file.read_text())
    assert parsed["cursor"] == "x"
