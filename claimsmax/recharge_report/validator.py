"""HTML-AST blocking validator for rendered RechargeReport HTML.

Enforces: exact 7 H2 set in canonical order (with templated 'What happened with the
<X> work'), required visual primitives (claim-figures triplet, evidence-table 5-9
rows, split-table with total, delta-conflict block), and total word range. Raises
RechargeReportValidationError on any violation. Blocks save.
"""
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


# Lower bound calibrated against the Director-ratified V2 Lohberger exemplar
# (~1145 body words). Brief originally suggested 1200; lowered to 1000 to give
# canonical-reference headroom without permitting truly sparse reports.
TOTAL_WORD_RANGE: tuple[int, int] = (1_000, 2_400)
EVIDENCE_ROW_RANGE: tuple[int, int] = (5, 9)

# H2 #3 is the templated "What happened with the <X> work" — regex-matched at the
# expected position. The other six are exact-string-matched in canonical order.
CANONICAL_H2_EXACT: list[str] = [
    "The parties",
    "Background",
    "What Hagenauer failed to do",
    "The evidence chain",
    "The amount Brisen claims",
    "Brisen's Arguments (to be validated)",
]
WHAT_HAPPENED_RE = re.compile(r"^What happened with the .+ work$")


class RechargeReportValidationError(Exception):
    """Raised when a rendered report violates the canonical V3 contract."""


@dataclass
class ValidationFinding:
    rule: str
    detail: str


@dataclass
class _ParsedReport:
    h2_texts: list[str] = field(default_factory=list)
    claim_figure_kinds: list[str] = field(default_factory=list)
    evidence_row_count: int = 0
    split_total_rows: int = 0
    has_delta_conflict: bool = False
    body_text: list[str] = field(default_factory=list)


class _ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.r = _ParsedReport()
        self._stack: list[tuple[str, dict[str, str]]] = []
        self._in_h2 = False
        self._h2_buf: list[str] = []
        self._in_evidence_tbody = False
        self._in_split_table = False
        self._skip_text_tags = {"style", "script", "head", "title"}

    def _parent_has_class(self, klass: str) -> bool:
        for _tag, attrs in self._stack:
            if klass in attrs.get("class", "").split():
                return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict: dict[str, str] = {k: (v or "") for k, v in attrs}
        classes = attr_dict.get("class", "").split()

        if tag == "h2":
            self._in_h2 = True
            self._h2_buf = []
        elif tag == "div" and "figure-row" in classes:
            if self._parent_has_class("claim-figures"):
                if "headline" in classes:
                    kind = "headline"
                elif "ceiling" in classes:
                    kind = "ceiling"
                else:
                    kind = "before"
                self.r.claim_figure_kinds.append(kind)
        elif tag == "table" and "split-table" in classes:
            self._in_split_table = True
        elif tag == "tbody":
            if self._parent_has_class("evidence-table"):
                self._in_evidence_tbody = True
        elif tag == "tr":
            if self._in_evidence_tbody:
                self.r.evidence_row_count += 1
            if self._in_split_table and "total" in classes:
                self.r.split_total_rows += 1
        elif tag == "div" and "delta-conflict" in classes:
            self.r.has_delta_conflict = True

        # Push AFTER the start-tag handlers so parent-class lookups don't include self.
        self._stack.append((tag, attr_dict))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Void / self-closing tags (e.g. <br/>) shouldn't push onto the stack.
        # Treat as start+end with no body.
        pass

    def handle_endtag(self, tag: str) -> None:
        # Pop matching tag if present. Some sloppy HTML (e.g. <br>, <col>) never
        # gets an end tag — silently tolerate stack mismatch in those cases.
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if tag == "h2":
            self.r.h2_texts.append("".join(self._h2_buf).strip())
            self._in_h2 = False
        elif tag == "tbody":
            self._in_evidence_tbody = False
        elif tag == "table" and self._in_split_table:
            self._in_split_table = False

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_buf.append(data)
        inside_skip = any(t in self._skip_text_tags for t, _ in self._stack)
        if not inside_skip and data.strip():
            self.r.body_text.append(data)

    # Anthropic HTML may contain numeric entities (e.g. &euro; -> €) — normalise
    # them as plain text inside h2 buffers + body text for word counting.
    def handle_entityref(self, name: str) -> None:
        if self._in_h2:
            self._h2_buf.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._in_h2:
            self._h2_buf.append(f"&#{name};")


