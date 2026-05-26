# BRIEF: RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1 — Lock the Director-facing recharge-report shape via scaffold + Pydantic schema + blocking markdown-AST validator

## Context

Pichler/HEAD-4 (2026-05-25) is the canonical Director-facing recharge-failure report: 11 H2 sections, ~1,800 words, English-only, declarative tone. Over the next 2 weeks, 10 follow-up trade reports drifted to 14-16 sections and 3,500-4,000 words; today's V2 work added a Mehrkosten/Differenzmethode section not in the SOP. Bath Waterproofing draft repeated the overshoot (14 H2 vs spec 11). Full diagnosis on bus #1178 (hag-desk → lead).

Director's bar for good (2026-05-26): output must resemble the template **by construction** — spirit, message, format, size, presentation. No post-hoc correction. Structure fixed; content free.

Researcher's prior-art survey (bus #1180 + bus #1185, file `wiki/research/2026-05-26-template-drift-prior-art.md`) confirms production consensus is **hybrid scaffold + Pydantic schema + blocking markdown-AST validator**. Pattern lifts cleanly from WRITE_BRIEF_SOP_ENFORCER (zero brief-drift over 2 weeks). Adversarial sweep found no credible direct attack.

Director-ratified 2026-05-26 chat: ratify core design lock, approve 5-trade bilingual bake-off plan, confirm extended-thinking on Mehrkosten section.

### Surface contract: N/A — Python module + CLI + canonical markdown template. No dashboard UI, no API endpoint, no clickable surface. Used by Hag Desk via CLI invocation per claimsmax-recharge SOP Phase 6. Validated by unit + integration tests.

## Estimated time: ~7h
## Complexity: Medium
## Prerequisites: anthropic Python client (already in baker-master), Pydantic v2 (already), markdown-it-py or python-markdown (verify presence, add if missing)

---

## Fix 1: Canonical scaffold template file (baker-vault)

### Problem
Today the canonical Pichler/HEAD-4 shape lives only in `_ops/skills/claimsmax-recharge-investigation-pipeline/SKILL.md` prose. Authors drift because there is no physical template they fork from; they fork from the last similar report and accumulate drift.

### Current state
SKILL.md §Phase 6 lines 175-191 describe the 11-section spec in prose. Canonical realization at `wiki/matters/hagenauer-rg7/curated/2026-05-25-pichler-head-4-recharge-failure-report.html` (HTML render). No machine-readable template file.

### Implementation
Create NEW canonical markdown scaffold at `~/baker-vault/wiki/_templates/pichler-head4-template.md` with the 11 H2 sections in canonical order. Each H2 has a `{{slot_name}}` Jinja2-style placeholder under it. The H2 headings themselves are owned by the file — authors NEVER edit headings, only slot content.

Section list (canonical, from SKILL.md Phase 6):
1. Executive summary
2. Scope of this report
3. Counterparty and contract structure
4. Evidence base
5. Cost reconstruction — what was paid, by whom
6. Recharge basis — why the counterparty owes
7. Counterparty defence anticipated
8. Mehrkosten / Differenzmethode (single optional Delta-Conflict paragraph, NOT an H2 of its own — folded into §5)
9. Risks and open questions
10. Numbers we are claiming
11. Recommendation

Per-section word target carried as an HTML comment under each H2: `<!-- target: 150-180 words, declarative, no bullets -->`.

### Key constraint
Template is READ-ONLY in the runtime path. PR-gated revision only (i.e. version-bump via commit). Any author trying to write to this file fails the validator.

### AH1 owns vault write
This file goes into baker-vault via AH1 commit (B2 does NOT push to baker-vault). B2 references the template path; AH1 lands the template + SOP update in same session.

### Files NOT modified by B2
- `~/baker-vault/wiki/_templates/pichler-head4-template.md` — AH1 lands separately.

---

## Fix 2: Pydantic schema — `RechargeReport`

### Problem
Schema-less scaffold leaves the loophole open: an author who edits the template per run still drifts; a schema-bound author cannot add a 12th field without changing code.

### Implementation
Create NEW `claimsmax/recharge_report/schema.py` with the following Pydantic v2 model (canonical, no deviations):

