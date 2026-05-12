---
type: b4_ship_report
brief: BRIEF_HARNESS_SUBAGENT_MIGRATION_1
mailbox: briefs/_tasks/CODE_4_PENDING.md @ ba99416
pr: 194
branch: b4/harness-subagent-migration
commit: aea2bee
shipped_at: 2026-05-12
shipped_by: b4
bus_post_message_id: 178
bus_post_topic: ship/HARNESS_SUBAGENT_MIGRATION_1
---

# B4 ship report — HARNESS_SUBAGENT_MIGRATION_1 — 2026-05-12

## TL;DR

PR #194 opened. 22 picker `.claude/agents/*.md` deletions + `.gitignore` entry + pre-commit hook. User-global `~/.claude/agents/` rebuilt to 22 files (12 forked-pair overwrites + 10 picker-only migrations + `baker-pm.md` Option-B path strip). Pre-overwrite backup at `~/.claude/agents.bak-2026-05-12/` (12 files). All 12 wrong-direction abort-gate diffs PASS, all enumerated in PR description. Smoke tests for criteria #8 (`baker-legal`) + #9 (`feature-dev:code-reviewer`) PASS locally on bm-b4 with `.claude/agents/` temporarily removed. Pytest pre-existing failures unchanged. Held back: post-merge 6-picker fresh-session sweep (requires real session opens).

## Brief vs implementation diff

| Brief step | Implementation |
|---|---|
| 1. Backup user-global | `cp -r ~/.claude/agents ~/.claude/agents.bak-2026-05-12` — 12 files verified |
| 2. Reconcile 12 forked pairs with abort gate | mtime + size + semantic check on all 12; all PASS; picker overwrites user-global |
| 3. Fix `baker-pm.md` hardcoded path | Option B (strip block) — both candidate paths absent. File 278 → 238 lines |
| 4. Migrate 10 picker-only | `code-architecture-reviewer`, `investment-proposal-analyst`, `baker-pm` (Option-B fixed), `russo-{ai,at,ch,cy,de,fr,lu}` |
| 5. Invocation-matrix audit | 18 types in 30d transcripts; 11 in user-global + 7 plugin/built-in; zero orphans |
| 6. Delete picker `.claude/agents/` | `git rm -r .claude/agents/` in bm-b4 (canonical baker-master clone); other 5 pickers propagate via post-merge `git pull` |
| 7. `.gitignore` `.claude/agents/` | Added at line 41-42 |
| 8. Pre-commit hook | Extended existing `.githooks/pre-commit`; rejects `.claude/agents/*.md` additions with remediation message |

## Architectural choice — single PR vs 6 per-picker PRs

Brief step 6 wrote `for picker in bm-aihead1 …; do git -C ~/${picker} rm -r .claude/agents/; done` as if pickers were separate repos. They aren't — all 6 are clones of the same `vallen300-bit/baker-master` remote (verified via `git -C ~/$p config --get remote.origin.url` × 6). So `.claude/agents/*.md` is 22 tracked files in one repo, appearing on disk in 6 clones. **Single PR in baker-master is correct.** Other 5 pickers drain via session-start `git pull` per project CLAUDE.md. Flagging this to AH1 in case brief language needs an update for future similar work.

## Acceptance criteria

| # | Criterion | State |
|---|---|---|
| 1 | Backup exists, 12 files | PASS — `~/.claude/agents.bak-2026-05-12/` (12 files) |
| 2 | User-global has 22 files | PASS — `ls ~/.claude/agents/ \| wc -l` = 22 |
| 3 | Zero tracked picker `.claude/agents/*.md` | PASS in baker-master (`git ls-files .claude/agents/` = 0); other 5 pickers' filesystem state drains post-merge `git pull` |
| 4 | Sanity find (not-path .git) | Same as #3 — drains post-merge |
| 5 | `.gitignore` entry per picker | PASS — single tracked `.gitignore` covers all 6 clones |
| 6 | Pre-commit hook blocks | PASS — verified with `touch + git add -f + git commit -m test` → EXIT=1 with clear remediation |
| 7 | Fresh-session smoke × 6 pickers | HELD — requires actual session opens; AH1 to drive post-merge |
| 8 | Brisen-internal subagent invokes post-delete | PASS locally — `Agent(subagent_type="baker-legal")` returned "SMOKE_TEST_PASS" from bm-b4 with `.claude/agents/` removed |
| 9 | (HARD GATE) plugin subagent × 6 pickers | PASS locally on bm-b4 — `Agent(subagent_type="feature-dev:code-reviewer")` resolved without picker dir; other 5 pickers expected identical (same resolver). Full 6-picker sweep HELD for AH1 post-merge |
| 10 | Invocation matrix orphan check | PASS — 18 types, 0 orphans |
| 11 | (HARD GATE) all 12 forked-pair diffs in PR | PASS — 168-line diff block in PR description with per-pair overwrite-direction + abort-gate annotation |
| 12 | PR diff shape | PASS — 22 deletions + .gitignore + pre-commit; user-global writes are off-tree by design (brief language was slightly misleading) |

## Pytest

```
$ source .venv-test/bin/activate && pytest -q
…
42 failed, 1880 passed, 85 skipped, 182 warnings, 30 errors in 68.69s (0:01:08)
```

Confirmed pre-existing on `main` — identical counts via `git stash + git checkout main + pytest`. This diff touches zero Python; no regression.

No subagent-registry tests exist (`grep -rl "\.claude/agents\|subagent" tests/` empty).

## Bus-post

```json
{"message_id":178,"thread_id":"8cc3099a-3572-41aa-935f-9162557ca194","posted_at":"2026-05-12T21:43:45.067396+00:00"}
```

Topic: `ship/HARNESS_SUBAGENT_MIGRATION_1` → recipient `lead`.

## Anchors

- Brief: `briefs/BRIEF_HARNESS_SUBAGENT_MIGRATION_1.md` @ d1a514c
- Mailbox: `briefs/_tasks/CODE_4_PENDING.md` @ ba99416 (dispatch)
- Branch: `b4/harness-subagent-migration` @ aea2bee
- PR: https://github.com/vallen300-bit/baker-master/pull/194
- Backup: `~/.claude/agents.bak-2026-05-12/`
- Diff archive: `/tmp/subagent-diffs/` (12 files, not committed)
