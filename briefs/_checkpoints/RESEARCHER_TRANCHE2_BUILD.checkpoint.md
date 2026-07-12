---
brief_id: RESEARCHER_TRANCHE2_BUILD
dispatch: "#9299 (deputy, Director order #9258 via lead #9297)"
owner: b1
attempt: 1
checkpoint_reason: item-6 MERGED (vault#179); descope — #8 reassigned to b2 (#9723); b1 carries item #7 ONLY; item-7 design authored, at LEAD design-review
created: 2026-07-12
updated: 2026-07-12 (item-6 merged + #7-only trim)
---

# Checkpoint — Researcher Tranche-2 build arc

## Brief / scope
b1 is the tranche-2 builder for the researcher capability-extension brief
(`~/baker-vault/wiki/research/2026-07-12-researcher-capability-extension-brief.md` @22ab300).
Four items, **each its own PR, sequenced as listed**:
- **#5 Continuation queue** — deferred research items → structured follow-up brief artifact.
- **#6 Per-type output schemas** — typed output contract per channel, wire into `research-fan-out`.
- **#7 Operational recency override** — topics <7d require Grok/X or logged waiver; method ship-gate.
- **#8 Research memory / index** — searchable prior-report store. **DESIGN-FIRST** (open Q: new store vs reuse Baker memory / vault-wiki index — resolve with codex before any build).

**Standing rules (Director order, non-negotiable):** cages UNTOUCHED (every item read-only / proposal-only); **DESIGN-VERIFY via codex terminal BEFORE build for each item**; then build → codex build-gate → **lead merge**; branch+push per item, **NO self-merge** (Director rule #9255); report each PR+verdict to **lead**, loop **deputy** for visibility. Tranche-1 (reader + intake manifest + coverage ledger + adversarial-verify Step 6.6) is MERGED — do not redo.

## What's done
- Acked tranche-2 to lead (#9307).
- **Item 1 (#5) design authored + codex design-gate CLEARED-WITH-CHANGES.**
  - Design doc: `briefs/_reports/B1_researcher_tranche2_item1_continuation_queue_DESIGN_20260712.md` on branch `b1/researcher-tranche2-item1` @880776e8 (pushed).
  - Codex verdict #9312 = **DESIGN-CHANGES** (rulings below) — must fold before build.

## Codex rulings on item-1 (#9312) — FOLD THESE, then send build-gate
1. **Artifact:** use `_continuation/` subfolder (in-cage). **Filename must be parent-UNIQUE** — use `<parent-report-basename>-cont.md` (the proposed `<date>-<topic>-cont.md` can collide while design says one-file-per-parent).
2. **Trigger:** fail-closed ship-gate YES, but Step 8.6 must emit a **machine-readable deferral declaration** in the report/method-log — a structured closed-class list `deferrals: [{class, item, why, channels, effort, priority}]` (or `continuation_required=true`). Validator checks that declaration vs the artifact. **NO regex-only prose detection** (prose lives at SHORT lines 182-186, FULL 197-203, ceiling cuts line 130 — not reliably parseable).
3. **Intake reuse:** reuse tranche-1 intake-manifest schema for promoted continuations = PASS, but the continuation is not a valid intake until Brief / Must-answer-questions / Required-sources+channels / Budget / Deadline are populated. Derive/require these before promotion.
4. **Venue:** baker-vault = PASS (method.md + template + helper + `wiki/research/_continuation/`). baker-master only if a runtime consumer is later introduced.
- **Build shape confirmed: Option A** (method.md Step 8.6 + `_TEMPLATE.md` + cage-safe `validate_continuation.sh`). No new skill surface, no auto-dispatch.

## Item-1 status (COMPLETE — both gates cleared, at lead merge)
- **DONE + BOTH GATES CLEARED.** PR **vallen300-bit/baker-vault#175** @424a72f. Codex design-gate #9312 (folded) + codex BUILD-PASS #9433 (findings none). Handed to lead for merge #9434 (no self-merge #9255). Files: method.md Step 8.6 + §4.2; `wiki/research/_continuation/_TEMPLATE.md`; `scripts/validate_continuation.sh`. Validator exercised 5 paths.
- **NEXT CONCRETE STEP:** start **item-2 (#6 per-type output schemas)** — DESIGN first (read `~/.claude/skills/research-fan-out/SKILL.md` + `_ops/agents/researcher/research-types.md`; design typed output contract per channel to kill paraphrase drift across fan-out sub-agents; wire into research-fan-out) → send codex design-gate → build in vault worktree → codex build-gate → lead merge. (Lead offered parallel-start on #9434; proceed unless lead says hold.)

## Item-2 (#6 per-type output schemas) status — DESIGN-CHANGES received, folding
- Design doc: `briefs/_reports/B1_researcher_tranche2_item2_output_schemas_DESIGN_20260712.md` (branch b1/researcher-tranche2-item1).
- Codex #9456 = DESIGN-CHANGES (2 gaps) + all 5 rulings settled:
  - **F1 HIGH:** base schema MUST add a required `claim` field to every `findings[]` row (method §8 mandates Claim/URL/Pub date/Byline/Accessed/Tier/Confidence/Quote — my base omitted `claim`).
  - **F2 MED:** the 8 per-type field sets are NOT actually 1:1 with `research-types.md` "What to find" (e.g. Type 1 has 8 bullets, my schema had 4; Type 6 needs 3 practitioners + last-5-posts/specialisation/what-worked). Fix: read each type's full What-to-find bullets and expand each schema to cover them (or map each bullet→field).
  - **Rulings:** Q1 base+8 YES · Q2 strict JSON YES · Q3 prompt + **deterministic pre-synthesis JSON/schema conformance check**, invalid channel → §7 channel-failure · Q4 editing research-fan-out itself is in-scope, do NOT edit referenced skills · Q5 **edit `_ops/skills/research-fan-out/` (vault canonical) ONLY** — `~/.claude/skills/research-fan-out` is a SYMLINK to vault, no dual edit.
- **BUILT + at codex build-gate.** F1+F2 folded. PR **vallen300-bit/baker-vault#179**, branch `b1/researcher-tranche2-item2-schemas` @7b3377f. Files: `_ops/skills/research-fan-out/output-schemas.md` (base+8 + JSON example), `validate_channel_output.py` (deterministic conformance, exercised 9 paths + py_compile), `SKILL.md` §5/§6, `method.md §10`. Build-gate sent codex **#9539**. Awaiting build-PASS → lead merge (#9255). On build-CHANGES → fold in a fresh vault worktree.

## Item-6 (#6 per-type output schemas) — MERGED
- PR vault#179 MERGED (lead #9720). Lead Claude-review #9717 PASS-WITH-CHANGES folded @43bd3e9: REQUIRED_ROW_KEYS += pub_date/accessed/byline + output-schemas.md §Conformance aligned + validate_channel_output_selftest.py (13/13 green). Fold-ship #9719. Item-2 CLOSED.

## LANE CHANGE (codex seats SUSPENDED — Director order via lead #9712/#9720/#9723)
- New rails (NO codex): design → **LEAD design review** → build in vault worktree → **LEAD+deputy Claude review** → lead merge.
- **#8 research-memory REASSIGNED to b2** (#9723 scope trim). b1 store-landscape scouting handed to lead #9726 for b2.
- **b1 now carries item #7 ONLY.**

## Item-7 (#7 recency override) status — DESIGN AUTHORED, at LEAD review
- Design doc: `briefs/_reports/B1_researcher_tranche2_item7_recency_override_DESIGN_20260712.md` (this repo).
- Shape: new method §4.3 ship-gate (RECENCY-UNMET), sibling of §4.1/§4.2. Declared `recency_sensitive` field in §4.0 intake manifest (NO regex-on-prose, honours codex #9312 ruling 2). Fail-closed: recency_sensitive=true requires Grok/X channel walked (per §4.1 ledger) OR closed-class `recency_waiver` block. New cage-safe `scripts/validate_recency.sh` mirroring validate_continuation.sh.
- 3 open Qs posted to lead (waiver authority / window default / validator packaging) with b1 recommendations.
- **DESIGN PASS** (lead #9731) — all 3 recs accepted + addition folded (attempted-but-failed Grok/X ≠ recency met without waiver).
- **BUILT + PR OPEN.** PR **vallen300-bit/baker-vault#181**, branch `b1/researcher-tranche2-item7-recency-vault` (off latest main), worktree `/private/tmp/b1-vault-item7`. Files: `_ops/agents/researcher/method.md` (§4.0 recency fields + §4.1 anchor + §4.3 gate + HOW step 8.7); `scripts/validate_recency.sh` (mirrors validate_continuation.sh; 12 paths exercised, bash -n clean). Ship posted to lead #9734.
- **NEXT CONCRETE STEP:** await LEAD Claude-review on vault#181. On PASS → lead merges (no self-merge #9255) → **tranche-2 arc CLOSES** (b1's last item; #8 went to b2 #9723). On CHANGES → fold in worktree, re-push, re-post. After merge: `git -C ~/baker-vault worktree remove /private/tmp/b1-vault-item7` + light-pin + report arc-done to lead + EXIT clean.

## Build mechanics note (for successor)
baker-vault commits are BLOCKED in the shared `~/baker-vault` checkout (vault-writer-isolation hook; only `lead` commits there). Build pattern: `git -C ~/baker-vault worktree add -b <branch> ~/bm-b1-vault-<task> origin/main` → edit/commit/push/PR in the worktree → `git -C ~/baker-vault worktree remove <path>`. baker-vault PRs target `vallen300-bit/baker-vault`.

## Key paths / commits
- Design branch: `b1/researcher-tranche2-item1` @880776e8 (design doc pushed).
- Source brief: `~/baker-vault/wiki/research/2026-07-12-researcher-capability-extension-brief.md` @22ab300.
- Researcher method (build target): `~/baker-vault/_ops/agents/researcher/method.md` (Step 8.6 goes after Step 8 line 74 / before Step 9).
- Bus thread: design-verify/researcher-tranche2-item1 (my #9311 → codex #9312).

## Claim discipline
Successor claims this arc by the `attempt:` bump commit on THIS checkpoint (not a bus ack). If `attempt` already bumped by another session, stand down. At `attempt >= 3`, stop and escalate to lead/deputy with checkpoint path + last state.