```python
"""Recharge-report schema — Pydantic v2 model bound to the 11-section Pichler/HEAD-4
canonical template. Each field maps 1:1 to a {{slot}} in the scaffold. No optional
fields, no extras, no defaults.

Section count and order are the contract — do NOT modify without Director ratification.
"""
from pydantic import BaseModel, Field, ConfigDict


class RechargeReport(BaseModel):
    """The 11-section Director-facing recharge-failure report. Each field is one H2 slot."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    executive_summary: str = Field(
        description=(
            "2-4 sentences. Bottom-line outcome of the recharge attempt. "
            "Declarative, no bullets, no subordinate headings. Target ~120-150 words."
        )
    )
    scope_of_report: str = Field(
        description=(
            "2-3 sentences naming the trade, time window, counterparty, "
            "and the recharge claim being evaluated. Target ~100-120 words."
        )
    )
    counterparty_and_contract: str = Field(
        description=(
            "Counterparty identity, contract reference, and legal basis "
            "for the recharge attempt. Target ~150-180 words."
        )
    )
    evidence_base: str = Field(
        description=(
            "Numbered list (1-5) of evidence items: invoices, payment records, "
            "site reports, expert opinions. Cite document refs. Target ~180-220 words."
        )
    )
    cost_reconstruction: str = Field(
        description=(
            "What was paid, by whom, to whom. Include the single Delta-Conflict "
            "paragraph (Mehrkosten/Differenzmethode) here if applicable — NOT as a "
            "separate H2. Reasoning may use extended-thinking mode. Target ~200-250 words."
        )
    )
    recharge_basis: str = Field(
        description=(
            "Legal and factual basis for why the counterparty owes the claimed amount. "
            "Cite contract clauses + statute where relevant. Target ~150-180 words."
        )
    )
    counterparty_defence: str = Field(
        description=(
            "Anticipated counterparty defence with at least one named, foreseeable "
            "argument and our planned response. Target ~150-180 words."
        )
    )
    risks_and_open_questions: str = Field(
        description=(
            "Numbered list of open risks, missing evidence, or decisions "
            "pending Ofenheimer / Bauer review. Target ~120-150 words."
        )
    )
    numbers_claimed: str = Field(
        description=(
            "Single paragraph stating the claim quantum: filed EUR, Vorbehalt EUR, "
            "sub-positions if any. Numbers cited with source. Target ~80-120 words."
        )
    )
    recommendation: str = Field(
        description=(
            "Director-facing recommendation in 1-2 sentences. Names the action and "
            "the responsible party. Target ~50-80 words."
        )
    )
    anchors: str = Field(
        description=(
            "Provenance: source docs, vault paths, ratification anchors, date verified. "
            "Numbered list. Target ~80-120 words."
        )
    )


# Canonical H2 heading-to-field map (for renderer + validator). KEEP IN SYNC.
SECTION_ORDER: list[tuple[str, str]] = [
    ("Executive summary", "executive_summary"),
    ("Scope of this report", "scope_of_report"),
    ("Counterparty and contract structure", "counterparty_and_contract"),
    ("Evidence base", "evidence_base"),
    ("Cost reconstruction — what was paid, by whom", "cost_reconstruction"),
    ("Recharge basis — why the counterparty owes", "recharge_basis"),
    ("Counterparty defence anticipated", "counterparty_defence"),
    ("Risks and open questions", "risks_and_open_questions"),
    ("Numbers we are claiming", "numbers_claimed"),
    ("Recommendation", "recommendation"),
    ("Anchors", "anchors"),
]

assert len(SECTION_ORDER) == 11, "Canonical Pichler/HEAD-4 contract is exactly 11 sections"
```

### Key constraint
`extra="forbid"` blocks the LLM from inventing fields. `SECTION_ORDER` is the canonical heading-to-field map; renderer + validator both read from it (single source of truth).

### Files modified
- NEW: `claimsmax/recharge_report/__init__.py` — empty package marker
- NEW: `claimsmax/recharge_report/schema.py` — code above verbatim

---

## Fix 3: Scaffold renderer + markdown-AST blocking validator

### Problem
A schema-bound emit + a scaffold-render still needs a downstream check: word counts within tolerance, exact heading set, order preserved. Without a blocking validator the author can still hand-edit the rendered file and re-introduce drift.

### Implementation

#### 3a — Renderer

Create NEW `claimsmax/recharge_report/renderer.py`:

