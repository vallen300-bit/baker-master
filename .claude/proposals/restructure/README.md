# CLAUDE.md Restructure — staging area

**Status (2026-04-29):** Drafts ready for Director review. **NOT YET MIGRATED.**

This folder is the staging area for the three-tier CLAUDE.md restructure. Open these drafts in Code app, edit anything, then signal greenlight — migration script will copy the final state to the live paths below.

## Files in this staging area

| Staging file | Target path | Tier | Migration mechanism |
|---|---|---|---|
| `tier1-global-CLAUDE.md` | `~/.claude/CLAUDE.md` | 1 (global) | **cp** (machine-local; one file per machine) |
| `tier2-project-CLAUDE.md` | `~/bm-b1/CLAUDE.md` (replaces) | 2 (project) | **git commit + push to `main`** (propagates to b1/b2/b3/b4 + AI Head dirs via `git pull`) |
| `tier3-local-CLAUDE.local.md` | `~/bm-b1/CLAUDE.local.md` (new) | 3 (local) | **cp** at `bm-b1` only (gitignored, per-worktree; b2/b3/b4 create on-demand if Director needs local overrides there — no file-presence parity expected) |
| `dot-claude-docs-baker-mcp-api.md` | `~/bm-b1/.claude/docs/baker-mcp-api.md` | extract | **git commit** (tracked) |
| `dot-claude-docs-critical-ids.md` | `~/bm-b1/.claude/docs/critical-ids.md` | extract | **git commit** (tracked) |

Plus: add `CLAUDE.local.md` to `~/bm-b1/.gitignore` (committed change to `.gitignore`, propagates).

**Why hybrid (cp vs commit):** Tier 2 + `.claude/docs/*` exist on every worktree (b1-b4 + AI Head dirs). cp-script approach would split-brain across worktrees on day 1. Committing to `main` is the only way to keep all 6 active checkouts consistent. Tier 1 is `~/.claude/` (one per machine, not per-worktree). CLAUDE.local.md is gitignored by design.

## Tier 0 — note (do not edit from here)

Tier 0 = `/Users/dimitry/Vallen Dropbox/Dimitry vallen/CLAUDE.md` (life-cache, 12.8KB) — already canonical, **stays where it is**, just gets `@`-imported by Tier 1. No change in this migration. Slimming Tier 0 is post-migration backlog.

## Decisions already locked

See canonical proposal for full ratification chain:
`/Users/dimitry/baker-vault/_ops/ideas/2026-04-28-claude-md-restructure-proposal.md`

11 locked decisions (latest: hybrid migration approach + how-to INDEX import + Operating Model rewrite — all 2026-04-29). AI Head 2 reviewed three times; revisions per third pass folded 2026-04-29. `@import` mechanism verified against Claude Code docs (path-with-spaces handling unverified — eliminated via Tier 0 symlink). Anthropic best-practices doc audited via RA-24 — `/compact` directive folded into Tier 2. claude-code-guide subagent verified Q3 (`~/.claude/CLAUDE.md` is correct global path), Q2a (`/memory` lists tiers), Q2b (external-import dialog fires per project).

## How to review with Code app

