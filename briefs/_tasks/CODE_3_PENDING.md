# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-21 evening
**Status:** OPEN — review PR #34 `STEP6_FRONTMATTER_YAML_ESCAPE_FIX_1`

---

## Target

- **PR:** https://github.com/vallen300-bit/baker-master/pull/34
- **Branch:** `step6-frontmatter-yaml-escape-fix-1`
- **Author:** B2
- **Ship report:** `briefs/_reports/B2_step6_frontmatter_yaml_escape_fix_20260421.md`

## Context (one paragraph)

After PR #33 healed the bridge, 4 fresh signals (including Hagenauer + Lilienmatt in-scope matters) landed in `status='opus_failed'` due to a YAML parse error on a stub title `"Layer 2 gate: matter not in current scope"` — unquoted colon triggering "mapping values are not allowed here". Brief pointed at Step 6's emitter; B2 found root cause in **Step 5's two deterministic stub writers** (`_build_skip_inbox_stub`, `_build_stub_only_stub`), which compose YAML via raw f-string concat. B2 routed both through `yaml.safe_dump` — same call pattern Step 6 already uses canonically at `_serialize_final_markdown:526`.

## Focus items for review

1. **Scope deviation — bless or reject.** Brief said "no touch to Step 5 logic" and pointed at Step 6 emitter. B2 fixed Step 5's stub emitters. B2's argument: state flow, routing decisions, and dict shape are byte-identical; only the serialization mechanism changed (f-string → `yaml.safe_dump`). Verify that claim — confirm no routing, no state transition, no dict-key-order, no field-set change. If byte-identical, deviation is correct scoping. If not, REQUEST_CHANGES.
2. **Root-cause correctness.** Independently confirm the bug is in Step 5 stub emitters, not Step 6 emitter. Check Step 6's `_serialize_final_markdown` already uses `yaml.safe_dump` (as claimed). Check Step 5's two stub writers before patch — were they indeed f-string concat?
3. **Patch correctness.** `yaml.safe_dump(dict, sort_keys=False, allow_unicode=True, default_flow_style=False)` — args mirror Step 6's canonical call. Key order preserved via `sort_keys=False` + dict literal ordering. Non-ASCII safe via `allow_unicode=True`. Block-style output via `default_flow_style=False`.
4. **Regression tests (4).** (a) colon-in-title parse, (b) pathological triage-summary scalars (colons/quotes/`#`/leading-dash/newlines), (c) field-order stability, (d) end-to-end via Step 6's actual `_split_frontmatter`. Verify each asserts roundtrip `yaml.safe_load` succeeds AND dict shape matches expected. Non-trivial pass checks present.
5. **FULL_SYNTHESIS risk flag.** B2 noted Opus direct-to-draft path could surface the same class if the model emits bad YAML. Confirm this is out-of-scope for the PR and correctly captured as a post-Gate-1 audit candidate — not a blocker now.
6. **No scope creep.** Only files touched: `kbl/steps/step5_opus.py` (two stub writers), new test file, ship report. No changes to Step 6, pipeline_tick, bridge, or step1-4 consumers.
7. **Adjacent emitter audit.** Grep for any remaining f-string / concat frontmatter composition elsewhere in `kbl/steps/`. If any survive (non-Step-5, non-Step-6), flag in the review report — separate follow-up brief candidate.

## Deliverable

- Verdict: `APPROVE` / `APPROVE_WITH_NITS` / `REQUEST_CHANGES` on PR #34.
- Report: `briefs/_reports/B3_pr34_step6_frontmatter_yaml_escape_review_20260421.md`.
- Include: scope-deviation verdict with evidence (byte-identical check), per-focus-item verdict, adjacent-emitter grep result.

## Gate

- **Tier A auto-merge on APPROVE.**
- Post-merge, the 4 stranded rows need a recovery SQL (Tier B — AI Head will authorize separately; shape deviates from the standing recovery pattern).

## Working dir

`~/bm-b3`. `git pull -q` before starting. If on a feature branch, `git checkout main && git pull -q` first.

— AI Head
