# CODE_4 — PENDING (CORTEX_BOOTSTRAP_MATTER_1)

**From:** AI Head A
**To:** B4 (`~/bm-b4`)
**Status:** OPEN — assigned 2026-04-30 (post-V8 housekeeping window)
**Brief:** `briefs/BRIEF_CORTEX_BOOTSTRAP_MATTER_1.md` (merged baker-master `c76f39a`)
**Estimated:** ~5–6h
**Tier:** A (AI Head A merges on green, no Trigger-class match per RA-24)
**Branch:** `feature/cortex-bootstrap-matter-1`

## Prior task close

Previous task CORTEX_NOTIFICATION_DEFER_1 closed 2026-04-30T08:58Z — PR #92 merged, deploy `dep-d7phev7avr4c73e4rlp0` live, curl smoke green. Wave 2 fully closed.

## This task

Build the generic matter scaffolding generator that generalizes the precedent `scripts/bootstrap_hagenauer_wiki.py` to any matter slug. Two scripts:

1. `scripts/bootstrap_matter.py` — generates full `wiki/matters/<slug>/` directory from input YAML
2. `scripts/bootstrap_entities.py` — appends validated entity rows to staged `entities.yml`

**Reference template:** `wiki/matters/mrci/cortex-config.md` (Wave 2 Director-ratified canonical, NOT oskolkov).

**Test fixture matter:** `capital-call` slug — populate `briefs/_inputs/bootstrap_capital_call.yml` from V8 Q29 ratification (matter critical priority, this script's first real consumer).

Full spec at `briefs/BRIEF_CORTEX_BOOTSTRAP_MATTER_1.md`. All 8 verification criteria + literal pytest output mandatory in ship report.

## Coordination

- Other B-codes idle (B1/B2/B3/B5 mailboxes COMPLETE).
- No file overlap with any in-flight work.
- AI Head A is sole orchestrator for review + merge.

## Ship report path

`briefs/_reports/B4_cortex_bootstrap_matter_1_<YYYYMMDD>.md`