1. Open this directory in Code app (any session in `bm-b1`).
2. Read `tier1-global-CLAUDE.md`, `tier2-project-CLAUDE.md`, `tier3-local-CLAUDE.local.md`.
3. Compare against current `~/bm-b1/CLAUDE.md` (165 lines).
4. Edit drafts in place if needed — they're plain markdown.
5. When happy, signal greenlight in chat. Migration script (revised 2026-04-29 — hybrid cp + git, with Tier 0 symlink to avoid space-in-path @import unknown):

   ```bash
   cd ~/bm-b1

   # 0. Sanity: clean working tree on main, up-to-date
   git status && git pull --ff-only

   # 1. Local backups (machine-local files we're replacing/creating)
   cp ~/bm-b1/CLAUDE.md ~/bm-b1/CLAUDE.md.bak.20260429
   [ -f ~/.claude/CLAUDE.md ] && cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.bak.20260429

   # 1b. Commit the rollback script FIRST (separate commit, BEFORE migration)
   #     — so reverting the migration doesn't also remove the script needed to
   #     perform the revert.
   if [ -f scripts/claude_md_restructure_rollback.sh ] && \
      ! git ls-files --error-unmatch scripts/claude_md_restructure_rollback.sh >/dev/null 2>&1; then
     chmod +x scripts/claude_md_restructure_rollback.sh
     git add scripts/claude_md_restructure_rollback.sh
     git commit -m "$(cat <<'EOF'
scripts/claude_md_restructure_rollback.sh: single-shot rollback for three-tier restructure

<5 min RTO. Idempotent. Director-only manual fire. Reverses Tier 1/3 local
restores + removes Tier 0 symlink + git revert of migration commit + pulls
revert on all 5 sibling clones + verify eye-check.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
     git push origin main
   fi

   # 1c. Tier 0 symlink — eliminates the unknown of @import handling paths
   #     containing spaces (per claude-code-guide review 2026-04-29). Points
   #     to the canonical Dropbox-root CLAUDE.md.
   mkdir -p ~/.claude
   ln -snf "/Users/dimitry/Vallen Dropbox/Dimitry vallen/CLAUDE.md" ~/.claude/dropbox-tier0.md
   # Verify:
   readlink ~/.claude/dropbox-tier0.md && [ -f ~/.claude/dropbox-tier0.md ] && echo "symlink OK"

   # 2. Machine-local copies (cp): Tier 1 + Tier 3
   cp .claude/proposals/restructure/tier1-global-CLAUDE.md   ~/.claude/CLAUDE.md
   cp .claude/proposals/restructure/tier3-local-CLAUDE.local.md  ~/bm-b1/CLAUDE.local.md

   # 3. Tracked-content writes (will commit + push): Tier 2 + .claude/docs/*
   mkdir -p .claude/docs
   cp .claude/proposals/restructure/tier2-project-CLAUDE.md           CLAUDE.md
   cp .claude/proposals/restructure/dot-claude-docs-baker-mcp-api.md  .claude/docs/baker-mcp-api.md
   cp .claude/proposals/restructure/dot-claude-docs-critical-ids.md   .claude/docs/critical-ids.md
   grep -qxF "CLAUDE.local.md" .gitignore || echo "CLAUDE.local.md" >> .gitignore

   # 4. Commit + push (propagates Tier 2 + .claude/docs/* + .gitignore to all clones)
   git add CLAUDE.md .claude/docs/baker-mcp-api.md .claude/docs/critical-ids.md .gitignore
   git commit -m "$(cat <<'EOF'
CLAUDE.md three-tier restructure: Tier 2 rewrite + .claude/docs/ split

- Operating Model rewritten to current 5-terminal model (AI Head A/B + b1-b5 + Director); anchored to ai-head-autonomy-charter.md
- Capability count corrected to DB-verified 18 active / 24 total (was stale 21)
- RA-23 absorption status: ratified 2026-04-27, execution at first AO cycle
- Today anchor: Cortex Stage 2 V1 partial-shipped (1A/1B/1C/IDEMPOTENCY_1 merged); DRY_RUN pending
- Slug count refreshed to 34 / version 12 (was stale 19 / v1)
- Roadmap relabeled "canonical" (was misleading "legacy")
- Charter + Stage 2 tracker + worktree map added to reference pointers
- Compile-clean ≠ done anchored to Lesson #8
- .claude/docs/ split: baker-mcp-api.md + critical-ids.md extracted from root CLAUDE.md
- @.claude/how-to/INDEX.md import preserved at top (auto-loaded; bodies on-demand)
- Compaction directive folded per RA-24 audit

Reviewed by AI Head 2 (App) — 12 must-fix + 3 additions folded; 2 pre-commit checks cleared (clones not worktrees; PR #75 merged).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
   git push origin main

   # 5. All other clones pull (b5 included — has live commits even though 00_WORKTREES.md flags dormant)
   for d in ~/bm-b2 ~/bm-b3 ~/bm-b4 ~/bm-b5 ~/Desktop/baker-code; do
     [ -d "$d/.git" ] || continue
     ( cd "$d" && git pull --ff-only )
   done

   # 6. Canary — fresh Code session in ~/bm-b1 (NOT mid-session — currently-active
   #    sessions hold OLD CLAUDE.md in context; restart needed to pick up new file):
   #      - /memory shows Tier 0 (dropbox-tier0.md via symlink) + Tier 1 + Tier 2
   #        + Tier 3 (CLAUDE.local.md) all loaded
   #      - approve external-import dialog when it appears (ONE-TIME per project;
   #        will fire once per clone — b1 first, then b2/b3/b4/b5 each on their
   #        next fresh session; ~5 sequential approvals total across the machine)
   #      - DETERMINISTIC canary: ask "What is BAKER Space ID?" — must return
   #        901510186446 (from Tier 0's Critical IDs table). If wrong/missing,
   #        Tier 0 didn't load → check symlink + import dialog approval.

   # 7. Rollback (single command, <5 min RTO):
   #      bash scripts/claude_md_restructure_rollback.sh confirm
   #    (script handles: revert local Tier 1 from .bak, remove symlink, remove
   #     Tier 3, git revert + push, pull on all sibling clones, eye-check verify.
   #     Idempotent — safe to re-run.)

   # 8. Hold ~/bm-b1/CLAUDE.md.bak.20260429 + ~/.claude/CLAUDE.md.bak.20260429 for
   #    7 days, then delete. Rollback script remains valid as long as the
   #    migration commit is reachable on origin/main.
   ```

