"""Render RechargeReport into the canonical Pichler V3 HTML template.

The HTML template is read at runtime from the canonical vault path. Slots are
double-brace placeholders ({{report_title}}, {{tagline}}, {{parties}}, ...).
List-of-objects slots ({{claim_figures}}, {{evidence_chain}}, {{amount_claimed}},
{{arguments}}) are expanded to multi-line HTML fragments before substitution.
"""
import html
import os
from pathlib import Path

from .schema import (
    ArgumentItem,
    ClaimFiguresRow,
    EvidenceRow,
    RechargeReport,
    SplitTableRow,
)


CANONICAL_TEMPLATE_PATH = (
    Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
    / "wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html"
)


def _esc(text: str) -> str:
    """HTML-escape but preserve <strong>, <br>, <em>, and self-closing <br/>."""
    escaped = html.escape(text, quote=False)
    for tag in ("strong", "em", "br"):
        escaped = escaped.replace(f"&lt;{tag}&gt;", f"<{tag}>")
        escaped = escaped.replace(f"&lt;/{tag}&gt;", f"</{tag}>")
        escaped = escaped.replace(f"&lt;{tag}/&gt;", f"<{tag}/>")
    return escaped


def _render_claim_figures(rows: list[ClaimFiguresRow]) -> str:
    out: list[str] = []
    for row in rows:
        css = {"before": "", "headline": "headline", "ceiling": "ceiling"}[row.row_kind]
        cls = f' class="figure-row {css}"' if css else ' class="figure-row"'
        out.append(
            f'<div{cls}><span class="label">{_esc(row.label)}</span>'
            f'<span class="value">{_esc(row.value)}</span></div>'
        )
    return "\n  ".join(out)


def _render_evidence_chain(rows: list[EvidenceRow]) -> str:
    out: list[str] = []
    for row in rows:
        out.append(
            f"<tr><td>{_esc(row.date)}</td>"
            f"<td>{_esc(row.document)}</td>"
            f"<td>{_esc(row.proves)}</td></tr>"
        )
    return "\n    ".join(out)


def _render_amount_claimed(rows: list[SplitTableRow]) -> str:
    out: list[str] = []
    for row in rows:
        cls = "" if row.row_kind == "item" else f' class="{row.row_kind}"'
        if row.row_kind == "total":
            label_html = f"<strong>{_esc(row.label)}</strong>"
            amount_html = f"<strong>{_esc(row.amount)}</strong>"
        elif row.row_kind == "sub":
            label_html = f"&nbsp;&nbsp;{_esc(row.label)}"
            amount_html = _esc(row.amount)
        else:
            label_html = _esc(row.label)
            amount_html = _esc(row.amount)
        out.append(
            f'<tr{cls}><td>{label_html}</td><td class="num">{amount_html}</td></tr>'
        )
    return "\n    ".join(out)


def _render_arguments(items: list[ArgumentItem]) -> str:
    out: list[str] = []
    for it in items:
        out.append(
            f"<li><strong>{_esc(it.headline)}</strong><br>{_esc(it.body)}</li>"
        )
    return "\n  ".join(out)


def render_to_html(
    report: RechargeReport,
    template_path: Path = CANONICAL_TEMPLATE_PATH,
) -> str:
    """Substitute report fields into V3 HTML scaffold. Returns rendered HTML."""
    if not template_path.exists():
        raise FileNotFoundError(
            f"Canonical V3 HTML template missing at {template_path}"
        )
    template = template_path.read_text(encoding="utf-8")

    substitutions: dict[str, str] = {
        "{{report_title}}": _esc(report.report_title),
        "{{claim_type}}": _esc(report.claim_type),
        "{{report_date}}": _esc(report.report_date),
        "{{report_time}}": _esc(report.report_time),
        "{{tagline}}": _esc(report.tagline),
        "{{version_marker}}": _esc(report.version_marker),
        "{{claim_figures}}": _render_claim_figures(report.claim_figures),
        "{{parties}}": report.parties,
        "{{background}}": report.background,
        "{{trade_h2_suffix}}": _esc(report.trade_h2_suffix),
        "{{what_happened}}": report.what_happened,
        "{{what_hag_failed}}": report.what_hag_failed,
        "{{evidence_chain}}": _render_evidence_chain(report.evidence_chain),
        "{{amount_claimed}}": _render_amount_claimed(report.amount_claimed),
        "{{amount_claimed_notes}}": report.amount_claimed_notes,
        "{{delta_conflict}}": _esc(report.delta_conflict),
        "{{arguments}}": _render_arguments(report.arguments),
    }

    rendered = template
    for slot, value in substitutions.items():
        if slot not in rendered:
            raise ValueError(f"V3 template missing slot {slot!r}")
        rendered = rendered.replace(slot, value)

    if "{{" in rendered:
        unfilled = [line.strip() for line in rendered.splitlines() if "{{" in line]
        raise ValueError(f"Template has unfilled slots after render: {unfilled}")
    return rendered
