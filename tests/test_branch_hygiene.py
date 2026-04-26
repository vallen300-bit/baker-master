"""Tests for scripts/branch_hygiene.py.

Mocks the gh CLI compare endpoint so tests stay offline. Real branches /
real deletions never happen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import branch_hygiene as bh
from scripts.branch_hygiene import (
    DEFAULT_PROTECT_PATTERNS,
    BranchInfo,
    classify,
    execute_deletions,
    run_l3_batch,
    triaga_html,
)


def _b(name: str, age: int = 0, sha: str = "deadbeefcafebabe") -> BranchInfo:
    return BranchInfo(name=name, sha=sha, last_commit_iso="", age_days=age)


# ---------------------------- classify() ---------------------------------- #


def test_classify_protected_main():
    layer, _ = classify(
        _b("main"),
        repo="x/y",
        base="main",
        staleness_days=30,
        protect_patterns=DEFAULT_PROTECT_PATTERNS,
    )
    assert layer == "PROTECTED"


def test_classify_protected_release_pattern():
    layer, _ = classify(
        _b("release/2026-04"),
        repo="x/y",
        base="main",
        staleness_days=30,
        protect_patterns=DEFAULT_PROTECT_PATTERNS,
    )
    assert layer == "PROTECTED"


def test_classify_l1_squash_merged_when_ahead_zero():
    """ahead_by==0 → branch is fully merged → L1."""
    with patch.object(
        bh,
        "compare_to_base",
        return_value={"ahead_by": 0, "behind_by": 5, "status": "behind"},
    ):
        layer, reason = classify(
            _b("kbl-people-entity-loaders-1", age=2),
            repo="x/y",
            base="main",
            staleness_days=30,
            protect_patterns=DEFAULT_PROTECT_PATTERNS,
        )
    assert layer == "L1"
    assert "ahead_by=0" in reason


def test_classify_l1_negative_when_ahead_positive_and_recent():
    """Recent branch with unmerged commits → KEEP, not L1."""
    with patch.object(
        bh,
        "compare_to_base",
        return_value={"ahead_by": 3, "behind_by": 1, "status": "diverged"},
    ):
        layer, _ = classify(
            _b("active-feature", age=2),
            repo="x/y",
            base="main",
            staleness_days=30,
            protect_patterns=DEFAULT_PROTECT_PATTERNS,
        )
    assert layer == "KEEP"


def test_classify_l2_flagged_stale_unmerged():
    """Stale branch (>= 30d) with unmerged commits → L2_FLAGGED."""
    with patch.object(
        bh,
        "compare_to_base",
        return_value={"ahead_by": 4, "behind_by": 0, "status": "ahead"},
    ):
        layer, reason = classify(
            _b("step5-empty-draft-investigation-1", age=42),
            repo="x/y",
            base="main",
            staleness_days=30,
            protect_patterns=DEFAULT_PROTECT_PATTERNS,
        )
    assert layer == "L2_FLAGGED"
    assert "42d" in reason


def test_classify_mobile_cluster_default_delete():
    """Q2 default: feat/mobile-* gets MOBILE_CLUSTER tag (auto-delete)."""
    with patch.object(
        bh,
        "compare_to_base",
        return_value={"ahead_by": 5, "behind_by": 0, "status": "ahead"},
    ):
        layer, _ = classify(
            _b("feat/mobile-alerts-view-1", age=38),
            repo="x/y",
            base="main",
            staleness_days=30,
            protect_patterns=DEFAULT_PROTECT_PATTERNS,
        )
    assert layer == "MOBILE_CLUSTER"


def test_classify_mobile_cluster_specific_branches():
    """Q2 list also covers ios-shortcuts / document-browser / networking."""
    cases = [
        "feat/ios-shortcuts-1",
        "feat/document-browser-1",
        "feat/networking-phase1",
    ]
    with patch.object(
        bh,
        "compare_to_base",
        return_value={"ahead_by": 3, "behind_by": 0, "status": "ahead"},
    ):
        for name in cases:
            layer, _ = classify(
                _b(name, age=39),
                repo="x/y",
                base="main",
                staleness_days=30,
                protect_patterns=DEFAULT_PROTECT_PATTERNS,
            )
            assert layer == "MOBILE_CLUSTER", f"expected MOBILE_CLUSTER for {name}"


# ------------------------- execute_deletions() ---------------------------- #


def test_execute_deletions_dry_run_does_nothing(capsys):
    rows = [(_b("foo"), "L1: squashed"), (_b("bar"), "L1: squashed")]
    deletions: list[str] = []
    audited: list[str] = []
    n = execute_deletions(
        rows,
        repo="x/y",
        layer="L1",
        dry_run=True,
        deleter=lambda r, b: (deletions.append(b), True)[1],
        auditor=lambda branch, lyr, reason: (audited.append(branch.name), True)[1],
    )
    assert n == 0
    assert deletions == []
    assert audited == []
    out = capsys.readouterr().out
    assert "[dry-run]" in out


def test_execute_deletions_real_deletes_and_audits():
    rows = [(_b("merged-1"), "L1: squashed")]
    deletions: list[str] = []
    audited: list[str] = []
    n = execute_deletions(
        rows,
        repo="x/y",
        layer="L1",
        dry_run=False,
        throttle_per_minute=600,  # 0.1s sleep — keep test fast
        deleter=lambda r, b: (deletions.append(b), True)[1],
        auditor=lambda branch, lyr, reason: (audited.append(branch.name), True)[1],
    )
    assert n == 1
    assert deletions == ["merged-1"]
    assert audited == ["merged-1"]


def test_execute_deletions_failed_delete_not_audited():
    rows = [(_b("denied"), "L1: squashed")]
    audited: list[str] = []
    n = execute_deletions(
        rows,
        repo="x/y",
        layer="L1",
        dry_run=False,
        throttle_per_minute=600,
        deleter=lambda r, b: False,  # API refused
        auditor=lambda branch, lyr, reason: (audited.append(branch.name), True)[1],
    )
    assert n == 0
    assert audited == []


# ------------------------------ Triaga HTML ------------------------------- #


def test_triaga_html_lists_l2_branches():
    rows = [
        (_b("PM-TRIAGE-1", age=45), "stale 45d, ahead_by=2"),
        (_b("agent-bridge", age=60), "stale 60d, ahead_by=1"),
    ]
    out = triaga_html(rows, generated_at="2026-04-26T07:00:00+00:00")
    assert "PM-TRIAGE-1" in out
    assert "agent-bridge" in out
    assert 'type="checkbox"' in out
    assert 'name="delete"' in out
    assert "value=\"PM-TRIAGE-1\"" in out


def test_triaga_html_handles_empty_l2_list():
    out = triaga_html([], generated_at="2026-04-26T07:00:00+00:00")
    assert "No L2 branches" in out


def test_triaga_html_escapes_branch_names():
    rows = [(_b("evil<script>", age=33), "stale")]
    out = triaga_html(rows, generated_at="2026-04-26T07:00:00+00:00")
    assert "<script>" not in out  # raw tag must not appear unescaped
    assert "&lt;script&gt;" in out


# ------------------------------- L3 batch --------------------------------- #


def test_run_l3_batch_deletes_only_present_branches(tmp_path: Path):
    tick_file = tmp_path / "ticks.txt"
    tick_file.write_text("agent-bridge\nPM-TRIAGE-1\nghost-branch\n# a comment\n")

    fake_remote = [
        _b("agent-bridge", age=58),
        _b("PM-TRIAGE-1", age=64),
        _b("main"),
    ]
    deletions: list[str] = []
    audited: list[str] = []
    with patch.object(bh, "list_branches", return_value=fake_remote):
        n = execute_deletions(
            [
                (b, "L3 Director-confirmed")
                for b in fake_remote
                if b.name in {"agent-bridge", "PM-TRIAGE-1"}
            ],
            repo="x/y",
            layer="L3",
            dry_run=False,
            throttle_per_minute=600,
            deleter=lambda r, name: (deletions.append(name), True)[1],
            auditor=lambda branch, lyr, reason: (audited.append(branch.name), True)[1],
        )
    assert n == 2
    assert sorted(deletions) == ["PM-TRIAGE-1", "agent-bridge"]


def test_run_l3_batch_skips_missing_branches(tmp_path: Path, capsys):
    tick_file = tmp_path / "ticks.txt"
    tick_file.write_text("ghost-only\n")
    with patch.object(bh, "list_branches", return_value=[_b("main")]):
        n = run_l3_batch(tick_file, repo="x/y", dry_run=True)
    assert n == 0
    assert "SKIP ghost-only" in capsys.readouterr().err
