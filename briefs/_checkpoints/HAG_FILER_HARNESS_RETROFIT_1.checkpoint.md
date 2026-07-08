# CHECKPOINT — HAG_FILER_HARNESS_RETROFIT_1

attempt: 1
seat: b3 (fresh, 2026-07-08)
brief: ~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/BRIEF_HAG_FILER_HARNESS_RETROFIT_1.md @5fa8a0a (§7 rulings locked)
ordering: lead #7018/#7021 — HAG_FILER FIRST, commit-as-you-go, THEN BUS_READ_UNACKED_SCAN_FIX_1 (#6987/#7011).

## Reconstruction (do NOT re-derive — expensive)
- Predecessor's B2 ACL guard was NEVER persisted (confirmed via reflog + stash in bm-b3 AND bm-hag-filer; both autostashes unrelated). Only lane1 guard survived.
- Two repos: baker-master (bm-b3, `.claude/` harness) + baker-vault (filing tree `wiki/matters/hagenauer-rg7/**` + Publisher guard to clone).
- Vault is a SHARED dirty checkout — work in an isolated worktree, never branch ~/baker-vault directly.
- Legacy `wiki/hagenauer-rg7/**` is EXCLUDED (dead tree, #6526/#6807). Dual-slug hag-filer|hag-desk (#6814, final). Narrowing = deferred room-ledger follow-up.

## DONE (committed + pushed)
1. **d14f4117** (baker-master, branch `b3/hag-filer-harness-retrofit`) — lane1 meta-document guard own-copy `.claude/hooks/lane1-meta-document-guard.sh` + `.claude/settings.json` PreToolUse wiring. Smoke 6/6.
2. **3f75273** (baker-vault, branch `b3/hag-filer-filing-acl-guard`, worktree `~/bm-b3-vault-hag-filer-acl`) — B2 write-path ACL guard `.githooks/hagenauer_filing_acl_guard.sh` (clone of render_acl_guard.sh @da04b8e) + wired into vault pre-commit/pre-push + `.githooks/tests/test_hagenauer_filing_acl_guard.sh` 16/16. AC1+AC2+AC4 green.

## LEFT
3. **B4 filing done-gate** (AC3) — deterministic: artifact-exists-at-path AND receipt posted (bus + room-ledger). OPEN-2 LOCKED = BOTH. Vault-side script + test.
4. **Room-ledger entry** — filing sub-path map + log the deferred narrowing follow-up (#6814) as an open item.
5. **7 spec blocks + D3 row** (AC5) — hag-filer spec (4-slot charter B1, loop B3, model+cost rationale B5, rollout B6, kill-switch B7) + fleet-matrix-d3.md row stub→full contract. In vault `_ops/build/baker-os-v2/05_outputs/domain-agent-program/`.
6. **baker-master (bm-b3)** — git-identity per-commit injection (`git -c user.name='hag-filer worker' -c user.email=hag-filer@brisengroup.com` keyed off BAKER_ROLE; 2 existing b3-authored filings STAY, no amend) + model pin + tool trim.
7. **Ship** both branches → G1 self (done per-block) → G2 deputy cross-lane → G3 codex on bus → lead merge. Ship report `briefs/_reports/B3_HAG_FILER_HARNESS_RETROFIT_1_<date>.md` + bus receipt.

## NEXT CONCRETE STEP
Build B4 filing done-gate (block 3): `hag_filing_done_gate.sh` in the vault worktree `~/bm-b3-vault-hag-filer-acl` — stat artifact at declared path + verify room-ledger entry present; deterministic PASS/FAIL, no self-judgment. Add test. Commit+push on branch `b3/hag-filer-filing-acl-guard`.
