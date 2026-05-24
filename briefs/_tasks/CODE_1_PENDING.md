---
brief_id: BRISEN_LAB_CLICK_TO_WAKE_1
title: Click on badged Brisen Lab card opens picker in Terminal
status: PENDING
dispatched_at: 2026-05-24T21:18:00Z
dispatched_by: lead (AH1-Terminal)
brief_path: briefs/BRIEF_BRISEN_LAB_CLICK_TO_WAKE_1.md
target_repos:
  - brisen-lab (Components 1+2 — single PR)
  - baker-vault (Component 3 — separate PR for SOP Row 13)
expected_time: 3-4h
complexity: medium
director_ratified: 2026-05-24 (Path 1, cowork-ah1 bus #916)
authored_by: lead (AH1-Terminal)
reply_target: lead
target: b1
prior_mailbox_state: superseded — BRISEN_LAB_REDESIGN_PHASE_1 COMPLETE (merged PR #33 @ 19:30Z; deploy verified)
---

# CODE_1_PENDING — BRISEN_LAB_CLICK_TO_WAKE_1

## Read first

1. The brief: `briefs/BRIEF_BRISEN_LAB_CLICK_TO_WAKE_1.md` (canonical spec — read end-to-end).
2. The Surface Contract block at top of the brief — explains the 6-check verification done at brief-authoring time so you don't have to re-do it.
3. The Gate-1+2 reviewer instructions block at the bottom — those four invariants are what your ship report MUST demonstrate.

## Working directories

- **Components 1+2 (brisen-lab repo):** work in `~/bm-b1-brisen-lab/` (your existing brisen-lab clone). Create branch `b1/brisen-lab-click-to-wake-1`. Single PR against `vallen300-bit/brisen-lab` main.
- **Component 3 (baker-vault):** create `/tmp/baker-vault-c2w` fresh clone (avoid shared-FS race with the lead's working copy of baker-vault). Branch `b1/click-to-wake-sop-row-13`. Separate PR against `vallen300-bit/baker-vault` main.

## Sequence

1. Component 1: AppleScript + build.sh + README. Verify locally — run `bash tools/wake-handler/build.sh`, then `open 'brisen-lab://wake/b1'` and confirm a Terminal window opens running `b1` shell function.
2. Component 2: app.js click handler + cache-bust bumps in index.html (both app.js?v= AND styles.css?v=).
3. Open brisen-lab PR for 1+2 together. Ship report under `briefs/_reports/B1_BRISEN_LAB_CLICK_TO_WAKE_1_<YYYYMMDD>.md` with literal output for all 5 ship-gate items in the brief.
4. After brisen-lab PR merges + deploy verified + live `curl` confirms new `WAKEABLE_ALIASES` line is served: do Component 3 (baker-vault SOP PR).
5. Bus-post lead on ship (per agent-bus-posting-contract — bus on every state change).

## Gate chain (your trigger after ship)

- Gate-1 architecture: deputy (AH2)
- Gate-2 /security-review: deputy (AH2)
- Gate-3 picker-architect: SKIP (no install, no picker symlink change)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2)
- Gate-5 merge: lead (AH1)

## Reply target

Post your ship report bus message to `lead` (NOT deputy). Lead orchestrates the gate chain — will dispatch deputy for gates after your ship lands.

## Director context

Director just spent ~45 minutes today personally installing the 14 Terminal.app profiles + 5 new shell functions. This brief eliminates the manual step entirely going forward: badge appears → click card → picker opens. Director-ratified Path 1 (cowork-ah1 bus #916) explicitly.

## What NOT to do

- Do NOT add a new HTTP route on baker-master or brisen-lab. This is a client-side + macOS-local feature.
- Do NOT touch `~/.zshrc` or `~/Library/Preferences/com.apple.Terminal.plist`. Shell functions + Terminal profiles already exist.
- Do NOT widen `WAKEABLE_ALIASES` beyond TERMINALS. Cortex card + matter placeholders MUST fall through to existing detail-modal behavior.
- Do NOT remove the existing detail-modal click handler. Badge-gating preserves it; shift+click escape hatch preserves it for badged cards too.
- Do NOT ship without verifying that `open 'brisen-lab://wake/b1'` produces a real Terminal window in your environment. AppleScript-looks-right is not a ship gate.
