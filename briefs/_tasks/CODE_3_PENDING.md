---
status: PENDING
brief: briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md
brief_id: WRITE_BRIEF_SOP_ENFORCER_HOOK_1
target_repo: multi (baker-master + baker-vault)
matter_slug: baker-internal
dispatched_at: 2026-05-23T18:30:00Z
dispatched_by: lead
target: b3
working_branch_baker_master: b3/write-brief-sop-enforcer-hook-1
working_branch_baker_vault: b3/write-brief-sop-enforcer-hook-1
working_dir_baker_master: ~/bm-b3
working_dir_baker_vault: ~/bm-b3-baker-vault
reply_to: lead
priority: tier-b
estimated_time: 4.5-5.5h
trigger_class: MEDIUM
gate_chain:
  gate_1_architecture_review: REQUIRED (AH2)
  gate_2_security_review: REQUIRED — expected NO_FINDINGS (hooks read stdin/transcript only; no network, no auth, no secrets)
  gate_3_picker_architect: REQUIRED — cross-picker install verification (5 picker pickers)
  gate_4_code_reviewer_2nd_pass: REQUIRED (AH2 feature-dev:code-reviewer)
  gate_5_ah1_final: REQUIRED
prior_mailbox_state: superseded — MD_SCHEME_ALLOWLIST_1 V0.2 status CHANGES_REQUESTED in mailbox but ACTUAL state on main is MERGED via PR #246 (commit 7298a3d). b3 idle since.
ui_surface_prebrief: brief §Surface contract = N/A (pure harness/hook infra) — gate satisfied
---

# CODE_3_PENDING — WRITE_BRIEF_SOP_ENFORCER_HOOK_1 — 2026-05-23

**Brief:** `briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md`
**Target repos:** baker-master + baker-vault (multi-repo brief)
**Working dirs:** `~/bm-b3` (baker-master) + `~/bm-b3-baker-vault` (baker-vault — clone if missing via `git clone https://github.com/vallen300-bit/baker-vault.git ~/bm-b3-baker-vault`)
**Pre-requisites:** none

## Bottom line

Director ratified harness enforcement of /write-brief SOP after weekly reminder cycle. Two-layer enforcement parallel to render_env_guard + pre-commit Part 4 belt-and-braces:

- **Layer 2 (in-session):** PreToolUse hook blocks Write/Edit on brief paths unless /write-brief skill was invoked in the session. Bypass: env `BAKER_BRIEF_SOP_BYPASS=1`.
- **Layer 3 (git-time):** pre-commit hook scans staged brief diffs for 3+ of 5 canonical SOP section headers. Bypass: commit-msg trailer `Brief-SOP-bypass: <reason>`.

Combined single brief — not split. 12 test cases total. Eat-own-dog-food: this brief itself was authored via /write-brief (AC8).

## Pre-flight (mandatory before edit)

1. `cd ~/bm-b3 && git fetch origin main && git checkout main && git pull --ff-only` — sync baker-master.
2. `[ -d ~/bm-b3-baker-vault ] || git clone https://github.com/vallen300-bit/baker-vault.git ~/bm-b3-baker-vault` — ensure baker-vault checkout.
3. `cd ~/bm-b3-baker-vault && git fetch origin main && git checkout main && git pull --ff-only` — sync baker-vault.
4. `cd ~/bm-b3 && git checkout -b b3/write-brief-sop-enforcer-hook-1`
5. `cd ~/bm-b3-baker-vault && git checkout -b b3/write-brief-sop-enforcer-hook-1`
6. `git config core.hooksPath .githooks` (already configured per CLAUDE.md but verify in both repos).

## Scope (4 features per brief)

