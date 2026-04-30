"""Citation parser tests for orchestrator.cortex_phase6_reflector.

Brief: CORTEX_PHASE6_REFLECTOR_1 §5.1.

Pure-Python — no DB, no filesystem. Exercises CITATION_RE / DIRECTIVE_ID_RE
across the matrix listed in brief §5.1.
"""
from __future__ import annotations

from orchestrator.cortex_phase6_reflector import parse_citations


def test_single_valid_id():
    valid, invalid, has = parse_citations("some text [directive: foo-001]")
    assert valid == ["foo-001"]
    assert invalid == []
    assert has is True


def test_multi_valid_ids_in_one_block():
    valid, invalid, has = parse_citations(
        "prefix [directive: foo-001, bar-002] suffix"
    )
    assert valid == ["foo-001", "bar-002"]
    assert invalid == []
    assert has is True


def test_two_separate_blocks():
    valid, invalid, has = parse_citations(
        "two blocks [directive: a-1] middle [directive: b-2]"
    )
    assert valid == ["a-1", "b-2"]
    assert invalid == []
    assert has is True


def test_dedupe_repeated_ids():
    valid, invalid, has = parse_citations("dedup [directive: x-1, x-1]")
    assert valid == ["x-1"]
    assert invalid == []
    assert has is True


def test_case_insensitive_keyword():
    valid, invalid, has = parse_citations("case [DIRECTIVE: foo-001]")
    assert valid == ["foo-001"]
    assert has is True


def test_no_whitespace_after_colon():
    valid, _, has = parse_citations("whitespace [directive:foo-001]")
    assert valid == ["foo-001"]
    assert has is True


def test_malformed_id_kebab_violation():
    """NotKebab violates DIRECTIVE_ID_RE (uppercase)."""
    valid, invalid, has = parse_citations("malformed [directive: NotKebab]")
    assert valid == []
    assert invalid == ["NotKebab"]
    assert has is True


def test_empty_directive_block_has_match_no_ids():
    valid, invalid, has = parse_citations("empty list [directive: ]")
    assert valid == []
    assert invalid == []
    assert has is True


def test_no_citation_block_at_all():
    valid, invalid, has = parse_citations("no citation block")
    assert valid == []
    assert invalid == []
    assert has is False


def test_empty_string():
    valid, invalid, has = parse_citations("")
    assert valid == []
    assert invalid == []
    assert has is False


def test_global_id():
    valid, _, has = parse_citations("global [directive: _global-001]")
    assert valid == ["_global-001"]
    assert has is True


def test_mixed_valid_and_invalid():
    valid, invalid, has = parse_citations(
        "mixed [directive: foo-001, NotKebab]"
    )
    assert valid == ["foo-001"]
    assert invalid == ["NotKebab"]
    assert has is True


def test_none_input_treated_as_empty():
    """Defensive: None proposal_text must not crash."""
    valid, invalid, has = parse_citations(None)  # type: ignore[arg-type]
    assert valid == []
    assert invalid == []
    assert has is False


def test_kebab_with_topic_segment():
    """Brief 4 id format: <matter>-<topic>-<NNN>."""
    valid, _, has = parse_citations(
        "topic id [directive: movie-aukera-001]"
    )
    assert valid == ["movie-aukera-001"]
    assert has is True
