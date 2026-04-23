"""Ship gate for BRIEF_AI_HEAD_WEEKLY_AUDIT_1.

Covers:
  1. Module imports cleanly (registered scheduler + job wrapper)
  2. run_weekly_audit() composes a plain-text ≤3-line summary with no
     markdown tokens (iPhone-safe)
  3. Drift classification: OPERATING >7d old → flagged; LONGTERM <30d
     old → not flagged
  4. Non-fatal on Slack failure: returns a result dict, writes a PG row
     (mocked), and does NOT raise
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _fresh_operating() -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "---\nupdated: " + today + "\n---\n\n"
        "# AI Head — Operating Memory\n\n"
        "Last touched " + today + ".\n\n"
        "## Standing Tier A\n"
        "- PR merges on B2 APPROVE + green CI\n"
        "- Mailbox dispatches\n"
    )


def _stale_operating() -> str:
    stale = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
    return (
        "---\nupdated: " + stale + "\n---\n\n"
        "# AI Head — Operating Memory\n\n"
        "Last touched " + stale + ".\n\n"
        "## Standing Tier A\n"
        "- Old entry from " + stale + "\n"
    )


def _fresh_longterm() -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return "---\nupdated: " + today + "\n---\n\n# Longterm\n"


def _archive() -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "---\ntype: ops\n---\n\n# Archive\n\n"
        "## Session 1 — " + today + "\n\n"
        "**Lessons / will change:**\n"
        "- Always pull-rebase before push\n"
        "- Always verify column names against information_schema\n"
    )


def test_module_imports():
    from triggers import ai_head_audit  # noqa: F401
    from triggers.embedded_scheduler import _ai_head_weekly_audit_job  # noqa: F401


def test_summary_is_plain_text_three_lines_max():
    from triggers.ai_head_audit import _compose_summary
    s = _compose_summary(
        drift_items=[{"category": "x", "file": "y", "detail": "z"}],
        lesson_patterns=[{"pattern": "a", "count": 3}],
        mirror_info={"stale": False},
    )
    assert "**" not in s
    assert "```" not in s
    assert s.count("\n") <= 2  # ≤3 lines
    assert "audit" in s.lower()


def test_fresh_operating_yields_no_operating_stale_flag():
    from triggers.ai_head_audit import _classify_drift
    now = datetime.now(timezone.utc)
    items = _classify_drift(
        operating_content=_fresh_operating(),
        longterm_content=_fresh_longterm(),
        archive_content=_archive(),
        reference_now=now,
    )
    assert not any(i["category"] == "operating_stale" for i in items)
    assert not any(i["category"] == "longterm_stale" for i in items)


def test_stale_operating_yields_flag():
    from triggers.ai_head_audit import _classify_drift
    now = datetime.now(timezone.utc)
    items = _classify_drift(
        operating_content=_stale_operating(),
        longterm_content=_fresh_longterm(),
        archive_content=_archive(),
        reference_now=now,
    )
    assert any(i["category"] == "operating_stale" for i in items)


def test_run_weekly_audit_is_non_fatal_on_slack_failure():
    """End-to-end non-fatal path: mock everything except the logic itself."""
    vault_mirror_mock = MagicMock()
    vault_mirror_mock.mirror_status.return_value = {
        "vault_mirror_last_pull": datetime.now(timezone.utc).isoformat(),
        "vault_mirror_commit_sha": "abc123",
    }
    vault_mirror_mock.read_ops_file.side_effect = lambda p: {
        "content_utf8": _fresh_operating()
        if p.endswith("OPERATING.md") else
        _fresh_longterm() if p.endswith("LONGTERM.md") else _archive()
    }
    sys.modules["vault_mirror"] = vault_mirror_mock

    store_instance = MagicMock()
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    cur_mock.fetchone.return_value = (42,)
    conn_mock.cursor.return_value = cur_mock
    store_instance._get_conn.return_value = conn_mock
    store_instance._put_conn = MagicMock()
    store_class_mock = MagicMock()
    store_class_mock._get_global_instance.return_value = store_instance
    store_back_mock = MagicMock()
    store_back_mock.SentinelStoreBack = store_class_mock
    sys.modules["memory.store_back"] = store_back_mock

    slack_notifier_mock = MagicMock()
    slack_notifier_mock.post_to_channel.return_value = False
    sys.modules["outputs.slack_notifier"] = slack_notifier_mock

    config_mock = MagicMock()
    config_mock.config.slack.cockpit_channel_id = "C0AF4FVN3FB"
    sys.modules["config.settings"] = config_mock

    from triggers.ai_head_audit import run_weekly_audit
    result = run_weekly_audit()

    assert result["record_id"] == 42
    assert result["slack_cockpit_ok"] is False
    assert result["slack_dm_ok"] is False

    assert slack_notifier_mock.post_to_channel.call_count == 2


def test_ship_gate_verifies_scheduler_registration():
    """Static check: scheduler file references the audit job."""
    from pathlib import Path
    src = Path("triggers/embedded_scheduler.py").read_text()
    assert "ai_head_weekly_audit" in src
    assert 'CronTrigger(day_of_week="mon"' in src
    assert 'timezone="UTC"' in src
    assert "_ai_head_weekly_audit_job" in src
