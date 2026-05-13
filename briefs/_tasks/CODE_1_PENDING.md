---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_2.md
brief_id: BRISEN_LAB_CARD_STATE_FIX_2
trigger_class: TIER_B_GLANCE_UX_PLUS_BUS_HYGIENE_FAST_FOLLOW
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b1
phase: fast-follow v0-2 (post-gate-chain REQUEST_CHANGES)
re_dispatch_reason: |
  Originally dispatched to b3 at b74da09. B3 shipped PRs #201 + #16 + baker-vault
  d64c07d. AH1 4-gate chain returned PASS-WITH-NITS with 1 HIGH on PR #201 +
  1 MEDIUM on PR #16 — fast-follow required. Mid-gate-chain, parallel-AH1
  re-dispatched B3 to DEADLINE_SIGNAL_HYGIENE_1 (Director-ratified post-Triaga).
  Director directive 2026-05-13: "direct the work not to B3 but to B1, B2, or
  B4." AH1 picked B1 (cleanest mailbox state, fresh forge/daemon perimeter
  context from PR #196).
mandatory_2nd_pass: true
security_review_required: false (covered in v0-1 gate chain; fix-by-fix is scoped)
effort_estimate: ~1-1.5h (fix-by-fix only — small additions to existing branch)
existing_branches:
  baker_master: b3/brisen-lab-card-state-fix-2 (PR #201, head c-prefix already on origin)
  brisen_lab: b3/brisen-lab-card-state-fix-2 (PR #16, head already on origin)
prs_open:
  - https://github.com/vallen300-bit/baker-master/pull/201
  - https://github.com/vallen300-bit/brisen-lab/pull/16
fix_by_fix_pointer:
  pr_201_comment: https://github.com/vallen300-bit/baker-master/pull/201#issuecomment-4439021572
  pr_16_comment: https://github.com/vallen300-bit/brisen-lab/pull/16#issuecomment-4439022390
hard_ship_gate: |
  1. PR #201 HIGH (extract_brief_name branch-aware) + 2 MEDIUMs (Case H' integration + cold-clone fallback) addressed; literal pytest + bash output paste.
  2. PR #16 MEDIUM (drift key extended to age + topics, not just count) addressed; literal manual reveal showing badge auto-corrects when count stable + age drifting.
  3. LOWs: fix what's easy in the same fast-follow commit (suggest read -ra array fix for ack_dispatch_msgs.sh:131, -f drop from inbox curl :244, drift comment alignment on app.js:54-56 and :60).
  4. Re-trigger gate chain via bus-post topic `ship/BRISEN_LAB_CARD_STATE_FIX_2-v0-2` on push of fix-by-fix commit to existing branches.
scope: |
  Fast-follow ONLY. Continue work on existing branches `b3/brisen-lab-card-state-fix-2`
  in both baker-master (~/bm-b1 or fresh clone of vallen300-bit/baker-master) AND
  brisen-lab (~/bm-b1-brisen-lab — create if absent). Do NOT open new PRs. Do NOT
  rename branches (Director-pragmatic call — branch prefix is convention, not
  binding).
coordination: |
  B3 is occupied with DEADLINE_SIGNAL_HYGIENE_1 (parallel-AH1's dispatch). B3
  received msg #214 with request-changes details for FIX_2 — that message is now
  obsolete for B3; AH1 acked it on B3's behalf via curl + sent B3 a standdown.
  B1 owns FIX_2 fast-follow from this dispatch forward.
ship_report_to: |
  Bus-post to `lead` on completion with topic `ship/BRISEN_LAB_CARD_STATE_FIX_2-v0-2`.
  Include literal pytest/bash output + manual reveal confirmation + fix-by-fix
  closure summary per PR.
---

# Dispatch notice

Read first (in order):
1. `briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_2.md` — full original spec (you are picking up fast-follow on it).
2. PR #201 comment 4439021572 — fix-by-fix instructions for baker-master HIGH + MEDIUMs + LOWs.
3. PR #16 comment 4439022390 — fix-by-fix instructions for brisen-lab MEDIUM + LOWs.
4. B3's original ship report at `briefs/_reports/B3_BRISEN_LAB_CARD_STATE_FIX_2_*.md` — what B3 already built (so you don't redo it).

Pre-flight:
1. `cd ~/bm-b1 && git fetch origin && git checkout b3/brisen-lab-card-state-fix-2 && git pull --ff-only origin b3/brisen-lab-card-state-fix-2`.
2. For brisen-lab: `git clone git@github.com:vallen300-bit/brisen-lab.git ~/bm-b1-brisen-lab` (if absent) and checkout `b3/brisen-lab-card-state-fix-2`.

Build discipline (fast-follow only):
- baker-master: address HIGH + 2 MEDIUMs + LOWs per PR #201 comment. Add Case J test (feature branch with no local mailbox file). Single commit. Push to existing branch — PR auto-updates.
- brisen-lab: address MEDIUM + LOWs per PR #16 comment. Extend drift key to include `oldest_unacked_age_sec` and `topics`. Single commit. Push to existing branch.
- Mirror install: re-run `cp + launchctl kickstart` on Mac Mini after baker-master fast-follow lands. Capture daemon state in ship report.

End-of-work:
- Bus-post to `lead` with topic `ship/BRISEN_LAB_CARD_STATE_FIX_2-v0-2`.
- Body: per-PR fix-by-fix closure (HIGH closed by X, MEDIUMs closed by Y/Z) + literal pytest/bash paste + manual reveal output.
- Use the NEW `scripts/ack_dispatch_msgs.sh` from this brief's Fix 1 as the FIRST verification step — ack this dispatch's wake-ping (you'll get one shortly after AH1 bus-posts you). That's the Fix 1 dogfood.
- Mailbox flip `CODE_1_PENDING.md` → frontmatter `status: COMPLETE` after AH1 confirms re-gate-chain clear.
