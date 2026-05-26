"""Markdown-AST blocking validator for rendered RechargeReport markdown.

Enforces: exact 11 H2 set, canonical order, per-section word range,
total word range. Raises ValidationError on any violation. Blocks save.
"""
import re
from dataclasses import dataclass

from .schema import SECTION_ORDER

# Per-section word target ranges (tolerance ±30% per researcher recommendation).
WORD_TARGETS: dict[str, tuple[int, int]] = {
    "executive_summary": (84, 195),
    "scope_of_report": (70, 156),
    "counterparty_and_contract": (105, 234),
    "evidence_base": (126, 286),
    "cost_reconstruction": (140, 325),
    "recharge_basis": (105, 234),
    "counterparty_defence": (105, 234),
    "risks_and_open_questions": (84, 195),
    "numbers_claimed": (56, 156),
    "recommendation": (35, 104),
    "anchors": (56, 156),
}

TOTAL_WORD_RANGE: tuple[int, int] = (1_400, 2_200)


class RechargeReportValidationError(Exception):
    """Raised when a rendered report violates the canonical contract."""


@dataclass
class ValidationFinding:
    rule: str
    detail: str


def _parse_h2_sections(markdown: str) -> list[tuple[str, str]]:
    """Return [(heading_text, body_text), ...] in document order. H2 = lines beginning '## '.

    Lines inside a fenced code block (delimited by ``` at the start of a line)
    are NEVER interpreted as H2, so an LLM-emitted code sample containing a
    '## X' line cannot fool the parser into seeing a new section.
    """
    lines = markdown.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_body: list[str] = []
    in_fence = False
    for line in lines:
        if re.match(r"^```", line):
            in_fence = not in_fence
            if current_heading is not None:
                current_body.append(line)
            continue
        if not in_fence:
            m = re.match(r"^##\s+(.+?)\s*$", line)
        else:
            m = None
        if m:
            if current_heading is not None:
                sections.append((current_heading, current_body))
            current_heading = m.group(1).strip()
            current_body = []
        else:
            if current_heading is not None:
                current_body.append(line)
    if current_heading is not None:
        sections.append((current_heading, current_body))
    return [(h, "\n".join(b)) for h, b in sections]


def _word_count(text: str) -> int:
    """Count whitespace-separated tokens, excluding punctuation-only artifacts."""
    return len(
        [t for t in re.split(r"\s+", text.strip()) if t and not re.fullmatch(r"[\W_]+", t)]
    )


def validate_recharge_report(markdown: str) -> None:
    """Validate rendered markdown. Raises RechargeReportValidationError on failure."""
    findings: list[ValidationFinding] = []
    sections = _parse_h2_sections(markdown)
    actual_headings = [h for h, _ in sections]
    canonical_headings = [h for h, _ in SECTION_ORDER]

    if len(sections) != 11:
        findings.append(
            ValidationFinding(
                "section_count",
                f"Expected exactly 11 H2 sections; found {len(sections)}. "
                f"Actual: {actual_headings}",
            )
        )
    elif actual_headings != canonical_headings:
        findings.append(
            ValidationFinding(
                "section_order_or_set",
                f"H2 headings drift from canonical. Expected {canonical_headings}; "
                f"got {actual_headings}",
            )
        )

    by_heading = {h: b for h, b in sections}
    for heading, field in SECTION_ORDER:
        if heading not in by_heading:
            continue
        wc = _word_count(by_heading[heading])
        lo, hi = WORD_TARGETS[field]
        if wc < lo or wc > hi:
            findings.append(
                ValidationFinding(
                    f"word_count:{field}",
                    f"Section {heading!r} ({field}) word count {wc} outside [{lo}, {hi}]",
                )
            )

    total = sum(_word_count(b) for _, b in sections)
    if total < TOTAL_WORD_RANGE[0] or total > TOTAL_WORD_RANGE[1]:
        findings.append(
            ValidationFinding(
                "total_word_count",
                f"Total word count {total} outside canonical range {TOTAL_WORD_RANGE}",
            )
        )

    if findings:
        msg = "Rendered RechargeReport failed canonical validation:\n" + "\n".join(
            f"  - [{f.rule}] {f.detail}" for f in findings
        )
        raise RechargeReportValidationError(msg)
