---
brief_id: RESEARCHER_TRANCHE2_BUILD
dispatch: "#9299 (deputy, Director order #9258 via lead #9297)"
owner: b1
attempt: 1
checkpoint_reason: item-1 boundary refresh — built + PR #175 + at codex build-gate (lead #9415 resume-on-live-seat)
created: 2026-07-12
updated: 2026-07-12 (item-1 boundary)
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
- **NEXT CONCRETE STEP:** fold F1 (add `claim`) + F2 (expand 8 schemas from `_ops/agents/researcher/research-types.md` What-to-find bullets), then BUILD in a vault worktree: edit `_ops/skills/research-fan-out/SKILL.md` §5 (output contract → typed schema) + §6 (add deterministic conformance-check → §7 failure) + new `_ops/skills/research-fan-out/output-schemas.md` (base+8 schemas, JSON examples) + `method.md §10` pointer. Then codex build-gate → lead merge. Codex already gave the fix path — no design re-gate needed, go straight to build after folding.

## Remaining items
- #7 recency-override ship-gate, #8 research-memory (DESIGN-FIRST: store question — new store vs reuse Baker memory/vault-wiki). Each: design → codex design-gate → build (vault worktree) → codex build-gate → lead merge.

## Build mechanics note (for successor)
baker-vault commits are BLOCKED in the shared `~/baker-vault` checkout (vault-writer-isolation hook; only `lead` commits there). Build pattern: `git -C ~/baker-vault worktree add -b <branch> ~/bm-b1-vault-<task> origin/main` → edit/commit/push/PR in the worktree → `git -C ~/baker-vault worktree remove <path>`. baker-vault PRs target `vallen300-bit/baker-vault`.

## Key paths / commits
- Design branch: `b1/researcher-tranche2-item1` @880776e8 (design doc pushed).
- Source brief: `~/baker-vault/wiki/research/2026-07-12-researcher-capability-extension-brief.md` @22ab300.
- Researcher method (build target): `~/baker-vault/_ops/agents/researcher/method.md` (Step 8.6 goes after Step 8 line 74 / before Step 9).
- Bus thread: design-verify/researcher-tranche2-item1 (my #9311 → codex #9312).

## Claim discipline
Successor claims this arc by the `attempt:` bump commit on THIS checkpoint (not a bus ack). If `attempt` already bumped by another session, stand down. At `attempt >= 3`, stop and escalate to lead/deputy with checkpoint path + last state.