```python
"""Render RechargeReport into the canonical Pichler/HEAD-4 markdown scaffold."""
from pathlib import Path
from .schema import RechargeReport, SECTION_ORDER


CANONICAL_TEMPLATE_PATH = Path("/Users/dimitry/baker-vault/wiki/_templates/pichler-head4-template.md")


def render_to_markdown(report: RechargeReport, template_path: Path = CANONICAL_TEMPLATE_PATH) -> str:
    """Substitute report fields into scaffold template. Returns rendered markdown."""
    if not template_path.exists():
        raise FileNotFoundError(f"Canonical template missing at {template_path}")
    template = template_path.read_text(encoding="utf-8")
    data = report.model_dump()
    rendered = template
    for heading, field in SECTION_ORDER:
        slot = "{{" + field + "}}"
        if slot not in rendered:
            raise ValueError(f"Template missing slot for field {field!r} (expected {slot!r})")
        rendered = rendered.replace(slot, data[field])
    # Sanity check: no unfilled slots remain.
    if "{{" in rendered:
        unfilled = [line.strip() for line in rendered.splitlines() if "{{" in line]
        raise ValueError(f"Template has unfilled slots after render: {unfilled}")
    return rendered
```

#### 3b — Validator

Create NEW `claimsmax/recharge_report/validator.py`:

```python
"""Markdown-AST blocking validator for rendered RechargeReport markdown.

Enforces: exact 11 H2 set, canonical order, per-section word range,
total word range. Raises ValidationError on any violation. Blocks save.
"""
import re
from dataclasses import dataclass
from .schema import SECTION_ORDER

# Per-section word target ranges (tolerance ±30% per researcher recommendation).
WORD_TARGETS: dict[str, tuple[int, int]] = {
    "executive_summary": (84, 195),       # 120-150 ±30%
    "scope_of_report": (70, 156),         # 100-120 ±30%
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

TOTAL_WORD_RANGE: tuple[int, int] = (1_400, 2_200)  # 1,800 ±~20%


class RechargeReportValidationError(Exception):
    """Raised when a rendered report violates the canonical contract."""


@dataclass
class ValidationFinding:
    rule: str
    detail: str


def _parse_h2_sections(markdown: str) -> list[tuple[str, str]]:
    """Return [(heading_text, body_text), ...] in document order. H2 = lines beginning '## '."""
    lines = markdown.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_body: list[str] = []
    for line in lines:
        m = re.match(r'^##\s+(.+?)\s*$', line)
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
    """Count whitespace-separated tokens, excluding markdown punctuation-only artifacts."""
    return len([t for t in re.split(r'\s+', text.strip()) if t and not re.fullmatch(r'[\W_]+', t)])


def validate_recharge_report(markdown: str) -> None:
    """Validate rendered markdown. Raises RechargeReportValidationError on failure."""
    findings: list[ValidationFinding] = []
    sections = _parse_h2_sections(markdown)
    actual_headings = [h for h, _ in sections]
    canonical_headings = [h for h, _ in SECTION_ORDER]

    if len(sections) != 11:
        findings.append(ValidationFinding(
            "section_count",
            f"Expected exactly 11 H2 sections; found {len(sections)}. "
            f"Actual: {actual_headings}"
        ))

    if actual_headings != canonical_headings:
        findings.append(ValidationFinding(
            "section_order_or_set",
            f"H2 headings drift from canonical. Expected {canonical_headings}; "
            f"got {actual_headings}"
        ))

    # Per-section word range (only check sections that line up by name).
    by_heading = {h: b for h, b in sections}
    for heading, field in SECTION_ORDER:
        if heading not in by_heading:
            continue
        wc = _word_count(by_heading[heading])
        lo, hi = WORD_TARGETS[field]
        if wc < lo or wc > hi:
            findings.append(ValidationFinding(
                f"word_count:{field}",
                f"Section {heading!r} ({field}) word count {wc} outside [{lo}, {hi}]"
            ))

    # Total word range.
    total = sum(_word_count(b) for _, b in sections)
    if total < TOTAL_WORD_RANGE[0] or total > TOTAL_WORD_RANGE[1]:
        findings.append(ValidationFinding(
            "total_word_count",
            f"Total word count {total} outside canonical range {TOTAL_WORD_RANGE}"
        ))

    if findings:
        msg = "Rendered RechargeReport failed canonical validation:\n" + \
              "\n".join(f"  - [{f.rule}] {f.detail}" for f in findings)
        raise RechargeReportValidationError(msg)
```

### Key constraint
Validator BLOCKS (raises) on any single violation — never warns. Caller decides whether to retry or surface to human.

### Files modified
- NEW: `claimsmax/recharge_report/renderer.py`
- NEW: `claimsmax/recharge_report/validator.py`

---

## Fix 4: Anthropic tool-use orchestrator with extended thinking