1. **Layer 2 hook + 5 picker installs** — canonical at `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh` + 5 copies at AH1-T / AH1-cowork / AH2 / Researcher / legacy-AH1-T pickers + 5 `.claude/settings.json` (or `settings.local.json` for researcher) edits
2. **Layer 3 hook + 2 pre-commit chain edits** — canonical at `~/baker-vault/.githooks/brief_sop_check.sh` + mirror at `~/bm-b3/.githooks/brief_sop_check.sh` + chain into both pre-commit hooks
3. **Tests** — 12 cases total: Layer 2 (6) at `~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh` + Layer 3 (6) at `~/baker-vault/.githooks/tests/test_brief_sop_check.sh`
4. **lessons.md append** — Layer 2 vs Layer 3 pattern (in-session harness + git-time audit; render_env_guard parallel)

## Hard constraints

- **No "by inspection"** — every AC needs literal bash test output pasted verbatim in ship report (Lesson #8)
- **Fail-open posture** on hook errors — gate-logic bugs must NEVER block legitimate work (mirror `ui-surface-prebrief-check.sh` ERR trap)
- **Anchored regex `\.md$`** — don't catch `.md.bak` etc.
- **Excluded paths from BOTH layers:** `briefs/_reports/*` + `briefs/_tasks/CODE_*_<state>.md`
- **Mirror drift mitigation:** `~/bm-b3/.githooks/brief_sop_check.sh` header MUST comment "MIRROR OF baker-vault/.githooks/brief_sop_check.sh — keep in sync"
- **Hook completion <1s** for common case — no LLM, no network, regex only
- **`git show :<path>`** to read staged blob — NOT on-disk file (pre-commit fires before commit)
- **JSON validity** — every settings.json edit MUST be `jq -e .` valid; if PreToolUse block exists, APPEND to its `hooks` array (don't replace `ui-surface-prebrief-check.sh`)
- **Researcher picker uses `settings.local.json`** — NOT `settings.json`. Verified at brief authoring time via `find`.

## Acceptance criteria (AC1-AC13 per brief)

See brief §Acceptance criteria. Highlights:
- AC1-AC8 (Layer 2 install + tests + dog-food)
- AC9-AC12 (Layer 3 install + tests + pre-commit chain)
- AC13 (combined literal 12-test output verbatim in ship report)

## Ship gate

- Literal output of both test harnesses (6/6 + 6/6 = 12/12 PASS) pasted in ship report
- `jq -e .` validates all 5 picker settings files
- `bash -n` syntax-clean on both hook scripts + both test scripts
- Mirror diff `~/baker-vault/.githooks/brief_sop_check.sh` vs `~/bm-b3/.githooks/brief_sop_check.sh` (tail -n +3 for both, skipping the differing header comment) returns empty
- Layer 2 manual smoke (post-install): write to /tmp/briefs/BRIEF_SMOKE.md without /write-brief invocation in a fresh shell → blocks
- Layer 3 manual smoke: stage partial brief in sandbox → blocks; add bypass trailer → passes

## Reporting (bus reply-to-sender)

Two PRs to open (one per repo). Bus-post `lead` on both PRs open:

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh lead \
  "ship/write-brief-sop-enforcer-hook-1 — baker-master PR #<N1> + baker-vault PR #<N2> open; +X LOC across N files; AC1-AC13 verified literal 12/12 PASS; awaiting AH2 gate chain (1+2+3+4) then AH1 merge." \
  ship/write-brief-sop-enforcer-hook-1
```

`lead` (AH1-T) handles gate orchestration + merge sequence (merge baker-vault first, then baker-master — Layer 3 mirror reads from vault canonical).

## References

- Brief: `briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md`
- Parent brief request: bus #788 (AH2)
- Layer 3 amendment: bus #790 (AH2)
- Existing PreToolUse precedent: `~/bm-aihead1/.claude/hooks/ui-surface-prebrief-check.sh`
- Existing pre-commit Part 4 precedent: `~/bm-aihead1/.githooks/pre-commit`
- jq schema verified live against current AH1-T session transcript by brief author 2026-05-23T18:00Z

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Two consecutive 12h misses → `lead` auto-surfaces stall to Director. Given ~4.5-5.5h scope, expect 1-2 heartbeats max.
