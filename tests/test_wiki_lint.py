"""WIKI_LINT_1 — entrypoint, report writer, severity gating."""
from __future__ import annotations

import datetime as _dt

import pytest

import kbl.wiki_lint as W
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault, NOW, TODAY


class _StubResp:
    def __init__(self, text="STILL_RELEVANT"):
        self.text = text
        class _U:
            input_tokens = 50
            output_tokens = 5
        self.usage = _U()


def _stub_caller(messages, max_tokens=2000, system=None):
    # 2 emit shapes are enough: stale → STILL_RELEVANT, contradiction → NO_CONFLICTS
    return _StubResp("NO_CONFLICTS")


def test_run_produces_report_file(tmp_path, monkeypatch):
    vault = build_fixture_vault(tmp_path)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    res = W.run(
        vault_path=vault,
        dry_run=True,
        post_slack=False,
        llm_caller=_stub_caller,
        today=TODAY,
        output_dir=tmp_path / "outputs" / "lint",
        overrides={
            "retired_slugs": {"defunct"},
            "now_utc": NOW.isoformat(),
            "signal_last_seen": {},
            "_skip_cost_log": True,
        },
    )
    assert res["ok"] is True
    report = tmp_path / "outputs" / "lint" / f"{TODAY.isoformat()}.md"
    assert report.is_file()
    body = report.read_text(encoding="utf-8")
    assert body.startswith(f"# Wiki lint — {TODAY.isoformat()}")
    # All seven check headers must appear in "Checks executed" footer
    for name in W.ALL_CHECK_NAMES:
        assert name in body


def test_run_aggregates_errors_warnings_info(tmp_path):
    vault = build_fixture_vault(tmp_path)
    res = W.run(
        vault_path=vault,
        dry_run=True,
        post_slack=False,
        llm_caller=_stub_caller,
        today=TODAY,
        output_dir=tmp_path / "outputs" / "lint",
        overrides={
            "retired_slugs": {"defunct"},
            "now_utc": NOW.isoformat(),
            "signal_last_seen": {},
            "_skip_cost_log": True,
        },
    )
    assert res["errors"] >= 1, "expected at least one error (defunct slug + flat-new + nested-missing)"
    assert res["warnings"] >= 1, "expected at least one warning"
    assert res["info"] >= 1, "expected at least one info (inbox_overdue)"


def test_severity_tag_red_when_errors():
    from collections import Counter
    counts = Counter({"error": 3, "warn": 1, "info": 0})
    assert "🔴" in W._severity_tag(counts, None)


def test_severity_tag_yellow_when_warnings_only():
    from collections import Counter
    counts = Counter({"error": 0, "warn": 2, "info": 5})
    assert "🟡" in W._severity_tag(counts, None)


def test_severity_tag_clean_when_info_only():
    from collections import Counter
    counts = Counter({"error": 0, "warn": 0, "info": 3})
    assert "clean" in W._severity_tag(counts, None)


def test_severity_tag_aborted_overrides():
    from collections import Counter
    counts = Counter({"error": 0, "warn": 0, "info": 0})
    assert "aborted" in W._severity_tag(counts, "token_ceiling_exceeded")


def test_run_skips_when_vault_path_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    res = W.run(vault_path=None, dry_run=True, post_slack=False)
    assert res.get("ok") is False
    assert "BAKER_VAULT_PATH" in res.get("skipped", "")


def test_run_skips_when_wiki_dir_missing(tmp_path):
    (tmp_path / "vault").mkdir()
    res = W.run(vault_path=tmp_path / "vault", dry_run=True, post_slack=False)
    assert res.get("ok") is False
    assert "missing" in res.get("skipped", "")


def test_token_ceiling_simulated_abort(tmp_path):
    """Simulate a 200K-token run by setting an absurdly low ceiling with a
    drifted-stub caller — runner should mark abort + still write report."""
    vault = build_fixture_vault(tmp_path)
    res = W.run(
        vault_path=vault,
        dry_run=True,
        post_slack=False,
        llm_caller=lambda messages, max_tokens=10, system=None: _StubResp("DRIFTED"),
        today=TODAY,
        output_dir=tmp_path / "outputs" / "lint",
        overrides={
            "retired_slugs": set(),
            "now_utc": NOW.isoformat(),
            "signal_last_seen": {},
            "token_ceiling": 1,
            "_skip_cost_log": True,
        },
    )
    assert res["aborted"] == "token_ceiling_exceeded"
    body = (tmp_path / "outputs" / "lint" / f"{TODAY.isoformat()}.md").read_text("utf-8")
    assert "ABORTED" in body


def test_dry_run_no_slack_post(tmp_path, monkeypatch):
    """dry_run=True must not post to Slack regardless of env."""
    vault = build_fixture_vault(tmp_path)
    posted = {"n": 0}

    def fake_post(text):
        posted["n"] += 1
        return True

    monkeypatch.setattr(W, "_post_slack", fake_post)
    W.run(
        vault_path=vault,
        dry_run=True,
        post_slack=False,
        llm_caller=_stub_caller,
        today=TODAY,
        output_dir=tmp_path / "outputs" / "lint",
        overrides={"signal_last_seen": {}, "_skip_cost_log": True, "now_utc": NOW.isoformat()},
    )
    assert posted["n"] == 0


def test_check_failure_does_not_crash_runner(tmp_path, monkeypatch):
    """If one check raises, others must still run + report writes."""
    vault = build_fixture_vault(tmp_path)

    from kbl.lint_checks import retired_slug_reference as RC

    def boom(*a, **kw):
        raise RuntimeError("intentional")

    monkeypatch.setattr(RC, "run", boom)
    res = W.run(
        vault_path=vault,
        dry_run=True,
        post_slack=False,
        llm_caller=_stub_caller,
        today=TODAY,
        output_dir=tmp_path / "outputs" / "lint",
        overrides={"signal_last_seen": {}, "_skip_cost_log": True, "now_utc": NOW.isoformat()},
    )
    assert res["ok"] is True
    body = (tmp_path / "outputs" / "lint" / f"{TODAY.isoformat()}.md").read_text("utf-8")
    # Other check names still listed even though check 1 raised
    assert "missing_required_files" in body


def test_report_lists_all_seven_check_names_in_executed_footer(tmp_path):
    vault = build_fixture_vault(tmp_path)
    W.run(
        vault_path=vault,
        dry_run=True,
        post_slack=False,
        llm_caller=_stub_caller,
        today=TODAY,
        output_dir=tmp_path / "outputs" / "lint",
        overrides={"signal_last_seen": {}, "_skip_cost_log": True, "now_utc": NOW.isoformat()},
    )
    body = (tmp_path / "outputs" / "lint" / f"{TODAY.isoformat()}.md").read_text("utf-8")
    assert "Checks executed" in body
    for name in (
        "retired_slug_reference",
        "missing_required_files",
        "orphan_matter_dir",
        "one_way_cross_ref",
        "inbox_overdue",
        "stale_active_matter",
        "contradiction_within_matter",
    ):
        assert name in body
