"""Ship gate for BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1.

Five required tests per §D5 / §Ship Gate:

  1. test_parse_well_formed_json_object
  2. test_parse_json_in_markdown_fence
  3. test_parse_unquoted_property_names   — Opus's most common real-world
                                             failure on dense extractions
  4. test_parse_trailing_comma
  5. test_parse_unparseable_returns_none  — must return None, NOT {}
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
