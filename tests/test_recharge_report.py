"""Tests for claimsmax.recharge_report — schema, renderer, validator, generator, CLI.

Bound to the canonical Pichler V3 EN-only register (D-017, 2026-05-26).
Live API calls are mocked; vault file reads are mocked or gated by env.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from claimsmax.recharge_report.generator import (
    RechargeReportGenerationError,
    generate_recharge_report,
)
from claimsmax.recharge_report.renderer import render_to_html
from claimsmax.recharge_report.schema import (
    ArgumentItem,
    ClaimFiguresRow,
    EN_H2_ORDER,
    EvidenceRow,
    RechargeReport,
    SplitTableRow,
)
from claimsmax.recharge_report.validator import (
    RechargeReportValidationError,
    TOTAL_WORD_RANGE,
    validate_recharge_report_html,
)


# --- fixtures ---------------------------------------------------------------


VAULT_PATH = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
V2_LOHBERGER_FIXTURE = (
    VAULT_PATH
    / "wiki/matters/hagenauer-rg7/curated/"
    / "2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html"
)
V3_TEMPLATE_PATH = (
    VAULT_PATH / "wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html"
)


def _filler(n_words: int, base: str = "word") -> str:
    return " ".join([base] * n_words)


def _valid_report(overrides: dict | None = None) -> RechargeReport:
    """Return a RechargeReport that renders + validates clean against the V3 template.

    Sized to cross the 1000-word lower bound — total body words ~1300 after render.
    """
    overrides = overrides or {}
    base = dict(
        report_title="Test / Sample Trade",
        claim_type="Recharge-Failure Claim",
        report_date="29 May 2026",
        report_time="09:00",
        tagline="Test tagline naming the recharge-failure premise in plain English declarative prose.",
        version_marker="test-marker, audit pending",
        claim_figures=[
            ClaimFiguresRow(row_kind="before", label="Before ClaimsMax", value="\u20ac10,000"),
            ClaimFiguresRow(row_kind="headline", label="Conservative", value="\u20ac35,000"),
            ClaimFiguresRow(row_kind="ceiling", label="Max Ceiling", value="\u20ac70,000"),
        ],
        parties=(
            "<ol><li><strong>Counterparty:</strong> "
            + _filler(60)
            + "</li><li><strong>Brisen-side lead:</strong> Test Lead with supporting context "
            + _filler(40)
            + "</li></ol>"
        ),
        background=(
            "<ol>"
            + "".join(
                f"<li>Background fact number {i} with several supporting words "
                + _filler(12)
                + "</li>"
                for i in range(5)
            )
            + "</ol>"
        ),
        trade_h2_suffix="Test",
        what_happened=(
            "<p>" + _filler(80, "alpha") + "</p>"
            + "<p>" + _filler(80, "beta") + "</p>"
            + "<p>" + _filler(80, "gamma") + "</p>"
        ),
        what_hag_failed=(
            "<ul>"
            + "<li>Failed action one description filler text " + _filler(25) + "</li>"
            + "<li>Failed action two description filler text " + _filler(25) + "</li>"
            + "<li>Failed action three description filler text " + _filler(25) + "</li>"
            + "</ul>"
        ),
        evidence_chain=[
            EvidenceRow(
                date=f"{2020 + i}",
                document=f"doc-{i} document name with supporting tag",
                proves="proves point " + _filler(20),
            )
            for i in range(6)
        ],
        amount_claimed=[
            SplitTableRow(label="Line item one with supporting descriptor words", amount="\u20ac10,000", row_kind="item"),
            SplitTableRow(label="Line item two with supporting descriptor words", amount="\u20ac20,000", row_kind="item"),
            SplitTableRow(label="Total filed against counterparty", amount="\u20ac30,000", row_kind="total"),
            SplitTableRow(label="Vorbehalt G-uplift conditional ceiling reserve", amount="\u20ac45,000", row_kind="sub"),
        ],
        amount_claimed_notes=(
            "<p>Reserves note " + _filler(35) + "</p>"
            + "<p>Second reserves note " + _filler(30) + "</p>"
        ),
        delta_conflict=(
            "Delta paragraph leading with the conflict description, "
            + _filler(60)
            + " resolved by Bauer extraction before Forderungsanmeldung."
        ),
        arguments=[
            ArgumentItem(
                headline=f"Argument headline {i}",
                body=(
                    "Body line one with substantial content "
                    + _filler(18)
                    + ".<br>Body line two with named anchor "
                    + _filler(15)
                    + "."
                ),
            )
            for i in range(7)
        ],
    )
    base.update(overrides)
    return RechargeReport(**base)


def _stub_skill_bundle(template_path: Path = V3_TEMPLATE_PATH) -> tuple[str, str, str]:
    """Synthetic skill/spine + the real V3 template (worktree path)."""
    return (
        "stub SKILL.md body",
        "stub spine.md body",
        template_path.read_text(encoding="utf-8"),
    )


def _make_anthropic_response(report: RechargeReport) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = report.model_dump()
    resp = MagicMock()
    resp.content = [block]
    return resp


# --- schema tests -----------------------------------------------------------


def test_schema_h2_order_has_seven_entries():
    assert len(EN_H2_ORDER) == 7
    assert EN_H2_ORDER[0] == "The parties"
    assert "What happened with the {trade} work" in EN_H2_ORDER


def test_schema_accepts_valid_report():
    r = _valid_report()
    assert r.trade_h2_suffix == "Test"
    assert len(r.claim_figures) == 3
    assert len(r.arguments) == 7


def test_schema_rejects_extra_keys():
    data = _valid_report().model_dump()
    data["mehrkosten_section"] = "drift"
    with pytest.raises(ValidationError):
        RechargeReport.model_validate(data)


def test_schema_rejects_wrong_claim_figures_count():
    base = _valid_report()
    data = base.model_dump()
    data["claim_figures"] = data["claim_figures"][:2]  # only 2 rows
    with pytest.raises(ValidationError):
        RechargeReport.model_validate(data)


def test_schema_rejects_too_few_evidence_rows():
    base = _valid_report()
    data = base.model_dump()
    data["evidence_chain"] = data["evidence_chain"][:4]  # < 5
    with pytest.raises(ValidationError):
        RechargeReport.model_validate(data)


def test_schema_rejects_too_many_arguments():
    base = _valid_report()
    extra = base.arguments[0].model_dump()
    data = base.model_dump()
    data["arguments"] = base.model_dump()["arguments"] + [extra] * 3  # 10 > 8
    with pytest.raises(ValidationError):
        RechargeReport.model_validate(data)


def test_schema_literal_row_kind_rejects_unknown():
    with pytest.raises(ValidationError):
        ClaimFiguresRow(row_kind="middle", label="x", value="y")


# --- renderer tests ---------------------------------------------------------


@pytest.mark.skipif(
    not V3_TEMPLATE_PATH.exists(),
    reason="V3 HTML template not present in this checkout",
)
def test_renderer_emits_all_seven_h2s_including_templated():
    r = _valid_report({"trade_h2_suffix": "DrywallTest"})
    html_str = render_to_html(r, template_path=V3_TEMPLATE_PATH)
    assert "<h2>The parties</h2>" in html_str
    assert "<h2>Background</h2>" in html_str
    assert "<h2>What happened with the DrywallTest work</h2>" in html_str
    assert "<h2>What Hagenauer failed to do</h2>" in html_str
    assert "<h2>The evidence chain</h2>" in html_str
    assert "<h2>The amount Brisen claims</h2>" in html_str
    assert "<h2>Brisen's Arguments (to be validated)</h2>" in html_str


@pytest.mark.skipif(
    not V3_TEMPLATE_PATH.exists(),
    reason="V3 HTML template not present in this checkout",
)
def test_renderer_output_passes_validator():
    r = _valid_report()
    html_str = render_to_html(r, template_path=V3_TEMPLATE_PATH)
    validate_recharge_report_html(html_str)


def test_renderer_missing_template_raises(tmp_path):
    r = _valid_report()
    missing = tmp_path / "nope.html"
    with pytest.raises(FileNotFoundError):
        render_to_html(r, template_path=missing)


def test_renderer_unfilled_slot_raises(tmp_path):
    # Template missing the {{parties}} slot — renderer should raise ValueError.
    bad_template = tmp_path / "bad.html"
    bad_template.write_text(
        "<html><body><h1>{{report_title}}</h1></body></html>", encoding="utf-8"
    )
    r = _valid_report()
    with pytest.raises(ValueError):
        render_to_html(r, template_path=bad_template)


# --- validator tests --------------------------------------------------------


@pytest.mark.skipif(
    not V2_LOHBERGER_FIXTURE.exists(),
    reason="V2 Lohberger fixture not present (no baker-vault checkout)",
)
def test_validator_passes_canonical_v2_lohberger():
    html_str = V2_LOHBERGER_FIXTURE.read_text(encoding="utf-8")
    # Should not raise.
    validate_recharge_report_html(html_str)


@pytest.mark.skipif(
    not V2_LOHBERGER_FIXTURE.exists(),
    reason="V2 Lohberger fixture not present",
)
def test_validator_blocks_dropped_h2():
    html_str = V2_LOHBERGER_FIXTURE.read_text(encoding="utf-8")
    mutated = html_str.replace(
        "<h2>Background</h2>", "", 1
    )
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report_html(mutated)
    assert "h2_count" in str(excinfo.value) or "h2_order" in str(excinfo.value)


@pytest.mark.skipif(
    not V2_LOHBERGER_FIXTURE.exists(),
    reason="V2 Lohberger fixture not present",
)
def test_validator_blocks_renamed_h2():
    html_str = V2_LOHBERGER_FIXTURE.read_text(encoding="utf-8")
    mutated = html_str.replace("<h2>Background</h2>", "<h2>Background renamed</h2>", 1)
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report_html(mutated)
    assert "h2_order:1" in str(excinfo.value)


@pytest.mark.skipif(
    not V2_LOHBERGER_FIXTURE.exists(),
    reason="V2 Lohberger fixture not present",
)
def test_validator_blocks_missing_headline_figure_row():
    html_str = V2_LOHBERGER_FIXTURE.read_text(encoding="utf-8")
    # Strip the 'headline' class from the figure-row to break the triplet contract.
    mutated = html_str.replace('figure-row headline', 'figure-row plain', 1)
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report_html(mutated)
    assert "claim_figures_headline" in str(excinfo.value)


@pytest.mark.skipif(
    not V2_LOHBERGER_FIXTURE.exists(),
    reason="V2 Lohberger fixture not present",
)
def test_validator_blocks_too_few_evidence_rows():
    """Replace the V2 evidence table tbody with a 3-row stub."""
    html_str = V2_LOHBERGER_FIXTURE.read_text(encoding="utf-8")
    new_tbody = (
        "<tbody>"
        + "".join(f"<tr><td>2025</td><td>doc</td><td>proves x</td></tr>" for _ in range(3))
        + "</tbody>"
    )
    start = html_str.index('<table class="evidence-table">')
    inner_start = html_str.index("<tbody>", start)
    inner_end = html_str.index("</tbody>", inner_start) + len("</tbody>")
    mutated = html_str[:inner_start] + new_tbody + html_str[inner_end:]
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report_html(mutated)
    assert "evidence_row_count" in str(excinfo.value)


@pytest.mark.skipif(
    not V2_LOHBERGER_FIXTURE.exists(),
    reason="V2 Lohberger fixture not present",
)
def test_validator_blocks_missing_delta_conflict():
    html_str = V2_LOHBERGER_FIXTURE.read_text(encoding="utf-8")
    mutated = html_str.replace('class="delta-conflict"', 'class="delta-removed"', 1)
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report_html(mutated)
    assert "delta_conflict" in str(excinfo.value)


def test_validator_blocks_under_total_word_count():
    # Hand-build a minimal 7-H2 HTML with everything present but very short prose.
    minimal = """<html><body>
    <div class="claim-figures">
      <div class="figure-row"><span class="label">a</span><span class="value">b</span></div>
      <div class="figure-row headline"><span class="label">c</span><span class="value">d</span></div>
      <div class="figure-row ceiling"><span class="label">e</span><span class="value">f</span></div>
    </div>
    <h2>The parties</h2><p>Tiny.</p>
    <h2>Background</h2><p>Tiny.</p>
    <h2>What happened with the Tiny work</h2><p>Tiny.</p>
    <h2>What Hagenauer failed to do</h2><p>Tiny.</p>
    <h2>The evidence chain</h2>
    <table class="evidence-table"><tbody>
      <tr><td>x</td><td>x</td><td>x</td></tr>
      <tr><td>x</td><td>x</td><td>x</td></tr>
      <tr><td>x</td><td>x</td><td>x</td></tr>
      <tr><td>x</td><td>x</td><td>x</td></tr>
      <tr><td>x</td><td>x</td><td>x</td></tr>
    </tbody></table>
    <h2>The amount Brisen claims</h2>
    <table class="split-table"><tbody>
      <tr class="total"><td>Total</td><td>0</td></tr>
    </tbody></table>
    <div class="delta-conflict">Tiny.</div>
    <h2>Brisen's Arguments (to be validated)</h2>
    </body></html>"""
    with pytest.raises(RechargeReportValidationError) as excinfo:
        validate_recharge_report_html(minimal)
    assert "total_word_count" in str(excinfo.value)


def test_validator_word_range_lower_bound_is_calibrated():
    # Sanity-check: TOTAL_WORD_RANGE lower bound stays <= V2 canonical body word count.
    # Hardcoded reference: V2 Lohberger ~ 1145 body words at 2026-05-29.
    assert TOTAL_WORD_RANGE[0] <= 1145


# --- generator tests --------------------------------------------------------


@patch("claimsmax.recharge_report.generator._read_skill_bundle")
@patch("claimsmax.recharge_report.generator.anthropic.Anthropic")
def test_generator_returns_validated_html_on_first_pass(mock_client_cls, mock_bundle):
    mock_bundle.return_value = _stub_skill_bundle()
    good = _valid_report()
    mock_client = mock_client_cls.return_value
    mock_client.messages.create.return_value = _make_anthropic_response(good)
    rendered = generate_recharge_report(
        "facts about the Test trade",
        model_tier="routine",
        template_path=V3_TEMPLATE_PATH,
    )
    assert "<h2>The parties</h2>" in rendered
    assert mock_client.messages.create.call_count == 1


@patch("claimsmax.recharge_report.generator._read_skill_bundle")
@patch("claimsmax.recharge_report.generator.anthropic.Anthropic")
def test_generator_retries_once_on_validation_fail(mock_client_cls, mock_bundle):
    mock_bundle.return_value = _stub_skill_bundle()
    bad = _valid_report({"trade_h2_suffix": "X"})  # valid schema but make eval fail
    # Force a validation failure by mutating one slot to break renderer-output H2 set:
    # easiest path is to mock render_to_html to raise once via the validator.
    # Cleaner: bad report whose rendered output fails validator → use too-few evidence rows
    # is not schema-valid. Instead, simulate via under-word what_happened.
    bad_short = _valid_report({
        "what_happened": "<p>short</p>",
        "background": "<ol><li>one</li></ol>",
        "parties": "<ol><li>x</li></ol>",
        "delta_conflict": "short.",
        "amount_claimed_notes": "<p>short</p>",
        "arguments": [
            ArgumentItem(headline="h", body="b") for _ in range(5)
        ],
        "what_hag_failed": "<ul><li>x</li></ul>",
        "evidence_chain": [
            EvidenceRow(date="2025", document="d", proves="p") for _ in range(5)
        ],
    })
    good = _valid_report()
    mock_client = mock_client_cls.return_value
    mock_client.messages.create.side_effect = [
        _make_anthropic_response(bad_short),
        _make_anthropic_response(good),
    ]
    rendered = generate_recharge_report(
        "facts about the trade",
        model_tier="routine",
        template_path=V3_TEMPLATE_PATH,
    )
    assert "<h2>The parties</h2>" in rendered
    assert mock_client.messages.create.call_count == 2


@patch("claimsmax.recharge_report.generator._read_skill_bundle")
@patch("claimsmax.recharge_report.generator.anthropic.Anthropic")
def test_generator_surfaces_after_two_failures(mock_client_cls, mock_bundle):
    mock_bundle.return_value = _stub_skill_bundle()
    bad = _valid_report({
        "what_happened": "<p>short</p>",
        "background": "<ol><li>one</li></ol>",
        "parties": "<ol><li>x</li></ol>",
        "delta_conflict": "short.",
        "amount_claimed_notes": "<p>short</p>",
        "arguments": [
            ArgumentItem(headline="h", body="b") for _ in range(5)
        ],
        "what_hag_failed": "<ul><li>x</li></ul>",
        "evidence_chain": [
            EvidenceRow(date="2025", document="d", proves="p") for _ in range(5)
        ],
    })
    mock_client = mock_client_cls.return_value
    mock_client.messages.create.side_effect = [
        _make_anthropic_response(bad),
        _make_anthropic_response(bad),
    ]
    with pytest.raises(RechargeReportGenerationError):
        generate_recharge_report(
            "facts about the trade",
            model_tier="routine",
            template_path=V3_TEMPLATE_PATH,
        )
    assert mock_client.messages.create.call_count == 2


@patch("claimsmax.recharge_report.generator.anthropic.Anthropic")
def test_generator_raises_if_skill_bundle_missing(mock_client_cls, tmp_path):
    # Template path missing — _read_skill_bundle should raise FileNotFoundError early.
    missing = tmp_path / "no-template.html"
    with pytest.raises(FileNotFoundError):
        generate_recharge_report(
            "facts", model_tier="routine", template_path=missing
        )


# --- CLI tests --------------------------------------------------------------


def test_cli_help_documents_html_output():
    from scripts import recharge_report_cli as cli  # noqa: F401
    # Just import — argparse builds in main(). Verify help text references HTML.
    import importlib
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert "Output HTML path" in src
    assert "Pichler V3" in src
