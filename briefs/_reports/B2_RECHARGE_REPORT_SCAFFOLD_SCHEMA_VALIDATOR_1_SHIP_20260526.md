---
brief: RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1
from: b2
to: lead
status: SHIPPED
shipped_at: 2026-05-26
pr: https://github.com/vallen300-bit/baker-master/pull/267
branch: b2/recharge-report-scaffold-1
head_commit: 84ceee9d5af7caa803a270e9955a0b13b2cd25f5
dispatch_bus_id: 1186
---

# B2 ship report — RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1

## Bottom line
Shipped. PR #267 open. All 7 acceptance criteria green; zero regression vs main baseline.

## PR
- **URL:** https://github.com/vallen300-bit/baker-master/pull/267
- **Branch:** `b2/recharge-report-scaffold-1`
- **Head commit:** `84ceee9d5af7caa803a270e9955a0b13b2cd25f5`

## Files shipped (7 new + 1 mailbox)
- `claimsmax/__init__.py`
- `claimsmax/recharge_report/__init__.py`
- `claimsmax/recharge_report/schema.py` — Pydantic v2 `RechargeReport` (`extra="forbid"`, 11 fields, `SECTION_ORDER` SoT)
- `claimsmax/recharge_report/renderer.py` — slot substitution against canonical scaffold
- `claimsmax/recharge_report/validator.py` — markdown-AST blocking validator
- `claimsmax/recharge_report/generator.py` — Anthropic tool-use orchestrator (extended thinking 8k, prompt-caching, 1 repair retry, surfaces to human on 2nd failure)
- `scripts/recharge_report_cli.py` — CLI entry point
- `tests/test_recharge_report.py` — 11 unit/integration tests
- `briefs/_tasks/CODE_2_PENDING.md` — status flipped PENDING → COMPLETE on ship

## AC1-7 verdicts

| AC | Status | Evidence |
|----|--------|----------|
| AC1 — 11 tests pass | PASS | `pytest tests/test_recharge_report.py -v` → 11 passed in 0.19s |
| AC2 — py_compile clean | PASS | All 5 NEW Python files compile clean |
| AC3 — model_json_schema emits | PASS | Schema emits 11 fields |
| AC4 — CLI smoke success | PASS | Mocked Anthropic → CLI exit 0, file passes validator on re-read |
| AC5 — CLI fail path → exit 3 | PASS | Mocked persistent failure → 2 API calls, exit 3, no file written |
| AC6 — full suite no regression | PASS | 2305 passed (baseline 2294, +11 = my tests); 117 failed + 40 errors all pre-existing (confirmed via `git stash -u` baseline run) |
| AC7 — compile-clean on 5 NEW files | PASS | Covered under AC2 |

## Test output (AC1, literal)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b2
plugins: langsmith-0.7.38, anyio-4.12.1
collected 11 items

tests/test_recharge_report.py::test_schema_rejects_extra_fields PASSED   [  9%]
tests/test_recharge_report.py::test_schema_requires_all_11_fields PASSED [ 18%]
tests/test_recharge_report.py::test_renderer_substitutes_all_slots PASSED [ 27%]
tests/test_recharge_report.py::test_renderer_missing_template_raises PASSED [ 36%]
tests/test_recharge_report.py::test_validator_passes_canonical_report PASSED [ 45%]
tests/test_recharge_report.py::test_validator_blocks_extra_heading PASSED [ 54%]
tests/test_recharge_report.py::test_validator_blocks_reordered_headings PASSED [ 63%]
tests/test_recharge_report.py::test_validator_blocks_oversize_section PASSED [ 72%]
tests/test_recharge_report.py::test_validator_blocks_undersize_total PASSED [ 81%]
tests/test_recharge_report.py::test_generator_retries_once_on_validation_fail PASSED [ 90%]
tests/test_recharge_report.py::test_generator_surfaces_after_two_failures PASSED [100%]

============================== 11 passed in 0.19s ==============================
```

## CLI smoke (AC4 — mocked Anthropic, literal stdout/stderr)

```
=== AC4: CLI smoke success ===
exit_code=0
file_exists=True
validator on re-read: PASS
first 200 chars:
## Executive summary

word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word wor

