# CODE_1 — PENDING (B4 PR #107 review → CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A (App)
**Priority:** CRITICAL (sequence below)

## Sequence

### Step 1 (FIRST, ~10 min)

**Review PR #107 (B4 BOOTSTRAP_V2_GOLD_SKIP_1)** per trigger-class rule (Director-override surface).

- Brief: `briefs/BRIEF_BOOTSTRAP_V2_GOLD_SKIP_1.md`
- PR: https://github.com/vallen300-bit/baker-master/pull/107
- Verdict back to AI Head A via paste-block: PASS or REQUEST_CHANGES with specifics.

### Step 2 (SECOND, ~30-60 min)

**Build CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1** — your verification surfaced this gap, you have deepest context.

- Brief: `briefs/BRIEF_CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1.md`
- Branch: `b1/cortex-auto-trigger-dispatch-fix`
- Severity: CRITICAL — auto-trigger silently dead for ALL 22 matters since multi-matter gate shipped.
- Approach: Option A from your ship report (move dispatch from bridge to Step 6 finalize) + add `movie_am` underscore alias to `slugs.yml`.
- Trigger-class: cross-capability state writes → **B3 second-pair-of-eyes review BEFORE AI Head A merge** (B1 builder-conflict caveat).

## Previous task (closed)

PR #109 (AUTO_TRIGGER_FAN_OUT_VERIFY_1) merged 2026-04-30 — ship report locked in, gap surfaced, Option A ratified.
