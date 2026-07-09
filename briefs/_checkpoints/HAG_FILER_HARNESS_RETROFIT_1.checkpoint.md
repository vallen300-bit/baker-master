# CHECKPOINT — HAG_FILER_HARNESS_RETROFIT_1

attempt: 1
seat: b3 (resumed 2026-07-09)
brief: ~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/BRIEF_HAG_FILER_HARNESS_RETROFIT_1.md @5fa8a0a (§7 rulings locked)
ordering: lead #7018/#7021 — HAG_FILER FIRST, commit-as-you-go, THEN BUS_READ_UNACKED_SCAN_FIX_1 (#6987/#7011).

## STATE: build complete (all 6 blocks + spec landed) — awaiting G2/G3 gates + lead merge.

## DONE (committed + pushed) — ALL 5 ACs GREEN
Vault branch `b3/hag-filer-filing-acl-guard` (tip e3b004b):
1. **3f75273** — B2 ACL guard `.githooks/hagenauer_filing_acl_guard.sh` (reuse of render_acl_guard.sh @da04b8e) + wired pre-commit/pre-push. AC1+AC2+AC4. test 16/16.
2. **cb93d5e** — B4 done-gate `_ops/agents/hag-filer/hag_filing_done_gate.sh` + room-ledger `wiki/matters/hagenauer-rg7/creditor-claim-filing/_filing-ledger.md`. AC3. test 8/8.
3. **7ffe262** — B5 `_ops/agents/hag-filer/SPEC_HAG_FILER_v1.md` (7 blocks) + fleet-matrix-d3.md hag-filer row stub→full. AC5.
4. **e3b004b** — B6 companion `_ops/agents/hag-filer/picker-settings.reference.json` (model pin + 81-verb deny).

Baker-master branch `b3/hag-filer-harness-retrofit` (tip f7e79c10):
5. **d14f4117** — B1 lane1 meta-doc guard own-copy `.claude/hooks/lane1-meta-document-guard.sh` + settings.json PreToolUse. smoke 4/4.
6. **f7e79c10** — B6 `scripts/hag_filer_commit.sh` (per-commit identity, #6549(2)) + `.claude/role-context/hag-filer.md` (identity+model+trim). smoke 4/4.

Live picker applied: `~/bm-hag-filer/.claude/settings.local.json` (model claude-haiku-4-5-20251001 + deny list).
Ship report: `briefs/_reports/B3_HAG_FILER_HARNESS_RETROFIT_1_2026-07-09.md`.

## LEFT
- G2 deputy cross-lane + G3 codex on bus (effort=medium) → lead merges BOTH branches.
- On merge: pivot to BUS_READ_UNACKED_SCAN_FIX_1.

## NEXT CONCRETE STEP
Await G2/G3 verdicts on the bus; address any request-changes with a NEW commit (never amend) on the
relevant branch. If clean → lead merges both branches; then start BUS_READ_UNACKED_SCAN_FIX_1 off main.

## NOTE (reconciliation, do not re-derive)
baker-master local clone had diverged (prior seat pushed lane1 as d14f4117 under a different SHA than
local dup 3efe9ffc; lane1+settings content byte-identical, verified empty diff). Branch was moved to
origin tip + B6 cherry-picked. Origin SHAs are authoritative.
