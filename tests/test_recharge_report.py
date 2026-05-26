"""Tests for claimsmax.recharge_report — schema, renderer, validator, generator, CLI."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from claimsmax.recharge_report.generator import (
    RechargeReportGenerationError,
    generate_recharge_report,
)
from claimsmax.recharge_report.renderer import render_to_markdown
from claimsmax.recharge_report.schema import SECTION_ORDER, RechargeReport
from claimsmax.recharge_report.validator import (
    RechargeReportValidationError,
    validate_recharge_report,
)


# --- helpers -----------------------------------------------------------------

# Target word counts inside each section's valid range (no validator violations).
_VALID_WORDS_PER_FIELD: dict[str, int] = {
    "executive_summary": 130,
    "scope_of_report": 110,
    "counterparty_and_contract": 165,
    "evidence_base": 200,
    "cost_reconstruction": 230,
    "recharge_basis": 165,
    "counterparty_defence": 165,
    "risks_and_open_questions": 135,
    "numbers_claimed": 100,
    "recommendation": 65,
    "anchors": 100,
}


def _filler(n_words: int) -> str:
    return " ".join(["word"] * n_words)


def _valid_report_dict(overrides: dict[str, int] | None = None) -> dict[str, str]:
    overrides = overrides or {}
    return {
        field: _filler(overrides.get(field, count))
        for field, count in _VALID_WORDS_PER_FIELD.items()
    }


def _write_canonical_template(tmp_path: Path) -> Path:
    """Build a minimal canonical scaffold with 11 H2 headings + slots, in canonical order.

    Comments are omitted to keep word-count math deterministic in tests.
    """
    parts: list[str] = []
    for heading, field in SECTION_ORDER:
        parts.append(f"## {heading}\n")
        parts.append("{{" + field + "}}\n")
    template = "\n".join(parts)
    path = tmp_path / "pichler-head4-template.md"
    path.write_text(template, encoding="utf-8")
    return path


def _canonical_markdown(tmp_path: Path, overrides: dict[str, int] | None = None) -> str:
    template_path = _write_canonical_template(tmp_path)
    report = RechargeReport(**_valid_report_dict(overrides))
    return render_to_markdown(report, template_path=template_path)


def _make_anthropic_response(report_data: dict[str, str]) -> MagicMock:
    """Return a mock Anthropic response carrying a single tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.input = report_data
    resp = MagicMock()
    resp.content = [block]
    return resp


# --- Fix 2: schema -----------------------------------------------------------


def test_schema_rejects_extra_fields():
    data = _valid_report_dict()
    data["mehrkosten_section"] = _filler(120)  # 12th field — must be rejected
    with pytest.raises(ValidationError) as excinfo:
        RechargeReport(**data)
    assert "extra" in str(excinfo.value).lower() or "forbid" in str(excinfo.value).lower()


def test_schema_requires_all_11_fields():
    data = _valid_report_dict()
    data.pop("recommendation")
    with pytest.raises(ValidationError) as excinfo:
        RechargeReport(**data)
    assert "recommendation" in str(excinfo.value)


# --- Fix 3a: renderer --------------------------------------------------------


def test_renderer_substitutes_all_slots(tmp_path):
    template_path = _write_canonical_template(tmp_path)
    report = RechargeReport(**_valid_report_dict())
    rendered = render_to_markdown(report, template_path=template_path)
    assert "{{" not in rendered
    # And every canonical heading appears once.
    for heading, _field in SECTION_ORDER:
        assert f"## {heading}" in rendered


def test_renderer_missing_template_raises(tmp_path):
    report = RechargeReport(**_valid_report_dict())
    missing = tmp_path / "does-not-exist.md"
    with pytest.raises(FileNotFoundError):
        render_to_markdown(report, template_path=missing)


# --- Fix 3b: validator -------------------------------------------------------


def test_validator_passes_canonical_report(tmp_path):
    markdown = _canonical_markdown(tmp_path)
    # No exception.
    validate_recharge_report(markdown)


def test_validator_blocks_extra_heading(tmp_path):
    markdown = _canonical_markdown(tmp_path)
    markdown += "\n## Mehrkosten extras\n" + _filler(120) + "\n"
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report(markdown)
    assert "section_count" in str(excinfo.value)


def test_validator_blocks_reordered_headings():
    # Build markdown with same 11 headings but swap two adjacent ones.
    swapped_order = list(SECTION_ORDER)
    swapped_order[0], swapped_order[1] = swapped_order[1], swapped_order[0]
    chunks: list[str] = []
    for heading, field in swapped_order:
        wc = _VALID_WORDS_PER_FIELD[field]
        chunks.append(f"## {heading}\n{_filler(wc)}\n")
    markdown = "\n".join(chunks)
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report(markdown)
    assert "section_order_or_set" in str(excinfo.value)


def test_validator_blocks_oversize_section(tmp_path):
    markdown = _canonical_markdown(tmp_path, overrides={"executive_summary": 5000})
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report(markdown)
    assert "word_count:executive_summary" in str(excinfo.value)


def test_validator_blocks_undersize_total(tmp_path):
    # Per-section minimums sum to ~966 words, below TOTAL_WORD_RANGE lower bound (1400).
    minimums = {
        "executive_summary": 84,
        "scope_of_report": 70,
        "counterparty_and_contract": 105,
        "evidence_base": 126,
        "cost_reconstruction": 140,
        "recharge_basis": 105,
        "counterparty_defence": 105,
        "risks_and_open_questions": 84,
        "numbers_claimed": 56,
        "recommendation": 35,
        "anchors": 56,
    }
    markdown = _canonical_markdown(tmp_path, overrides=minimums)
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report(markdown)
    assert "total_word_count" in str(excinfo.value)


# --- Fix 4: generator (mocked Anthropic) ------------------------------------


@patch("claimsmax.recharge_report.generator.anthropic.Anthropic")
def test_generator_retries_once_on_validation_fail(mock_client_cls, tmp_path):
    template_path = _write_canonical_template(tmp_path)
    bad_data = _valid_report_dict({"executive_summary": 10})  # under minimum
    good_data = _valid_report_dict()
    mock_client = mock_client_cls.return_value
    mock_client.messages.create.side_effect = [
        _make_anthropic_response(bad_data),
        _make_anthropic_response(good_data),
    ]
    markdown = generate_recharge_report(
        "facts about the painter trade", model_tier="routine", template_path=template_path
    )
    # Validator passed → no exception. Two API calls observed.
    assert mock_client.messages.create.call_count == 2
    assert "## Executive summary" in markdown
    # And calling validator again is idempotent.
    validate_recharge_report(markdown)


@patch("claimsmax.recharge_report.generator.anthropic.Anthropic")
def test_generator_surfaces_after_two_failures(mock_client_cls, tmp_path):
    template_path = _write_canonical_template(tmp_path)
    bad_data = _valid_report_dict({"executive_summary": 10})
    mock_client = mock_client_cls.return_value
    mock_client.messages.create.side_effect = [
        _make_anthropic_response(bad_data),
        _make_anthropic_response(bad_data),
    ]
    with pytest.raises(RechargeReportGenerationError):
        generate_recharge_report(
            "facts about the painter trade",
            model_tier="routine",
            template_path=template_path,
        )
    assert mock_client.messages.create.call_count == 2


