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

## Item-1 status (BUILT — at codex build-gate)
- **DONE:** built in baker-vault (isolated worktree per vault-writer-isolation guard). PR **vallen300-bit/baker-vault#175**, branch `b1/researcher-tranche2-item1-continuation` @424a72f. Files: method.md Step 8.6 + §4.2; `wiki/research/_continuation/_TEMPLATE.md`; `scripts/validate_continuation.sh`. Validator exercised (clean/missing/inconsistent/bad-class/conform all correct).
- **Build-gate sent to codex #9428** (topic build-verify/researcher-tranche2-item1). Awaiting build-PASS.
- **NEXT CONCRETE STEP:** on codex build-PASS → hand PR #175 to **lead** for merge (NO self-merge, #9255). On build-CHANGES → fold in the same worktree pattern (recreate worktree, patch, re-gate). Then start **item-2 (#6 per-type output schemas)** design → codex design-gate.

## Remaining items
- #6 per-type output schemas (wire into research-fan-out), #7 recency-override ship-gate, #8 research-memory (DESIGN-FIRST: store question — new store vs reuse Baker memory/vault-wiki). Each: design → codex design-gate → build (vault worktree) → codex build-gate → lead merge.

## Build mechanics note (for successor)
baker-vault commits are BLOCKED in the shared `~/baker-vault` checkout (vault-writer-isolation hook; only `lead` commits there). Build pattern: `git -C ~/baker-vault worktree add -b <branch> ~/bm-b1-vault-<task> origin/main` → edit/commit/push/PR in the worktree → `git -C ~/baker-vault worktree remove <path>`. baker-vault PRs target `vallen300-bit/baker-vault`.

## Key paths / commits
- Design branch: `b1/researcher-tranche2-item1` @880776e8 (design doc pushed).
- Source brief: `~/baker-vault/wiki/research/2026-07-12-researcher-capability-extension-brief.md` @22ab300.
- Researcher method (build target): `~/baker-vault/_ops/agents/researcher/method.md` (Step 8.6 goes after Step 8 line 74 / before Step 9).
- Bus thread: design-verify/researcher-tranche2-item1 (my #9311 → codex #9312).

## Claim discipline
Successor claims this arc by the `attempt:` bump commit on THIS checkpoint (not a bus ack). If `attempt` already bumped by another session, stand down. At `attempt >= 3`, stop and escalate to lead/deputy with checkpoint path + last state.
