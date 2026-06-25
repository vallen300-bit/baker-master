"""Tests for SessionStart bus-drain hook.

Brief: BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1.

Hook lives at tests/fixtures/session-start-bus-drain.sh (canonical) and is
deployed user-global at ~/.claude/hooks/session-start-bus-drain.sh by Director
pre-merge per brief Sequencing step 3. Drift detection: see
test_user_global_matches_repo at the bottom of this file.

Tests stub `curl` and `op` by prepending a tempdir to PATH. The tempdir holds
shell stubs that echo a fixed response or fail per the test's scenario, so the
hook exercises real bash + python3 + JSON parsing without network or 1Password.

Coverage (per brief Quality Checkpoint #2 — 5 failure paths + happy path):
  1. BAKER_ROLE unset → silent no-op (no additionalContext emitted).
  2. `op read` failure (empty stdout) → "1Password fetch failed" status line.
  3. Daemon unreachable (curl exit 7) → "daemon unreachable" status line.
  4. Daemon returns malformed JSON → "bad daemon response" status line.
  5. Empty inbox (messages: []) → quiet no-op (no additionalContext).
  6. Happy path: 2 messages → rendered preview + state file written atomically.

Plus drift-detection on Director's Mac (skipped in CI):
  7. ~/.claude/hooks/session-start-bus-drain.sh matches the repo fixture.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "session-start-bus-drain.sh"
USER_GLOBAL_HOOK = Path.home() / ".claude" / "hooks" / "session-start-bus-drain.sh"


def _make_stub(path: Path, body: str) -> None:
    """Write an executable shell stub at `path` with the given body."""
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_hook(env: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the hook fixture with HOME pointed at tmp_path so state file lands there."""
    full_env = {
        "PATH": env["PATH"],
        "HOME": str(tmp_path),
        # Default: in-flight test mode. BAKER_ROLE / BRISEN_LAB_DAEMON_URL come from env.
    }
    full_env.update({k: v for k, v in env.items() if k != "PATH"})
    return subprocess.run(
        ["bash", str(HOOK_FIXTURE)],
        input="{}",  # Claude passes session metadata JSON; hook drains it.
        capture_output=True,
        text=True,
        env=full_env,
        timeout=10,
    )


@pytest.fixture
def stubs_dir(tmp_path):
    """Per-test tempdir holding curl + op stubs; prepended to PATH."""
    d = tmp_path / "bin"
    d.mkdir()
    return d


@pytest.fixture
def base_env(stubs_dir, monkeypatch):
    real_path = os.environ.get("PATH", "/usr/bin:/bin")
    return {
        "PATH": f"{stubs_dir}:{real_path}",
        "BRISEN_LAB_DAEMON_URL": "https://test-daemon.invalid",
    }


# ---------------------------------------------------------------------------
# Failure path 1: BAKER_ROLE unset
# ---------------------------------------------------------------------------

def test_baker_role_unset_silent_noop(stubs_dir, base_env, tmp_path):
    """No BAKER_ROLE → hook exits 0 with empty stdout (no additionalContext)."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'op should not be called'\nexit 99\n")
    _make_stub(stubs_dir / "curl", "#!/bin/bash\necho 'curl should not be called'\nexit 99\n")

    env = dict(base_env)
    # BAKER_ROLE intentionally unset.
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"expected silent no-op, got: {result.stdout!r}"


# ---------------------------------------------------------------------------
# Failure path 2: 1Password fetch failure
# ---------------------------------------------------------------------------

def test_op_fetch_failure_emits_status(stubs_dir, base_env, tmp_path):
    """`op read` returns empty → status line emitted, exit 0."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\nexit 1\n")
    _make_stub(stubs_dir / "curl", "#!/bin/bash\necho 'curl should not be called'\nexit 99\n")

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    # JSON envelope wraps the status line as additionalContext.
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "1Password fetch failed" in ctx
    assert "slug=b2" in ctx


