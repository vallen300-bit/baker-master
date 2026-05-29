---
dispatched_by: aihead1
dispatch_to: b2
brief_id: ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1
tier: B
ratified_by: Director
ratified_on: 2026-05-29
reply_target: aihead1 (bus + CODE_2_RETURN.md)
---

# BRIEF: ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1 — Refactor English-V1 CLI to invoke the canonical `pichler-report-english` skill instead of running a parallel 11-section markdown template

## Context

Three days ago (commit `6efc3d1`, PR #267, 2026-05-26) the recharge-report CLI shipped via `BRIEF_RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1`. It bakes its own 11-section markdown scaffold (`wiki/_templates/pichler-head4-template.md`) with legal-academic H2 naming (`Executive summary` / `Scope of this report` / `Counterparty and contract structure` / `Evidence base` / `Cost reconstruction` / `Recharge basis` / `Counterparty defence` / `Risks` / `Numbers` / `Recommendation` / `Anchors`).

Hours later (2026-05-26 evening, D-017), Director ratified a different canonical register — the **Pichler V3 HTML format** with **7 EN H2s** (`The parties` / `Background` / `What happened with the <trade> work` / `What Hagenauer failed to do` / `The evidence chain` / `The amount Brisen claims` / `Brisen's Arguments (to be validated)`) and rich visual primitives (`claim-figures` triplet, `evidence-table` 3-col fixed-width, `split-table` 70/30 with totals + sub rows, `delta-conflict` accent block). Canonical reference: `~/baker-vault/wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html`.

The CLI's 11-section markdown scaffold is therefore the wrong shape. Hag-desk proved this on 2026-05-29 via the Lohberger Großküchentechnik probe (bus arc #1280 → #1281 → #1282): the CLI produced syntactically valid markdown but Director's register check failed because the output is not Pichler V3. Hag-desk then hand-rebuilt the V2 HTML that DID pass Director's ratification this turn (`wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html`, baker-vault commit `d9e70a8`).

This refactor swaps the CLI from "render a baked 11-section markdown template" to "invoke the canonical `pichler-report-english` skill at runtime." The skill carries the canonical V3 register via:
- `~/baker-vault/_ops/skills/pichler-report-english/SKILL.md` — EN-only entry point (drops sections 9 + 10 from spine).
- `~/baker-vault/_ops/skills/pichler-report/spine.md` — shared spine (11 structural elements / 5 hard rules / structural deltas).
- `~/baker-vault/wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html` — canonical HTML template (the actual binding contract).

The CLI becomes a thin wrapper that reads these three files at runtime, bundles them into the system prompt with `cache_control: ephemeral`, and renders the model's tool-use output into the HTML template. Future spine.md edits propagate to CLI output without any code change. This eliminates the template-drift bug class permanently.

Three wire fixes from earlier probes fold into this same refactor (Director-ratified 2026-05-29):
1. `thinking={'type':'enabled', 'budget_tokens':8000}` → `thinking={'type':'adaptive'}` — Opus 4.7 rejected the old signature.
2. `report_title` schema orphan — schema asserts exactly 11 fields, template has 12 slots (`{{report_title}}` is the 12th). Fix: schema gains a `report_title` field (and trade name composes into the templated H2 `What happened with the <trade> work`).
3. Per-section word targets already on the schema (`Field(description=..., target ~120-150 words)`) were ignored on first pass (one-shot success rate = 0%, with-retry = 100%). Fix: make the targets explicit numeric ranges in the field description + add them as a numbered list in the system prompt.

### Surface contract: N/A — pure backend Python refactor of CLI module + tests + one baker-vault HTML template edit. No dashboard panel, modal, button, anchor link, drilldown card, frontend route, Slack Block Kit, or email-rendered HTML touched. Rendered HTML output is consumed by Director via vault file open / Obsidian, not as a Baker-served URL.

## Estimated time: ~5h
## Complexity: High
## Prerequisites:
- Read `~/baker-vault/_ops/skills/pichler-report-english/SKILL.md` + `~/baker-vault/_ops/skills/pichler-report/spine.md` before starting.
- Read `~/baker-vault/wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html` end-to-end — this is the binding contract.
- Read `~/baker-vault/wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html` — the Director-ratified exemplar from this morning.
- `BAKER_VAULT_PATH` env must resolve to vault checkout (default `~/baker-vault`) for runtime skill loading.
- `ANTHROPIC_API_KEY` set in env for the live probe at AC1.

---

## Fix 1: Schema — replace 11 markdown sections with 7 EN H2 sections + visual primitive slots

### Problem
`claimsmax/recharge_report/schema.py` codes 11 string fields matching 11 markdown H2s. Canonical V3 register has 7 EN H2s and rich HTML visual primitives (claim-figures, evidence-table, split-table, delta-conflict). The schema cannot represent the canonical shape.

### Current State
`claimsmax/recharge_report/schema.py:1-99` — Pydantic v2 `RechargeReport` with 11 string fields (`executive_summary`, `scope_of_report`, `counterparty_and_contract`, `evidence_base`, `cost_reconstruction`, `recharge_basis`, `counterparty_defence`, `risks_and_open_questions`, `numbers_claimed`, `recommendation`, `anchors`). `SECTION_ORDER` list-of-tuples maps H2 text to field name. Hard assert at line 99: `len(SECTION_ORDER) == 11`.

### Implementation

Replace the entire `RechargeReport` model + `SECTION_ORDER` constant. Reference shape is the V2 hand-rebuild HTML at `wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html` (verified Director-ratified this turn). Field types must support the visual primitives.

```python
"""Recharge-report schema — Pydantic v2 model bound to the canonical Pichler V3
EN-only register (D-017, Director-ratified 2026-05-26). Each field maps 1:1 to a
{{slot}} in the V3 HTML template. No optional fields, no extras.

H2 count, H2 order, claim-figures triplet, evidence-table 3-col, split-table 70/30,
delta-conflict accent are THE CONTRACT — do NOT modify without Director ratification
(template version bump, not in-line drift).
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ClaimFiguresRow(BaseModel):
    """One row inside the .claim-figures block. Three rows total per spine §3."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    row_kind: Literal["before", "headline", "ceiling"] = Field(
        description="Which of the three triplet rows: Before / Conservative (headline) / Max Ceiling"
    )
    label: str = Field(description="Left-hand label. Plain English, no HTML.")
    value: str = Field(description="Right-hand value. Currency formatted, plain text (€35,000 style).")


class EvidenceRow(BaseModel):
    """One row of the .evidence-table (3 columns: date, document, what it proves)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: str = Field(description="Date or period. Plain text (e.g. '15 Nov 2023', 'Q2 2025', 'baseline').")
    document: str = Field(description="Document reference. Plain text.")
    proves: str = Field(description="What it proves. One sentence, plain English.")


class SplitTableRow(BaseModel):
    """One row of the .split-table (label + numeric)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(description="Left column label. Plain English.")
    amount: str = Field(description="Right column numeric. Currency formatted (€18,000 style).")
    row_kind: Literal["item", "total", "sub"] = Field(
        description="'item' = ordinary row, 'total' = bordered total row, 'sub' = indented Vorbehalt/ceiling row"
    )


class ArgumentItem(BaseModel):
    """One numbered argument in 'Brisen's Arguments (to be validated)'."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    headline: str = Field(description="<strong>Headline sentence.</strong> One short bolded clause.")
    body: str = Field(description="Supporting paragraph. 2-3 short lines separated by spine §38 hard rule (no walls of text).")


class RechargeReport(BaseModel):
    """Canonical Pichler V3 EN-only recharge-failure report. Each field is one slot.

    Word-count targets per spine + ClaimsMax bake-off:
    - Background bullets: ≤ 5 items, one line each.
    - 'What X failed to do': ≤ 3 bullets per spine §5 hard rule (duplicates removed).
    - 'What happened with the <trade> work': 4 short paragraphs, ≤ 80 words each.
    - Arguments: 5-8 items.
    - Evidence rows: 5-9 rows.
    - Split-table rows: 3-6 line items + 1 total + 0-3 sub rows.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # --- Title block (spine §1) ---
    report_title: str = Field(
        description="Trade-name H1 title (e.g. 'Lohberger / Commercial Kitchen'). Plain text, max 60 chars."
    )
    claim_type: str = Field(
        description="Claim-type subtitle (e.g. 'Recharge-Failure Claim'). Plain text, max 40 chars."
    )
    report_date: str = Field(
        description="Date string for the report-meta line (e.g. '29 May 2026')."
    )
    report_time: str = Field(
        description="Time string for the report-meta line (e.g. '08:00')."
    )

    # --- Tagline + provenance (spine §2) ---
    tagline: str = Field(
        description="Italic strategic-frame sentence. 1-2 sentences, ≤ 50 words. Declarative, no hedges."
    )
    version_marker: str = Field(
        description="Bold provenance line under the tagline (e.g. 'Edita-solo audit · corpus enrichment pending'). ≤ 80 chars."
    )

    # --- Claim-figures triplet (spine §3) ---
    claim_figures: list[ClaimFiguresRow] = Field(
        description="Exactly 3 rows in order: before / headline / ceiling.",
        min_length=3, max_length=3,
    )

    # --- The parties (spine §4 / H2 #1) ---
    parties: str = Field(
        description="HTML <ol> body with 2-4 <li> items. Identify counterparty (Firma + FN + UID + Sitz + GF if known), then Brisen-side lead. Plain English, no German legal vocab. Target ~120-160 words. Counsel-readable in 30 seconds (spine rule 1)."
    )

    # --- Background (H2 #2) ---
    background: str = Field(
        description="HTML <ol> body, 4-6 numbered items. Each item is one fact, one line. No prose paragraphs inside the list. Target ~100-140 words total."
    )

    # --- What happened with the <trade> work (H2 #3) ---
    trade_h2_suffix: str = Field(
        description="Trade descriptor that completes the H2 heading 'What happened with the <X> work' (e.g. 'Lohberger', 'drywall', 'HVAC'). Plain text, ≤ 25 chars."
    )
    what_happened: str = Field(
        description="3-5 short <p> paragraphs, ≤ 80 words each. Chronological narrative of the trade work and where it broke. Target ~250-320 words total. No bullets."
    )

    # --- What Hagenauer failed to do (H2 #4) ---
    what_hag_failed: str = Field(
        description="HTML <ul> body, max 3 bullets (spine rule 5 — duplicates removed). Each bullet ≤ 30 words, declarative. Target ~80-120 words total."
    )

    # --- The evidence chain (H2 #5) ---
    evidence_chain: list[EvidenceRow] = Field(
        description="5-9 rows of the evidence-table. Chronological. Mix of baseline contracts, dated documents, and 'full period' negative-evidence rows. Each row's 'proves' column ≤ 35 words.",
        min_length=5, max_length=9,
    )

    # --- The amount Brisen claims (H2 #6) — split-table + Delta-Conflict ---
    amount_claimed: list[SplitTableRow] = Field(
        description="Split-table rows in display order: line items (kind='item'), then exactly 1 total (kind='total'), then 0-3 sub rows (kind='sub') for Vorbehalt/Mehrkosten ceiling. Total rows 3-8.",
        min_length=3, max_length=8,
    )
    amount_claimed_notes: str = Field(
        description="2 short <p> paragraphs after the split-table. Reserve-of-rights wording. ≤ 100 words total."
    )
    delta_conflict: str = Field(
        description="Single paragraph for the .delta-conflict accent block. Names same-loss-two-expressions OR cross-trade severability. 60-120 words. Lead with the conflict, end with how it's resolved (Bauer extraction / severability split / pending evidence)."
    )

    # --- Brisen's Arguments (to be validated) (H2 #7) ---
    arguments: list[ArgumentItem] = Field(
        description="5-8 numbered arguments. Each: bolded headline + 2-3 short body lines (separated by <br> per spine rule 2). Framed as working positions awaiting counsel validation, never legal verdicts (spine rule 4).",
        min_length=5, max_length=8,
    )


# Canonical H2 ordering (for renderer + validator). The 7 EN H2s as they appear in V3.
EN_H2_ORDER: list[str] = [
    "The parties",
    "Background",
    # The "What happened" H2 is templated — validator uses a regex match, not exact string.
    "What happened with the {trade} work",
    "What Hagenauer failed to do",
    "The evidence chain",
    "The amount Brisen claims",
    "Brisen's Arguments (to be validated)",
]

assert len(EN_H2_ORDER) == 7, "Canonical Pichler V3 EN register is exactly 7 H2 sections"
```

### Key Constraints
- `extra="forbid"` on every nested model — strict tool-use must not drift.
- `Literal["..."]` on every enum field — model returns must be exactly one of the listed values.
- All Pydantic field types must be JSON-Schema serialisable for `strict=True` tool-use (booleans / strings / ints / lists / nested objects only — no `datetime` raw, use ISO string).
- DO NOT add German fields here — bilingual sibling skill `pichler-report` will get its own schema later. This brief is English-only.
- DO NOT include `executive_summary` / `recommendation` / `anchors` legacy fields. They are not in the V3 register.

### Verification
- `python3 -c "from claimsmax.recharge_report.schema import RechargeReport, EN_H2_ORDER; print(len(EN_H2_ORDER)); print(RechargeReport.model_json_schema())"` exits 0 and prints `7` plus a JSON schema.
- The printed JSON schema contains zero `"additionalProperties": true` entries (recursive check) — every nested model is closed.

---

## Fix 2: Renderer — switch from markdown substitution to HTML template substitution

### Problem
`claimsmax/recharge_report/renderer.py` reads `wiki/_templates/pichler-head4-template.md` (markdown, 11 H2s) and string-substitutes 11 `{{slot}}` placeholders. Canonical output is HTML, not markdown.

### Current State
`claimsmax/recharge_report/renderer.py:1-34` — 34 lines, `CANONICAL_TEMPLATE_PATH` points at `BAKER_VAULT_PATH/wiki/_templates/pichler-head4-template.md`. Simple `str.replace("{{slot}}", value)` loop over `SECTION_ORDER`.

### Implementation

Rewrite to render the V3 HTML template. The HTML template at `~/baker-vault/wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html` becomes the canonical source. Use the Lohberger V2 hand-rebuild as the reference for slot semantics.

```python
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
    """HTML-escape but preserve <strong>, <br>, <em>, &-entities the model emits."""
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
            f"<tr{cls}><td>{label_html}</td><td class=\"num\">{amount_html}</td></tr>"
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
        raise FileNotFoundError(f"Canonical V3 HTML template missing at {template_path}")
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
```

### Key Constraints
- The V3 HTML template at the canonical path MUST be updated to use the `{{slot}}` placeholders listed above. The current file has inline Lohberger content (not slots) — b2 owns the in-place edit on the baker-vault side in a paired baker-vault PR (see Fix 6). Code refactor and template edit ship together for AC1 to pass.
- Keep `_esc()` simple — narrow whitelist of `<strong>`, `<em>`, `<br>`. Anything else from the model is escaped. Do NOT add a richer sanitizer (no `bleach`, no `lxml`) — that's scope creep.
- For `parties` / `background` / `what_happened` / `what_hag_failed` / `amount_claimed_notes` — the schema field description says "HTML <ol>/<ul>/<p> body". The model emits these as ready-made HTML fragments. The renderer does NOT escape them. This is intentional: the schema constrains the shape, the model is trusted on these fields (strict tool-use), the validator at Fix 3 verifies them.

### Verification
```bash
# Renders a stub RechargeReport without API call:
python3 -c "
from claimsmax.recharge_report.renderer import render_to_html
from claimsmax.recharge_report.schema import RechargeReport, ClaimFiguresRow, EvidenceRow, SplitTableRow, ArgumentItem
r = RechargeReport(
    report_title='Test / Sample Trade',
    claim_type='Recharge-Failure Claim',
    report_date='29 May 2026',
    report_time='09:00',
    tagline='Test tagline sentence here.',
    version_marker='test-marker',
    claim_figures=[
        ClaimFiguresRow(row_kind='before', label='Before', value='\u20ac10,000'),
        ClaimFiguresRow(row_kind='headline', label='Conservative', value='\u20ac35,000'),
        ClaimFiguresRow(row_kind='ceiling', label='Ceiling', value='\u20ac70,000'),
    ],
    parties='<ol><li><strong>Party A:</strong> details</li></ol>',
    background='<ol><li>Background fact one</li><li>Background fact two</li></ol>',
    trade_h2_suffix='Test',
    what_happened='<p>Para 1.</p><p>Para 2.</p><p>Para 3.</p>',
    what_hag_failed='<ul><li>Failed one</li><li>Failed two</li></ul>',
    evidence_chain=[EvidenceRow(date='2024', document='doc', proves='proves x') for _ in range(5)],
    amount_claimed=[
        SplitTableRow(label='line', amount='\u20ac10,000', row_kind='item'),
        SplitTableRow(label='line', amount='\u20ac20,000', row_kind='item'),
        SplitTableRow(label='Total filed', amount='\u20ac30,000', row_kind='total'),
    ],
    amount_claimed_notes='<p>Reserves note.</p>',
    delta_conflict='Delta paragraph here.',
    arguments=[ArgumentItem(headline='Arg headline', body='Arg body line 1.<br>Arg body line 2.') for _ in range(5)],
)
out = render_to_html(r)
assert '<h2>The parties</h2>' in out
assert '<h2>What happened with the Test work</h2>' in out
assert 'Brisen' in out
assert 'evidence-table' in out
print('OK', len(out), 'bytes')
"
```

---

## Fix 3: Validator — switch from markdown-AST to HTML-AST validation against the V3 register

### Problem
`claimsmax/recharge_report/validator.py` parses markdown H2 lines (`^##\s+...`), checks against an 11-section list, applies per-section word counts. Canonical output is HTML with 7 H2s; validator must parse HTML.

### Current State
`claimsmax/recharge_report/validator.py:1-132` — 132 lines, regex-based H2 parser with code-fence handling, hardcoded 11-section list, hardcoded per-section word ranges, hardcoded total-word range (1400-2200).

### Implementation

Replace with HTML-AST validator using stdlib `html.parser` (no new dependency). Validate:
1. Exactly 7 H2 elements in the canonical EN order (3rd H2 matches `What happened with the .+ work` regex).
2. `.claim-figures` div present, with exactly 3 `.figure-row` children including one `.headline` and one `.ceiling`.
3. `.evidence-table` present with 5-9 `<tr>` rows in `<tbody>`.
4. `.split-table` present with at least 1 `tr.total` row.
5. `.delta-conflict` div present with non-empty body.
6. Total rendered body word count within `[1200, 2400]` (looser than the markdown-era range to accommodate HTML structure).

```python
"""HTML-AST blocking validator for rendered RechargeReport HTML.

Enforces: exact 7 H2 set in canonical order (with templated 'What happened with the <X> work'),
required visual primitives (claim-figures triplet, evidence-table 5-9 rows, split-table with total,
delta-conflict block), and total word range. Raises ValidationError on any violation.
"""
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


TOTAL_WORD_RANGE: tuple[int, int] = (1_200, 2_400)
EVIDENCE_ROW_RANGE: tuple[int, int] = (5, 9)

CANONICAL_H2_EXACT: list[str] = [
    "The parties",
    "Background",
    # slot 2 is the templated "What happened with the <X> work" — regex-matched.
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
        self._stack: list[tuple[str, dict]] = []
        self._in_h2 = False
        self._h2_buf: list[str] = []
        self._in_evidence_tbody = False
        self._in_split_table = False

    def _parent_has_class(self, klass: str) -> bool:
        return any(klass in (a.get("class", "").split()) for _, a in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        classes = attr_dict.get("class", "").split()
        self._stack.append((tag, attr_dict))

        if tag == "h2":
            self._in_h2 = True
            self._h2_buf = []
        elif tag == "div" and "figure-row" in classes:
            if self._parent_has_class("claim-figures"):
                kind = (
                    "headline" if "headline" in classes
                    else "ceiling" if "ceiling" in classes
                    else "before"
                )
                self.r.claim_figure_kinds.append(kind)
        elif tag == "table" and "evidence-table" in classes:
            pass  # tracked via parent stack
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

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack[-1][0] == tag:
            self._stack.pop()
        if tag == "h2":
            self.r.h2_texts.append("".join(self._h2_buf).strip())
            self._in_h2 = False
        if tag == "tbody":
            self._in_evidence_tbody = False
        if tag == "table" and self._in_split_table:
            # Crude: assume one split-table per report. If multiple, refine.
            self._in_split_table = False

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_buf.append(data)
        inside_style_or_script = any(t in ("style", "script", "head") for t, _ in self._stack)
        if not inside_style_or_script and data.strip():
            self.r.body_text.append(data)


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
        findings.append(ValidationFinding(
            "h2_count",
            f"Expected exactly 7 H2 elements; found {len(parsed.h2_texts)}. Actual: {parsed.h2_texts}",
        ))
    else:
        expected_order = (
            CANONICAL_H2_EXACT[:2] + [WHAT_HAPPENED_RE] + CANONICAL_H2_EXACT[2:]
        )
        for idx, (got, expected) in enumerate(zip(parsed.h2_texts, expected_order)):
            if isinstance(expected, str):
                if got != expected:
                    findings.append(ValidationFinding(
                        f"h2_order:{idx}",
                        f"H2[{idx}] expected {expected!r}, got {got!r}",
                    ))
            else:
                if not expected.match(got):
                    findings.append(ValidationFinding(
                        f"h2_order:{idx}",
                        f"H2[{idx}] expected pattern {expected.pattern!r}, got {got!r}",
                    ))

    if len(parsed.claim_figure_kinds) != 3:
        findings.append(ValidationFinding(
            "claim_figures_count",
            f"Expected exactly 3 .figure-row inside .claim-figures; found {len(parsed.claim_figure_kinds)}",
        ))
    else:
        if "headline" not in parsed.claim_figure_kinds:
            findings.append(ValidationFinding("claim_figures_headline", "Missing .headline figure-row"))
        if "ceiling" not in parsed.claim_figure_kinds:
            findings.append(ValidationFinding("claim_figures_ceiling", "Missing .ceiling figure-row"))

    if not (EVIDENCE_ROW_RANGE[0] <= parsed.evidence_row_count <= EVIDENCE_ROW_RANGE[1]):
        findings.append(ValidationFinding(
            "evidence_row_count",
            f"Evidence-table row count {parsed.evidence_row_count} outside {EVIDENCE_ROW_RANGE}",
        ))

    if parsed.split_total_rows < 1:
        findings.append(ValidationFinding(
            "split_table_total",
            "split-table is missing the required <tr class='total'> row",
        ))

    if not parsed.has_delta_conflict:
        findings.append(ValidationFinding("delta_conflict", "Missing .delta-conflict accent block"))

    total = _word_count(parsed.body_text)
    if not (TOTAL_WORD_RANGE[0] <= total <= TOTAL_WORD_RANGE[1]):
        findings.append(ValidationFinding(
            "total_word_count",
            f"Total body word count {total} outside canonical range {TOTAL_WORD_RANGE}",
        ))

    if findings:
        msg = "Rendered RechargeReport failed canonical V3 validation:\n" + "\n".join(
            f"  - [{f.rule}] {f.detail}" for f in findings
        )
        raise RechargeReportValidationError(msg)
```

### Key Constraints
- Use stdlib `html.parser`. Do NOT add `beautifulsoup4` or `lxml` — keep dep footprint small.
- The stack-walk logic is hand-rolled. Run the V2 Lohberger HTML through the validator (AC3) as the primary correctness check; if any rule fires false-positive on V2, fix the parser rule rather than loosening the validator constraint.
- Rename the public symbol: `validate_recharge_report` → `validate_recharge_report_html`. Update all callers (generator.py at fix 4, test file at fix 5).

### Verification
```bash
python3 -c "
from pathlib import Path
from claimsmax.recharge_report.validator import validate_recharge_report_html
html_str = Path.home().joinpath(
    'baker-vault/wiki/matters/hagenauer-rg7/curated/'
    '2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html'
).read_text(encoding='utf-8')
validate_recharge_report_html(html_str)
print('OK V2 Lohberger validates clean')
"
```

---

## Fix 4: Generator — read skill bundle at runtime; switch thinking to adaptive; render HTML; rename validator call

### Problem
`claimsmax/recharge_report/generator.py` bakes the 11-section system prompt inline and reads only the markdown scaffold. Two more bugs: `thinking={'type':'enabled', 'budget_tokens':8000}` rejected by Opus 4.7 (must be `'adaptive'`); validator import name will change.

### Current State
`claimsmax/recharge_report/generator.py:1-115` — 115 lines. `_system_prompt(scaffold_text)` hardcodes 11-section guidance. `_call()` uses `thinking={"type": "enabled", "budget_tokens": EXTENDED_THINKING_BUDGET}` (line 89). Imports markdown renderer + markdown validator.

### Implementation

```python
"""Anthropic tool-use orchestrator for RechargeReport.

Reads the canonical pichler-report-english skill at runtime from baker-vault:
  - SKILL.md (EN-only entry point)
  - spine.md (shared spine: structure + 5 hard rules + structural deltas)
  - V3 HTML template (binding visual contract)

Bundles all three into the cached system prompt with cache_control: ephemeral.
Future spine.md edits propagate to CLI output without a code change.

Single entry point: generate_recharge_report(facts_for_trade, model_tier='high').
"""
import logging
import os
from pathlib import Path
from typing import Literal

import anthropic

from .renderer import CANONICAL_TEMPLATE_PATH, render_to_html
from .schema import RechargeReport
from .validator import RechargeReportValidationError, validate_recharge_report_html

log = logging.getLogger(__name__)

MODEL_HIGH = "claude-opus-4-7"
MODEL_ROUTINE = "claude-sonnet-4-6"

_VAULT = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
SKILL_FILE_PATH = _VAULT / "_ops/skills/pichler-report-english/SKILL.md"
SPINE_FILE_PATH = _VAULT / "_ops/skills/pichler-report/spine.md"


class RechargeReportGenerationError(Exception):
    """Raised after final validation failure (post-retry)."""


def _read_skill_bundle(template_path: Path) -> tuple[str, str, str]:
    """Read the 3-file skill bundle. Raises FileNotFoundError if any is missing."""
    for p in (SKILL_FILE_PATH, SPINE_FILE_PATH, template_path):
        if not p.exists():
            raise FileNotFoundError(f"Skill bundle file missing: {p}")
    return (
        SKILL_FILE_PATH.read_text(encoding="utf-8"),
        SPINE_FILE_PATH.read_text(encoding="utf-8"),
        template_path.read_text(encoding="utf-8"),
    )


def _system_prompt(skill_md: str, spine_md: str, template_html: str) -> list[dict]:
    """Cached system block: skill + spine + V3 HTML template. Cache hits across trades."""
    return [
        {
            "type": "text",
            "text": (
                "You are producing the Director-facing Pichler V3 recharge-failure report "
                "for an English-reading counterparty audience. You must comply with the "
                "canonical pichler-report-english skill, the shared spine, and the V3 HTML "
                "binding contract. Emit ONLY a single tool call with the schema fields. "
                "Do not narrate around the tool call. Do not propose new sections.\n\n"
                "=== SKILL: pichler-report-english ===\n\n" + skill_md + "\n\n"
                "=== SPINE (shared with bilingual sibling) ===\n\n" + spine_md + "\n\n"
                "=== V3 HTML BINDING TEMPLATE ===\n\n" + template_html + "\n\n"
                "PER-SECTION TARGETS (lift first-pass success):\n"
                "  - parties: 120-160 words, HTML <ol> with 2-4 <li> items.\n"
                "  - background: 100-140 words, HTML <ol> with 4-6 short numbered items.\n"
                "  - what_happened: 250-320 words, 3-5 short <p> paragraphs, no bullets.\n"
                "  - what_hag_failed: 80-120 words, HTML <ul>, max 3 bullets, duplicates removed.\n"
                "  - evidence_chain: 5-9 rows total.\n"
                "  - amount_claimed: 3-6 line items + 1 total + 0-3 sub rows.\n"
                "  - amount_claimed_notes: \u2264100 words, 2 short <p>.\n"
                "  - delta_conflict: 60-120 words, single paragraph, lead with conflict, end with resolution path.\n"
                "  - arguments: 5-8 items, each with bolded headline + 2-3 short body lines separated by <br>.\n"
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def generate_recharge_report(
    facts_for_trade: str,
    model_tier: Literal["high", "routine"] = "high",
    template_path: Path = CANONICAL_TEMPLATE_PATH,
) -> str:
    """Return rendered HTML that has PASSED canonical V3 validation. Blocks otherwise."""
    skill_md, spine_md, template_html = _read_skill_bundle(template_path)
    model = MODEL_HIGH if model_tier == "high" else MODEL_ROUTINE
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    tool = {
        "name": "emit_recharge_report",
        "description": "Emit the 7-section Pichler V3 EN recharge-failure report.",
        "strict": True,
        "input_schema": {
            **RechargeReport.model_json_schema(),
            "additionalProperties": False,
        },
        "cache_control": {"type": "ephemeral"},
    }

    def _call(repair_note: str = "") -> RechargeReport:
        user_content = (
            facts_for_trade
            if not repair_note
            else (
                facts_for_trade
                + "\n\nREPAIR NOTE: Prior attempt failed validation:\n"
                + repair_note
                + "\n\nRetry with corrected structure. Emit only the tool call."
            )
        )
        resp = client.messages.create(
            model=model,
            max_tokens=8_192,
            system=_system_prompt(skill_md, spine_md, template_html),
            tools=[tool],
            tool_choice={"type": "auto"},
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": user_content}],
        )
        tool_use_block = next(
            (b for b in resp.content if getattr(b, "type", "") == "tool_use"),
            None,
        )
        if tool_use_block is None:
            raise RechargeReportGenerationError("Model returned no tool_use block")
        return RechargeReport.model_validate(tool_use_block.input)

    report = _call()
    rendered = render_to_html(report, template_path)
    try:
        validate_recharge_report_html(rendered)
        return rendered
    except RechargeReportValidationError as e:
        log.warning("First-pass validation failed: %s", e)
        report = _call(repair_note=str(e))
        rendered = render_to_html(report, template_path)
        try:
            validate_recharge_report_html(rendered)
            return rendered
        except RechargeReportValidationError as e2:
            raise RechargeReportGenerationError(
                f"Validation failed twice; surfacing to human review. Last error:\n{e2}"
            ) from e2
```

### Key Constraints
- `thinking={'type': 'adaptive'}` is the only valid extended-thinking signature for Opus 4.7. Do NOT add `budget_tokens` back.
- `cache_control: ephemeral` on both the system block AND the tool definition — this is what makes the skill bundle cheap to reload on every cycle.
- DO NOT add network calls to fetch skill files from a remote URL. Read from disk only; vault is local. `BAKER_VAULT_PATH` override only.
- If `BAKER_VAULT_PATH` is wrong (skill files missing), raise `FileNotFoundError` early — do NOT silently fall back to a baked-in scaffold. Hard fail is the correct behavior; it surfaces "skill not reachable" instead of producing wrong-shape output.

### Verification
See AC1 in Quality Checkpoints — full live probe is the verification.

---

## Fix 5: Tests — rewrite `tests/test_recharge_report.py` against the new schema + HTML renderer + HTML validator

### Problem
`tests/test_recharge_report.py` is bound to the old 11-section markdown schema, markdown renderer, markdown validator. Every test will fail after fixes 1-4.

### Current State
`tests/test_recharge_report.py` — imports `SECTION_ORDER`, `RechargeReport` (old shape), `render_to_markdown`, `validate_recharge_report`. Helpers build `_VALID_WORDS_PER_FIELD` dict for the 11 markdown sections. Generator tests mock the Anthropic client and inject tool-use blocks.

### Implementation
Rewrite from scratch. Cover:

1. **Schema tests** — `RechargeReport` accepts a valid dict (use the Lohberger V2 HTML as ground truth: build a Python literal `dict` matching its fields). Rejects extra keys. Rejects wrong row counts (claim_figures != 3, evidence_chain < 5 or > 9, etc.). `Literal` fields reject unknown values.
2. **Renderer tests** — `render_to_html()` on a valid `RechargeReport` produces output containing all 7 H2s (including templated `What happened with the X work` for variable `X`). Output passes `validate_recharge_report_html()`. Missing slot in template raises `ValueError`.
3. **Validator tests** —
   - The Director-ratified V2 Lohberger HTML (`~/baker-vault/wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html`) passes clean. **This is the canonical pass-fixture.** Skip the test with `pytest.skip` if file missing (CI without vault).
   - Mutated copies fail with the expected `findings.rule`: drop an H2 → `h2_count`; rename Background → `h2_order:1`; drop `.headline` from claim-figures → `claim_figures_headline`; cut evidence rows to 3 → `evidence_row_count`; remove `.delta-conflict` → `delta_conflict`.
4. **Generator tests** — mock the Anthropic client; inject `tool_use_block` matching the new schema; assert `generate_recharge_report()` returns HTML that validates clean. Test the one-retry path: first call returns invalid → second call returns valid → return rendered HTML. Test the two-failure path: both calls invalid → raises `RechargeReportGenerationError`. Mock `_read_skill_bundle()` to return synthetic strings so tests don't depend on vault.
5. **CLI tests** — `scripts/recharge_report_cli.py` was not modified, but its imports need re-verification. Update help text if `--output` default extension changed (was `.md`, now `.html`); update tests accordingly.

### Key Constraints
- Use the actual V2 Lohberger HTML file as the canonical pass-fixture, gated by `BAKER_VAULT_PATH` existence.
- Mock the Anthropic client + skill-bundle reader at module level — no live API calls + no vault dependency in pytest. Live probe is AC1 only.
- Keep test runtime under 5s.

### Verification
```bash
cd ~/bm-b2
pytest tests/test_recharge_report.py -v
# Expected: every test passes.
```

---

## Fix 6: Paired baker-vault PR — add `{{slot}}` placeholders to V3 template; delete misnamed markdown template

### Problem
1. `~/baker-vault/wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html` currently has inline Lohberger content from the V3 ratification commit — no `{{slot}}` placeholders. The renderer at Fix 2 needs slots.
2. `~/baker-vault/wiki/_templates/pichler-head4-template.md` (87 lines, the old markdown scaffold) becomes dead after Fix 4 lands. Must be deleted to enforce single source of truth.

### Implementation
Open one paired baker-vault PR with both changes:
- Edit `wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html` in place: replace the Pichler/RHTB inline content with `{{slot}}` placeholders. PRESERVE all CSS, all DOM structure (cream/navy register, `.claim-figures`, `.evidence-table`, `.split-table`, `.delta-conflict`, page-break, `@media print`). Replace only the variable bits: H1 → `{{report_title}}`, claim-type div → `{{claim_type}}`, etc. The CSS block stays byte-identical. Diff this against the Lohberger V2 hand-rebuild to confirm the slot set matches the renderer's substitution dict at Fix 2.
- Delete `wiki/_templates/pichler-head4-template.md` in the same PR.

### Key Constraints
- Both PRs (baker-master + baker-vault) ship together. AC1 cannot pass without the V3 template having slots. Order: open both PRs, get both reviewed, merge baker-vault first (so the template is ready), then merge baker-master.
- Do NOT touch the Lohberger V2 curated report — it is the Director-ratified exemplar and must stay frozen.
- Do NOT change `_ops/skills/pichler-report-english/SKILL.md` or `_ops/skills/pichler-report/spine.md` — those are read-only fixtures here.

### Verification
After baker-vault PR ships:
```bash
ls ~/baker-vault/wiki/_templates/pichler-head4-template.md 2>&1
# expected: ls: ...: No such file or directory
grep -r "pichler-head4-template" ~/baker-vault ~/bm-aihead1
# expected: no matches
grep -c "{{" ~/baker-vault/wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html
# expected: \u2265 17 (one per substitution slot)
```

---

## Files Modified

- `claimsmax/recharge_report/schema.py` — rewrite: 7 EN H2 fields + visual primitive sub-models (claim_figures, evidence_chain, split-table rows, arguments). `EN_H2_ORDER` constant replaces `SECTION_ORDER`.
- `claimsmax/recharge_report/renderer.py` — rewrite: `render_to_html()` replaces `render_to_markdown()`. Canonical template path moves to `wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html`.
- `claimsmax/recharge_report/validator.py` — rewrite: `validate_recharge_report_html()` HTML-AST validator replaces markdown-AST validator. Stdlib `html.parser`, no new deps.
- `claimsmax/recharge_report/generator.py` — refactor: skill-bundle assembly, adaptive thinking, HTML rendering. Imports updated.
- `tests/test_recharge_report.py` — rewrite end-to-end.
- `scripts/recharge_report_cli.py` — minor: update help text + `--output` documentation (markdown → HTML); no functional changes.

Paired baker-vault PR (separate repo, ships first):
- `wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html` — replace inline content with `{{slot}}` placeholders.
- `wiki/_templates/pichler-head4-template.md` — delete.

## Files NOT to Touch

- `~/baker-vault/_ops/skills/pichler-report-english/SKILL.md` — canonical skill. b2 reads it; does not edit. Spine + skill changes are AH1 + Director ratification only.
- `~/baker-vault/_ops/skills/pichler-report/spine.md` — shared spine. b2 reads it; does not edit.
- `~/baker-vault/_ops/skills/pichler-report/SKILL.md` — bilingual sibling. Out of scope for this brief.
- `~/baker-vault/wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html` — Director-ratified exemplar. b2 reads it as fixture; does not modify.
- Anything in `claimsmax/` outside `recharge_report/` — out of scope.
- Any other test file in `tests/` — out of scope.

## Quality Checkpoints

1. **AC1 — Live probe on Lohberger.** Re-run the CLI on the Lohberger facts file (`/tmp/lohberger-kitchen-facts.txt`, see bus #1280). If facts file is missing, request it from hag-desk via bus before declaring AC1 blocked. First-pass output is HTML, passes `validate_recharge_report_html()` without invoking the repair retry. Wall-time ≤ 180s. Cost ≤ $1.
2. **AC2 — Output structural parity with V2 hand-rebuild.** Diff the AC1 output's H2 names + primitive shapes against `2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html`. All 7 H2s present + in canonical order. `.claim-figures` triplet present. `.evidence-table` present with 5-9 rows. `.split-table` present with at least 1 total row. `.delta-conflict` present. Visual register CSS classes match.
3. **AC3 — V2 fixture validates clean.** `validate_recharge_report_html()` on the V2 Lohberger HTML returns without raising.
4. **AC4 — Spine-edit propagation.** Touch `~/baker-vault/_ops/skills/pichler-report/spine.md` (append a trailing comment like `<!-- AC4 probe 2026-05-29 -->`), re-run the CLI on a stub facts file, confirm the appended comment surfaces in the system prompt (capture via debug log of `_system_prompt()` content). Revert the spine touch before commit. The test proves the runtime-read mechanism works.
5. **AC5 — Generator is a thin wrapper.** `wc -l claimsmax/recharge_report/generator.py` ≤ 130 lines. No hardcoded section names or per-section word counts inside generator.py — those live in spine.md / schema.py / system prompt assembly only.
6. **Pytest green.** `pytest tests/test_recharge_report.py -v` exits 0 with all tests passing. Literal output captured in the ship report — no "pass by inspection."
7. **Syntax check.** `python3 -c "import py_compile; py_compile.compile('claimsmax/recharge_report/<each>.py', doraise=True)"` exits 0 for all 4 module files.
8. **Singleton-guard CI.** `bash scripts/check_singletons.sh` exits 0.
9. **No new dependencies.** `git diff requirements.txt` shows no additions. Stdlib only for the HTML parser.

## Verification — full pipeline probe

```bash
# Run from ~/bm-b2.
export BAKER_VAULT_PATH=~/baker-vault
export ANTHROPIC_API_KEY="$(op read 'op://Baker API Keys/ANTHROPIC_API_KEY/credential')"

# AC3 — V2 fixture validates clean.
python3 -c "
from pathlib import Path
from claimsmax.recharge_report.validator import validate_recharge_report_html
html_str = Path('$HOME/baker-vault/wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html').read_text(encoding='utf-8')
validate_recharge_report_html(html_str)
print('AC3 PASS — V2 Lohberger validates clean')
"

# AC1 + AC2 — live probe on Lohberger facts.
if [ ! -f /tmp/lohberger-kitchen-facts.txt ]; then
  echo "AC1 BLOCKED — facts file missing; request /tmp/lohberger-kitchen-facts.txt from hag-desk via bus before retry"
  exit 1
fi
python3 scripts/recharge_report_cli.py --tier high --output /tmp/lohberger-probe.html < /tmp/lohberger-kitchen-facts.txt
python3 -c "
from claimsmax.recharge_report.validator import validate_recharge_report_html
from pathlib import Path
html_str = Path('/tmp/lohberger-probe.html').read_text(encoding='utf-8')
validate_recharge_report_html(html_str)
print('AC1 PASS — probe output validates clean on first pass')
"
echo "AC2 — diff probe vs V2 hand-rebuild manually in ship report"
diff <(grep -E '^<h2|class=\"[a-z-]+\"' /tmp/lohberger-probe.html) \
     <(grep -E '^<h2|class=\"[a-z-]+\"' $HOME/baker-vault/wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html)
```

## Anchors

- Director ratification 2026-05-29 (this AH1 chat): skill-invocation refactor path ratified after hag-desk bus arc #1280 / #1281 / #1282.
- Canonical skill location D-017 (`wiki/matters/hagenauer-rg7/curated/06_decisions_log.md`), Director-ratified 2026-05-26 evening.
- V3 register exemplar: `wiki/matters/hagenauer-rg7/curated/2026-05-26-pichler-rhtb-recharge-failure-report-v3.html`.
- V2 hand-rebuild Director-ratified this turn: `wiki/matters/hagenauer-rg7/curated/2026-05-29-lohberger-kitchen-recharge-failure-report-v2.html` (baker-vault commit `d9e70a8`).
- Predecessor brief shipped 2026-05-26 (commit `6efc3d1`, PR #267): `BRIEF_RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1` — the 11-section markdown CLI this refactor replaces.
- Wire-fix anchors: bus #1276 (thinking-API broken), bus #1280 (Lohberger probe succeeds with 2 local patches + 3 wire issues).

## Reply target

Bus-post ship report to `lead` (AI Head A) on completion. Also write `CODE_2_RETURN.md` per coordination protocol. Do NOT post directly to hag-desk — AH1 relays the outcome.
