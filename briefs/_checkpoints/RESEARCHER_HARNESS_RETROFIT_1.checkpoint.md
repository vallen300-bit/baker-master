---
brief_id: RESEARCHER_HARNESS_RETROFIT_1
attempt: 1
seat: b1
status: MERGED + follow-up hardening pushed (2 commits not yet on main)
updated: 2026-07-07
---

# Checkpoint — RESEARCHER_HARNESS_RETROFIT_1 (rollover at ~91% ctx)

## What's done
- P1 lethal-trifecta retrofit **MERGED** by lead → vault main `@f539e0d` (squash).
- Deputy G2 **FULL PASS** (#6602/#6594). All lead rulings folded (#6535 chrome, #6559 enforce-split, #6562 inbox_post, #6577 VIP-deny reversal, #6616 F1-accepted-residual + time-box).
- Deliverables (in the merge): `researcher_write_cage.sh` (fail-closed write cage, ENFORCE ON, 23/23) + `researcher_bash_cage.sh` (Bash cage, WARN-default) + picker `settings.json` (81-verb `permissions.deny`, 2 PreToolUse matchers) + `SPEC_RESEARCHER_v1.md` (7 blocks) + fleet-matrix row + audit verdict + orientation (standby + PEOPLE-UPSERT propose-block + Baker-first revised) + method B5 4.7→4.8 + `picker-settings.reference.json`. WAHA skill symlink removed from picker.
- Non-git picker wiring applied LIVE (2 hook symlinks → main-checkout paths + settings + skill removal). Goes ENFORCE-live (Write leg) on shared `~/baker-vault` pull + researcher restart.
- **SECOND task DONE:** 57-doc AO re-tag (single-writer) — `documents.matter_slug` re-tagged per ao-desk map, read-back verified, `Oskolkov-RG7` drained to 0. Report `briefs/_reports/B1_AO_57_DOC_MANUAL_RETAG_1_20260707.md`.

## What's left (handed to lead via bus #6663 — NOT lost)
1. **Land 2 follow-up commits on vault main** (they postdate the `f539e0d` merge): `2b538ef` (codex G3 #6618 chaining/encoding hardening — quote-aware per-segment allow-list) + `21a1b88` (codex G3 #6657 git/gh/env-prefix hardening). Must land BEFORE the Bash-leg ENFORCE flip (2026-07-10 15:00Z) or the flip is porous. Cherry-pick both onto main, OR prep a follow-up branch off main.
2. **codex G3 re-gate of #6657** requested on `21a1b88` (#6662) — awaiting verdict. (codex has FAILed 3 rounds on enforced-mode Bash holes; each fixed. May find more — git surface is leaky.)
3. **Durable git fix (recommended follow-up brief):** a vetted `research_commit.sh` wrapper (like `bus_post.sh`) so raw `git` can be removed from the Bash allow-list entirely — git stays allow-listed now only because the researcher commits research to baker-vault (delivery); `git push <arbitrary-remote>` remains an exfil path.

## Key paths / commits
- baker-vault worktree: `~/bm-b1-vault-researcher-cage` (branch `b1/researcher-harness-retrofit`, tip `21a1b88`, pushed).
- Merged: vault main `@f539e0d`. Follow-up (unmerged): `2b538ef`, `21a1b88`.
- Hooks: `baker-vault/_ops/hooks/researcher_{write_cage,bash_cage}.sh` (+ `tests/`). Suites: write 23/23, bash 66/66.
- Brief: `baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/BRIEF_RESEARCHER_HARNESS_RETROFIT_1.md @4673937`. Spec: `SPEC_RESEARCHER_v1.md` same dir.

## Next concrete step (for successor)
Arc is handed to lead (#6663) — do NOT rebuild. If lead reassigns: (a) land `2b538ef`+`21a1b88` on main + confirm codex #6657 re-gate on `21a1b88`; (b) OR take **ADVISORY_SEAT_EXFIL_TRIM_1** (brief `@a9e1d80` same domain-agent-program dir, §6/§7 locked, mirror this retrofit's landed shape — lead #6630). Claim by the attempt-bump commit on THIS checkpoint, not a bus ack.
