"""WIKI_LINT_1 — check 5 stale_active_matter (LLM-assisted)."""
from __future__ import annotations

import datetime as _dt
import os
import time

from kbl.lint_checks import stale_active_matter as M
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault, NOW


class _StubResp:
    def __init__(self, text):
        self.text = text
        class _U:
            input_tokens = 100
            output_tokens = 5
        self.usage = _U()


def _stub_drifted(messages, max_tokens=10, system=None):
    return _StubResp("DRIFTED")


def _stub_relevant(messages, max_tokens=10, system=None):
    return _StubResp("STILL_RELEVANT")


def test_recent_matter_skips_llm(tmp_path):
    vault = build_fixture_vault(tmp_path)
    calls = {"n": 0}

    def caller(messages, max_tokens=10, system=None):
        calls["n"] += 1
        return _StubResp("DRIFTED")

    registries = {
        "now_utc": NOW.isoformat(),
        "stale_days": 60,
        "_skip_cost_log": True,
    }
    hits = M.run(vault, registries, llm_caller=caller)
    nested_good = [h for h in hits if h.path == "wiki/matters/nested-good"]
    assert nested_good == []
    # nested-good is recent → no LLM call for it
    # other dirs may still trigger LLM. Test: nested-good doesn't appear.


def test_stale_dir_with_drifted_verdict_flagged(tmp_path):
    vault = build_fixture_vault(tmp_path)
    # Force flat-old to be considered stale (it already is, mtime 2026-01-10)
    registries = {
        "now_utc": NOW.isoformat(),
        "stale_days": 60,
        "_skip_cost_log": True,
    }
    hits = M.run(vault, registries, llm_caller=_stub_drifted)
    paths = {h.path for h in hits}
    assert "wiki/flat-old" in paths
    flat_old_hits = [h for h in hits if h.path == "wiki/flat-old"]
    assert all(h.severity is Severity.WARN for h in flat_old_hits)


def test_stale_dir_with_still_relevant_verdict_not_flagged(tmp_path):
    vault = build_fixture_vault(tmp_path)
    registries = {
        "now_utc": NOW.isoformat(),
        "stale_days": 60,
        "_skip_cost_log": True,
    }
    hits = M.run(vault, registries, llm_caller=_stub_relevant)
    assert hits == []


def test_token_ceiling_aborts(tmp_path):
    vault = build_fixture_vault(tmp_path)
    registries = {
        "now_utc": NOW.isoformat(),
        "stale_days": 60,
        "token_ceiling": 1,  # impossibly low — first matter aborts
        "_skip_cost_log": True,
    }
    hits = M.run(vault, registries, llm_caller=_stub_drifted)
    assert registries.get("_aborted") == "token_ceiling_exceeded"
    assert hits == []


def test_llm_failure_does_not_crash(tmp_path):
    vault = build_fixture_vault(tmp_path)

    def boom(messages, max_tokens=10, system=None):
        raise RuntimeError("network down")

    registries = {
        "now_utc": NOW.isoformat(),
        "stale_days": 60,
        "_skip_cost_log": True,
    }
    hits = M.run(vault, registries, llm_caller=boom)
    assert hits == []  # no crash, no hits


def test_signal_stub_files_excluded_from_mtime(tmp_path):
    """Files that begin with the signal-stub HTML comment should NOT count
    as "Director-authored content" — verifies stub-tagged pastes don't
    keep a long-stale matter falsely fresh."""
    vault = build_fixture_vault(tmp_path)
    # Create a brand-new stub file under flat-old
    stub = vault / "wiki/flat-old/2026-04-26_signal-stub.md"
    stub.write_text(
        "<!-- stub:signal_id=999 -->\n# auto-paste from signal_queue\n",
        encoding="utf-8",
    )
    fresh = time.mktime(_dt.datetime(2026, 4, 26).timetuple())
    os.utime(stub, (fresh, fresh))

    registries = {
        "now_utc": NOW.isoformat(),
        "stale_days": 60,
        "_skip_cost_log": True,
    }
    hits = M.run(vault, registries, llm_caller=_stub_drifted)
    assert any(h.path == "wiki/flat-old" for h in hits), \
        "stub-tagged file should not refresh flat-old's authored mtime"
