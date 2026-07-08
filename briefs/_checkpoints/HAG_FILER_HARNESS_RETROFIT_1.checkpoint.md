# CHECKPOINT — HAG_FILER_HARNESS_RETROFIT_1

attempt: 1
seat: b3 (fresh, 2026-07-08)
brief: ~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/BRIEF_HAG_FILER_HARNESS_RETROFIT_1.md @5fa8a0a (§7 rulings locked)
ordering: lead #7018/#7021 — HAG_FILER FIRST, commit-as-you-go, THEN BUS_READ_UNACKED_SCAN_FIX_1 (#6987/#7011).

## Reconstruction (do NOT re-derive — expensive)
- Predecessor's B2 ACL guard was NEVER persisted (reflog+stash confirmed in both clones). Rebuilt from scratch.
- Two repos: baker-master (bm-b3, `.claude/` harness) + baker-vault (filing tree `wiki/matters/hagenauer-rg7/**` + Publisher guard cloned).
- Vault is SHARED+dirty — work in isolated worktree `~/bm-b3-vault-hag-filer-acl` (branch `b3/hag-filer-filing-acl-guard`), never branch ~/baker-vault.
- Legacy `wiki/hagenauer-rg7/**` EXCLUDED. Dual-slug hag-filer|hag-desk (#6814). Narrowing = deferred room-ledger follow-up.

## DONE (committed + pushed) — ALL FOUR STRUCTURAL ACs GREEN
1. **d14f4117** (baker-master `b3/hag-filer-harness-retrofit`) — lane1 guard own-copy + settings.json PreToolUse wiring. Smoke 6/6.
2. **3f75273** (vault `b3/hag-filer-filing-acl-guard`) — B2 ACL guard `.githooks/hagenauer_filing_acl_guard.sh` (clone of render_acl_guard.sh @da04b8e) + wired pre-commit/pre-push + test 16/16. **AC1+AC2+AC4**.
3. **cb93d5e** (vault, same branch) — B4 done-gate `_ops/agents/hag-filer/hag_filing_done_gate.sh` + test 8/8 + room-ledger `wiki/matters/hagenauer-rg7/creditor-claim-filing/_filing-ledger.md`. **AC3**. Live guard warn captured at pre-commit AND pre-push.
- checkpoint commits on baker-master branch.

## LEFT
5. **7 spec blocks + D3 row** (AC5) — hag-filer 7-block spec (agent-spec-template) in vault `_ops/agents/hag-filer/SPEC_HAG_FILER_v1.md` (or domain-agent-program/): B1 4-slot charter, B3 loop, B5 model+cost rationale (small tier — mechanical placement, defensible), B6 rollout ramp+tripwires, B7 kill-switch doc (HAGENAUER_FILING_ACL_BYPASS). Upgrade `_ops/build/baker-os-v2/05_outputs/domain-agent-program/fleet-matrix-d3.md` hag-filer row stub→full contract (Status=write-in-lane; Forbidden: no matter-reasoning/cross-matter/external-send).
6. **baker-master (bm-b3 `b3/hag-filer-harness-retrofit`)** — git-identity per-commit injection (`git -c user.name='hag-filer worker' -c user.email=hag-filer@brisengroup.com` keyed off BAKER_ROLE; 2 existing b3-authored filings STAY, no amend) + model pin + tool trim in hag-filer picker config.
7. **Ship** — report `briefs/_reports/B3_HAG_FILER_HARNESS_RETROFIT_1_2026-07-08.md` + bus receipt; G2 deputy cross-lane + G3 codex on bus → lead merges both branches. THEN pivot to BUS_READ_UNACKED_SCAN_FIX_1.

## NEXT CONCRETE STEP
Block 5: write `_ops/agents/hag-filer/SPEC_HAG_FILER_v1.md` (7 blocks per agent-spec-template) + upgrade fleet-matrix-d3.md hag-filer row. Commit+push on vault branch `b3/hag-filer-filing-acl-guard` (docs → guard no-op, no warn).
