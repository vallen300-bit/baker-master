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
