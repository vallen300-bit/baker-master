"""Unit tests for the Scan system prompt."""
import pytest
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT


def test_prompt_is_non_empty_string():
    assert isinstance(SCAN_SYSTEM_PROMPT, str)
    assert len(SCAN_SYSTEM_PROMPT) > 100


def test_prompt_is_conversational_no_json_requirement():
    """The scan prompt must NOT require JSON output (unlike pipeline prompt)."""
    lower = SCAN_SYSTEM_PROMPT.lower()
    assert "do not output json" in lower or "do not return json" in lower
    # Must not contain a JSON schema or output format block requiring JSON
    assert '"alerts"' not in SCAN_SYSTEM_PROMPT
    assert '"analysis"' not in SCAN_SYSTEM_PROMPT


def test_prompt_mentions_source_attribution():
    """Scan prompt should instruct Baker to cite sources."""
    lower = SCAN_SYSTEM_PROMPT.lower()
    assert "source" in lower
    assert "attribution" in lower or "cite" in lower or "per your" in lower