## Pre-migration: rollback dry-run (recommended)

Before treating migration as live, prove the rollback safety net works. ~15 min added to migration session, but the rollback is theoretical without it.

```bash
cd ~/bm-b1

# 1. Run migration (steps 0-5 above)
# 2. Verify canary passes (step 6 above)
# 3. Run rollback
bash scripts/claude_md_restructure_rollback.sh confirm
# 4. Verify state restored: diff key files against backups
diff ~/bm-b1/CLAUDE.md ~/bm-b1/CLAUDE.md.bak.20260429 && echo "Tier 2 restored"
[ ! -e ~/.claude/dropbox-tier0.md ] && echo "symlink removed"
[ ! -e ~/bm-b1/CLAUDE.local.md ] && echo "Tier 3 removed"
# 5. Re-run migration (steps 0-5; step 1b is a no-op on second run since
#    rollback script is already on main from the first migration attempt)
# 6. Verify canary passes again (step 6)
# 7. Treat migration as live.
```

If any dry-run step fails, do NOT proceed to live migration — debug + report.

**Important:** verify on a **fresh session** post-pull, not mid-session. Active sessions across all 5 terminals (aihead1/aihead2/b1/b2/b3/b4) hold the OLD CLAUDE.md in their loaded context — they'll only pick up the new file on next session start (or `/memory reload` if Claude Code surfaces that).

## What's already wired (do NOT regress)

- **`@.claude/how-to/INDEX.md`** import — added to live `~/bm-b1/CLAUDE.md` 2026-04-29. Preserved at top of `tier2-project-CLAUDE.md` draft. INDEX currently lists 2 how-tos: X/Twitter access + Local research via Gemma 4.
- **Compaction directive** — folded into Tier 2 per RA-24 audit.
- **`scripts/claude_md_restructure_rollback.sh`** — written 2026-04-29 (~110 lines). Single-shot rollback. Idempotent. <5 min RTO. Gets committed as a separate commit BEFORE the migration commit (step 1b) so reverting migration doesn't also remove the script.