### Problem
Need a single entry point that takes trade-facts + invokes claude-opus-4-7 / sonnet-4-6 via tool-use with `strict: true`, prompt-caches the scaffold + tool def, enables extended thinking for `cost_reconstruction` (Mehrkosten reasoning), validates the rendered output, retries once on failure, and surfaces to human on second failure.

### Implementation

Create NEW `claimsmax/recharge_report/generator.py`:

```python
"""Anthropic tool-use orchestrator for RechargeReport.

Single entry point: generate_recharge_report(facts_for_trade, model_tier="high").
- Loads canonical scaffold template (read-only).
- Calls claude-opus-4-7 (high) or claude-sonnet-4-6 (routine) via tool-use,
  strict=True, prompt-caching on tool def + scaffold.
- Extended thinking enabled (8000-token budget) for Mehrkosten reasoning.
- Validates rendered markdown; one repair retry on ValidationError; surfaces to human on second failure.
"""
import os
import logging
from pathlib import Path
from typing import Literal
import anthropic
from .schema import RechargeReport
from .renderer import render_to_markdown, CANONICAL_TEMPLATE_PATH
from .validator import validate_recharge_report, RechargeReportValidationError

log = logging.getLogger(__name__)

MODEL_HIGH = "claude-opus-4-7"
MODEL_ROUTINE = "claude-sonnet-4-6"
EXTENDED_THINKING_BUDGET = 8_000


class RechargeReportGenerationError(Exception):
    """Raised after final validation failure (post-retry)."""


def _system_prompt(scaffold_text: str) -> list[dict]:
    """Cached system block: scaffold + tone guide. Cache hits on every subsequent trade."""
    return [
        {
            "type": "text",
            "text": (
                "You are producing the Director-facing Pichler/HEAD-4 recharge-failure report. "
                "Use the canonical scaffold below. Emit ONLY a single tool call with the 11 "
                "schema fields. Do not narrate around the tool call. Do not propose new sections. "
                "Declarative tone, no bullets within paragraphs, no subordinate headings.\n\n"
                "CANONICAL SCAFFOLD (do not modify):\n\n" + scaffold_text
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def generate_recharge_report(
    facts_for_trade: str,
    model_tier: Literal["high", "routine"] = "high",
    template_path: Path = CANONICAL_TEMPLATE_PATH,
) -> str:
    """Returns rendered markdown that has PASSED canonical validation. Blocks otherwise."""
    scaffold_text = template_path.read_text(encoding="utf-8")
    model = MODEL_HIGH if model_tier == "high" else MODEL_ROUTINE
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    tool = {
        "name": "emit_recharge_report",
        "description": "Emit the 11-section Pichler/HEAD-4 recharge-failure report.",
        "input_schema": RechargeReport.model_json_schema(),
        "cache_control": {"type": "ephemeral"},
    }

    def _call(repair_note: str = "") -> RechargeReport:
        user_content = facts_for_trade if not repair_note else (
            facts_for_trade + "\n\nREPAIR NOTE: Prior attempt failed validation:\n" + repair_note +
            "\n\nRetry with corrected structure. Emit only the tool call."
        )
        resp = client.messages.create(
            model=model,
            max_tokens=8_192,
            system=_system_prompt(scaffold_text),
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit_recharge_report"},
            thinking={"type": "enabled", "budget_tokens": EXTENDED_THINKING_BUDGET},
            messages=[{"role": "user", "content": user_content}],
            extra_headers={"anthropic-beta": "tools-strict-2025-01"},  # strict tool schema flag
        )
        # response.content is a list of blocks; tool_use block carries the dict.
        tool_use_block = next(
            (b for b in resp.content if getattr(b, "type", "") == "tool_use"),
            None,
        )
        if tool_use_block is None:
            raise RechargeReportGenerationError("Model returned no tool_use block")
        return RechargeReport.model_validate(tool_use_block.input)

    # Pass 1.
    report = _call()
    markdown = render_to_markdown(report, template_path)
    try:
        validate_recharge_report(markdown)
        return markdown
    except RechargeReportValidationError as e:
        log.warning("First-pass validation failed: %s", e)
        # Pass 2 (repair).
        report = _call(repair_note=str(e))
        markdown = render_to_markdown(report, template_path)
        try:
            validate_recharge_report(markdown)
            return markdown
        except RechargeReportValidationError as e2:
            raise RechargeReportGenerationError(
                f"Validation failed twice; surfacing to human review. Last error:\n{e2}"
            ) from e2
```

