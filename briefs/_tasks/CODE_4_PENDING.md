# CODE_4 — IN_REVIEW (BOOTSTRAP_V2_GOLD_SKIP_1)

**Status:** IN_REVIEW — PR #107 opened 2026-04-30 by B4 (awaiting B1 second-pair-of-eyes per Trigger-class rule, then AI Head A merge)
**Brief:** `briefs/BRIEF_BOOTSTRAP_V2_GOLD_SKIP_1.md`
**Builder:** B4
**Priority:** HIGH
**ETA:** 2026-05-02

## Task summary

`scripts/bootstrap_matter.py` (you shipped, PR #96) emits `gold.md` per matter. CHANDA #4 author:director guard blocks any agent-authored `gold.md` commit, so emission is wasted work that requires manual revert. Remove the emission. ~30 min.

4 manual revert drops today: capital-call, aukera, uk-homes, 12-matter batch. Stop the bleed.

## Dispatch

1. Read brief: `briefs/BRIEF_BOOTSTRAP_V2_GOLD_SKIP_1.md`
2. Branch: `b4/bootstrap-v2-gold-skip`
3. Pre-pytest re-checkout ritual.
4. **Trigger-class:** B1 second-pair-of-eyes review BEFORE AI Head A merge (touches Director-override surface). Dispatch sequence: B4 builds + opens PR → AI Head A pings B1 for review → B1 PASS → AI Head A merges.

## Previous task (closed)

PR #96 (CORTEX_BOOTSTRAP_MATTER_1) squash-merged 2026-04-30T10:27Z.
