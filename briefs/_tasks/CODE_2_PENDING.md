# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** Step 6 scope challenge → REDIRECT verdict filed at `f1b4209`. Director pre-ratified REDIRECT at prior turn; AI Head now folding into brief.
**Task posted:** 2026-04-18
**Status:** OPEN — two deliverables in sequence

---

## Task A (now): Review PR #4 — LAYER0-LOADER-1

**PR:** https://github.com/vallen300-bit/baker-master/pull/4
**Branch:** `layer0-loader-1`
**Head:** `fa0cfe8`
**Tests:** 13/13 green (28/28 including SLUGS-1)

### Scope of review

**IN**
- Loader module (`kbl/layer0_rules.py`) structural fidelity to `kbl/slug_registry.py` pattern
- `Layer0RulesError` exception class completeness
- Fail-loud posture: missing file / malformed YAML / schema violation / missing required keys
- Cache + reload semantics (mirror slug_registry)
- Fixture YAML validity + schema coverage
- Test coverage of failure paths (not just happy path)
- CHANDA compliance: does loader violate any invariant? (expected: no — it's pure data loading)

**OUT**
- Rule content (empty, fixtures only — B3 owns real rules)
- Rule evaluation logic (out of scope per brief)
- Any SLUGS-1 code changes (none expected)

### Non-issue confirmed

B1 used `BAKER_VAULT_PATH` (matches SLUGS-1 + Mac Mini convention). My brief had a typo saying `BAKER_VAULT_ROOT`. **Canonical is `BAKER_VAULT_PATH` — no rename needed.** Do not flag this as an issue.

### Format

Standard review report: `briefs/_reports/B2_pr4_review_20260418.md`
Verdict: APPROVE / REDIRECT (list small-surface fixes, inline-appliable) / BLOCK (structural issues)

### Timeline

~15-20 min. Loader is small; review is pattern-fidelity check.

---

## Task B (queued, fires when AI Head commits REDIRECT fold): Review KBL-B Brief REDIRECT Fold

AI Head is folding Step 6 REDIRECT into KBL-B brief §2, §3.2, §4.7, §6, §8, §9, §10, §11. Expected commit in ~30-45 min. When you see `fold(KBL-B): Step 6 REDIRECT` in git log:

### Scope of review

**IN**
- All 8 sections updated consistently (no residual Sonnet references)
- §4.7 rewrite matches the concrete spec you gave in your scope-challenge report's "Recommended Step 6 shape" section
- §8 retry ladder updated (Sonnet retry paths deleted, Opus R3 ladder carries frontmatter-validation-failure case)
- §9 cost-control no longer references `sonnet_step6` ledger rows (but cost ledger enum value stays — per your "preserves option" note)
- §3.2 state enum cleanup: `awaiting_sonnet`, `sonnet_running`, `sonnet_failed` removed; `awaiting_opus`, `opus_running`, `opus_failed` replaced with `awaiting_finalize`, `finalize_running`, `finalize_failed`
- §10 testing plan updated for no-Sonnet path (fixture #6 `step_6_sonnet_fires: no` becomes `step_6_runs: yes, no_llm: true`)
- §11 observability: no Sonnet latency / cost metric

**OUT**
- Re-opening the REDIRECT decision (ratified)
- Prompt content (there are none now for Step 6 — that's the point)
- Pydantic schema definition details (implementation-level, KBL-B impl ticket)

### Format

`briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`
Verdict: APPROVE / REDIRECT (list fix items, inline-appliable) / BLOCK

### Timeline

~20-30 min.

---

## Then: CHANDA ack (queued, post-Task-B)

After Task B, you receive the third task: CHANDA.md ack following the same pattern as B1 + B3's acks. Short, ~15-20 min. Detail arrives in your next PENDING dispatch.

---

## Status after Task A + B

You become the reviewer-of-record for both the Layer 0 loader impl and the KBL-B Step 6 scope collapse. Clean reviewer-separation across three architectural decisions.

### Dispatch back (after each task)

> B2 PR #4 review done — `briefs/_reports/B2_pr4_review_20260418.md`, commit `<SHA>`. Verdict: <APPROVE|REDIRECT|BLOCK>.

> B2 KBL-B REDIRECT fold review done — `briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`, commit `<SHA>`. Verdict: <...>.

---

*Posted 2026-04-18 by AI Head. B1 parallel-running LOOP-SCHEMA-1 migration. B3 parallel-running Step 1 Inv-3 amendment.*