### Key constraints
- `model` literal MUST be `claude-opus-4-7` for HIGH tier, `claude-sonnet-4-6` for routine (per CLAUDE.md and researcher round-2). Do NOT substitute older model IDs.
- `strict` tool schema mode enabled via `extra_headers={"anthropic-beta": "tools-strict-2025-01"}` (verify exact beta flag against current Anthropic docs at https://platform.claude.com/docs at build time).
- Extended thinking budget capped at 8,000 tokens — Mehrkosten reasoning fits inside; do NOT raise without Director ratification (cost risk).
- One repair retry only. Second failure surfaces to human — do NOT loop indefinitely.
- Prompt caching: scaffold (system block) + tool def both marked `cache_control: ephemeral`. 5-min TTL. Cache hits across consecutive trades amortize 10x.

### Files modified
- NEW: `claimsmax/recharge_report/generator.py`

---

## Fix 5: CLI entry point + integration test

### Problem
Hag Desk currently runs the workflow manually (paste facts → run report → paste into vault). The CLI is the single Phase-6 command in the updated SOP.

### Implementation

Create NEW `scripts/recharge_report_cli.py`:

```python
#!/usr/bin/env python3
"""Recharge-report CLI. Reads facts from stdin (or --facts-file), writes
rendered markdown to stdout (or --output). Validates before writing.

Usage:
  python scripts/recharge_report_cli.py --tier high --output report.md < facts.txt
  python scripts/recharge_report_cli.py --tier routine --facts-file facts.txt --output report.md
"""
import argparse
import sys
from pathlib import Path
from claimsmax.recharge_report.generator import generate_recharge_report, RechargeReportGenerationError


def main() -> int:
    p = argparse.ArgumentParser(description="Generate canonical Pichler/HEAD-4 recharge report.")
    p.add_argument("--tier", choices=["high", "routine"], default="high")
    p.add_argument("--facts-file", type=Path, help="Path to facts text file (default: stdin)")
    p.add_argument("--output", type=Path, help="Output markdown path (default: stdout)")
    p.add_argument("--template", type=Path, help="Override canonical template path")
    args = p.parse_args()

    facts = args.facts_file.read_text(encoding="utf-8") if args.facts_file else sys.stdin.read()
    if not facts.strip():
        print("ERROR: no facts provided", file=sys.stderr)
        return 2

    template_kwargs = {"template_path": args.template} if args.template else {}
    try:
        markdown = generate_recharge_report(facts, model_tier=args.tier, **template_kwargs)
    except RechargeReportGenerationError as e:
        print(f"ERROR: report generation failed:\n{e}", file=sys.stderr)
        return 3

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
        print(f"OK: wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Tests

Create NEW `tests/test_recharge_report.py` with these test cases (all must pass):

1. `test_schema_rejects_extra_fields` — Pydantic schema rejects an LLM-output dict with a 12th field.
2. `test_schema_requires_all_11_fields` — schema raises on any field missing.
3. `test_renderer_substitutes_all_slots` — render of a valid report has no `{{` remaining.
4. `test_renderer_missing_template_raises` — render against nonexistent template path raises FileNotFoundError.
5. `test_validator_passes_canonical_report` — fixture markdown with 11 canonical headings + word counts in range passes.
6. `test_validator_blocks_extra_heading` — fixture with 12 H2 headings raises with `section_count` finding.
7. `test_validator_blocks_reordered_headings` — fixture with same 11 headings in wrong order raises with `section_order_or_set` finding.
8. `test_validator_blocks_oversize_section` — fixture with one section at 5,000 words raises with `word_count:<field>` finding.
9. `test_validator_blocks_undersize_total` — fixture with all sections at minimum raises with `total_word_count` finding.
10. `test_generator_retries_once_on_validation_fail` — mocked Anthropic client returning a bad-then-good schema instance, generator returns markdown.
11. `test_generator_surfaces_after_two_failures` — mocked client returning bad-then-bad, generator raises `RechargeReportGenerationError`.

Mock Anthropic via `unittest.mock.patch` on `anthropic.Anthropic.messages.create`. Construct fixture markdown by composing valid sections from a builder helper inside the test file. Use Pydantic model_construct for invalid-extras paths.

### Files modified
- NEW: `scripts/recharge_report_cli.py`
- NEW: `tests/test_recharge_report.py`

---

## Out-of-scope (this brief explicitly does NOT cover)

- Bilingual DE+EN rendering. Researcher recommended 5-trade bake-off (two-pass DeepL vs single-schema `_de`/`_en`). AH1 will author a follow-on brief after this brief lands and Hag Desk has run 1-2 English-only trades through the new path.
- Other report templates (Edita V4, future MaBV). Add new templates only when a genuinely different shape appears. Schema + validator parameterize on the canonical heading-to-field map — second template = new schema + new template file + new generator entry point; the framework is reusable.
- Dashboard UI for monitoring runs (cost spend, retry rate). Surface via existing claimsmax dashboard if needed; out of scope here.
- Re-rendering the 10 already-shipped V2 reports through the new path. Director must explicitly authorize a backfill batch — this brief ships the FORWARD path only.

## Files Modified (summary)

Net NEW in baker-master:
- `claimsmax/recharge_report/__init__.py`
- `claimsmax/recharge_report/schema.py`
- `claimsmax/recharge_report/renderer.py`
- `claimsmax/recharge_report/validator.py`
- `claimsmax/recharge_report/generator.py`
- `scripts/recharge_report_cli.py`
- `tests/test_recharge_report.py`

Dependencies (verify before adding):
- `anthropic` — already in `requirements.txt` (Baker uses Claude API)
- `pydantic>=2` — already in `requirements.txt`
- No markdown parser needed (validator uses regex-based H2 parsing — explicit choice per researcher: "Normalize headings via markdown AST parser, not regex" — but regex matching `^## ` is unambiguous on our scaffold which we control; trade-off acceptable. If a future template uses indented or fenced H2s, swap to markdown-it-py at that time).

Outside baker-master (AH1 handles separately, NOT B2):
- `~/baker-vault/wiki/_templates/pichler-head4-template.md` — canonical scaffold (AH1 lands)
- `~/baker-vault/_ops/skills/claimsmax-recharge-investigation-pipeline/SKILL.md` — Phase 6 update to invoke CLI (AH1 lands)

## Do NOT Touch

- `outputs/dashboard.py` — unrelated; no dashboard surface in this brief.
- Existing `claimsmax/*.py` files — recharge_report is a new submodule. Do NOT refactor or "tidy up" sibling modules.
- `~/baker-vault/` — separate repo; AH1 lane.
- `tasks/lessons.md` — append-only by AH1 after deploy.

## Quality Checkpoints

1. `pytest tests/test_recharge_report.py -v` — all 11 tests pass with literal output (no "by inspection").
2. `python -c "from claimsmax.recharge_report.schema import RechargeReport, SECTION_ORDER; assert len(SECTION_ORDER) == 11"` — runs clean.
3. `python -c "from claimsmax.recharge_report.schema import RechargeReport; RechargeReport.model_json_schema()"` — JSON schema emits without error.
4. CLI smoke (with mocked Anthropic in test env, or `ANTHROPIC_API_KEY` set in B2's env): `echo 'TRADE: Painter, facts...' | python scripts/recharge_report_cli.py --tier routine --output /tmp/out.md` — exits 0, writes file, file passes validator on re-read.
5. End-to-end fail path: pass facts that produce a 12-section response (e.g. force the LLM to add a Mehrkosten H2) — generator surfaces `RechargeReportGenerationError` after one repair attempt; CLI exits 3.
6. `pytest -q` — full suite passes (no regression in unrelated tests).
7. `python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['claimsmax/recharge_report/schema.py', 'claimsmax/recharge_report/renderer.py', 'claimsmax/recharge_report/validator.py', 'claimsmax/recharge_report/generator.py', 'scripts/recharge_report_cli.py']]"` — all compile clean.

## Anchors

- Director ratification 2026-05-26 chat — *"follow your recommends and proceed"* (core design lock + bake-off + extended thinking).
- Researcher round-1 ship: bus #1180 → `wiki/research/2026-05-26-template-drift-prior-art.md`.
- Researcher round-2 ship: bus #1185 → §Round-2 append in same file.
- Hag-desk diagnosis: bus #1178.
- Canonical Pichler/HEAD-4 reference render: `wiki/matters/hagenauer-rg7/curated/2026-05-26-pichler-rhtb-recharge-failure-report-v3.html`.
- SOP: `_ops/skills/claimsmax-recharge-investigation-pipeline/SKILL.md` Phase 6.
- Engineering line: scaffold-first + Pydantic schema + blocking markdown-AST validator. Pattern lift from WRITE_BRIEF_SOP_ENFORCER (zero brief-drift over 2 weeks).
