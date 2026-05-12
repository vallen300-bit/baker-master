---
report: B3_brisen_lab_card_state_fix_1
brief: BRIEF_BRISEN_LAB_CARD_STATE_FIX_1
brief_path: briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_1.md
shipped_by: b3
shipped_at: 2026-05-12T17:30Z
prs:
  - https://github.com/vallen300-bit/baker-master/pull/190
  - https://github.com/vallen300-bit/brisen-lab/pull/13
baker_master_head: e184251
brisen_lab_head: 3cacc71
test_output: literal `bash tests/test_forge_snapshot_push.sh` exit-0 with 5 PASS lines (pasted in baker-master PR #190)
manual_smoke_pasted_in: brisen-lab PR #13 description (6 cases table)
deviations: 1 (flock → mkdir-mutex; bus-posted blocker msg #142 to lead)
gates_required:
  - AH2 /security-review (both PRs)
  - picker-architect (both PRs)
---

# B3 ship report — BRISEN_LAB_CARD_STATE_FIX_1

## What shipped

3 fold-fixes for post-deploy bugs in brisen-lab dashboard card UX:

1. **Fix 1 — Worktree-aware daemon.** `TERMINALS` array now holds comma-separated candidate paths per b-code; `pick_active_clone()` scores: open PR (+1000), pending mailbox (+100), recency tiebreaker. Subshell isolates `IFS=','`; all state vars `local`. Missing clones return score 0; empty result falls back to first candidate.
2. **Fix 3 — `extract_brief_name()` 3-step parser.** YAML frontmatter `brief:` field → first `# heading` → explicit `(unparseable)` marker. awk regex `[[:space:]]*` (zero-or-more) accepts `brief:value`, `brief: value`, `brief:\tvalue`.
3. **Fix 3b — Single-instance guard.** `mkdir`-mutex (not `flock` — see Deviation below). Stale-lock reclaim via `kill -0` check on owning PID. Exit 0 on collision so launchd doesn't back off.
4. **Fix 4 — Test harness extended to 5 cases (A/B/C/D/E).** `DEBUG_DUMP_PAYLOAD=1` env-var hook for JSON-field assertions without HTTP receiver. Per-case `LOCK_DIR` so mkdir-mutex doesn't block sequential cases.
5. **Fix 2 — Brisen-lab `cardState()` rewrite.** Priority-ordered rules: green/grey first → yellow-with-PR (`open_pr_number` present, branch-agnostic) → yellow-without-PR → red. Subject-line updates: yellow+PR shows `PR #N: <title>`; green-no-PR shows `Shipped (no PR): <subject>` (architect-folded distinct label).
6. **Fix 2.3 — Cache-bust bump** `app.js?v=5` → `?v=6`.

## Literal test output (baker-master PR #190 ship gate)

```
PASS: Case A — heading-style mailbox, single clone.
PASS: Case B — YAML frontmatter mailbox extracts brief: field.
PASS: Case C — two-clone alias picks pending-mailbox clone (overrides recency).
PASS: Case D — two-clone alias falls back to recency tiebreaker.
PASS: Case E — two non-git candidate paths fall back to first; daemon still emits stderr without crash.

All 5 cases PASS.
EXIT=0
```

No "by inspection" anywhere. Manual smoke checklist (6 cases) pasted into brisen-lab PR #13 description.

## PRs

| Repo | PR | Branch | HEAD | Status |
|---|---|---|---|---|
| baker-master | [#190](https://github.com/vallen300-bit/baker-master/pull/190) | `b3/brisen-lab-card-state-fix-1` | `e184251` | open, awaiting gates |
| brisen-lab | [#13](https://github.com/vallen300-bit/brisen-lab/pull/13) | `b3/brisen-lab-card-state-fix-1` | `3cacc71` | open, awaiting gates |

## Deviation: `flock` → `mkdir`-mutex

Brief specified `flock` for Fix 3b. macOS doesn't ship `flock` and no Homebrew formula installed on b3 host (probe results: `which flock` → not found; `/opt/homebrew/opt/flock` → empty; `brew list flock` → error). Also no `lockfile-create` / `lockfile` / `dotlockfile` (procmail-tools not installed).

Posted `blocker/brisen-lab-card-state-fix-1` to lead bus msg **#142** at 2026-05-12T17:02Z with proposal: `mkdir`-mutex (POSIX-atomic, zero deps, every macOS) with stale-lock reclaim via `kill -0` on owning PID. Proceeded with implementation under assumption AH1 ratifies; AH1 may redirect via mailbox UPDATE if a different alternative is wanted (`lockfile-create` install or Homebrew `flock` formula on Mac Mini) — I'll fold same branch.

Implementation matches brief's intent: single-instance guard, exit 0 on collision (launchd no back-off), survives across daemon restarts, cleared on Mac Mini reboot. Mac Mini operational behavior should be identical.

## Files touched

### baker-master (`~/bm-b3`)
- `scripts/forge_snapshot_push.sh` (+150 / -8)
- `tests/test_forge_snapshot_push.sh` (+230 / -42)

### brisen-lab (`~/bm-b3-brisen-lab`, newly cloned)
- `static/app.js` (+25 / -14)
- `static/index.html` (+1 / -1)

## Files NOT touched (per brief §"Do NOT Touch")

- `scripts/launchd/com.baker.forge-snapshot-push.plist`
- `scripts/install_forge_push.sh`
- brisen-lab `app.py` `/api/snapshot` handler + `db.py` schema
- `static/styles.css`
- `renderCortexCard()` / `renderCoworkCard()`
- baker-vault files

## Gates required before merge

1. AH2 `/security-review` on both PRs
2. picker-architect on both PRs
3. `feature-dev:code-reviewer` 2nd-pass — SKIPPED per brief frontmatter (`mandatory_2nd_pass: FALSE`; AH1 may invoke at discretion if review surfaces ambiguity)

## Post-merge ownership (AH1)

Per brief §"On ship": AH1 reinstalls daemon on Mac Mini + visual-verifies all 6 cards on https://brisen-lab.onrender.com. b3 does NOT do the Mac Mini step.

## Lessons applied

- **Migration-aware DDL grep:** N/A (no DB column added)
- **No ship by inspection:** literal pytest-equivalent output captured + pasted
- **Hot-fix vs amend:** no amends after push; all changes are net-new commits
- **Cache-bust on iOS PWA:** `app.js?v=N` bumped
- **YAML scalar parsing:** awk treats `brief:` value as string; no type-coercion
