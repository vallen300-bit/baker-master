# BRIEF_BRANCH_HYGIENE_1 — baker-master Stale-Branch Auto-Prune

**Date:** 2026-04-26
**Source spec:** `_ops/ideas/2026-04-26-branch-hygiene-1.md`
**Author:** AI Head Build-reviewer (promoting from RA spec)
**Director defaults:** Q1/Q2/Q3 all defaulted to RA recommendations 2026-04-26 ("Your 3 question — you default. I skip"). Q2: **mobile UI cluster (8 branches) → DELETE.**
**Trigger class:** **LOW** (no auth/DB-migration/secrets/financial — touches GitHub external API only) → AI Head solo merge per autonomy charter §4

---

## 1. Bottom-line

Auto-prune merged branches in `baker-master` (squash-merged tip already in main) and flag >30-day-unmerged branches for Director review. Cat 7 close found **75 non-main branches** accumulated; 21 are 30–90d old, 0 are >90d.

Three-layer logic:
- **L1** auto-delete confirmed-squash-merged (≈50 branches expected)
- **L2** flag stale-unmerged 30d+ for Director review (do not auto-delete)
- **L3** Director-confirmed bulk delete (Triaga checkbox → batch action)

## 2. Why now

Block 2 Cat 7 close 2026-04-26:
- **0 open PRs** ✅ (clean in-flight)
- **75 non-main branches** accumulated as side effect of squash-merge workflow + abandoned exploration
- 37 branches <7d (recent ship work; mostly L1 candidates)
- 17 branches 7–30d (KBL Layer0/Loop, step1–7-impl — likely superseded)
- 21 branches 30–90d (mobile UI cluster + PM-TRIAGE-1 + agent-bridge — Director Q2 default = delete)

## 3. Architecture

| Layer | Trigger | Action |
|---|---|---|
| L1 | Branch HEAD's commit message + diff matches an already-merged commit on main (squash detected via `git merge-base --is-ancestor` OR tree-equal check) | Auto-delete remote branch; log to `branch_hygiene_log` |
| L2 | Branch >30d, no merge activity, tip not in main | Flag in Triaga HTML; do NOT auto-delete |
| L3 | Director ticks Triaga checkbox | Bulk-delete approved branches |

**Implementation:** new script `scripts/branch_hygiene.py`. One-shot or weekly cron (default: one-shot first, then weekly via APScheduler `branch_hygiene_weekly` Mon 10:30 UTC).

## 4. Director Q's — defaulted

| Q | Default applied |
|---|---|
| Q1: Auto-delete cadence? | **One-shot now (cleans backlog) + weekly cron** (Mon 10:30 UTC, post AI Head audit) |
| Q2: Mobile UI cluster (8 branches at 37–39d) | **DELETE** (not on Cortex-3T roadmap; reads as abandoned exploration). Branches: `feat/mobile-*`, `feat/ios-shortcuts-1`, `feat/document-browser-1`, `feat/networking-phase1` |
| Q3: L2 staleness threshold | **30d V1; tune to 14d after backlog cleared** |

## 5. Code Brief Standards

1. **API version:** GitHub REST `/repos/{owner}/{repo}/branches` (stable, no deprecation).
2. **Deprecation check:** confirm `gh` CLI version supports `gh api repos/.../branches` at build start (verified 2026-04-26 working in this session).
3. **Fallback note:** if GitHub rate-limits, exponential backoff (mirror Plaud / Todoist client pattern).
4. **DDL drift check:** new audit table `branch_hygiene_log`. Grep `store_back.py` for any `_ensure_branch_hygiene_*_base` bootstrap before migration. Verify type match.
5. **Ship gate:** literal `pytest` output. Tests: L1 squash detection, L2 staleness flag, L3 deletion API call (mocked), audit-log row created.
6. **Test plan:** see §7.
7. **file:line citations:** verify any cite into existing infra (e.g., APScheduler registration in `triggers/embedded_scheduler.py:N`) by reading the file.
8. **Singleton pattern:** N/A.
9. **Post-merge handoff:** the first one-shot run executes from a working tree — handoff must include `git pull --rebase origin main` immediately before script invocation.
10. **Invocation-path audit:** N/A.

## 6. Definition of done

- [ ] `scripts/branch_hygiene.py` implemented with L1+L2+L3 logic
- [ ] First run: auto-delete L1 squash-merged branches (~50 expected)
- [ ] Mobile UI cluster (8 branches) explicitly included in L1 OR L3 batch (Director default = delete)
- [ ] Triaga HTML for L2 flagged branches → Director review
- [ ] L3 bulk-delete after Director ticks
- [ ] APScheduler `branch_hygiene_weekly` job registered Mon 10:30 UTC
- [ ] Audit log table `branch_hygiene_log` records every deletion (branch_name, last_commit_sha, deleted_at, layer, reason)

## 7. Test plan

```
pytest tests/test_branch_hygiene.py -v
# ≥6 tests: L1 squash detection (positive + negative) / L2 staleness flag / L3 delete (mocked) / whitelist (main + protected) / log row creation
pytest tests/ 2>&1 | tail -3
# full-suite no regressions
```

Smoke run:
```
python3 scripts/branch_hygiene.py --dry-run
# expect: ~50 L1 candidates listed; 21 L2 flagged; 0 deletions
```

## 8. Out of scope

- Local branch cleanup (Director's local clones — separate concern)
- Worktree cleanup (`Desktop/baker-code/00_WORKTREES.md` separate process)
- PR auto-close on stale branch (orthogonal — branches without PRs are the issue here)

## 9. Promotion + dispatch path

- AI Head Tier B promotes spec → this brief.
- Dispatch to B3 (clearing HOLD; non-trigger-class).
- B3 builds, ships PR. AI Head solo review.

## 10. Risk register

| Risk | Mitigation |
|---|---|
| Mass-delete a not-yet-merged branch | L1 only acts on confirmed-squash-merged via `git merge-base --is-ancestor`; L2 flags only |
| GitHub API rate-limit during bulk-delete | Throttle to 10 deletions/min |
| Branch revival needed post-deletion | All deletions logged; GitHub provides 90-day branch revival window |
| Mobile UI cluster turns out wanted | Director default-delete = explicit; revival within 90d remains possible |

## 11. Authority chain

- Director ratification: 2026-04-26 "C" (Cat 7 close) + default-fallback ("you default. I skip")
- RA-19 spec: `_ops/ideas/2026-04-26-branch-hygiene-1.md`
- AI Head Tier B: this brief + dispatch
