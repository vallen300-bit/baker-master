"""Ship gate for BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1 + _MAX_TOKENS_2.

Six required tests (5 parser + 1 telemetry):

  1. test_parse_well_formed_json_object
  2. test_parse_json_in_markdown_fence
  3. test_parse_unquoted_property_names   — Opus's most common real-world
                                             failure on dense extractions
  4. test_parse_trailing_comma
  5. test_parse_unparseable_returns_none  — must return None, NOT {}
  6. test_extract_logs_output_tokens_on_success — BRIEF_PM_EXTRACTION_MAX_TOKENS_2
     D3. Asserts INFO log fires with output_tokens + stop_reason anchors on
     every completed claude.messages.create call.
"""
from __future__ import annotations

from orchestrator.capability_runner import _robust_json_parse_object


def test_parse_well_formed_json_object():
    text = '{"sub_matters": {}, "summary": "ok"}'
    assert _robust_json_parse_object(text) == {"sub_matters": {}, "summary": "ok"}


def test_parse_json_in_markdown_fence():
    text = '```json\n{"red_flags": ["x"], "summary": "y"}\n```'
    result = _robust_json_parse_object(text)
    assert result == {"red_flags": ["x"], "summary": "y"}


def test_parse_unquoted_property_names():
    # Opus's observed dense-extraction malformation — bare identifier keys.
    text = '{sub_matters: {}, red_flags: ["trust risk"], summary: "ok"}'
    result = _robust_json_parse_object(text)
    assert result is not None, "Pass-4 repair should recover unquoted keys"
    assert "red_flags" in result
    assert result["red_flags"] == ["trust risk"]
    assert result["summary"] == "ok"


def test_parse_trailing_comma():
    text = '{"a": 1, "b": 2,}'
    result = _robust_json_parse_object(text)
    assert result == {"a": 1, "b": 2}


def test_parse_unparseable_returns_none():
    text = "not even close to JSON"
    assert _robust_json_parse_object(text) is None, (
        "Unparseable input must return None (NOT {}) so callers can "
        "distinguish parse failure from empty state."
    )


def test_extract_logs_output_tokens_on_success(caplog, monkeypatch):
    """D2: output_tokens logged at INFO level on every extraction call."""
    import logging
    import sys
    from unittest.mock import MagicMock
    from orchestrator import capability_runner

    class _FakeUsage:
        output_tokens = 1234

    class _FakeContentBlock:
        text = '{"sub_matters": {}, "summary": "ok"}'

    class _FakeResp:
        content = [_FakeContentBlock()]
        usage = _FakeUsage()
        stop_reason = "end_turn"

    class _FakeClient:
        def __init__(self, api_key=None):
            pass

        class messages:
            @staticmethod
            def create(**kwargs):
                return _FakeResp()

    monkeypatch.setattr(
        capability_runner, "anthropic",
        type("M", (), {"Anthropic": _FakeClient}),
    )

    class _NoopStore:
        def update_pm_project_state(self, *a, **k):
            pass

        def create_cross_pm_signal(self, *a, **k):
            pass

    class _NoopStoreClass:
        @staticmethod
        def _get_global_instance():
            return _NoopStore()

    # Inject fake memory.store_back via sys.modules — avoids importing the real
    # module (which uses PEP-604 union syntax that breaks type evaluation on
    # the test runner's Python version).
    store_mod = MagicMock()
    store_mod.SentinelStoreBack = _NoopStoreClass
    monkeypatch.setitem(sys.modules, "memory.store_back", store_mod)

    # Stub CapabilityRunner.__init__ to skip ToolExecutor + Voyage AI setup
    # — extract_and_update_pm_state constructs a throwaway runner only for
    # the two instance helpers we're about to override.
    monkeypatch.setattr(
        capability_runner.CapabilityRunner, "__init__", lambda self: None,
    )
    monkeypatch.setattr(
        capability_runner.CapabilityRunner,
        "_get_extraction_dedup_context", lambda self, slug: "",
    )
    monkeypatch.setattr(
        capability_runner.CapabilityRunner,
        "_store_pending_insights", lambda self, *a, **k: None,
    )

    with caplog.at_level(logging.INFO, logger="baker.capability_runner"):
        result = capability_runner.extract_and_update_pm_state(
            pm_slug="ao_pm",
            question="test",
            answer="test",
            mutation_source="test_unit",
        )

    assert result is not None
    assert any(
        "output_tokens=1234" in rec.message
        and "stop_reason=end_turn" in rec.message
        for rec in caplog.records
    )
