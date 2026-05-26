---
dispatch: RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1
to: b2
from: lead
dispatched_by: lead
status: PENDING
dispatched_at: 2026-05-26T17:30:00Z
authored: 2026-05-26
target_repo: baker-master
estimated_time: ~7h
complexity: medium
reply_to: lead
priority: tier-a
anchor_incident: bus #1178 (hag-desk SOP drift) + bus #1180/#1185 (researcher round-1+2)
research_anchor: /Users/dimitry/baker-vault/wiki/research/2026-05-26-template-drift-prior-art.md
brief_path: briefs/BRIEF_RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1.md
---

# B2 dispatch — RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1

## Bottom line
Ship a Python module that locks the Director-facing recharge-report shape via canonical scaffold + Pydantic schema (`strict: true` Anthropic tool-use) + blocking markdown-AST validator. Pattern lifts from WRITE_BRIEF_SOP_ENFORCER (zero brief-drift over 2 weeks).

## Why now
Hag Desk surfaced template drift on bus #1178: Pichler/HEAD-4 spec is 11 sections / ~1,800 words / English; 10 follow-up trade reports drifted to 14-16 sections + ~3,500-4,000 words. Today's V2 added a Mehrkosten H2 not in the SOP. Researcher prior-art (bus #1180, #1185) confirms hybrid scaffold + schema + validator is production consensus. Director ratified 2026-05-26 chat: *"follow your recommends and proceed."*

## Scope (5 fixes — single PR)
1. Pydantic `RechargeReport` schema (11 string fields, `extra="forbid"`).
2. Scaffold renderer (substitutes fields into canonical template).
3. Markdown-AST blocking validator (11 H2s, canonical order, per-section + total word counts).
4. Anthropic tool-use orchestrator with extended thinking (`claude-opus-4-7` HIGH / `claude-sonnet-4-6` routine, `strict: true`, prompt caching, 1 repair retry).
5. CLI entry point + 11 unit/integration tests.

## Target files (all NEW)
- `claimsmax/recharge_report/__init__.py`
- `claimsmax/recharge_report/schema.py`
- `claimsmax/recharge_report/renderer.py`
- `claimsmax/recharge_report/validator.py`
- `claimsmax/recharge_report/generator.py`
- `scripts/recharge_report_cli.py`
- `tests/test_recharge_report.py`

## Out of scope
Bilingual DE+EN handling (AH1 follow-on brief after 5-trade bake-off). Backfill of already-shipped V2 reports (Director must authorize separately). Dashboard UI.

## Do NOT touch
- `outputs/dashboard.py`
- `~/baker-vault/` (AH1 lane — scaffold template + SOP update land separately).
- Any existing `claimsmax/*.py` sibling modules — no refactoring.

## Full brief
`briefs/BRIEF_RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1.md` — read first; carries copy-pasteable code snippets for schema, renderer, validator, generator, CLI, test plan.

## Acceptance criteria
1. All 11 tests pass with literal `pytest -v` output (no "by inspection").
2. Compile-clean on all 5 NEW Python files (`py_compile` doraise).
3. `RechargeReport.model_json_schema()` emits without error.
4. CLI smoke run produces a markdown file that passes the validator on re-read.
5. End-to-end fail path: 12-section response → generator raises after one repair retry → CLI exits 3.
6. Full pytest suite passes (no regression).

## Ship report contract
Reply to `lead` on the bus with: PR URL, branch, head commit, AC1-6 verdicts, smoke-test output snippet, ship report path under `briefs/_reports/B2_RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1_SHIP_*.md`.

## Anchors
- Director ratification 2026-05-26 chat — core design lock + bake-off + extended thinking.
- Researcher round-1 ship: bus #1180.
- Researcher round-2 ship: bus #1185.
- Hag-desk diagnosis: bus #1178.
- Canonical reference render: `wiki/matters/hagenauer-rg7/curated/2026-05-26-pichler-rhtb-recharge-failure-report-v3.html`.
- Pattern anchor: WRITE_BRIEF_SOP_ENFORCER (zero brief-drift over 2 weeks).
