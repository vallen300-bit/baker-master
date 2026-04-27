"""WIKI_LINT_1 — check 7 inbox_overdue."""
from __future__ import annotations

from kbl.lint_checks import inbox_overdue as M
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault, TODAY


def test_old_inbox_file_flagged(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {"today_utc": TODAY.isoformat(), "inbox_days": 14})
    paths = sorted({h.path for h in hits})
    assert "wiki/_inbox/2026-01-01_old-stuck.md" in paths


def test_fresh_inbox_file_not_flagged(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {"today_utc": TODAY.isoformat(), "inbox_days": 14})
    paths = {h.path for h in hits}
    assert "wiki/_inbox/2026-04-25_fresh.md" not in paths


def test_severity_info(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {"today_utc": TODAY.isoformat()})
    assert hits, "expected at least one inbox_overdue hit"
    assert all(h.severity is Severity.INFO for h in hits)


def test_threshold_override(tmp_path):
    vault = build_fixture_vault(tmp_path)
    # With 200-day cutoff, even old inbox file should NOT trip
    hits = M.run(vault, {"today_utc": TODAY.isoformat(), "inbox_days": 200})
    assert hits == []


def test_no_inbox_dir_returns_empty(tmp_path):
    (tmp_path / "baker-vault" / "wiki").mkdir(parents=True)
    assert M.run(tmp_path / "baker-vault", {"today_utc": TODAY.isoformat()}) == []
