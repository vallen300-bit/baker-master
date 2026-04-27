"""WIKI_LINT_1 — check 6 contradiction_within_matter (LLM-assisted)."""
from __future__ import annotations

from kbl.lint_checks import contradiction_within_matter as M
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault, NOW


class _StubResp:
    def __init__(self, text):
        self.text = text
        class _U:
            input_tokens = 250
            output_tokens = 50
        self.usage = _U()


def test_no_conflict_returns_empty(tmp_path):
    vault = build_fixture_vault(tmp_path)

    def stub(messages, max_tokens=2000, system=None):
        return _StubResp("NO_CONFLICTS")

    hits = M.run(vault, {"_skip_cost_log": True, "now_utc": NOW.isoformat()}, llm_caller=stub)
    assert hits == []


def test_conflict_lines_emitted_as_hits(tmp_path):
    vault = build_fixture_vault(tmp_path)

    def stub(messages, max_tokens=2000, system=None):
        return _StubResp(
            "CONFLICT | gold.md:funding €1.2M || _overview.md:funding €800K\n"
            "CONFLICT | gold.md:status active || _overview.md:status closed\n"
        )

    hits = M.run(vault, {"_skip_cost_log": True, "now_utc": NOW.isoformat()}, llm_caller=stub)
    assert hits, "expected hits"
    assert all(h.severity is Severity.WARN for h in hits)
    assert all("CONFLICT" in h.message for h in hits)


def test_aborted_skip_propagates(tmp_path):
    vault = build_fixture_vault(tmp_path)

    def stub(messages, max_tokens=2000, system=None):
        return _StubResp("CONFLICT | a:b || c:d")

    registries = {"_aborted": "token_ceiling_exceeded", "_skip_cost_log": True}
    hits = M.run(vault, registries, llm_caller=stub)
    assert hits == []


def test_garbage_llm_output_safely_ignored(tmp_path):
    vault = build_fixture_vault(tmp_path)

    def stub(messages, max_tokens=2000, system=None):
        return _StubResp("I am not following the format and saying random things.")

    hits = M.run(vault, {"_skip_cost_log": True, "now_utc": NOW.isoformat()}, llm_caller=stub)
    assert hits == []


def test_token_ceiling_aborts(tmp_path):
    vault = build_fixture_vault(tmp_path)

    def stub(messages, max_tokens=2000, system=None):
        return _StubResp("CONFLICT | a:b || c:d")

    registries = {
        "_skip_cost_log": True,
        "token_ceiling": 1,
        "now_utc": NOW.isoformat(),
    }
    hits = M.run(vault, registries, llm_caller=stub)
    assert registries.get("_aborted") == "token_ceiling_exceeded"
    assert hits == []


def test_llm_exception_does_not_crash(tmp_path):
    vault = build_fixture_vault(tmp_path)

    def boom(messages, max_tokens=2000, system=None):
        raise RuntimeError("api unavailable")

    hits = M.run(vault, {"_skip_cost_log": True, "now_utc": NOW.isoformat()}, llm_caller=boom)
    assert hits == []
