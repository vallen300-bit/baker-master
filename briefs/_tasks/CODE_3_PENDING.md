---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_2.md
brief_id: BRISEN_LAB_CARD_STATE_FIX_2
trigger_class: TIER_B_GLANCE_UX_PLUS_BUS_HYGIENE
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
mandatory_2nd_pass: true
security_review_required: true
effort_estimate: ~3-4h
predecessor:
  brief: briefs/BRIEF_DEADLINE_MATTER_SLUG_BACKFILL_1.md
  pr: 200
  merge_commit: 761b07d
director_ratification: |
  Director 2026-05-13 "Follow your recommendation" (twice — first on the bundled-vs-split
  brief question, then on the dispatch-order recommendation after parallel-AH1's
  DEADLINE_MATTER_SLUG_BACKFILL_1 self-cleared via PR #200).
priority: P2
phase: 1 of 1
expected_pr_count: 3 (baker-master + brisen-lab + baker-vault direct-push)
expected_branch_baker_master: b3/brisen-lab-card-state-fix-2
expected_branch_brisen_lab: b3/brisen-lab-card-state-fix-2
expected_complexity: medium (~3-4h; new bash helper + bash daemon patch + JS poll loop + process-doc update + 3 test files)
mandatory_gates:
  - AH2 /security-review on baker-master PR (helper script reads `op` credentials)
  - picker-architect (code-architecture-reviewer) on all 3 PRs
  - feature-dev:code-reviewer 2nd-pass on all 3 PRs — MANDATORY per Tier-B trigger #4 (external surface)
hard_ship_gate: |
  1. Literal `pytest` PASS for tests/test_ack_dispatch_msgs.py.
  2. Literal bash-test PASS for tests/test_forge_snapshot_push.sh feature-branch + stale-main case.
  3. Manual end-to-end verification of all three fixes per brief §Quality Checkpoints 3-5.
  4. Mirror install of forge_snapshot_push.sh to `/Users/dimitry/Library/Application Support/baker/` + launchctl kickstart (executed by B3 with literal output in ship report).
scope: |
  Three orthogonal fixes bundled by shared surface (glance-UX truth pipeline):
  Fix 1 — Worker ack-on-ship hygiene (new `scripts/ack_dispatch_msgs.sh` + process-doc update).
  Fix 2 — Forge daemon stale-local-clone read (git fetch + ff-pull before classify; `git show origin/main:...` on feature branches).
  Fix 3 — Lab UI badge SSE-reconnect staleness (60s sanity poll in app.js).
coordination: |
  B3's prior dispatch DEADLINE_MATTER_SLUG_BACKFILL_1 shipped via PR #200 (`761b07d`) and
  mailbox closed at `fbd2bcc` BEFORE this dispatch landed. B3 inbox drained (id=207 acked
  by AH1 2026-05-13 ~10:05Z as one-off pre-FIX_1 cleanup). Clean board.
ship_report_to: |
  Bus-post to `lead` on completion with topic `ship/BRISEN_LAB_CARD_STATE_FIX_2`.
  Include literal pytest/bash output + 4-gate verdicts in the post.
---

# Dispatch notice

Read `briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_2.md` end-to-end before starting.

Pre-flight:
1. `cd ~/bm-b3 && git fetch origin && git checkout main && git pull --ff-only origin main`.
2. Verify clean working tree on b3 (no leftover work from prior brief).
3. For the brisen-lab PR: clone or update `~/bm-b3-brisen-lab` (FIX_1 worktree pattern). If absent, `git clone git@github.com:vallen300-bit/brisen-lab.git ~/bm-b3-brisen-lab`.
4. For the baker-vault PR: use `/tmp/baker-vault-b3-card-fix-2` fresh clone to avoid shared-FS race (lesson 2026-04-30 anchor in brief).

Build discipline:
- Three PRs. Sequence: baker-master first (ack helper + forge daemon patch + tests), then brisen-lab (JS poll), then baker-vault (process-doc update — direct push to main per CHANDA Inv 9, no PR).
- Run the 4-gate chain on EACH of the 2 PRs (baker-master + brisen-lab). 2nd-pass MANDATORY per Tier-B trigger #4 (external surface — daemon + post-commit hooks across all clones + UI consumer).
- Heartbeat every 12h via mailbox UPDATE entry if mid-flight beyond first cycle.

End-of-work:
- Bus-post to `lead` with topic `ship/BRISEN_LAB_CARD_STATE_FIX_2`.
- Body: 4-gate verdicts per PR + literal pytest paste + manual-test outputs for all 5 Quality Checkpoints + mirror-install confirmation.
- Mailbox flip `CODE_3_PENDING.md` → frontmatter `status: COMPLETE` with PR refs; ack this dispatch's wake-ping (id will be visible in your inbox post-bus-post-from-lead — use the NEW `scripts/ack_dispatch_msgs.sh` against your own brief slug as the FIRST verification step of Fix 1 dogfooding).
