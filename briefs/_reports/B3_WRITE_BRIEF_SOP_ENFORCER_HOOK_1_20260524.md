# B3 Ship Report — WRITE_BRIEF_SOP_ENFORCER_HOOK_1 (2026-05-24)

**Brief:** `briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md` (commit `4548869`)
**Dispatch:** `briefs/_tasks/CODE_3_PENDING.md` (bus #792, `dispatched_by: lead`)
**PRs:**
- baker-vault: https://github.com/vallen300-bit/baker-vault/pull/109
- baker-master: https://github.com/vallen300-bit/baker-master/pull/253
**Branches:** `b3/write-brief-sop-enforcer-hook-1` in both repos.
**Merge order (AH1):** baker-vault first, then baker-master (Layer 3 mirror in baker-master references vault canonical via byte-identity QC).

## Bottom line

12/12 test cases PASS (Layer 2 6/6 + Layer 3 6/6). All 9 brief Quality Checkpoints PASS. Two design notes surfaced for AH2 gate-1 architecture review (jq + ERR-trap; Layer 3 trailer-bypass mechanism). No "by inspection" — every assertion has a literal exit-code + stderr capture below.

## AC verification matrix

| AC | Description | Status | Evidence |
|---|---|---|---|
| AC1 | Layer 2 hook at canonical + 5 picker copies; all executable | ✅ | QC #6 below |
| AC2 | Layer 2 path regex matches brief paths; excludes `_reports` + `_tasks/CODE_*_<state>` | ✅ | L2 test cases 5+6 (PASS) |
| AC3 | Layer 2 block message names skill + bypass env | ✅ | Manual smoke 1 stderr below |
| AC4 | Layer 2 bypass env logs + passes | ✅ | L2 case 4 PASS + manual smoke 2 |
| AC5 | Layer 2 installed in 5 picker settings files (NOT B-codes or global) | ✅ | QC #7 below |
| AC6 | Layer 2 test harness 6 cases / 6/6 PASS | ✅ | QC #4 below |
| AC7 | Literal test output in this ship report | ✅ | QC #4 + #5 below (verbatim) |
| AC8 | Brief itself authored via `/write-brief` (dog-food) | ✅ | Brief commit `4548869` per AH1 anchor 2026-05-23T18:00Z (verified by brief author) |
| AC9 | Layer 3 hook canonical + bm-b3 mirror; 3+/5 missing → block | ✅ | QC #3 (mirror diff empty) + L3 case 2 PASS |
| AC10 | Layer 3 bypass via commit-msg trailer | ⚠️ | **See Design Note 2.** Hook code includes trailer-detection branch; test case 3 covers the env-var bypass (the reliable path under git's commit lifecycle). Trailer-via-`-m`/`-F` cannot fire from a pre-commit hook because git writes `COMMIT_EDITMSG` at commit-msg stage AFTER pre-commit. AC10 spirit (working bypass for legitimate edits) satisfied by env-var; trailer code preserved for editor-flow archival commits + future commit-msg-stage companion. Flagged for AH2 architecture verdict. |
| AC11 | Layer 3 test harness 6 cases / 6/6 PASS | ✅ | QC #5 below |
| AC12 | Layer 3 chained in vault pre-commit + invoked from baker-master Part 5 | ✅ | QC #8 + #9 below |
| AC13 | Combined 12-case literal output pasted verbatim | ✅ | QC #4 + #5 below |

## Quality Checkpoints (literal output)

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

### QC #3: Mirror diff (vault canonical vs baker-master mirror, skipping header lines 1-2)

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
(L2 exit: 0)
```

### QC #5: Layer 3 tests (6 cases)

```
$ bash ~/baker-vault/.githooks/tests/test_brief_sop_check.sh
PASS: 1 full brief passes (exit 0)
PASS: 2 partial brief (3+ missing) blocks (exit nonzero)
PASS: 3 partial brief + bypass env passes (exit 0)
PASS: 4 non-brief file passes (exit 0)
PASS: 5 ship report passes (exit 0)
PASS: 6 dispatch envelope passes (exit 0)

Layer 3: 6 passed, 0 failed
(L3 exit: 0)
```

### QC #6: Picker hook copies all executable (5 pickers + bm-b3 tracked copy)

```
$ for p in ~/bm-aihead1 ~/bm-aihead1-cowork ~/bm-aihead2 ~/bm-researcher ~/Desktop/baker-code ~/bm-b3; do
    test -x "$p/.claude/hooks/write_brief_sop_enforcer.sh" && echo "OK: $p" || echo "FAIL: $p"
done
OK: /Users/dimitry/bm-aihead1
OK: /Users/dimitry/bm-aihead1-cowork
OK: /Users/dimitry/bm-aihead2
OK: /Users/dimitry/bm-researcher
OK: /Users/dimitry/Desktop/baker-code
OK: /Users/dimitry/bm-b3
```

### QC #7: All 5 picker settings files valid JSON

```
$ for p in ~/bm-aihead1/.claude/settings.json ~/bm-aihead1-cowork/.claude/settings.json ~/bm-aihead2/.claude/settings.json ~/bm-researcher/.claude/settings.local.json ~/Desktop/baker-code/.claude/settings.json; do
    jq -e . "$p" >/dev/null && echo "OK: $p" || echo "FAIL: $p"
done
OK: /Users/dimitry/bm-aihead1/.claude/settings.json
OK: /Users/dimitry/bm-aihead1-cowork/.claude/settings.json
OK: /Users/dimitry/bm-aihead2/.claude/settings.json
OK: /Users/dimitry/bm-researcher/.claude/settings.local.json
OK: /Users/dimitry/Desktop/baker-code/.claude/settings.json
```

### QC #8: baker-vault pre-commit chains brief_sop_check.sh

```
$ grep -q 'brief_sop_check.sh' ~/baker-vault/.githooks/pre-commit && echo "OK (chained)"
OK (chained)
```

### QC #9: baker-master pre-commit invokes brief_sop_check.sh (Part 5)

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

$ printf '...' | BAKER_BRIEF_SOP_BYPASS=1 bash ~/bm-b3/.claude/hooks/write_brief_sop_enforcer.sh 2>&1
INFO [write-brief-sop-enforcer]: bypass env set (BAKER_BRIEF_SOP_BYPASS=1); allowing write to /tmp/briefs/BRIEF_SMOKE.md at 2026-05-24T04:48:39Z
EXIT=0
```

### QC #12: Layer 3 manual smoke (block + bypass)

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
[main (root-commit) 162bcc9] partial smoke - bypass
 1 file changed, 4 insertions(+)
 create mode 100644 briefs/BRIEF_SMOKE.md
EXIT=0
```

## Design notes for AH2 Gate 1 (architecture review)

### Design Note 1 — jq `-e` + `set -u` + `trap ERR` trips silent fail-open

**Symptom caught at L2 test case 1's first run:** the brief's literal jq query used `jq -e -s ... | length > 0`. With `-e`, jq exits 1 when the bool result is `false` (no skill invoked). Inside `$(...)` with `set -u` + `trap '... exit 0' ERR`, the non-zero return tripped the ERR trap → hook exited 0 silently → block path never executed → silent bypass.

**Fix:** drop `-e` from jq, add `|| echo "false"` fallback. Pattern:

```bash
SKILL_INVOKED="$(jq -s '...' "$TRANSCRIPT_PATH" 2>/dev/null || echo "false")"
```

**Reusable lesson** (captured in `tasks/lessons.md`): any hook script using the `set -u` + `trap ERR` defensive posture (pattern from `ui-surface-prebrief-check.sh`) must avoid `jq -e` in command substitution — use stdout string compare instead. Test block path EXPLICITLY; the pass path can mask the silent-fail-open bug.

### Design Note 2 — Layer 3 trailer-bypass mechanism gap (gate verdict requested)

The brief Layer 3 hook (and brief AC10) specifies a trailer-bypass via commit-msg `Brief-SOP-bypass: <reason>`. The implementation reads `.git/COMMIT_EDITMSG` and matches the trailer. **The trailer mechanism cannot reliably fire from a pre-commit hook because git writes `COMMIT_EDITMSG` at the commit-msg stage (step 6 of git's commit lifecycle), AFTER pre-commit fires (step 2).**

Tested live with git 2.50.1:
- `git commit -m "msg\n\nBrief-SOP-bypass: reason"` — pre-commit reads no COMMIT_EDITMSG (file doesn't exist for first-commit-of-repo); on a non-fresh repo, reads PREVIOUS commit's message (semantically wrong)
- `git commit -F /tmp/msg.txt` — same behavior
- Editor flow: pre-commit fires before editor opens, so the user hasn't typed the trailer yet; COMMIT_EDITMSG when read contains the prior commit's text (if any)

**Pragmatic decision shipped in this PR:**
- Trailer-detection code preserved in `brief_sop_check.sh` (for the rare case where COMMIT_EDITMSG happens to be pre-populated with the trailer — edge case)
- Env-var bypass `BAKER_BRIEF_SOP_BYPASS=1` is the documented reliable path for `-m`/`-F`/fresh-repo flows (matches render-env-guard Part 4 pattern from the same gap)
- Test case 3 covers env-var bypass (the path that actually works)
- Open gap: a true audit-permanent trailer bypass would need a commit-msg-stage companion hook that can re-validate, OR a different architecture (e.g., pre-commit always allows, commit-msg performs the gate).

**AH2 Gate-1 verdict needed:** keep current dual-path bypass / migrate to commit-msg companion / drop trailer entirely. No blocker for ship; design choice for the architecture-review gate.

## Files modified

**baker-vault PR (#109):**
- NEW `_ops/hooks/write_brief_sop_enforcer.sh` — Layer 2 canonical (3.9 KB)
- NEW `_ops/hooks/tests/test_write_brief_sop_enforcer.sh` — Layer 2 test harness (2.5 KB)
- NEW `.githooks/brief_sop_check.sh` — Layer 3 canonical (3.5 KB)
- NEW `.githooks/tests/test_brief_sop_check.sh` — Layer 3 test harness (3.0 KB)
- EDIT `.githooks/pre-commit` — chain brief_sop_check.sh after state_reconciler_pre_commit.sh

**baker-master PR (#253):**
- NEW `.claude/hooks/write_brief_sop_enforcer.sh` — tracked picker copy (Layer 2)
- EDIT `.claude/settings.json` — add PreToolUse matcher invoking Layer 2 hook
- NEW `.githooks/brief_sop_check.sh` — Layer 3 mirror with `MIRROR OF` header
- EDIT `.githooks/pre-commit` — add Part 5 invoking external brief_sop_check.sh between Part 4 (render-env-guard) and Part 1 (migration immutability exec)
- EDIT `tasks/lessons.md` — append two-layer enforcement pattern + jq/ERR-trap gotcha + Layer 3 trailer-gap note

**Out-of-PR picker installs (live now; reconcile via git pull post-merge):**
- bm-aihead1 / bm-aihead1-cowork / bm-aihead2 / Desktop/baker-code: `.claude/hooks/write_brief_sop_enforcer.sh` + `.claude/settings.json` PreToolUse edits
- bm-researcher: `.claude/hooks/write_brief_sop_enforcer.sh` + `.claude/settings.local.json` hooks block

## Coordination notes for AH1 merge sequence

1. **Merge baker-vault PR #109 first.** Layer 3 mirror in baker-master references vault canonical via `MIRROR OF` header comment; the byte-identity QC depends on vault canonical being source-of-truth.
2. **Then merge baker-master PR #253.** Renders Layer 2 hook + settings.json + Part 5 + lessons.md live across all baker-master clones on next `git pull`.
3. **bm-aihead1 settings.json local divergence.** bm-aihead1 has an UNCOMMITTED local change to `.claude/settings.json` (adds `ui-surface-prebrief-check.sh` PreToolUse). My picker install added `write_brief_sop_enforcer.sh` to the existing array (preserving ui-surface-prebrief). After baker-master merge, bm-aihead1 pull will see the canonical PreToolUse (write_brief_sop_enforcer only) vs its local (both hooks) — git will mark conflict. AH1 should either (a) discard the local ui-surface-prebrief addition (write_brief_sop_enforcer alone is sufficient if that's the intent), or (b) commit ui-surface-prebrief to tracked settings.json in a follow-up. Not blocking this PR; flagged for awareness.

## Gate chain

Per brief frontmatter (MEDIUM trigger class):
1. AH2 architecture review — please verdict trailer-bypass design (Design Note 2 above)
2. AH2 `/security-review` — expect NO_FINDINGS (hooks read stdin/transcript only; no network, no auth, no secrets)
3. AH2 picker-architect — verify cross-picker install (QC #6 + #7 above)
4. AH2 `feature-dev:code-reviewer` 2nd-pass
5. AH1 final merge per sequence above

## References

- Brief: `briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md` (commit `4548869`)
- Mailbox: `briefs/_tasks/CODE_3_PENDING.md` (bus #792)
- Upstream: AH2 bus #788 (parent) + bus #790 (Layer 3 amendment)
- Director ratification: chat anchor 2026-05-23 evening
- Existing PreToolUse precedent: `~/bm-aihead1/.claude/hooks/ui-surface-prebrief-check.sh`
- Existing pre-commit precedent: `~/baker-vault/.githooks/cascade_backprop_check.sh` + `~/bm-aihead1/.githooks/pre-commit` Parts 1-4
- Layer-2-vs-Layer-3 parallel: `tools/render_env_guard.py` (wrapper) + `.githooks/pre-commit` Part 4 (audit)
- Skill: `~/.claude/skills/write-brief/SKILL.md`
