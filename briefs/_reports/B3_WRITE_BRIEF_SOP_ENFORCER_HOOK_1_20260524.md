# B3 Ship Report — WRITE_BRIEF_SOP_ENFORCER_HOOK_1 (2026-05-24, v2 fix-pass)

**Brief:** `briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md` (commit `4548869`)
**Dispatch:** `briefs/_tasks/CODE_3_PENDING.md` (bus #792, `dispatched_by: lead`)
**REQUEST_CHANGES anchor:** bus #799 (4 required + 1 cosmetic) → AH2 Gate verdict bus #797
**PRs:**
- baker-vault: https://github.com/vallen300-bit/baker-vault/pull/109
- baker-master: https://github.com/vallen300-bit/baker-master/pull/253
**Branches:** `b3/write-brief-sop-enforcer-hook-1` in both repos.
**Merge order (AH1):** baker-vault first, then baker-master (live picker symlinks resolve to vault canonical post-merge + `~/baker-vault` git pull).

## Bottom line

**13/13 PASS** (Layer 2 6/6 + Layer 3 7/7 after Case 7 H1-only regression added per Fix 4). AC10 trailer-bypass acknowledged as **PARTIAL by-design** (pre-commit-stage timing constraint; env-var bypass is the reliable path that ships). All 4 required fixes from bus #799 applied; cosmetic Fix 5 reflected below.

## Fix-pass summary (bus #799 → b3)

| Fix | Description | Resolution |
|---|---|---|
| 1 | `"timeout": 10` missing on PreToolUse hook entry | Added to 6 settings.json (bm-b3 tracked + 5 live pickers). QC #7 below. |
| 2 | 5 picker copies were orphaned byte-identical files (no source-of-truth) | Refactored to **canonical + symlink** pattern per `ui-surface-prebrief-check.sh` precedent. Canonical at `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh`. Live picker installs are untracked symlinks to that path. Tracked file `bm-b3/.claude/hooks/write_brief_sop_enforcer.sh` REMOVED from baker-master PR (git rm). QC #6 below. |
| 3 | Researcher wired in `settings.local.json` (local-override layer, gitignored by convention) | Moved to `~/bm-researcher/.claude/settings.json` (new file). settings.local.json now contains only `permissions`. |
| 4 | Layer 3 section regex `^##?` accepts H1 (spec requires `##`) | Tightened to literal `^## ` for Context / Files Modified / Verification / Quality Checkpoints. Problem regex `^(##\|###) Problem` already correct + retained. Added Case 7 H1-only regression. L3 cases: 6 → 7. QC #5 below. |
| 5 | Cosmetic — AC10 trailer-bypass mark | Updated AC10 to ⚠️ PARTIAL; headline 12/12 → 13/13 PASS + 1 partial-by-design (AC10 trailer path inert by pre-commit-stage timing; env-var path PASS). |

## Live install state after fix-pass

- **Canonical (REAL file):** `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh` (committed via baker-vault PR #109; pre-staged in `~/baker-vault` working dir so symlinks resolve pre-merge)
- **6 live symlinks** (all pointing → canonical above): bm-b3, bm-aihead1, bm-aihead1-cowork, bm-aihead2, bm-researcher, ~/Desktop/baker-code (all untracked per ui-surface-prebrief precedent)
- **Tracked settings.json edit** (baker-master PR #253): bm-b3/.claude/settings.json — adds PreToolUse Write|Edit|MultiEdit invoking `.claude/hooks/write_brief_sop_enforcer.sh` (with `timeout: 10`). On merge, other baker-master clones receive the same PreToolUse block on pull; each picker still needs its own local symlink (operator runs `ln -s ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh .claude/hooks/write_brief_sop_enforcer.sh` once per fresh clone, same convention as ui-surface-prebrief).

## AC verification matrix (v2)

| AC | Description | Status | Evidence |
|---|---|---|---|
| AC1 | Layer 2 hook at vault canonical + 5 picker installs; all executable | ✅ | QC #6 below — 6 symlinks resolve + executable |
| AC2 | Layer 2 path regex matches brief paths; excludes `_reports` + `_tasks/CODE_*_<state>` | ✅ | L2 cases 5+6 PASS |
| AC3 | Layer 2 block message names skill + bypass env | ✅ | Manual smoke 1 stderr (QC #11) |
| AC4 | Layer 2 bypass env logs + passes | ✅ | L2 case 4 PASS + manual smoke 2 |
| AC5 | Layer 2 installed in 5 picker settings files (NOT B-codes or global) | ✅ | QC #7 below |
| AC6 | Layer 2 test harness 6 cases / 6/6 PASS | ✅ | QC #4 below |
| AC7 | Literal test output in this ship report | ✅ | QC #4 + #5 below (verbatim) |
| AC8 | Brief itself authored via `/write-brief` (dog-food) | ✅ | Brief commit `4548869` per AH1 anchor 2026-05-23T18:00Z |
| AC9 | Layer 3 hook canonical + bm-b3 mirror; 3+/5 missing → block | ✅ | QC #3 (mirror diff empty) + L3 case 2 PASS |
| AC10 | Layer 3 bypass via commit-msg trailer | ⚠️ PARTIAL | env-var path passes (L3 case 3 PASS); trailer path inert by pre-commit-stage timing (git writes COMMIT_EDITMSG at commit-msg stage AFTER pre-commit). Trailer-detection branch preserved in hook for future commit-msg companion. AH2 Gate-1 verdict requested. |
| AC11 | Layer 3 test harness — 7 cases (6 from brief + Case 7 H1-only regression for Fix 4) / 7/7 PASS | ✅ | QC #5 below |
| AC12 | Layer 3 chained in vault pre-commit + invoked from baker-master Part 5 | ✅ | QC #8 + #9 below |
| AC13 | Combined literal output pasted verbatim (13 cases) | ✅ | QC #4 + #5 below |

## Quality Checkpoints (literal output, post-fix-pass)

### QC #1: Layer 2 hook syntax check
```
$ bash -n ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh && echo OK
OK
```

### QC #2: Layer 3 hook syntax check
```
$ bash -n ~/baker-vault/.githooks/brief_sop_check.sh && echo OK
OK
```

### QC #3: Mirror diff (vault canonical vs baker-master mirror, tail -n +3)
```
$ diff <(tail -n +3 ~/baker-vault/.githooks/brief_sop_check.sh) <(tail -n +3 ~/bm-b3/.githooks/brief_sop_check.sh)
(empty — mirror byte-identical from line 3 onward)
```

### QC #4: Layer 2 tests (6 cases)
```
$ bash ~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh
PASS: 1 brief-path+no-skill blocks (exit 2)
PASS: 2 brief-path+skill passes (exit 0)
PASS: 3 non-brief-path passes (exit 0)
PASS: 4 bypass-env passes (exit 0)
PASS: 5 ship-report path passes (exit 0)
PASS: 6 dispatch-envelope passes (exit 0)

Layer 2: 6 passed, 0 failed
```

### QC #5: Layer 3 tests (7 cases — Case 7 added for Fix 4 H1-only regression)
```
$ bash ~/baker-vault/.githooks/tests/test_brief_sop_check.sh
PASS: 1 full brief passes (exit 0)
PASS: 2 partial brief (3+ missing) blocks (exit nonzero)
PASS: 3 partial brief + bypass env passes (exit 0)
PASS: 4 non-brief file passes (exit 0)
PASS: 5 ship report passes (exit 0)
PASS: 6 dispatch envelope passes (exit 0)
PASS: 7 H1-only brief (all # not ##) blocks (exit nonzero)

Layer 3: 7 passed, 0 failed
```

### QC #6: All 6 picker installs are symlinks → vault canonical + executable
```
$ for p in ~/bm-b3 ~/bm-aihead1 ~/bm-aihead1-cowork ~/bm-aihead2 ~/bm-researcher ~/Desktop/baker-code; do
    target="$p/.claude/hooks/write_brief_sop_enforcer.sh"
    [ -L "$target" ] && [ -x "$target" ] && echo "OK: $p → $(readlink "$target")" || echo "FAIL: $p"
done
OK: /Users/dimitry/bm-b3 → /Users/dimitry/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
OK: /Users/dimitry/bm-aihead1 → /Users/dimitry/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
OK: /Users/dimitry/bm-aihead1-cowork → /Users/dimitry/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
OK: /Users/dimitry/bm-aihead2 → /Users/dimitry/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
OK: /Users/dimitry/bm-researcher → /Users/dimitry/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
OK: /Users/dimitry/Desktop/baker-code → /Users/dimitry/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
```

### QC #7: All 5 picker settings.json valid JSON + write-brief PreToolUse entry has `timeout: 10`
```
$ for p in ~/bm-aihead1/.claude/settings.json ~/bm-aihead1-cowork/.claude/settings.json ~/bm-aihead2/.claude/settings.json ~/bm-researcher/.claude/settings.json ~/Desktop/baker-code/.claude/settings.json; do
    jq -e '.hooks.PreToolUse[]?.hooks[] | select(.command|test("write_brief_sop_enforcer")) | .timeout == 10' "$p" >/dev/null && echo "OK: $p" || echo "FAIL: $p"
done
OK: /Users/dimitry/bm-aihead1/.claude/settings.json
OK: /Users/dimitry/bm-aihead1-cowork/.claude/settings.json
OK: /Users/dimitry/bm-aihead2/.claude/settings.json
OK: /Users/dimitry/bm-researcher/.claude/settings.json
OK: /Users/dimitry/Desktop/baker-code/.claude/settings.json
```

### QC #8: baker-vault pre-commit chains brief_sop_check.sh
```
$ grep -q 'brief_sop_check.sh' ~/baker-vault/.githooks/pre-commit && echo "OK (chained)"
OK (chained)
```

### QC #9: baker-master pre-commit Part 5 invokes brief_sop_check.sh
```
$ grep -q 'brief_sop_check.sh' ~/bm-b3/.githooks/pre-commit && echo "OK (invoked)"
OK (invoked)
```

### QC #11: Layer 2 manual smoke (block + bypass)
```
$ printf '{"tool_name":"Write","tool_input":{"file_path":"/tmp/briefs/BRIEF_SMOKE.md","content":"x"},"transcript_path":"/tmp/empty.jsonl"}' \
    | bash ~/bm-b3/.claude/hooks/write_brief_sop_enforcer.sh 2>&1
BLOCKED by write-brief-sop-enforcer: Write/Edit to a brief path requires the `/write-brief` skill to be invoked first in this session.

Run: Skill(skill="write-brief") and walk through the 6 SOP steps (EXPLORE → PLAN → WRITE → REVIEW → PRESENT → CAPTURE LESSONS).

Bypass for legitimate non-authoring edits (typo fix, status update, link refresh): set env `BAKER_BRIEF_SOP_BYPASS=1` before the tool call. Bypass usage is logged to stderr for audit.

Skill location: ~/.claude/skills/write-brief/SKILL.md
Director directive 2026-05-23 evening.
EXIT=2

$ ... | BAKER_BRIEF_SOP_BYPASS=1 bash ~/bm-b3/.claude/hooks/write_brief_sop_enforcer.sh 2>&1
INFO [write-brief-sop-enforcer]: bypass env set (BAKER_BRIEF_SOP_BYPASS=1); allowing write to /tmp/briefs/BRIEF_SMOKE.md at 2026-05-24T04:48:39Z
EXIT=0
```

### QC #12: Layer 3 manual smoke (block + bypass) — re-verified post-fix-pass
```
$ cd $(mktemp -d) && git init -q && cp ~/baker-vault/.githooks/brief_sop_check.sh .git/hooks/pre-commit
$ chmod +x .git/hooks/pre-commit
$ mkdir briefs && cat > briefs/BRIEF_SMOKE.md <<'EOF'
# BRIEF: SMOKE
## Context
ctx only — missing 4 sections
EOF
$ git add briefs/BRIEF_SMOKE.md && git commit -m "partial smoke" >/dev/null 2>&1
Git commit exit code: 1  (expect non-zero = blocked)

$ BAKER_BRIEF_SOP_BYPASS=1 git commit -m "partial smoke - bypass"
[main (root-commit) ...] partial smoke - bypass
EXIT=0
```

## Design notes for AH2 Gate 1 (architecture review) — carry-forward

### Design Note 1 — jq `-e` + `set -u` + `trap ERR` trips silent fail-open

**Caught at L2 test case 1's first run:** the brief's literal jq query used `jq -e -s ... | length > 0`. With `-e`, jq exits 1 when bool result is `false`. Inside `$(...)` with `set -u` + `trap '... exit 0' ERR`, the non-zero return tripped the ERR trap → hook exited 0 silently → block path never executed → silent bypass. Fix: drop `-e` from jq, add `|| echo "false"` fallback. Captured in `tasks/lessons.md`. (No change in v2 fix-pass.)

### Design Note 2 — Layer 3 trailer-bypass mechanism gap (AC10 ⚠️ PARTIAL)

Live-tested with git 2.50.1: `git commit -m "...\n\nBrief-SOP-bypass: reason"` and `git commit -F /tmp/msg.txt` both leave pre-commit unable to see the trailer (git writes `COMMIT_EDITMSG` at commit-msg stage AFTER pre-commit). Editor-flow pre-commit fires before editor opens; first-commit-of-fresh-repo has no `COMMIT_EDITMSG` at all.

**Pragmatic decision shipped in this PR:**
- Trailer-detection code preserved in `brief_sop_check.sh` (no harm; would fire on the rare case where COMMIT_EDITMSG happens to be pre-populated with the trailer)
- Env-var bypass `BAKER_BRIEF_SOP_BYPASS=1` is the documented + tested reliable path (matches render-env-guard Part 4 pattern from the same gap)
- Layer 3 test case 3 covers env-var bypass (the path that actually works)
- AC10 marked ⚠️ PARTIAL with explicit reason

**AH2 Gate-1 verdict still needed** (not blocking ship): keep current dual-path with env-var-tested / migrate to commit-msg-stage companion / drop trailer entirely.

## Files modified (v2)

**baker-vault PR (#109):**
- NEW `_ops/hooks/write_brief_sop_enforcer.sh` — Layer 2 canonical (3.9 KB)
- NEW `_ops/hooks/tests/test_write_brief_sop_enforcer.sh` — 6 cases
- NEW `.githooks/brief_sop_check.sh` — Layer 3 canonical (regex tightened per Fix 4)
- NEW `.githooks/tests/test_brief_sop_check.sh` — 7 cases (Case 7 H1-only regression for Fix 4)
- EDIT `.githooks/pre-commit` — chain brief_sop_check.sh

**baker-master PR (#253) — v2 changes:**
- ~~REMOVED `.claude/hooks/write_brief_sop_enforcer.sh`~~ — no longer tracked per Fix 2 (canonical+symlink pattern). Live install is untracked symlink to vault canonical.
- EDIT `.claude/settings.json` — PreToolUse Write|Edit|MultiEdit invokes `.claude/hooks/write_brief_sop_enforcer.sh` with `timeout: 10` (Fix 1)
- NEW `.githooks/brief_sop_check.sh` — Layer 3 mirror with `MIRROR OF` header (rebuilt after Fix 4)
- EDIT `.githooks/pre-commit` — add Part 5 invoking external brief_sop_check.sh
- EDIT `tasks/lessons.md` — append two-layer enforcement lesson + Fix-Pass v2 amendment block (Fix 4 regex-tighten note + canonical+symlink convention note)
- NEW `briefs/_reports/B3_WRITE_BRIEF_SOP_ENFORCER_HOOK_1_20260524.md` — this report (v2)

**Out-of-PR live installs (untracked, per ui-surface-prebrief precedent):**
- 6 symlinks: bm-b3 / bm-aihead1 / bm-aihead1-cowork / bm-aihead2 / bm-researcher / Desktop/baker-code → `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh`
- 5 settings.json edits (4 pickers + 1 new bm-researcher/settings.json file)
- `~/bm-researcher/.claude/settings.local.json` — hooks block REMOVED (Fix 3)
- `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh` — pre-staged copy (will be reconciled by AH1's `git pull` post-merge)

## Coordination notes for AH1 merge sequence (unchanged)

1. **Merge baker-vault PR #109 first.** Live symlinks resolve to `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh`; AH1 should `git pull` ~/baker-vault after merge for the canonical to fully replace the pre-staged copy.
2. **Then merge baker-master PR #253.** Renders Layer 2 settings + Part 5 + lessons.md live across all baker-master clones on next `git pull`.
3. **bm-aihead1 settings.json local divergence** (unchanged from v1): bm-aihead1 has UNCOMMITTED local `.claude/settings.json` adding both ui-surface-prebrief + write_brief_sop_enforcer in PreToolUse. After baker-master merge, bm-aihead1 pull will see canonical PreToolUse (write_brief_sop_enforcer only, with timeout: 10) vs its local (both hooks, only write_brief_sop_enforcer has timeout). Git will mark conflict. AH1 should either (a) discard the local ui-surface-prebrief addition (write_brief_sop_enforcer alone suffices), or (b) commit ui-surface-prebrief to tracked settings.json in a follow-up. Not blocking this PR.

## Gate chain status

| Gate | Owner | v1 verdict | v2 status |
|---|---|---|---|
| 1 — architecture | AH2 | found issues (Fix 1 timeout, Fix 2 canonical/symlinks) | re-run requested |
| 2 — /security-review | AH2 | NO_FINDINGS | unchanged (hooks read stdin/transcript only; no network, no auth, no secrets — fix-pass doesn't expand surface) |
| 3 — picker-architect | AH2 | found issues (Fix 2 + Fix 3 researcher settings) | re-run requested |
| 4 — feature-dev:code-reviewer 2nd-pass | AH2 | HIGH conf 85 on Fix 4 regex tighten | re-run requested |
| 5 — AH1 final merge | lead | pending | pending AH2 gates 1+3+4 PASS |

## References

- Brief: `briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md` (commit `4548869`)
- Mailbox: `briefs/_tasks/CODE_3_PENDING.md` (bus #792)
- Upstream: AH2 bus #788 (parent) + bus #790 (Layer 3 amendment)
- Director ratification: chat anchor 2026-05-23 evening
- v1 dispatch ship: bus #795 (2026-05-24T04:54:48Z)
- AH2 gate verdict v1: bus #797 (REQUEST_CHANGES)
- lead REQUEST_CHANGES → b3: bus #799 (2026-05-24T05:13:52Z)
- Existing PreToolUse precedent: `~/baker-vault/_ops/hooks/ui-surface-prebrief-check.sh` + bm-aihead1 untracked symlink
- Existing pre-commit precedent: `~/baker-vault/.githooks/cascade_backprop_check.sh` + bm-aihead1 .githooks/pre-commit Parts 1-4
- Skill: `~/.claude/skills/write-brief/SKILL.md`
