"""Ship gate for BRIEF_APSCHEDULER_VAULT_SCANNER_V1.

Covers all 8 scenarios from the brief §Test plan, literal pytest only —
no "by inspection". DB calls are stubbed via monkeypatch; Slack calls
are stubbed too. Filesystem state is built under a tmp_path BAKER_VAULT_PATH.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Build a tmp baker-vault layout + point BAKER_VAULT_PATH at it."""
    vault_root = tmp_path / "baker-vault"
    agents = vault_root / "_ops" / "agents"
    agents.mkdir(parents=True)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault_root))
    return {"root": vault_root, "agents": agents, "tmp_path": tmp_path}


@pytest.fixture
def stub_slack(monkeypatch):
    """Stub outputs.slack_notifier.post_to_channel — collect calls; return True."""
    calls: list[tuple[str, str]] = []

    def fake_post(channel_id, text, **kwargs):
        calls.append((channel_id, text))
        return True

    import outputs.slack_notifier as sn
    monkeypatch.setattr(sn, "post_to_channel", fake_post)
    return calls


@pytest.fixture
def no_db(monkeypatch):
    """Stub models.deadlines.get_conn → None (so _query_deadlines returns [])."""
    import models.deadlines as dl
    monkeypatch.setattr(dl, "get_conn", lambda: None)
    monkeypatch.setattr(dl, "put_conn", lambda conn: None)


def _make_desk(agents: Path, desk: str) -> Path:
    d = agents / desk / "tasks" / "active"
    d.mkdir(parents=True)
    return agents / desk


def _write_task(desk_dir: Path, slug: str, **fm) -> Path:
    """Write a vault task file with YAML frontmatter."""
    active = desk_dir / "tasks" / "active"
    p = active / f"{slug}.md"
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, date) and not isinstance(v, datetime):
            lines.append(f"{k}: {v.isoformat()}")
        elif v is None:
            lines.append(f"{k}: null")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {fm.get('title', slug)}")
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Empty vault — no desks have tasks/active/
# ---------------------------------------------------------------------------
def test_1_empty_vault(vault, no_db, stub_slack):
    from triggers.vault_scanner import run_scan
    result = run_scan()
    assert result["desks_scanned"] == []
    assert result["files_written"] == []
    assert result["consolidated_dm_sent"] is False
    assert stub_slack == []  # no Slack call
    # No marker should be written because no DM was sent
    state = vault["agents"] / "_scanner-state"
    if state.exists():
        markers = [p for p in state.iterdir() if p.name.startswith("last-run-")]
        assert markers == []


# ---------------------------------------------------------------------------
# 2. MOHG task only — parse frontmatter, write today file, send 1 DM
# ---------------------------------------------------------------------------
def test_2_mohg_task_writes_today_and_sends_dm(vault, no_db, stub_slack):
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(
        desk_dir, slug="2026-05-13-mohg-debrief",
        title="MOHG residence-fee debrief", due=today, priority="normal",
    )
    result = run_scan()
    assert "movie-desk" in result["desks_scanned"]
    # Today file + stable today.md + upcoming-deadlines.md all written
    today_path = desk_dir / f"today-{today.isoformat()}.md"
    stable_path = desk_dir / "today.md"
    upcoming_path = desk_dir / "upcoming-deadlines.md"
    assert today_path.exists()
    assert stable_path.exists()
    assert upcoming_path.exists()
    # ONE consolidated DM sent
    assert result["consolidated_dm_sent"] is True
    assert len(stub_slack) == 1
    channel, body = stub_slack[0]
    assert channel == "D0AFY28N030"
    assert "movie-desk" in body
    assert "Daily digest" in body


