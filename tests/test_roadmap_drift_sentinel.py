"""Ship gate for ROADMAP_DRIFT_CLICKUP_SENTINEL_1.

Covers brief §"Test plan":
  (a) <5 PRs, no drift, no ClickUp write
  (b) >=5 PRs (combined across both repos), drift, ClickUp write fired
  (c) GitHub API failure -> graceful no-op + log, no ClickUp write
  (d) ClickUp API failure -> log error but return cleanly (don't crash)

Plus:
  * format_drift_comment shape (deterministic snapshot of the body)
  * advisory_lock contention -> "skipped" status (no fetch, no write)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# --- Fixtures --------------------------------------------------------------


def _store_with_lock(got_lock: bool) -> MagicMock:
    """Mock SentinelStoreBack that returns a conn whose advisory_lock query
    yields ``got_lock``."""
    cur = MagicMock()
    cur.fetchone.return_value = [bool(got_lock)]
    conn = MagicMock()
    conn.cursor.return_value = cur
    store = MagicMock()
    store._get_conn.return_value = conn
    return store


def _gh_response(json_payload, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_payload
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def _commit_payload(ts: str = "2026-04-25T12:00:00Z", sha: str = "abc1234567") -> list:
    return [
        {
            "sha": sha,
            "commit": {"committer": {"date": ts}},
        }
    ]


def _pr(number: int, title: str, merged_at: str | None) -> dict:
    return {"number": number, "title": title, "merged_at": merged_at}


# --- Pure helpers ----------------------------------------------------------


def test_format_drift_comment_deterministic_shape():
    from orchestrator.roadmap_drift_sentinel import format_drift_comment

    yaml_dt = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 4, 30, 6, 0, tzinfo=timezone.utc)
    vault_prs = [{"number": 9, "title": "seed hagenauer-rg7"}]
    master_prs = [
        {"number": 75, "title": "phase5 idempotency"},
        {"number": 76, "title": "another"},
    ]

    body = format_drift_comment(
        yaml_dt, "abc1234", vault_prs, master_prs, now=now
    )

    assert "Drift detected 2026-04-30 06:00 UTC." in body
    assert "YAML last edit: 2026-04-25 12:00 UTC on abc1234" in body
    assert "- baker-vault:" in body
    assert "  - #9 seed hagenauer-rg7" in body
    assert "- baker-master:" in body
    assert "  - #75 phase5 idempotency" in body
    assert "  - #76 another" in body
    assert "Total: 3 PRs without YAML update." in body


def test_format_drift_comment_handles_empty_repo_list():
    from orchestrator.roadmap_drift_sentinel import format_drift_comment

    yaml_dt = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 4, 30, 6, 0, tzinfo=timezone.utc)

    body = format_drift_comment(
        yaml_dt, "abc1234", [], [{"number": 1, "title": "x"}], now=now
    )

    assert "- baker-vault:\n  (none)" in body
    assert "- baker-master:\n  - #1 x" in body
    assert "Total: 1 PRs without YAML update." in body


# --- Case (a): no drift ----------------------------------------------------


def test_run_no_drift_below_threshold():
    """Case (a): 4 PRs (< threshold of 5) → no drift, no ClickUp write."""
    from orchestrator import roadmap_drift_sentinel as mod

    yaml_ts = "2026-04-25T12:00:00Z"
    # 4 PRs total (2 vault + 2 master) — below threshold of 5
    vault_pulls = [
        _pr(101, "vault-a", "2026-04-26T10:00:00Z"),
        _pr(102, "vault-b", "2026-04-27T10:00:00Z"),
    ]
    master_pulls = [
        _pr(201, "master-a", "2026-04-28T10:00:00Z"),
        _pr(202, "master-b", "2026-04-29T10:00:00Z"),
    ]

    def _fake_get(url, **kwargs):
        if "/commits" in url:
            return _gh_response(_commit_payload(yaml_ts))
        if "baker-vault/pulls" in url:
            return _gh_response(vault_pulls)
        if "baker-master/pulls" in url:
            return _gh_response(master_pulls)
        return _gh_response([])

    post_comment_mock = MagicMock()

    with patch.object(mod.httpx, "get", side_effect=_fake_get), patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=_store_with_lock(True),
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=MagicMock(post_comment=post_comment_mock),
    ):
        result = mod.run_roadmap_drift_sentinel()

    assert result["status"] == "no_drift"
    assert result["pr_count"] == 4
    assert result["comment_posted"] is False
    post_comment_mock.assert_not_called()


# --- Case (b): drift detected, comment written ----------------------------


def test_run_drift_writes_clickup_comment():
    """Case (b): >=5 PRs combined → drift, ClickUp comment posted."""
    from orchestrator import roadmap_drift_sentinel as mod

    yaml_ts = "2026-04-25T12:00:00Z"
    # 6 PRs total — over threshold
    vault_pulls = [
        _pr(101, "vault-a", "2026-04-26T10:00:00Z"),
        _pr(102, "vault-b", "2026-04-27T10:00:00Z"),
        _pr(103, "closed-not-merged", None),  # closed but not merged — must be ignored
    ]
    master_pulls = [
        _pr(201, "master-a", "2026-04-28T10:00:00Z"),
        _pr(202, "master-b", "2026-04-28T11:00:00Z"),
        _pr(203, "master-c", "2026-04-29T10:00:00Z"),
        _pr(204, "master-d", "2026-04-29T11:00:00Z"),
        _pr(205, "older-than-yaml", "2026-04-20T10:00:00Z"),  # before YAML edit → ignored
    ]

    def _fake_get(url, **kwargs):
        if "/commits" in url:
            return _gh_response(_commit_payload(yaml_ts))
        if "baker-vault/pulls" in url:
            return _gh_response(vault_pulls)
        if "baker-master/pulls" in url:
            return _gh_response(master_pulls)
        return _gh_response([])

    post_comment_mock = MagicMock(return_value={"id": "comment-xyz"})

    with patch.object(mod.httpx, "get", side_effect=_fake_get), patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=_store_with_lock(True),
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=MagicMock(post_comment=post_comment_mock),
    ):
        result = mod.run_roadmap_drift_sentinel()

    assert result["status"] == "drift"
    # 2 vault (closed-not-merged ignored) + 4 master (older-than-yaml ignored) = 6
    assert result["pr_count"] == 6
    assert result["comment_posted"] is True
    post_comment_mock.assert_called_once()
    args, _ = post_comment_mock.call_args
    assert args[0] == mod.DRIFT_TASK_ID
    body = args[1]
    assert "Drift detected" in body
    assert "Total: 6 PRs without YAML update." in body
    # Verify out-of-window items are absent
    assert "older-than-yaml" not in body
    assert "closed-not-merged" not in body


# --- Case (c): GitHub failure ---------------------------------------------


def test_run_yaml_fetch_failure_no_clickup_write():
    """Case (c) variant 1: YAML commit-list fetch fails -> graceful no-op."""
    from orchestrator import roadmap_drift_sentinel as mod

    def _fake_get(url, **kwargs):
        # Every GET raises a network error
        raise mod.httpx.ConnectError("simulated DNS failure")

    post_comment_mock = MagicMock()

    with patch.object(mod.httpx, "get", side_effect=_fake_get), patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=_store_with_lock(True),
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=MagicMock(post_comment=post_comment_mock),
    ):
        result = mod.run_roadmap_drift_sentinel()

    assert result["status"] == "yaml_fetch_failed"
    assert result["comment_posted"] is False
    post_comment_mock.assert_not_called()


def test_run_pr_fetch_failure_no_clickup_write():
    """Case (c) variant 2: YAML fetch OK, but PR list fails -> no write."""
    from orchestrator import roadmap_drift_sentinel as mod

    yaml_ts = "2026-04-25T12:00:00Z"

    def _fake_get(url, **kwargs):
        if "/commits" in url:
            return _gh_response(_commit_payload(yaml_ts))
        # PR endpoints fail (502)
        return _gh_response([], status=502)

    post_comment_mock = MagicMock()

    with patch.object(mod.httpx, "get", side_effect=_fake_get), patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=_store_with_lock(True),
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=MagicMock(post_comment=post_comment_mock),
    ):
        result = mod.run_roadmap_drift_sentinel()

    assert result["status"] == "pr_fetch_failed"
    assert result["comment_posted"] is False
    post_comment_mock.assert_not_called()


# --- Case (d): ClickUp failure --------------------------------------------


def test_run_clickup_post_failure_does_not_crash():
    """Case (d): drift detected, ClickUp post returns None -> logged failure,
    runner returns cleanly with comment_posted=False (no exception)."""
    from orchestrator import roadmap_drift_sentinel as mod

    yaml_ts = "2026-04-25T12:00:00Z"
    master_pulls = [
        _pr(n, f"master-{n}", "2026-04-29T10:00:00Z") for n in range(1, 7)
    ]

    def _fake_get(url, **kwargs):
        if "/commits" in url:
            return _gh_response(_commit_payload(yaml_ts))
        if "baker-vault/pulls" in url:
            return _gh_response([])
        if "baker-master/pulls" in url:
            return _gh_response(master_pulls)
        return _gh_response([])

    # post_comment returns None on HTTP error per ClickUpClient contract
    post_comment_mock = MagicMock(return_value=None)

    with patch.object(mod.httpx, "get", side_effect=_fake_get), patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=_store_with_lock(True),
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=MagicMock(post_comment=post_comment_mock),
    ):
        result = mod.run_roadmap_drift_sentinel()

    assert result["status"] == "drift"
    assert result["pr_count"] == 6
    assert result["comment_posted"] is False
    post_comment_mock.assert_called_once()


def test_run_clickup_post_raises_does_not_crash():
    """Case (d) bonus: post_comment raises -> caught, returner reports
    comment_posted=False without re-raising."""
    from orchestrator import roadmap_drift_sentinel as mod

    yaml_ts = "2026-04-25T12:00:00Z"
    master_pulls = [
        _pr(n, f"master-{n}", "2026-04-29T10:00:00Z") for n in range(1, 7)
    ]

    def _fake_get(url, **kwargs):
        if "/commits" in url:
            return _gh_response(_commit_payload(yaml_ts))
        if "baker-vault/pulls" in url:
            return _gh_response([])
        if "baker-master/pulls" in url:
            return _gh_response(master_pulls)
        return _gh_response([])

    post_comment_mock = MagicMock(
        side_effect=RuntimeError("ClickUp 5xx storm")
    )

    with patch.object(mod.httpx, "get", side_effect=_fake_get), patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=_store_with_lock(True),
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=MagicMock(post_comment=post_comment_mock),
    ):
        result = mod.run_roadmap_drift_sentinel()

    assert result["status"] == "drift"
    assert result["comment_posted"] is False


# --- Advisory-lock contention -------------------------------------------


def test_run_skips_when_advisory_lock_contended():
    """Lock contended -> skipped, no GitHub fetch, no ClickUp write."""
    from orchestrator import roadmap_drift_sentinel as mod

    httpx_get_mock = MagicMock()
    post_comment_mock = MagicMock()

    with patch.object(mod.httpx, "get", httpx_get_mock), patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=_store_with_lock(False),  # lock NOT acquired
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=MagicMock(post_comment=post_comment_mock),
    ):
        result = mod.run_roadmap_drift_sentinel()

    assert result["status"] == "skipped"
    assert result.get("reason") == "lock_contended"
    httpx_get_mock.assert_not_called()
    post_comment_mock.assert_not_called()


# --- Module-level constants -----------------------------------------------


def test_lock_key_is_900900():
    """Audit per LOCK_KEY_900300_COLLISION_1 — key must be 900900."""
    from orchestrator import roadmap_drift_sentinel as mod
    assert mod.ADVISORY_LOCK_KEY == 900900


def test_drift_threshold_is_five():
    from orchestrator import roadmap_drift_sentinel as mod
    assert mod.DRIFT_THRESHOLD == 5


def test_drift_task_id_is_recurring_clickup_task():
    from orchestrator import roadmap_drift_sentinel as mod
    assert mod.DRIFT_TASK_ID == "86c9k6kau"
