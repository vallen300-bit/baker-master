"""Unit tests for tier normalization."""
import pytest
from orchestrator.pipeline import _normalize_tier


def test_integer_tiers():
    assert _normalize_tier(1) == 1
    assert _normalize_tier(2) == 2
    assert _normalize_tier(3) == 3


def test_string_tiers_fallback():
    assert _normalize_tier("urgent") == 1
    assert _normalize_tier("important") == 2
    assert _normalize_tier("info") == 3
    assert _normalize_tier("Urgent") == 1  # case insensitive


def test_invalid_tiers_default_to_3():
    assert _normalize_tier(0) == 3
    assert _normalize_tier(4) == 3
    assert _normalize_tier("banana") == 3
    assert _normalize_tier(None) == 3
    assert _normalize_tier("") == 3