# ---------------------------------------------------------------------------
# 3. Malformed frontmatter — scanner logs warning, skips file, continues
# ---------------------------------------------------------------------------
def test_3_malformed_frontmatter_skipped(vault, no_db, stub_slack, caplog):
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    # One good task
    _write_task(
        desk_dir, slug="good-task",
        title="Good", due=today, priority="normal",
    )
    # One bad task — frontmatter with malformed YAML
    bad = desk_dir / "tasks" / "active" / "bad-task.md"
    bad.write_text("---\nthis: is: not: valid: yaml: at all\n  - bad indent\n---\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="sentinel.vault_scanner"):
        result = run_scan()
    assert "movie-desk" in result["desks_scanned"]
    # At least one WARNING log mentions bad-task or YAML
    assert any(
        ("bad-task" in r.message or "frontmatter" in r.message or "YAML" in r.message)
        for r in caplog.records
    )
    # Today file still written for the good task
    today_path = desk_dir / f"today-{today.isoformat()}.md"
    assert today_path.exists()


# ---------------------------------------------------------------------------
# 4. Overdue critical — triggers urgent per-desk DM in addition to consolidated
# ---------------------------------------------------------------------------
def test_4_overdue_critical_triggers_urgent_dm(vault, no_db, stub_slack):
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    _write_task(
        desk_dir, slug="critical-overdue",
        title="Critical overdue task", due=yesterday, priority="critical",
    )
    result = run_scan()
    assert "movie-desk" in result["urgent_dms_sent"]
    # 2 Slack calls: consolidated + urgent
    assert len(stub_slack) == 2
    bodies = [b for (_c, b) in stub_slack]
    urgent_body = next((b for b in bodies if "URGENT" in b), None)
    assert urgent_body is not None
    assert "movie-desk" in urgent_body
    assert "critical-overdue" in urgent_body


# ---------------------------------------------------------------------------
# 5. Rate cap — second scan in same UTC day does NOT send another consolidated DM
# ---------------------------------------------------------------------------
def test_5_rate_cap_blocks_second_consolidated_dm(vault, no_db, stub_slack):
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(
        desk_dir, slug="task-1",
        title="Task 1", due=today, priority="normal",
    )
    r1 = run_scan()
    r2 = run_scan()
    assert r1["consolidated_dm_sent"] is True
    assert r2["consolidated_dm_sent"] is False
    # Only ONE Slack call across both runs
    assert len(stub_slack) == 1


# ---------------------------------------------------------------------------
# 6. Marker file — exists after successful scan; old markers pruned
# ---------------------------------------------------------------------------
def test_6_marker_file_and_prune(vault, no_db, stub_slack):
    from triggers.vault_scanner import run_scan, MARKER_PRUNE_DAYS
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(
        desk_dir, slug="t",
        title="T", due=today, priority="normal",
    )
    # Pre-seed an OLD marker (older than prune cutoff)
    state = vault["agents"] / "_scanner-state"
    state.mkdir(parents=True, exist_ok=True)
    old_date = today - timedelta(days=MARKER_PRUNE_DAYS + 3)
    old_marker = state / f"last-run-{old_date.isoformat()}.marker"
    old_marker.touch()
    # Also a recent marker (5 days old — should survive)
    recent_date = today - timedelta(days=3)
    recent_marker = state / f"last-run-{recent_date.isoformat()}.marker"
    recent_marker.touch()
    run_scan()
    # Today marker exists
    today_marker = state / f"last-run-{today.isoformat()}.marker"
    assert today_marker.exists()
    # Old marker pruned, recent survived
    assert not old_marker.exists()
    assert recent_marker.exists()


# ---------------------------------------------------------------------------
# 7. Idempotent restart — call scanner twice in same call window
# ---------------------------------------------------------------------------
def test_7_idempotent_double_call(vault, no_db, stub_slack):
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(
        desk_dir, slug="task-x",
        title="X", due=today, priority="normal",
    )
    run_scan()
    run_scan()
    # Rate cap respected: still only one consolidated DM
    assert len(stub_slack) == 1


# ---------------------------------------------------------------------------
# 8. DB unavailable — scanner still processes vault tasks, writes today files,
# sends DM (degraded but not dead)
# ---------------------------------------------------------------------------
def test_8_db_unavailable_degrades_gracefully(vault, stub_slack, monkeypatch):
    # Force get_conn → None to simulate DB outage
    import models.deadlines as dl
    monkeypatch.setattr(dl, "get_conn", lambda: None)
    monkeypatch.setattr(dl, "put_conn", lambda conn: None)
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(
        desk_dir, slug="task-degraded",
        title="Degraded", due=today, priority="normal",
    )
    result = run_scan()
    # Today file written despite DB down
    today_path = desk_dir / f"today-{today.isoformat()}.md"
    assert today_path.exists()
    # No "Hard deadlines" section since deadline rows were empty
    body = today_path.read_text(encoding="utf-8")
    assert "Hard deadlines" not in body
    # Consolidated DM still sent
    assert result["consolidated_dm_sent"] is True
    assert len(stub_slack) == 1


# ---------------------------------------------------------------------------
# Path-traversal hardening (extra coverage for /security-review gate)
# ---------------------------------------------------------------------------
def test_path_traversal_symlinked_desk_rejected(vault, no_db, stub_slack):
    """Symlinked desk directory must be rejected, not followed."""
    from triggers.vault_scanner import run_scan
    # Real desk outside the agents/ tree
    outside = vault["tmp_path"] / "outside-desk"
    (outside / "tasks" / "active").mkdir(parents=True)
    today = datetime.now(timezone.utc).date()
    _write_task(outside, slug="evil", title="Evil", due=today, priority="normal")
    # Symlink inside agents/ pointing at it
    link = vault["agents"] / "evil-desk"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this filesystem")
    result = run_scan()
    # Symlinked desk should NOT appear in desks_scanned
    assert "evil-desk" not in result["desks_scanned"]


def test_path_traversal_dotdot_desk_rejected(vault, no_db, stub_slack):
    """A desk name with disallowed characters is silently skipped."""
    from triggers.vault_scanner import _discover_desks, _agents_dir
    # listdir-returned name with disallowed chars wouldn't be a directory anyway;
    # exercise the regex gate directly via _is_safe_desk_dir
    from triggers.vault_scanner import _is_safe_desk_dir
    assert _is_safe_desk_dir(vault["agents"], "movie..desk") is False
    assert _is_safe_desk_dir(vault["agents"], "Movie-Desk") is False  # uppercase rejected
    assert _is_safe_desk_dir(vault["agents"], "movie/desk") is False  # slash rejected


# ===========================================================================
# UPDATE 2026-05-13 — architecture-review amendments A-E
# ===========================================================================

@pytest.fixture
def fake_db(monkeypatch):
    """Stub get_conn/put_conn with a recording fake connection.

    Captures every (sql, params) tuple in ``calls`` and lets the test
    pre-load results via ``add_result(rows)`` (FIFO queue). Each cursor
    fetchone/fetchall pops one queued result. Returns the controller dict
    so tests can both seed and inspect.
    """
    calls: list[tuple[str, tuple]] = []
    results: list = []
    last_rowid = {"v": 100}

    class _Cur:
        def __init__(self):
            self._last_row: object = None
            self._last_rows: list = []

        def execute(self, sql, params=()):
            calls.append((sql, tuple(params) if params else ()))
            if "INSERT INTO scanner_run_log" in sql:
                last_rowid["v"] += 1
                self._last_row = (last_rowid["v"],)
                self._last_rows = [self._last_row]
                return
            if results:
                rows = results.pop(0)
                self._last_rows = list(rows)
                self._last_row = rows[0] if rows else None
            else:
                self._last_rows = []
                self._last_row = None

        def fetchone(self):
            return self._last_row

        def fetchall(self):
            return list(self._last_rows)

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

        def rollback(self):
            pass

    import models.deadlines as dl
    monkeypatch.setattr(dl, "get_conn", lambda: _Conn())
    monkeypatch.setattr(dl, "put_conn", lambda conn: None)

    def add_result(rows):
        results.append(rows)

    return {"calls": calls, "add_result": add_result, "last_rowid": last_rowid}


# Test 9 — scanner_run_log INSERT happens at end of successful run
def test_9_scanner_run_log_row_on_success(vault, fake_db, stub_slack):
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(desk_dir, slug="t", title="T", due=today, priority="normal")
    # Pre-load: query_deadlines (per-desk), unassigned query, empty_streak query
    fake_db["add_result"]([])  # deadlines for movie-desk
    fake_db["add_result"]([])  # _unassigned
    # streak query won't run because tasks_found > 0
    result = run_scan()
    assert result["consolidated_dm_sent"] is True
    assert result["scanner_run_log_id"] is not None
    insert_calls = [c for c in fake_db["calls"] if "INSERT INTO scanner_run_log" in c[0]]
    assert len(insert_calls) == 1
    params = insert_calls[0][1]
    # (desks_scanned, tasks_found, deadlines_found, dm_sent, dm_error_msg, error_count, notes)
    assert params[0] == 1                # desks_scanned
    assert params[1] >= 1                # tasks_found
    assert params[2] == 0                # deadlines_found (DB returned [])
    assert params[3] is True             # dm_sent
    assert params[4] is None             # dm_error_msg
    assert params[5] == 0                # error_count


# Test 10 — scanner_run_log row records DM failure
def test_10_scanner_run_log_row_on_dm_failure(vault, fake_db, monkeypatch):
    # Stub slack to FAIL
    import outputs.slack_notifier as sn
    monkeypatch.setattr(sn, "post_to_channel", lambda *a, **kw: False)
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(desk_dir, slug="t", title="T", due=today, priority="normal")
    fake_db["add_result"]([])  # deadlines
    fake_db["add_result"]([])  # _unassigned
    result = run_scan()
    assert result["consolidated_dm_sent"] is False
    assert result["dm_error_msg"] is not None
    insert_calls = [c for c in fake_db["calls"] if "INSERT INTO scanner_run_log" in c[0]]
    assert len(insert_calls) == 1
    params = insert_calls[0][1]
    assert params[3] is False            # dm_sent
    assert params[4] is not None         # dm_error_msg populated
    assert params[5] >= 1                # error_count incremented
    # last-error file written to _scanner-state/
    state = vault["agents"] / "_scanner-state"
    err_files = list(state.glob("last-error-*.txt"))
    assert len(err_files) == 1


# Test 11 — empty-streak sentinel fires at exactly threshold, idempotent across same streak
def test_11_empty_streak_sentinel_one_shot(vault, fake_db, stub_slack):
    """When the empty-streak query returns >= threshold rows in the prior
    window, sentinel fires once. Subsequent identical streaks (count grows
    past threshold) do NOT re-fire.
    """
    from triggers.vault_scanner import (
        run_scan, EMPTY_STREAK_THRESHOLD,
    )
    _make_desk(vault["agents"], "movie-desk")  # empty (no tasks)

    # First run — pre-load: deadlines [], _unassigned [], streak query.
    # Streak query runs AFTER scanner_run_log INSERT, so the just-inserted
    # current run shows up first in DESC order. Seed: THRESHOLD empty rows
    # (this run + prior empties) + 1 non-empty row that broke the prior
    # streak. _empty_streak_count walks newest-first, breaks at non-empty,
    # returns exactly THRESHOLD → sentinel fires.
    fake_db["add_result"]([])  # per-desk deadlines
    fake_db["add_result"]([])  # _unassigned
    empties = [(0, 0, 0)] * EMPTY_STREAK_THRESHOLD
    fake_db["add_result"](empties + [(1, 0, 0)])
    r1 = run_scan()
    assert r1["empty_streak_sentinel_sent"] is True

    # Clear day marker to allow a 2nd scan to send consolidated DM in same UTC day
    marker = vault["agents"] / "_scanner-state" / f"last-run-{datetime.now(timezone.utc).date().isoformat()}.marker"
    if marker.exists():
        marker.unlink()

    # Second run — same streak, but now LIMIT-4 returns more than THRESHOLD
    # contiguous empties → streak == THRESHOLD+1 → sentinel does NOT re-fire.
    fake_db["add_result"]([])  # per-desk deadlines
    fake_db["add_result"]([])  # _unassigned
    over_threshold = [(0, 0, 0)] * (EMPTY_STREAK_THRESHOLD + 1)
    fake_db["add_result"](over_threshold)
    r2 = run_scan()
    assert r2["empty_streak_sentinel_sent"] is False


# Test 12 — today-*.md pruning: 120 dated files reduced to 90 most-recent
def test_12_today_files_prune_90_day_retention(vault, no_db, stub_slack):
    from triggers.vault_scanner import run_scan, TODAY_FILE_RETENTION_DAYS
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    # Create 120 dated files: days 0..119 in the past
    for i in range(120):
        d = today - timedelta(days=i)
        p = desk_dir / f"today-{d.isoformat()}.md"
        p.write_text(f"---\ngenerated: {d}\n---\n", encoding="utf-8")
    # Sanity: 120 files exist
    pre = list(desk_dir.glob("today-*.md"))
    assert len(pre) == 120
    # No tasks to avoid generating a new today file inside the test (would push to 121)
    # Run scan triggers prune at top
    run_scan()
    post = list(desk_dir.glob("today-*.md"))
    # files older than TODAY_FILE_RETENTION_DAYS removed; today's file kept
    # files at days 0..TODAY_FILE_RETENTION_DAYS-1 survive (i.e. TODAY_FILE_RETENTION_DAYS files)
    assert len(post) == TODAY_FILE_RETENTION_DAYS
    # Verify the oldest surviving is exactly (TODAY_FILE_RETENTION_DAYS - 1) days ago
    oldest_keep = today - timedelta(days=TODAY_FILE_RETENTION_DAYS - 1)
    assert (desk_dir / f"today-{oldest_keep.isoformat()}.md").exists()
    # And the cutoff day itself is pruned
    pruned_day = today - timedelta(days=TODAY_FILE_RETENTION_DAYS)
    assert not (desk_dir / f"today-{pruned_day.isoformat()}.md").exists()


# Test 13 — _unassigned deadlines bucket appears in DM when assigned_to IS NULL rows exist
def test_13_unassigned_bucket_in_dm(vault, fake_db, stub_slack):
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(desk_dir, slug="t", title="T", due=today, priority="normal")
    fake_db["add_result"]([])  # per-desk deadlines
    # _unassigned query returns 2 rows — one overdue, one due this week
    fake_db["add_result"]([
        (901, "Unassigned overdue deadline", datetime.now(timezone.utc) - timedelta(days=2),
         "high", "firm", None, None, None, False),
        (902, "Unassigned due-this-week deadline", datetime.now(timezone.utc) + timedelta(days=3),
         "normal", "firm", "mo-vie", None, None, False),
    ])
    result = run_scan()
    assert result["consolidated_dm_sent"] is True
    assert len(stub_slack) == 1
    _channel, body = stub_slack[0]
    assert "_unassigned" in body
    assert "without desk attribution" in body
    assert "Overdue: 1" in body or "Overdue: 1\n" in body
    # _unassigned rows counted toward deadlines_found in scanner_run_log
    insert_calls = [c for c in fake_db["calls"] if "INSERT INTO scanner_run_log" in c[0]]
    assert len(insert_calls) == 1
    params = insert_calls[0][1]
    assert params[2] >= 2  # deadlines_found includes the 2 _unassigned rows


# Test 14 — Amendment D recovery prefix on next-successful run, then cleared
def test_14_recovery_prefix_then_cleared(vault, fake_db, stub_slack):
    """If a last-error-YYYY-MM-DD.txt exists in _scanner-state/ from a recent
    failed run, the NEXT successful consolidated DM is prefixed and the
    error files are deleted afterwards.
    """
    from triggers.vault_scanner import run_scan
    desk_dir = _make_desk(vault["agents"], "movie-desk")
    today = datetime.now(timezone.utc).date()
    _write_task(desk_dir, slug="t", title="T", due=today, priority="normal")
    # Pre-seed a last-error file from yesterday
    state = vault["agents"] / "_scanner-state"
    state.mkdir(parents=True, exist_ok=True)
    err_path = state / f"last-error-{(today - timedelta(days=1)).isoformat()}.txt"
    err_path.write_text("2026-05-12T06:00:00+00:00\nTimeout: connection closed\n", encoding="utf-8")
    fake_db["add_result"]([])  # per-desk deadlines
    fake_db["add_result"]([])  # _unassigned
    result = run_scan()
    assert result["consolidated_dm_sent"] is True
    assert result["recovery_prefix_applied"] is True
    _channel, body = stub_slack[0]
    assert "Previous" in body and "send errors" in body
    # error file cleared
    assert not err_path.exists()