=== AC5: CLI exits 3 on persistent failure ===
exit_code=3
file_not_written=True
```

Smoke runner is `/tmp/recharge_smoke.py` (not committed — operating tool only).

## Full-suite baseline diff (AC6)

- **Without my branch** (`git stash -u` against main HEAD `03470c31`): `117 failed, 2294 passed, 259 skipped, 40 errors in 77.40s`
- **With my branch**: `117 failed, 2305 passed, 259 skipped, 40 errors in 77.11s`
- **Delta:** +11 passed (= my 11 new tests). Zero new failures, zero new errors. Pre-existing fails: missing `dateutil`, MCP vault tools env-bound, ClickUp mock/int comparisons, Gmail OAuth env, cortex stream asyncio markers — all unrelated to recharge_report module.

## Out of scope (per brief — not touched)
- `~/baker-vault/wiki/_templates/pichler-head4-template.md` (AH1 lane)
- `~/baker-vault/_ops/skills/claimsmax-recharge-investigation-pipeline/SKILL.md` Phase 6 update (AH1 lane)
- Bilingual DE+EN handling (AH1 follow-on after 5-trade bake-off)
- Backfill of 10 already-shipped V2 reports (Director authorization required)
- Dashboard UI; `outputs/dashboard.py`; sibling `claimsmax/*.py` modules

## Notes for AH1 / Hag Desk
1. CLI requires `ANTHROPIC_API_KEY` in env when run against the live API. Until the canonical template lands at `/Users/dimitry/baker-vault/wiki/_templates/pichler-head4-template.md`, callers must pass `--template <path>` (or the renderer raises `FileNotFoundError`).
2. Strict tool schema is enabled via `extra_headers={"anthropic-beta": "tools-strict-2025-01"}` per brief. If Anthropic has since renamed the beta flag, swap the constant `STRICT_TOOLS_BETA` in `generator.py` — single source of truth.
3. Extended-thinking budget is fixed at 8,000 tokens (brief constraint — do not raise without Director ratification).
4. Validator is BLOCKING — never warns. `RechargeReportValidationError` is the single boundary; `RechargeReportGenerationError` surfaces after the second failure.
5. Tests assume Python 3.12. Local repo `python3` defaulted to 3.9 (PEP-604 union syntax in `memory/store_back.py` blocks conftest); use `/opt/homebrew/bin/python3.12 -m pytest`.

## V0.2 fold addendum (bus #1189 Gate-1 fail → fix)

Gate-1 returned FAIL on PR #267 V0.1 (2 CRITICAL + 2 HIGH + 2 MED). Mock-based tests masked live-API surface issues. All 6 findings folded on same branch (commit `af59cd02`); 12th test added.

| # | Severity | Fix | File |
|---|----------|-----|------|
| C1 | CRITICAL | `tool_choice` → `{'type': 'auto'}` (forced choice + extended thinking = API 400) | `generator.py` |
| C2 | CRITICAL | Drop `anthropic-beta: tools-strict-2025-01` (flag does not exist); add `'strict': True` on tool def | `generator.py` |
| H1 | HIGH | Patch `additionalProperties: False` into `input_schema` (defensive lock) | `generator.py` |
| H2 | HIGH | Validator tracks `in_fence` toggle; `## X` inside ``` ``` never splits sections | `validator.py` |
| M1 | MED | `CANONICAL_TEMPLATE_PATH` reads `BAKER_VAULT_PATH` env with `~/baker-vault` fallback | `renderer.py` |
| M2 | MED | Guard `section_order_or_set` with `len(sections)==11` (no double-finding on count mismatch) | `validator.py` |

**New test:** `test_validator_ignores_h2_in_fenced_code_block` — fenced `## Imposter` line must not split section count.

**Re-verification after fold:**
- AC1 `pytest tests/test_recharge_report.py -v` → **12/12 PASS** (0.27s)
- AC2/AC7 py_compile clean on all 5 NEW files
- AC4 CLI smoke (mocked) → exit 0, validator re-read PASS
- AC5 CLI persistent-fail → exit 3, no file written
- AC6 full `pytest -q` → 2306 passed (+12 vs baseline 2294); 117 failed + 40 errors all pre-existing (zero new regressions)

**New HEAD:** `af59cd021647641d1203f6bbc9d711a56440d5ed`. Same branch; not force-pushed (additive commit).

---

## Anchors
- Dispatch bus #1186 (lead → b2, 2026-05-26T17:34Z)
- Gate-1 fail bus #1189 (lead → b2, 2026-05-26T17:57Z)
- Brief: `briefs/BRIEF_RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1.md`
- Diagnosis bus #1178 (hag-desk → lead)
- Research bus #1180 (round-1) + #1185 (round-2) → `wiki/research/2026-05-26-template-drift-prior-art.md`
- Director ratification 2026-05-26 chat: *"follow your recommends and proceed"*
- Pattern anchor: WRITE_BRIEF_SOP_ENFORCER (zero brief-drift over 2 weeks)