def test_cache_key_skips_op_fetch(stubs_dir, base_env, tmp_path):
    """Populated ~/.brisen-lab/keys/<slug> means SessionStart never calls op."""
    cache_dir = tmp_path / ".brisen-lab" / "keys"
    cache_dir.mkdir(parents=True)
    (cache_dir / "b2").write_text("cache-key\n")
    op_sentinel = tmp_path / "op-called"
    curl_sentinel = tmp_path / "curl-called"
    _make_stub(stubs_dir / "op", f"#!/bin/bash\ntouch {op_sentinel}\nexit 99\n")
    _make_stub(
        stubs_dir / "curl",
        f"#!/bin/bash\ntouch {curl_sentinel}\necho '{{\"messages\": []}}'\nexit 0\n",
    )

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert curl_sentinel.exists(), "daemon fetch should still run with cached key"
    assert not op_sentinel.exists(), "op must not run when cache is populated"


def test_op_fallback_seeds_key_cache(stubs_dir, base_env, tmp_path):
    """Successful last-resort op read writes ~/.brisen-lab/keys/<slug>."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'op-key-1234'\n")
    _make_stub(stubs_dir / "curl", '#!/bin/bash\necho \'{"messages": []}\'\nexit 0\n')

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    cache_file = tmp_path / ".brisen-lab" / "keys" / "b2"
    assert cache_file.read_text().strip() == "op-key-1234"


# ---------------------------------------------------------------------------
# Failure path 3: Daemon unreachable (curl non-zero exit)
# ---------------------------------------------------------------------------

def test_daemon_unreachable_emits_status(stubs_dir, base_env, tmp_path):
    """curl returns non-zero (e.g. timeout) → 'daemon unreachable' status, exit 0."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    _make_stub(stubs_dir / "curl", "#!/bin/bash\nexit 28\n")  # 28 = curl timeout

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "daemon unreachable" in ctx
    assert "timeout 4s" in ctx
    assert "slug=b2" in ctx


# ---------------------------------------------------------------------------
# Failure path 4: Daemon returns malformed JSON
# ---------------------------------------------------------------------------

def test_bad_daemon_response_emits_status(stubs_dir, base_env, tmp_path):
    """Daemon returns non-JSON (e.g. HTML 502 page) → 'bad daemon response', exit 0."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    _make_stub(stubs_dir / "curl", "#!/bin/bash\necho '<html>502 bad gateway</html>'\nexit 0\n")

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "bad daemon response" in ctx


# ---------------------------------------------------------------------------
# Failure path 5: Empty inbox
# ---------------------------------------------------------------------------

def test_empty_inbox_quiet_noop(stubs_dir, base_env, tmp_path):
    """Daemon returns {messages: []} → silent no-op (no additionalContext)."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    _make_stub(stubs_dir / "curl", '#!/bin/bash\necho \'{"messages": []}\'\nexit 0\n')

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"expected silent no-op, got: {result.stdout!r}"


