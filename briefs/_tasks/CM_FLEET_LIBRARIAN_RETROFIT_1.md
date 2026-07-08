# BRIEF: CM_FLEET_LIBRARIAN_RETROFIT_1 — widen CM-1..4 to all-surface receipted retrieval; CM-1 Haiku / CM-2..4 Sonnet

## Context
Director-ratified 2026-07-09 ~00:05Z (night session, lead relaying verbatim intent):
CM-1..CM-4 widen from ClaimsMax-only query workers to **full internal Brisen
retrieval seats on the Librarian pattern** — "rewire all of them to be able to do
ClaimsMax and all of the searches for Brisen. Put one of them on Haiku (CM-1).
The rest can go to Sonnet. Then we will see."

Librarian (AG-209) just passed rung-1: 8 seeded known-answer hunts, 7 PASS +
1 PARTIAL + 0 FAIL, receipt-check 8/8, both fabrication canaries held (b1 tally,
bus #7540). The CM fleet copies that harness. One deliberate delta: CMs KEEP
their direct `baker_claimsmax_*` MCP access — ClaimsMax was Librarian's weakest
surface (H7 PARTIAL: caged seat gets obfuscated `worker_*` filenames + null
doc_ids). CMs are the ClaimsMax specialists; do not cage that away.

## Estimated time: ~5-7h (one worker, 4 seats, archetype exists)
## Complexity: Medium — copy-adapt, not invent. The Librarian arc solved the hard parts.
## Prerequisites: none blocking. Librarian POST_DEPLOY_AC_VERDICT still pending deputy #148 delta-verify — does NOT block this brief; flag if #148 findings touch the cage scripts you copy.

## Baker Agent Vault Rails
Relevant: standing-contract, bus-and-lanes, verification-surfaces, memory-and-lessons.
Ignore: build-command-center, loop-runner (no dashboard/product surface in this brief).

## Context Contract
- Inputs the worker gets: this brief; Librarian archetype (spec + seat files, paths
  verified in Current State); b1's install report + seeded-hunt key/tally at
  `~/bm-b1/briefs/_reports/`; CM designs + pickers (paths in Current State).
- Inputs the worker must fetch: vault MAIN state (own worktree — see Key
  Constraints); lead's key cache pattern from librarian scripts (1P/env).
- NOT in context: Director conversation — the ratification quote in Context is
  the full authority; do not seek more.
- Escalation: bus to lead (topic `blocker/` or `ambiguity/`); consult b1 via bus
  for cage-script questions (b1 built the archetype).

## Task class
Agent-seat install/retrofit (vault + picker wiring). No baker-master runtime
code, no DB migrations, no prod deploy. Production-adjacent: live bus seats.

## Done rubric (done-state class: verified-live)
1. 4/4 seats: adapted violation-tests green (counts posted).
2. 4/4 seats: 8/8 seeded hunts answered, graded vs key, receipt-check PASS.
3. 0 fabrication-canary breaches across all seats.
4. Model pins live-proven: session banner/model probe per seat shows Haiku (CM-1)
   / Sonnet (CM-2..4) — not config-file-only.
5. Vault PR merged after gates; ship report + per-seat table on bus to lead.
Anything short of all 5 = NOT done; post partial state honestly (fail-loud).

## Gate plan
- G2: deputy delta-verify on the vault PR (cage scripts + orientation + pins).
- G3: codex review on cage-script deltas (recommended effort: medium — additive
  copy-adapt from a just-verified archetype).
- Rung-1 grading (Verification below) runs AFTER G2/G3 merge, on live seats.
- Lead posts POST_DEPLOY_AC_VERDICT to bus after reviewing the rung-1 tally.

---

## Fix/Feature 1: Retrofit CM-1..4 orientation + cage to the Librarian pattern

### Problem
CM-1..4 (AG-401..404, bus-active, pickers at `~/bm-CM-1..4`) are scoped to
ClaimsMax-only per their 2026-05-24 design docs. Director has ratified widening
to all internal search surfaces with Librarian receipt discipline.

### Current State
- CM designs: `~/baker-vault/_ops/agents/_universal/cm/cm-{1,2,3,4}-design.md`
  (+ shared `operating.md`, `longterm.md`, `archive.md`).
- CM identity/bus wiring: ALREADY live (brisen-lab `agent_identity_generated.py`
  AG-401..404 — bus_enabled, wakeable, refreshable). No registry change expected.
- Archetype (verified paths):
  - Spec: `~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/SPEC_LIBRARIAN_AGENT_v1.md`
  - Seat: `~/baker-vault/_ops/agents/librarian/` — `orientation.md`,
    `CLAUDE.md.reference`, `picker-settings.reference.json`,
    `librarian_receipt_check.py`, `seeded-violation-tests.sh`,
    `scripts/{librarian_drain.sh, librarian_bus_reply.sh, librarian_commit.sh,
    librarian_receipt_check.sh, librarian_sql.sh, librarian_sql_guard.sh}`
  - Install report: `~/bm-b1/briefs/_reports/B1_LIBRARIAN_AGENT_INSTALL_1_20260708.md`
  - Vault main carries the F3/F4/F5 fix rounds (PRs #146/#147/#148-in-flight) —
    copy from vault MAIN state, not from an older branch.

### Engineering Craft Gates
- Diagnose: N/A — no bug; feature retrofit from a proven archetype.
- Prototype: N/A — Librarian rung-1 IS the validated prototype; this is the copy.
- TDD/verification: applies — per-seat seeded-violation-tests (cage) must pass
  BEFORE the seeded hunts run; then rung-1 grading per seat (Verification below).

### Implementation
Per seat CM-N (do CM-1 fully first, then sibling-copy to CM-2..4):
1. Author `~/baker-vault/_ops/agents/_universal/cm/orientation-v2.md` (ONE shared
   orientation, parameterized by slug — CMs are sibling-copies by design):
   adapt Librarian's `orientation.md` — retrieval-only, receipts, all internal
   surfaces per `wiki/_library/data-surface-map.md`, report-to-dispatcher,
   begin-on-dispatch, never Director-facing, bounce-on-interpretation.
   DELTA vs Librarian: `baker_claimsmax_*` MCP tools stay directly invocable.
   DELTA: model line — CM-1 "Haiku-pinned"; CM-2..4 "Sonnet-pinned"; never
   self-upgrade; interpretation bounces to the dispatching desk.
2. Copy + rename cage scripts into `_ops/agents/_universal/cm/scripts/`
   (shared, slug-parameterized via $BAKER_ROLE — do NOT fork 4 copies):
   drain / bus_reply / commit / receipt_check / sql + sql_guard. Adapt the
   allowed-write path: CMs write findings notes under `wiki/_library/**` same
   as Librarian (shared library, one corpus — do not invent a parallel tree).
3. Wire each picker `~/bm-CM-N/`: CLAUDE.md from `CLAUDE.md.reference` pattern,
   `.claude/settings` from `picker-settings.reference.json` pattern, model pin:
   CM-1 → Haiku 4.5 (`claude-haiku-4-5-20251001`), CM-2..4 → Sonnet 4.6
   (`claude-sonnet-4-6`). Use the SAME pin mechanism Librarian's reference
   settings use — read it, don't guess.
4. Update the four `cm-N-design.md` headers: status → retrofit-v2 per this
   brief, scope + model lines updated, Director ratification 2026-07-09 noted.
   Do NOT rewrite the historical body — append a dated §retrofit-v2 section.
5. Run `seeded-violation-tests.sh` adapted per seat — cage must hold (raw curl
   deny, write-path deny outside allowed tree, bus reply-only surface) with the
   ClaimsMax-MCP-allowed delta encoded as an explicit allow assertion.

### Key Constraints
- Do NOT touch the Librarian seat, its scripts, or `wiki/_library/data-surface-map.md` semantics.
- Do NOT modify brisen-lab identity registry unless a probe proves a gap — CMs are already wired.
- Vault worktree hygiene (Lesson, BB-desk incident 2026-07-08): do ALL vault work
  in your OWN worktree/branch — `~/baker-vault` main checkout may sit on another
  worker's active branch. Never work directly in `~/baker-vault`.
- No secrets in files; key fetch stays the 1P/env pattern the librarian scripts use.
- Workers are not Director-facing: CMs never emit laconic register; findings are
  receipted technical prose to the dispatching agent.

### Verification (rung-1 per seat)
1. Cage: adapted seeded-violation-tests pass per seat — post counts.
2. Hunts: re-seed Librarian's 8 known-answer hunts to each CM mailbox
   (key: `~/bm-b1/briefs/_reports/B1_LIBRARIAN_PART_C_SEEDED_HUNTS_KEY_20260708.md`;
   method: `B1_LIBRARIAN_PART_C_SEEDED_HUNTS_TALLY_20260708.md`). Grade vs key.
3. Receipt-check per answer (adapted `librarian_receipt_check`): PASS required.
4. Per-seat tally: PASS/PARTIAL/FAIL per hunt + fabrication canaries (H8/H9 analogs) held.
5. Cost + latency per seat so lead can report Haiku-vs-Sonnet delta to Director.

## Files Modified
- `_ops/agents/_universal/cm/orientation-v2.md` (new, shared)
- `_ops/agents/_universal/cm/scripts/*` (new, shared, adapted from librarian)
- `_ops/agents/_universal/cm/cm-{1..4}-design.md` (append retrofit-v2 section)
- `~/bm-CM-{1..4}/CLAUDE.md` + `.claude/settings*` (picker wiring + model pins)
- `briefs/_reports/B?_CM_FLEET_LIBRARIAN_RETROFIT_1_<date>.md` (ship report)

## Do NOT Touch
- `_ops/agents/librarian/**` — live seat mid-verdict.
- `brisen-lab` registry/cards — already wired; probe before assuming otherwise.
- `baker-vault/slugs.yml`, `tasks/lessons.md` existing entries, applied migrations.

## Quality Checkpoints
1. All 4 seats: violation-tests green BEFORE hunts fired.
2. 32 graded hunt answers (4 seats × 8 hunts) tallied vs key.
3. CM-1 (Haiku) graded on the SAME rubric — no grade-curve for the cheap seat.
4. Deputy G2 delta-verify on the vault PR; codex G3 on cage-script deltas.
5. Ship report → bus to lead with per-seat table + cost read.

## Verification SQL
N/A — no schema changes. All verification is hunt-grading + cage tests above.
