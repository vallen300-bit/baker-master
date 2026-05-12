---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_1.md
trigger_class: TIER_B_FRONTEND_PLUS_DAEMON_LOGIC
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
director_ratification: Director ratified 2026-05-13 ("ratified") after architect + reviewer review chain folded into brief (3 HIGH/SIGNIFICANT findings + 4 MINOR/LOW)
priority: P2
phase: 1 of 1
expected_pr_count: 2 (baker-master + brisen-lab)
expected_branch_baker_master: b3/brisen-lab-card-state-fix-1
expected_branch_brisen_lab: b3/brisen-lab-card-state-fix-1
expected_complexity: low-medium (~2-3h)
mandatory_2nd_pass: FALSE  # No auth/DB migration/concurrency/external surface; AH1 may invoke at discretion if review surfaces ambiguity
hard_ship_gate: literal `bash tests/test_forge_snapshot_push.sh` exit-0 output (all 5 cases PASS) pasted in baker-master PR description; manual smoke checklist (6 card states) pasted in brisen-lab PR description
gates_required:
  - AH2 /security-review on both PRs
  - picker-architect on both PRs
last_heartbeat: null
heartbeat_cadence: 12h max; mailbox UPDATE / commit-msg / ship-report all count
---

# CODE_3_PENDING — BRISEN_LAB_CARD_STATE_FIX_1 — 2026-05-13

**Brief:** `briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_1.md`
**Repos:** `baker-master` (your primary clone at `~/bm-b3`) + `brisen-lab` (you will need to clone to `~/bm-b3-brisen-lab`)
**Branches:**
  - `b3/brisen-lab-card-state-fix-1` in `~/bm-b3` (baker-master)
  - `b3/brisen-lab-card-state-fix-1` in `~/bm-b3-brisen-lab` (brisen-lab)
**Base SHAs:**
  - baker-master main: `9dbb97a` or newer
  - brisen-lab main: latest (b2 PR #12 squash `b612489` is the merge base)

**Supersedes:** prior CODE_3 slot (BRIEF_BRISEN_LAB_FORGE_PUSH_FOLD_1, PR #188 merged 334362a + daemon live on Mac Mini).

## What this dispatch is

Fold-fix for 3 post-deploy bugs in brisen-lab dashboard glance-UX after PR #12 (BRISEN_LAB_CARD_UX_CLEANUP_1):
1. **Worktree-blind daemon** — daemon scans single clone per terminal; b-codes work across multiple clones (`~/bm-bN` + `~/bm-bN-brisen-lab`).
2. **Card-state heuristic** — uses local branch as primary signal; ignores merge state + open PR.
3. **Mailbox brief-name parser** — `head -1 | sed` returns `---` on YAML frontmatter.

Plus, folded from architect/reviewer review pass:
- **Fix 3b** — `flock` single-instance guard against daemon overlap (per-cycle work grew with multi-clone snapshots).
- **Local var hygiene + subshell IFS isolation** in `pick_active_clone()` (real bash-scope bugs caught pre-dispatch).
- **awk regex tightened** (`[[:space:]]*` instead of `[[:space:]]`).
- **`(unparseable)` explicit-fail marker** in parser fallback instead of useless filename slug.
- **"Shipped (no PR)" distinct label** when green card has no PR trail.
- **Test cases extended** to 5 cases including non-git fallback (Case E).

Full brief at `briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_1.md` — read it first. The brief is the source of truth; this mailbox file is just the routing header.

## Pre-flight before you start

1. `git pull --ff-only origin main` in `~/bm-b3`.
2. `git clone https://github.com/vallen300-bit/brisen-lab.git ~/bm-b3-brisen-lab` (you don't have this clone yet).
3. `cd ~/bm-b3-brisen-lab && git pull --ff-only origin main`.
4. Read the brief end-to-end before touching any file. Pay attention to the "Review Chain Folded" table — the snippet shapes already reflect 2 HIGH bugs caught.
5. Branch from latest main in both repos as `b3/brisen-lab-card-state-fix-1`.

## Ship gate (mandatory)

**Baker-master PR:**
- Run `bash tests/test_forge_snapshot_push.sh` and paste the LITERAL output (all 5 cases PASS, exit 0) into the PR description.
- No "pass by inspection" language anywhere in the PR description or ship report.

**Brisen-lab PR:**
- Manual smoke checklist from Fix 2 §Verification (6 card-state cases) pasted into the PR description, each line checked.
- Cache-bust bump on `app.js?v=N` visible in the diff.

**Both PRs:**
- 4-gate review: AH2 `/security-review` + picker-architect. (No `feature-dev:code-reviewer` 2nd-pass — trigger evaluation in brief frontmatter explains why; AH1 invokes at discretion.)

## Heartbeat cadence

12h max between heartbeats while actively building. Heartbeats may be:
- Mailbox UPDATE entry (preferred — most reliable read path for AH1).
- Commit-msg heartbeat on either working branch (`mailbox(b3): heartbeat <ISO> — <where>`).
- Ship-report file.
- Bus-post to `lead` with topic `heartbeat/brisen-lab-card-state-fix-1`.

Two consecutive 12h misses (24h cumulative) → AH1 surfaces stall to Director once.

## On ship

Bus-post to `lead` with topic `ship/brisen-lab-card-state-fix-1` containing:
- Both PR links + commit SHAs (HEAD of each PR branch).
- Confirmation of pytest output presence in baker-master PR description.
- Confirmation of smoke-checklist presence in brisen-lab PR description.
- Any deviations from the brief (none expected, but flag explicitly if present).

After both PRs merge: AH1 reinstalls the daemon on Mac Mini + visual-verifies all 6 cards. You don't need to do the Mac Mini step — AH1 owns post-merge ops.

## Questions

If anything in the brief is ambiguous or you spot a bug in a snippet that escaped reviewer pass, post `blocker/brisen-lab-card-state-fix-1` to `lead` BEFORE writing code. Specifically: if `flock` isn't installed on macOS by default (or under a different name), bus-post the alternative you'd use (e.g. `lockfile-create`, `mkdir`-mutex) — AH1 ratifies.