def _word_count(parts: list[str]) -> int:
    joined = " ".join(parts)
    return len(
        [t for t in re.split(r"\s+", joined.strip()) if t and not re.fullmatch(r"[\W_]+", t)]
    )


def validate_recharge_report_html(html_str: str) -> None:
    """Validate rendered HTML. Raises RechargeReportValidationError on failure."""
    parser = _ReportParser()
    parser.feed(html_str)
    parsed = parser.r

    findings: list[ValidationFinding] = []

    if len(parsed.h2_texts) != 7:
        findings.append(
            ValidationFinding(
                "h2_count",
                f"Expected exactly 7 H2 elements; found {len(parsed.h2_texts)}. "
                f"Actual: {parsed.h2_texts}",
            )
        )
    else:
        # Position 0-1 exact, 2 regex, 3-6 exact (offset by one in CANONICAL_H2_EXACT).
        expected_order: list[str | re.Pattern[str]] = (
            CANONICAL_H2_EXACT[:2] + [WHAT_HAPPENED_RE] + CANONICAL_H2_EXACT[2:]
        )
        for idx, (got, expected) in enumerate(zip(parsed.h2_texts, expected_order)):
            if isinstance(expected, str):
                if got != expected:
                    findings.append(
                        ValidationFinding(
                            f"h2_order:{idx}",
                            f"H2[{idx}] expected {expected!r}, got {got!r}",
                        )
                    )
            else:
                if not expected.match(got):
                    findings.append(
                        ValidationFinding(
                            f"h2_order:{idx}",
                            f"H2[{idx}] expected pattern {expected.pattern!r}, got {got!r}",
                        )
                    )

    if len(parsed.claim_figure_kinds) != 3:
        findings.append(
            ValidationFinding(
                "claim_figures_count",
                f"Expected exactly 3 .figure-row inside .claim-figures; found "
                f"{len(parsed.claim_figure_kinds)}",
            )
        )
    else:
        if "headline" not in parsed.claim_figure_kinds:
            findings.append(
                ValidationFinding(
                    "claim_figures_headline", "Missing .headline figure-row"
                )
            )
        if "ceiling" not in parsed.claim_figure_kinds:
            findings.append(
                ValidationFinding(
                    "claim_figures_ceiling", "Missing .ceiling figure-row"
                )
            )

    if not (EVIDENCE_ROW_RANGE[0] <= parsed.evidence_row_count <= EVIDENCE_ROW_RANGE[1]):
        findings.append(
            ValidationFinding(
                "evidence_row_count",
                f"Evidence-table row count {parsed.evidence_row_count} outside "
                f"{EVIDENCE_ROW_RANGE}",
            )
        )

    if parsed.split_total_rows < 1:
        findings.append(
            ValidationFinding(
                "split_table_total",
                "split-table is missing the required <tr class='total'> row",
            )
        )

    if not parsed.has_delta_conflict:
        findings.append(
            ValidationFinding("delta_conflict", "Missing .delta-conflict accent block")
        )

    total = _word_count(parsed.body_text)
    if not (TOTAL_WORD_RANGE[0] <= total <= TOTAL_WORD_RANGE[1]):
        findings.append(
            ValidationFinding(
                "total_word_count",
                f"Total body word count {total} outside canonical range {TOTAL_WORD_RANGE}",
            )
        )

    if findings:
        msg = "Rendered RechargeReport failed canonical V3 validation:\n" + "\n".join(
            f"  - [{f.rule}] {f.detail}" for f in findings
        )
        raise RechargeReportValidationError(msg)