def test_clerk_haiku_role_resolves_to_clerk_haiku_state(stubs_dir, base_env, tmp_path):
    """Generated role map includes Clerk Chat's clerk-haiku terminal slug."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\nexit 1\n")
    _make_stub(stubs_dir / "curl", "#!/bin/bash\necho 'curl should not be called'\nexit 99\n")

    env = dict(base_env, BAKER_ROLE="clerk-haiku")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "1Password fetch failed" in ctx
    assert "slug=clerk-haiku" in ctx


# ---------------------------------------------------------------------------
# Failure path 5b: Daemon returns auth error JSON ({detail: ...})
# ---------------------------------------------------------------------------

def test_daemon_detail_error_emits_status(stubs_dir, base_env, tmp_path):
    """Daemon returns 401 JSON {detail: 'unauthorized'} → 'daemon error' status, exit 0."""
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'wrong-key'\n")
    _make_stub(
        stubs_dir / "curl",
        '#!/bin/bash\necho \'{"detail": "Unauthorized terminal key"}\'\nexit 0\n',
    )

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "daemon error" in ctx
    assert "Unauthorized" in ctx


# ---------------------------------------------------------------------------
# Happy path: 2 messages drained, state file written atomically
# ---------------------------------------------------------------------------

def test_happy_path_renders_and_writes_state(stubs_dir, base_env, tmp_path):
    """2 messages → rendered preview + state file holds newest created_at."""
    sample = {
        "messages": [
            {
                "id": 100,
                "thread_id": "t-abc",
                "parent_id": None,
                "from_terminal": "lead",
                "to_terminals": ["b2"],
                "topic": "bus/smoke",
                "kind": "dispatch",
                "body_preview": "first message body — short single line.",
                "created_at": "2026-05-11T10:00:00Z",
                "wake_attempted_at": None,
                "acknowledged_at": None,
                "deleted_at": None,
                "tier_required": "B",
            },
            {
                "id": 101,
                "thread_id": "t-abc",
                "parent_id": 100,
                "from_terminal": "lead",
                "to_terminals": ["b2"],
                "topic": "bus/smoke",
                "kind": "dispatch",
                "body_preview": "second message body\nwith\nmultiple\nlines.",
                "created_at": "2026-05-11T10:05:00Z",
                "wake_attempted_at": None,
                "acknowledged_at": "2026-05-11T10:06:00Z",
                "deleted_at": None,
                "tier_required": "B",
            },
        ]
    }
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    _make_stub(stubs_dir / "curl", f"#!/bin/bash\ncat <<'EOF'\n{json.dumps(sample)}\nEOF\nexit 0\n")

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "[bus-drain] 2 unread message(s) for b2" in ctx
    assert "#100" in ctx
    assert "#101" in ctx
    assert "from lead" in ctx
    assert "topic: bus/smoke" in ctx
    # First message body shows on first line; second message multi-line note shows.
    assert "first message body" in ctx
    assert "more line(s)" in ctx  # second message has 3 extra lines
    # ACK + reply hints.
    assert "POST" in ctx and "/ack" in ctx
    assert "bus_post.sh" in ctx
    # INSTALL_TOOLING_FASTFOLLOW_1 FIX 2: reply hint must NOT point at the stale
    # ~/Desktop/baker-code clone (lags origin/main → stale slug list). With
    # HOME=tmp_path, BAKER_ROLE=b2 and no CLAUDE_PROJECT_DIR set, the resolver
    # falls through to the per-role clone path.
    assert "Desktop/baker-code" not in ctx, f"reply hint still points at stale Desktop clone:\n{ctx}"
    assert "bm-b2/scripts/bus_post.sh" in ctx, f"reply hint should name the per-role clone:\n{ctx}"

    # State file exists, atomic-named, holds newest timestamp.
    state_file = tmp_path / ".brisen-lab-bus-last-seen-b2.txt"
    assert state_file.exists(), "state file should have been written"
    assert state_file.read_text().strip() == "2026-05-11T10:05:00Z"

    # No leftover .tmp files in HOME (atomic replace cleans up).
    leftover_tmps = list(tmp_path.glob(".brisen-lab-bus-last-seen-tmp-*"))
    assert leftover_tmps == [], f"leftover tmp files: {leftover_tmps}"

    # V0.3: rendered-ID ledger holds exactly the rendered ids (ack-only-what-renders).
    ledger_file = tmp_path / ".brisen-lab-bus-rendered-b2.txt"
    assert ledger_file.exists(), "rendered-ID ledger should have been written"
    assert ledger_file.read_text().splitlines() == ["100", "101"]


# ---------------------------------------------------------------------------
# FIX 2: reply hint prefers the agent's OWN running clone via CLAUDE_PROJECT_DIR.
# ---------------------------------------------------------------------------

def test_reply_hint_prefers_claude_project_dir(stubs_dir, base_env, tmp_path):
    """When CLAUDE_PROJECT_DIR/scripts/bus_post.sh exists, the reply hint names
    it (the agent's own fresh clone) rather than the stale Desktop clone."""
    clone = tmp_path / "myclone"
    (clone / "scripts").mkdir(parents=True)
    bp = clone / "scripts" / "bus_post.sh"
    _make_stub(bp, "#!/bin/bash\nexit 0\n")

    sample = {
        "messages": [
            {
                "id": 7,
                "thread_id": "t-7",
                "parent_id": None,
                "from_terminal": "lead",
                "to_terminals": ["b2"],
                "topic": "bus/smoke",
                "kind": "dispatch",
                "body_preview": "hello",
                "created_at": "2026-05-11T10:00:00Z",
                "wake_attempted_at": None,
                "acknowledged_at": None,
                "deleted_at": None,
                "tier_required": "B",
            }
        ]
    }
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    _make_stub(stubs_dir / "curl", f"#!/bin/bash\ncat <<'EOF'\n{json.dumps(sample)}\nEOF\nexit 0\n")

    env = dict(base_env, BAKER_ROLE="b2", CLAUDE_PROJECT_DIR=str(clone))
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert f"{clone}/scripts/bus_post.sh" in ctx, f"reply hint should name the running clone:\n{ctx}"
    assert "Desktop/baker-code" not in ctx


# ---------------------------------------------------------------------------
# FIX 2 / G2-F1: even when CLAUDE_PROJECT_DIR *is* the stale Desktop clone,
# the resolver must reject it and fall through to the per-role clone.
# ---------------------------------------------------------------------------

def test_reply_hint_rejects_desktop_clone_as_project_dir(stubs_dir, base_env, tmp_path):
    """CLAUDE_PROJECT_DIR pointing at a ~/Desktop/baker-code clone (the legacy
    AH path, still operational) must NOT be chosen even though its bus_post.sh
    is executable — the resolver skips it and picks the per-role clone."""
    desktop = tmp_path / "Desktop" / "baker-code"
    (desktop / "scripts").mkdir(parents=True)
    _make_stub(desktop / "scripts" / "bus_post.sh", "#!/bin/bash\nexit 0\n")
    # A per-role clone also exists → it must win.
    role_clone = tmp_path / "bm-b2" / "scripts"
    role_clone.mkdir(parents=True)
    _make_stub(role_clone / "bus_post.sh", "#!/bin/bash\nexit 0\n")

    sample = {
        "messages": [
            {
                "id": 9,
                "thread_id": "t-9",
                "parent_id": None,
                "from_terminal": "lead",
                "to_terminals": ["b2"],
                "topic": "bus/smoke",
                "kind": "dispatch",
                "body_preview": "hi",
                "created_at": "2026-05-11T10:00:00Z",
                "wake_attempted_at": None,
                "acknowledged_at": None,
                "deleted_at": None,
                "tier_required": "B",
            }
        ]
    }
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    _make_stub(stubs_dir / "curl", f"#!/bin/bash\ncat <<'EOF'\n{json.dumps(sample)}\nEOF\nexit 0\n")

    env = dict(base_env, BAKER_ROLE="b2", CLAUDE_PROJECT_DIR=str(desktop))
    result = _run_hook(env, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "Desktop/baker-code" not in ctx, f"resolver picked the stale Desktop clone:\n{ctx}"
    assert f"{tmp_path}/bm-b2/scripts/bus_post.sh" in ctx, f"resolver should fall through to per-role clone:\n{ctx}"


# ---------------------------------------------------------------------------
# Happy path 2: state file from previous run is consumed as `since` cursor
# ---------------------------------------------------------------------------

def test_existing_state_file_used_as_since(stubs_dir, base_env, tmp_path):
    """Existing state file → its timestamp passed to curl as ?since=..."""
    state_file = tmp_path / ".brisen-lab-bus-last-seen-b2.txt"
    state_file.write_text("2026-05-10T22:00:00Z")

    # Curl stub captures the URL it was called with into a sentinel file.
    sentinel = tmp_path / "curl-args.txt"
    _make_stub(
        stubs_dir / "curl",
        textwrap.dedent(f"""\
            #!/bin/bash
            # Capture the URL (last positional arg).
            for a in "$@"; do echo "$a"; done > {sentinel}
            echo '{{"messages": []}}'
            exit 0
        """),
    )
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)
    assert result.returncode == 0, result.stderr

    captured = sentinel.read_text()
    assert "since=2026-05-10T22:00:00Z" in captured, captured
    assert "limit=50" in captured, captured  # token-budget fold


# ---------------------------------------------------------------------------
# Regression: overflow path — cursor must advance to rendered slice's max,
# not the full fetched slice's max. Otherwise messages RENDER_CAP+1..N are
# silently lost. Daemon orders ASC by created_at (bus.py:349), so shown[:30]
# are oldest unread; max(shown).created_at = msgs[29].created_at.
# ---------------------------------------------------------------------------

def test_overflow_cursor_advances_to_rendered_max(stubs_dir, base_env, tmp_path):
    """40 messages → cursor lands on msgs[29] (rendered slice's max),
    NOT msgs[39] (full slice's max). Guards against silent loss of 31-40."""
    sample = {
        "messages": [
            {
                "id": i,
                "thread_id": f"t-{i}",
                "parent_id": None,
                "from_terminal": "lead",
                "to_terminals": ["b2"],
                "topic": None,
                "kind": "broadcast",
                "body_preview": f"msg {i}",
                "created_at": f"2026-05-11T01:{i:02d}:00Z",
                "wake_attempted_at": None,
                "acknowledged_at": None,
                "deleted_at": None,
                "tier_required": "B",
            }
            for i in range(40)
        ]
    }
    _make_stub(stubs_dir / "op", "#!/bin/bash\necho 'fake-key-1234'\n")
    _make_stub(stubs_dir / "curl", f"#!/bin/bash\ncat <<'EOF'\n{json.dumps(sample)}\nEOF\nexit 0\n")

    env = dict(base_env, BAKER_ROLE="b2")
    result = _run_hook(env, tmp_path)
    assert result.returncode == 0, result.stderr

    state_file = tmp_path / ".brisen-lab-bus-last-seen-b2.txt"
    assert state_file.exists(), "state file should have been written"
    cursor = state_file.read_text().strip()
    # RENDER_CAP=30 → shown = msgs[:30] → max(shown) = msgs[29]
    assert cursor == "2026-05-11T01:29:00Z", (
        f"cursor should be msgs[29] (rendered slice's max), got {cursor!r}"
    )
    # Negative guard: cursor must NOT be msgs[39] (full slice's max — would
    # silently lose messages 30-39 on next drain).
    assert cursor != "2026-05-11T01:39:00Z"

    # V0.3: ledger holds ONLY the 30 rendered ids — elided 30-39 must NOT be
    # eligible for turn-end auto-ack (they were never seen).
    ledger_file = tmp_path / ".brisen-lab-bus-rendered-b2.txt"
    assert ledger_file.exists(), "rendered-ID ledger should have been written"
    ledger_ids = ledger_file.read_text().splitlines()
    assert ledger_ids == [str(i) for i in range(30)], ledger_ids


# ---------------------------------------------------------------------------
# Drift detection: deployed user-global hook matches the repo fixture.
# Skipped on machines without ~/.claude/hooks/session-start-bus-drain.sh
# (e.g. CI). Director's Mac runs this test post-deploy to catch drift.
# ---------------------------------------------------------------------------

def test_user_global_matches_repo():
    if not USER_GLOBAL_HOOK.exists():
        pytest.skip(
            f"user-global hook not deployed at {USER_GLOBAL_HOOK} "
            "(expected on CI; Director ratifies cp pre-merge)"
        )
    fixture_bytes = HOOK_FIXTURE.read_bytes()
    deployed_bytes = USER_GLOBAL_HOOK.read_bytes()
    assert fixture_bytes == deployed_bytes, (
        "drift detected: ~/.claude/hooks/session-start-bus-drain.sh differs from "
        "tests/fixtures/session-start-bus-drain.sh — re-run "
        "`cp tests/fixtures/session-start-bus-drain.sh ~/.claude/hooks/session-start-bus-drain.sh`"
    )
