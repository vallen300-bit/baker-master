"""CASE_ONE_E23_SESSION_STATE_PERSISTENCE_1 — close-pin gate + orientation hook.

Covers the brief verification matrix:
  1. close-pin fires on live-state-no-checkpoint, passes on checkpoint-present.
  2. interactive-seat path warns + names the LIGHT floor, never force-terminates
     (no decision:block by default).
  3. orientation surfaces a pending brief/deadline/handover, and emits the explicit
     "checked N sources, none pending" on a truly-clean seat (fail-loud inverse).
  4. both respect the exit-0 contract + emit a valid envelope.
  5. the shared live-state predicate biases to fire (false-miss = 0).
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLOSE_PIN = REPO_ROOT / ".claude" / "hooks" / "close-pin-check.sh"
ORIENT = REPO_ROOT / ".claude" / "hooks" / "session-open-orientation.sh"
PREDICATE = REPO_ROOT / ".claude" / "hooks" / "live_state_predicate.py"

_spec = importlib.util.spec_from_file_location("live_state_predicate", PREDICATE)
lsp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lsp)


# --------------------------------------------------------------------------- utils
def _transcript(tmp: Path, *, iso_ts: str = "2026-07-13T09:00:00Z", edit: bool = False) -> Path:
    """A minimal JSONL transcript whose first line carries `timestamp` (the session
    start proxy). `edit=True` embeds a Write tool-use so the predicate sees a draft."""
    lines = [json.dumps({"type": "user", "timestamp": iso_ts})]
    if edit:
        lines.append(json.dumps({"type": "assistant", "message": {
            "content": [{"type": "tool_use", "name": "Write", "input": {}}]}}))
    p = tmp / "transcript.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return p


def _worker_picker(tmp: Path, *, active_brief=True, brief_id="CASE_ONE_E23_1",
                   fresh_checkpoint=False) -> Path:
    root = tmp / "seat"
    (root / "briefs" / "_tasks").mkdir(parents=True, exist_ok=True)
    (root / "briefs" / "_checkpoints").mkdir(parents=True, exist_ok=True)
    if active_brief:
        (root / "briefs" / "_tasks" / "CODE_4_PENDING.md").write_text(
            f"---\nstatus: ACTIVE\nbrief_id: {brief_id}\n---\n# active\n")
    if fresh_checkpoint:
        cp = root / "briefs" / "_checkpoints" / f"{brief_id}.checkpoint.md"
        cp.write_text("# checkpoint\n")
        # Make it clearly newer than the session start (2026 ts -> use now).
        os.utime(cp, None)
    return root


def _run_close_pin(payload: dict, role: str = "b4", *, cwd: Path | None = None,
                   extra_env: dict | None = None):
    env = os.environ.copy()
    env["BAKER_ROLE"] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["bash", str(CLOSE_PIN)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=10)


def _run_orient(payload: dict, role: str = "b4"):
    env = os.environ.copy()
    env["BAKER_ROLE"] = role
    return subprocess.run(["bash", str(ORIENT)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=10)


def _system_message(stdout: str):
    out = stdout.strip()
    return json.loads(out).get("systemMessage") if out else None


def _decision(stdout: str):
    out = stdout.strip()
    return json.loads(out).get("decision") if out else None


def _additional_context(stdout: str):
    out = stdout.strip()
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


# ---------------------------------------------------------------- scripts hygiene
def test_scripts_exist_executable_syntax_clean():
    for s in (CLOSE_PIN, ORIENT, PREDICATE):
        assert s.is_file()
        assert s.stat().st_mode & stat.S_IXUSR, f"{s} not executable"
    for s in (CLOSE_PIN, ORIENT):
        r = subprocess.run(["bash", "-n", str(s)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, "-m", "py_compile", str(PREDICATE)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------- predicate (5)
def test_predicate_clean_seat_not_dirty(tmp_path):
    root = _worker_picker(tmp_path, active_brief=False)
    t = _transcript(tmp_path)
    v = lsp.evaluate(str(root), "b4", str(t))
    assert v["dirty"] is False
    assert v["has_live_state"] is False


def test_predicate_live_no_checkpoint_is_dirty(tmp_path):
    root = _worker_picker(tmp_path, active_brief=True, fresh_checkpoint=False)
    t = _transcript(tmp_path)
    v = lsp.evaluate(str(root), "b4", str(t))
    assert v["dirty"] is True
    assert any("mailbox" in r for r in v["reasons"])


def test_predicate_fresh_checkpoint_clears_dirty(tmp_path):
    root = _worker_picker(tmp_path, active_brief=True, fresh_checkpoint=True)
    # session start well BEFORE the checkpoint's now-mtime -> checkpoint is fresh.
    t = _transcript(tmp_path, iso_ts="2020-01-01T00:00:00Z")
    v = lsp.evaluate(str(root), "b4", str(t))
    assert v["fresh_checkpoint"] is True
    assert v["dirty"] is False


def test_predicate_biases_to_fire_when_session_start_unknown(tmp_path):
    # No transcript -> session_start_ts unknown -> a checkpoint CANNOT be proven
    # fresh -> treated as stale -> dirty (false-miss = 0).
    root = _worker_picker(tmp_path, active_brief=True, fresh_checkpoint=True)
    v = lsp.evaluate(str(root), "b4", None)
    assert v["session_start_ts"] is None
    assert v["fresh_checkpoint"] is False
    assert v["dirty"] is True


def test_predicate_never_raises_returns_dirty_on_error():
    # A bogus cwd type still returns a verdict (fail-toward-firing), never raises.
    v = lsp.evaluate(cwd=12345, role="b4", transcript_path=None)  # type: ignore[arg-type]
    assert isinstance(v, dict) and "dirty" in v


# ------------------------------------------------------ close-pin Stop path (1,2)
def test_close_pin_stop_warns_worker_no_block(tmp_path):
    root = _worker_picker(tmp_path, fresh_checkpoint=False)
    t = _transcript(tmp_path)
    payload = {"hook_event_name": "Stop", "cwd": str(root), "transcript_path": str(t),
               "session_id": "s1"}
    r = _run_close_pin(payload, role="b4")
    assert r.returncode == 0, r.stderr
    msg = _system_message(r.stdout)
    assert msg and "close-pin" in msg
    assert "briefs/_checkpoints/<BRIEF_ID>.checkpoint.md" in msg  # worker LIGHT floor
    assert _decision(r.stdout) is None  # warn-only by default (no forced-terminate)


def test_close_pin_stop_warn_once_per_session(tmp_path):
    root = _worker_picker(tmp_path, fresh_checkpoint=False)
    t = _transcript(tmp_path)
    payload = {"hook_event_name": "Stop", "cwd": str(root), "transcript_path": str(t),
               "session_id": "s1"}
    first = _run_close_pin(payload, role="b4")
    assert _system_message(first.stdout) is not None
    second = _run_close_pin(payload, role="b4")
    assert second.returncode == 0
    assert second.stdout.strip() == "", "must not nag every turn"


def test_close_pin_stop_silent_on_clean_seat(tmp_path):
    root = _worker_picker(tmp_path, active_brief=False)
    t = _transcript(tmp_path)
    payload = {"hook_event_name": "Stop", "cwd": str(root), "transcript_path": str(t),
               "session_id": "s1"}
    r = _run_close_pin(payload, role="b4")
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_close_pin_stop_interactive_seat_warns_seat_floor(tmp_path):
    # An interactive desk (PINNED OPEN item, no checkpoint) gets the seat LIGHT
    # floor + a warn, never a block (E17: cannot force-terminate a human window).
    root = tmp_path / "desk"
    root.mkdir()
    (root / "PINNED.md").write_text("## A\n- [OPEN] Weippert re-review\n")
    t = _transcript(tmp_path)
    payload = {"hook_event_name": "Stop", "cwd": str(root), "transcript_path": str(t),
               "session_id": "s1"}
    r = _run_close_pin(payload, role="hag-desk")
    assert r.returncode == 0, r.stderr
    msg = _system_message(r.stdout)
    assert msg and "PINNED §A" in msg  # seat floor, not the worker checkpoint floor
    assert _decision(r.stdout) is None


def test_close_pin_stop_block_opt_in(tmp_path):
    root = _worker_picker(tmp_path, fresh_checkpoint=False)
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text(
        json.dumps({"close_pin_block_on_stop": True}))
    t = _transcript(tmp_path)
    payload = {"hook_event_name": "Stop", "cwd": str(root), "transcript_path": str(t),
               "session_id": "s1"}
    r = _run_close_pin(payload, role="b4")
    assert r.returncode == 0, r.stderr
    assert _decision(r.stdout) == "block"  # opted in -> first fire blocks


# --------------------------------------------- close-pin SessionEnd path (1, R3)
def test_close_pin_sessionend_worker_writes_unverified_auto_stub(tmp_path):
    root = _worker_picker(tmp_path, brief_id="CASE_ONE_E23_1", fresh_checkpoint=False)
    t = _transcript(tmp_path)
    payload = {"hook_event_name": "SessionEnd", "cwd": str(root),
               "transcript_path": str(t), "session_id": "s1", "reason": "logout"}
    r = _run_close_pin(payload, role="b4")
    assert r.returncode == 0, r.stderr
    stub = root / "briefs" / "_checkpoints" / "CASE_ONE_E23_1.autostub.checkpoint.md"
    assert stub.exists(), "non-interactive worker must persist a stub at close"
    body = stub.read_text()
    assert "UNVERIFIED-AUTO STUB" in body  # R3: clearly marked, not a fake full pin
    assert "successor MUST verify" in body


def test_close_pin_sessionend_interactive_leaves_breadcrumb_not_stub(tmp_path):
    root = tmp_path / "desk"
    (root / "briefs" / "_checkpoints").mkdir(parents=True, exist_ok=True)
    (root / "PINNED.md").write_text("## A\n- [OPEN] live risk\n")
    t = _transcript(tmp_path)
    payload = {"hook_event_name": "SessionEnd", "cwd": str(root),
               "transcript_path": str(t), "session_id": "s1", "reason": "logout"}
    r = _run_close_pin(payload, role="hag-desk")
    assert r.returncode == 0, r.stderr
    # No fabricated pin for an interactive seat (R3); a warn-log breadcrumb instead.
    stubs = list((root / "briefs" / "_checkpoints").glob("*.autostub.checkpoint.md"))
    assert stubs == []
    log = root / "briefs" / "_checkpoints" / ".close-pin-warnlog"
    assert log.exists() and "CLOSE-WITHOUT-PIN" in log.read_text()


# --------------------------------------------------- orientation hook (3, R2)
def test_orientation_surfaces_pending_brief(tmp_path):
    root = _worker_picker(tmp_path, active_brief=True, brief_id="CASE_ONE_E23_1")
    payload = {"hook_event_name": "SessionStart", "cwd": str(root)}
    r = _run_orient(payload, role="b4")
    assert r.returncode == 0, r.stderr
    ctx = _additional_context(r.stdout)
    assert ctx and "[brief]" in ctx and "CASE_ONE_E23_1" in ctx
    assert "clean bus does NOT mean nothing pending" in ctx
    assert len(ctx.splitlines()) <= 30  # R2 budget


def test_orientation_surfaces_deadline_and_handover(tmp_path):
    root = _worker_picker(tmp_path, active_brief=False)
    (root / "briefs" / "_deadlines").mkdir(parents=True, exist_ok=True)
    (root / "briefs" / "_deadlines" / "d1.md").write_text("due soon\n")
    (root / "briefs" / "_checkpoints" / "PRIOR.checkpoint.md").write_text("# prior\n")
    payload = {"hook_event_name": "SessionStart", "cwd": str(root)}
    r = _run_orient(payload, role="b4")
    ctx = _additional_context(r.stdout)
    assert ctx and "[deadline]" in ctx and "[handover]" in ctx


def test_orientation_clean_seat_emits_none_pending(tmp_path):
    root = _worker_picker(tmp_path, active_brief=False)
    payload = {"hook_event_name": "SessionStart", "cwd": str(root)}
    r = _run_orient(payload, role="b4")
    assert r.returncode == 0, r.stderr
    ctx = _additional_context(r.stdout)
    assert ctx and "none pending" in ctx
    assert "checked 4 state sources" in ctx  # fail-loud denominator, not silent
    assert len(ctx.splitlines()) == 1  # R2: 1 line when clean


def test_orientation_autostub_handover_is_flagged(tmp_path):
    root = _worker_picker(tmp_path, active_brief=False)
    (root / "briefs" / "_checkpoints" / "X.autostub.checkpoint.md").write_text("# stub\n")
    payload = {"hook_event_name": "SessionStart", "cwd": str(root)}
    r = _run_orient(payload, role="b4")
    ctx = _additional_context(r.stdout)
    assert ctx and "UNVERIFIED-AUTO STUB" in ctx and "verify" in ctx.lower()
