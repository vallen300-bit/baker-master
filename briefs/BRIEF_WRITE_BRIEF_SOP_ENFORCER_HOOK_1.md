# BRIEF: WRITE_BRIEF_SOP_ENFORCER_HOOK_1 — Two-Layer /write-brief SOP Enforcement

## Context

Brief-author agents (AH1-T, AH1-C, AH2, Researcher) routinely start drafting briefs without first invoking the `/write-brief` skill. Result: briefs ship missing Step 1 EXPLORE (read code first), Step 2 PLAN (file lists, risks, simpler-way challenge), Step 4 REVIEW (lessons.md check). Director catches gaps mid-review weekly and reminds. The skill at `~/.claude/skills/write-brief/SKILL.md` exists; memory mandates exist (Rule 0 of `ai-head-brief-and-gate`); but neither enforces — agents forget.

Director ratified harness enforcement 2026-05-23 evening. Two-layer pattern parallel to the proven `tools/render_env_guard.py` (wrapper at action-time) + `.githooks/pre-commit` Part 4 (audit at git-time) belt-and-braces design:

- **Layer 2 (in-session):** `PreToolUse` hook blocks `Write/Edit/MultiEdit` on brief paths unless the current session's transcript shows `/write-brief` was invoked. Bypass via env `BAKER_BRIEF_SOP_BYPASS=1` (stderr-logged for audit).
- **Layer 3 (at git-time):** `pre-commit` hook scans staged brief diffs for canonical /write-brief structure (3+ of 5 section headers required). Bypass via commit-msg trailer `Brief-SOP-bypass: <reason>` (permanent in git log).

Director chat anchor 2026-05-23 evening: *"I need constantly to remind to use /write-brief S.O.P. ... render_env_guard.py + pre-commit Part 4 is the template. Worth adding Layer 3 to the brief."* Combined into single brief per AH1 engineering judgment (tightly coupled; same SOP, same regex, same purpose).

Upstream anchors: AH2 bus #788 (parent brief request) + bus #790 (Layer 3 amendment).

### Surface contract: N/A — pure harness/hook infrastructure (PreToolUse + pre-commit + tests); no clickable user surface introduced.

## Estimated time: ~4.5-5.5h
## Complexity: Medium
## Prerequisites: none (additive only; no Phase 0 dependency)
## Dispatch target: b3 (b1 busy on Substack PR #251, b2 busy on TRANSCRIPT_CURATION_PHASE_1 PR #252)
## Target repos: baker-master (`~/bm-b3`) + baker-vault (`~/bm-b3-baker-vault` — clone if missing)

---

## Fix/Feature 1: Layer 2 — PreToolUse hook (in-session enforcement)

### Problem

`Write/Edit/MultiEdit` to `briefs/BRIEF_*.md` or `_ops/briefs/BRIEF_*.md` paths currently has no gate verifying `/write-brief` skill was invoked first. Agents draft briefs from a cold start, skip EXPLORE/PLAN, ship gaps.

### Current State

- Existing PreToolUse hook precedent: `~/bm-aihead1/.claude/hooks/ui-surface-prebrief-check.sh` (gates brief writes for `### Surface contract` block). Pattern verified working — it blocked my last brief write 30 min ago for missing the block.
- Picker `.claude/settings.json` already configured with `PreToolUse` matcher `Write|Edit|MultiEdit` → calls `.claude/hooks/ui-surface-prebrief-check.sh`. Add `write_brief_sop_enforcer.sh` to the same matcher.
- Skill at `~/.claude/skills/write-brief/SKILL.md` is the canonical SOP — verified exists at session-start.

### Implementation

**Step 1 — Canonical hook script `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh`:**

```bash
#!/usr/bin/env bash
# write_brief_sop_enforcer.sh — PreToolUse hook blocking Write/Edit on brief
# paths unless /write-brief skill was invoked in the current session.
#
# Director-ratified 2026-05-23 evening (AH2 bus #788).
# Pattern parallels ~/bm-aihead1/.claude/hooks/ui-surface-prebrief-check.sh.
#
# Stage: PreToolUse (Write | Edit | MultiEdit)
# Exit codes:
#   0 — pass / not applicable / malformed input (FAIL-OPEN)
#   2 — block; stderr surfaced to Claude as error context
#
# Fail-open posture: ANY internal error → exit 0 + stderr warning.
# Gate-logic bugs must NEVER block legitimate tool use.
#
# Bypass: env BAKER_BRIEF_SOP_BYPASS=1 (logged to stderr with timestamp + file_path).

set -u
trap 'echo "WARN [write-brief-sop-enforcer]: hook errored unexpectedly, failing open" >&2; exit 0' ERR

PAYLOAD="$(cat)"

# Validate JSON; fail-open if malformed.
if ! printf '%s' "$PAYLOAD" | jq -e . >/dev/null 2>&1; then
    echo "WARN [write-brief-sop-enforcer]: malformed JSON on stdin, failing open" >&2
    exit 0
fi

TOOL="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // empty')"
case "$TOOL" in
    Write|Edit|MultiEdit) ;;
    *) exit 0 ;;
esac

FILE_PATH="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // empty')"
[ -z "$FILE_PATH" ] && exit 0

# Path filter: anchor on `(_ops/)?briefs/BRIEF_<name>.md` (at any directory depth).
# Excludes: briefs/_reports/* (B-code ship reports) and briefs/_tasks/CODE_*_PENDING.md
# (dispatch envelopes — AH1 edits directly, not via /write-brief).
if printf '%s' "$FILE_PATH" | grep -qE '/_reports/|/_tasks/CODE_[1-5]_(PENDING|COMPLETE|DROPPED|RETURN|PARKED)'; then
    exit 0
fi
if ! printf '%s' "$FILE_PATH" | grep -qE '(^|/)(_ops/)?briefs/BRIEF_[^/]+\.md$'; then
    exit 0
fi

# Bypass check — env BAKER_BRIEF_SOP_BYPASS=1. Logged for audit.
if [ "${BAKER_BRIEF_SOP_BYPASS:-}" = "1" ]; then
    printf 'INFO [write-brief-sop-enforcer]: bypass env set (BAKER_BRIEF_SOP_BYPASS=1); allowing write to %s at %s\n' \
        "$FILE_PATH" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
    exit 0
fi

TRANSCRIPT_PATH="$(printf '%s' "$PAYLOAD" | jq -r '.transcript_path // empty')"

# If no transcript_path, FAIL-OPEN with warning (skill-internal hook fires may
# lack transcript context; brief-time false-blocks are worse than false-passes).
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "WARN [write-brief-sop-enforcer]: transcript_path missing or unreadable, failing open" >&2
    exit 0
fi

# Scan transcript JSONL for a `Skill` tool_use event with skill="write-brief".
# Each JSONL line is a complete JSON message; -e returns exit 0 on match.
SKILL_INVOKED="$(jq -e -s '
    map(select(
        .type == "assistant" and
        (.message.content // []) | any(
            .type == "tool_use" and
            .name == "Skill" and
            (.input.skill // "") == "write-brief"
        )
    )) | length > 0
' "$TRANSCRIPT_PATH" 2>/dev/null)"

if [ "$SKILL_INVOKED" = "true" ]; then
    exit 0
fi

# Skill not invoked — block.
cat >&2 <<'MSG'
BLOCKED by write-brief-sop-enforcer: Write/Edit to a brief path requires the `/write-brief` skill to be invoked first in this session.

Run: Skill(skill="write-brief") and walk through the 6 SOP steps (EXPLORE → PLAN → WRITE → REVIEW → PRESENT → CAPTURE LESSONS).

Bypass for legitimate non-authoring edits (typo fix, status update, link refresh): set env `BAKER_BRIEF_SOP_BYPASS=1` before the tool call. Bypass usage is logged to stderr for audit.

Skill location: ~/.claude/skills/write-brief/SKILL.md
Director directive 2026-05-23 evening.
MSG
exit 2
```

**Step 2 — Install canonical at vault + 5 picker copies:**

```bash
# Vault canonical (commit to baker-vault repo)
mkdir -p ~/baker-vault/_ops/hooks
# (Write the script above to ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh)
chmod +x ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh

# 5 picker copies (committed to baker-master + baker-vault picker .claude/ dirs)
for picker in \
    ~/bm-aihead1 \
    ~/bm-aihead1-cowork \
    ~/bm-aihead2 \
    ~/bm-researcher \
    ~/Desktop/baker-code ; do
    mkdir -p "$picker/.claude/hooks"
    cp ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh \
       "$picker/.claude/hooks/write_brief_sop_enforcer.sh"
    chmod +x "$picker/.claude/hooks/write_brief_sop_enforcer.sh"
done
```

**Step 3 — Add PreToolUse entry to each picker's settings.json (5 edits):**

For pickers using `settings.json` (AH1-T, AH1-cowork, AH2, legacy AH1-T): add a second hook in the existing `PreToolUse` matcher block (sibling of `ui-surface-prebrief-check.sh`).

For Researcher (uses `settings.local.json`): same pattern, in that file.

Example edit for `~/bm-aihead1/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": ".claude/hooks/session-start-role.sh", "timeout": 10 }] }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/ui-surface-prebrief-check.sh" },
          { "type": "command", "command": ".claude/hooks/write_brief_sop_enforcer.sh" }
        ]
      }
    ]
  }
}
```

If a picker has no existing `PreToolUse` block, add the full block. If a picker already has `ui-surface-prebrief-check.sh` configured, append the new hook to the existing `hooks` array (don't replace).

### Key Constraints

- **Fail-open posture** — any error inside the hook MUST exit 0. Gate-logic bugs blocking legitimate work is the worst failure mode. Mirror `ui-surface-prebrief-check.sh` ERR trap.
- **Empty `transcript_path`** — fail-open with warning, per AH2's anti-pattern note in #788.
- **Anchored regex `\.md$`** — don't catch `.md.bak`, `.md~`, or extension variants.
- **Excluded paths** — `briefs/_reports/*` (B-code ship reports) and `briefs/_tasks/CODE_*_PENDING|COMPLETE|DROPPED|RETURN|PARKED.md` (dispatch envelopes) MUST NOT trigger this hook.
- **Bypass logging** — every bypass invocation logs to stderr with ISO timestamp + file_path.
- **jq query** — uses `-s` (slurp JSONL into array) + `-e` (exit-status sensitive). `(.input.skill // "") == "write-brief"` defends against missing-skill-field shapes.
- **Skill-tool-use detection in transcript JSONL:** the message records assistant tool calls under `.message.content[]` with `.type == "tool_use"` + `.name == "Skill"` + `.input.skill == "write-brief"`. Verify with: `head -100 "$transcript_path" | jq -c '.message.content // []'` on a known-good session transcript.

### Verification

```bash
# Manual smoke test: with /write-brief NOT invoked in current session
echo '{"tool_name":"Write","tool_input":{"file_path":"/tmp/briefs/BRIEF_TEST.md","content":"x"},"transcript_path":"/tmp/empty-transcript.jsonl"}' \
    | bash ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
echo "Exit: $?"
# Expected: exit 2 + BLOCKED message on stderr (if transcript exists; or exit 0 fail-open if not)

# Bypass test
BAKER_BRIEF_SOP_BYPASS=1 echo '{"tool_name":"Write","tool_input":{"file_path":"/tmp/briefs/BRIEF_TEST.md","content":"x"},"transcript_path":"/tmp/empty-transcript.jsonl"}' \
    | bash ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh
echo "Exit: $?"
# Expected: exit 0 + INFO bypass log on stderr
```

---

## Fix/Feature 2: Layer 3 — pre-commit hook (git-time enforcement)

### Problem

Layer 2 covers in-session writes. It misses: (a) edits made with `BAKER_BRIEF_SOP_BYPASS=1` set, (b) manual edits via `vim` / `nano` outside Claude Code, (c) `scp`/paste-in edits, (d) edits made in a non-AH picker. Need a git-time gate that scans actual staged content for canonical /write-brief structure.

### Current State

- `~/baker-vault/.githooks/pre-commit` is a 24-line orchestrator chaining `state_reconciler_pre_commit.sh`. Easy to extend with another chained script.
- `~/bm-aihead1/.githooks/pre-commit` has 4 inline Parts (migration / subagent / model-id / render-env). Will add Part 5 invoking external `brief_sop_check.sh` for symmetry with vault canonical (intentional mirror; mirror-drift risk mitigated via test harness in both repos).
- Existing pre-commit precedent — Part 4 render-env-var scan uses `git diff --cached --name-only --diff-filter=ACMR` + grep pattern. Same idiom.
- `git config core.hooksPath .githooks` is documented in CLAUDE.md as required setup; both repos already configured.

### Implementation

**Step 4 — Canonical hook script `~/baker-vault/.githooks/brief_sop_check.sh`:**

```bash
#!/usr/bin/env bash
# brief_sop_check.sh — pre-commit gate scanning staged brief files for
# canonical /write-brief structure.
#
# Director-ratified 2026-05-23 evening (AH2 bus #790 amendment to #788).
# Layer 3 of two-layer enforcement; parallel to render_env_guard pre-commit Part 4.
#
# Triggers on:
#   git diff --cached --name-only --diff-filter=AM matches
#     (briefs/BRIEF_*.md OR _ops/briefs/BRIEF_*.md)
#   AND NOT (briefs/_reports/* OR briefs/_tasks/CODE_*_PENDING|COMPLETE|...md)
#
# Blocks if 3+ of 5 canonical SOP section headers are missing in the staged
# content:
#   1. ## Context
#   2. ## Problem  (or ### Problem inside a ## Fix/Feature block)
#   3. ## Files Modified  (or ## Files to touch)
#   4. ## Verification  (or ## Verification SQL)
#   5. ## Quality Checkpoints  (or ## Acceptance criteria)
#
# Bypass: commit-msg trailer `Brief-SOP-bypass: <reason>`. Audit-permanent in
# git log. DIFFERENT bypass from Layer 2 (env var) BY DESIGN — Layer 3 is
# git-time + auditable-forever.
#
# Stage: pre-commit (chained from .githooks/pre-commit orchestrator in vault;
# Part 5 in baker-master pre-commit).
#
# Must complete <1s for the common case (no LLM, regex-only).

set -u
trap 'echo "WARN [brief-sop-check]: hook errored unexpectedly, failing open" >&2; exit 0' ERR

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$REPO_ROOT" || exit 0

# Bypass via commit-msg trailer — read COMMIT_EDITMSG if present.
# Note: pre-commit fires BEFORE git writes COMMIT_EDITMSG for `-m`/`-F` flows,
# so the env override below is the practical path for those flows.
COMMIT_MSG_FILE=".git/COMMIT_EDITMSG"
if [ -f "$COMMIT_MSG_FILE" ]; then
    if grep -qE '^Brief-SOP-bypass:' "$COMMIT_MSG_FILE" 2>/dev/null; then
        REASON="$(grep -E '^Brief-SOP-bypass:' "$COMMIT_MSG_FILE" | head -1 | sed 's/^Brief-SOP-bypass:[[:space:]]*//')"
        echo "INFO [brief-sop-check]: bypass via commit trailer ($REASON); allowing." >&2
        exit 0
    fi
fi
# Env-var bypass for `-m`/`-F` flows where COMMIT_EDITMSG isn't yet written
# (matches render-env-guard Part 4 pattern for the same constraint).
if [ "${BAKER_BRIEF_SOP_BYPASS:-}" = "1" ]; then
    echo "INFO [brief-sop-check]: bypass env BAKER_BRIEF_SOP_BYPASS=1 set; allowing." >&2
    exit 0
fi

# Detect staged formal-brief files (additions + modifications; no rename/delete).
STAGED_BRIEFS="$(git diff --cached --name-only --diff-filter=AM \
    | grep -E '(^|/)(_ops/)?briefs/BRIEF_[^/]+\.md$' \
    | grep -vE '/_reports/|/_tasks/CODE_[1-5]_(PENDING|COMPLETE|DROPPED|RETURN|PARKED)' \
    || true)"

[ -z "$STAGED_BRIEFS" ] && exit 0

# For each staged brief, scan staged content for required section headers.
# 3+ missing of 5 = block. Required headers (accept variant headings):
#   1. Context  — `^## Context`
#   2. Problem  — `^## Problem` OR `^### Problem` (inside a Fix/Feature block)
#   3. Files Modified  — `^## Files Modified` OR `^## Files to touch`
#   4. Verification  — `^## Verification` OR `^## Verification SQL`
#   5. Quality Checkpoints  — `^## Quality Checkpoints` OR `^## Acceptance criteria`

VIOLATIONS=""

while IFS= read -r brief_path; do
    [ -z "$brief_path" ] && continue
    # Get staged content (not on-disk — `git show :path` reads staged blob)
    STAGED_CONTENT="$(git show ":$brief_path" 2>/dev/null)" || continue

    MISSING=()
    grep -qE '^##? Context' <<< "$STAGED_CONTENT" || MISSING+=("Context")
    grep -qE '^(##|###) Problem' <<< "$STAGED_CONTENT" || MISSING+=("Problem")
    grep -qE '^## Files (Modified|to touch)' <<< "$STAGED_CONTENT" || MISSING+=("Files Modified")
    grep -qE '^## Verification( SQL)?' <<< "$STAGED_CONTENT" || MISSING+=("Verification")
    grep -qE '^## (Quality Checkpoints|Acceptance criteria)' <<< "$STAGED_CONTENT" || MISSING+=("Quality Checkpoints/Acceptance criteria")

    if [ ${#MISSING[@]} -ge 3 ]; then
        VIOLATIONS+=$'\n  - '"$brief_path"' — missing: '"${MISSING[*]}"
    fi
done <<< "$STAGED_BRIEFS"

if [ -n "$VIOLATIONS" ]; then
    cat >&2 <<MSG
[pre-commit] BLOCKED (brief-sop-check): staged brief(s) lack 3+ of 5 canonical /write-brief section headers:$VIOLATIONS

Required (accepts variants): Context, Problem, Files Modified (or "Files to touch"), Verification (or "Verification SQL"), Quality Checkpoints (or "Acceptance criteria").

Run \`/write-brief\` to regenerate, or add the missing sections.

Bypass for legitimate cases (corrections to historical briefs, archival edits):
  - Commit-msg trailer: \`Brief-SOP-bypass: <reason>\` (audit-permanent in git log)
  - Env (for \`-m\`/\`-F\` flows): \`BAKER_BRIEF_SOP_BYPASS=1 git commit -m "..."\`

Skill: ~/.claude/skills/write-brief/SKILL.md
Director directive 2026-05-23 evening.
MSG
    exit 1
fi

exit 0
```

**Step 5 — Mirror at `~/bm-aihead1/.githooks/brief_sop_check.sh`:**

Copy the same script byte-for-byte. Add header comment: `# MIRROR OF baker-vault/.githooks/brief_sop_check.sh — keep in sync. Drift caught by test harnesses in both repos.`

**Step 6 — Chain into baker-vault `.githooks/pre-commit`:**

Edit `~/baker-vault/.githooks/pre-commit` to add `brief_sop_check.sh` to the for-loop:

```bash
# BEFORE (line 18):
for hook in state_reconciler_pre_commit.sh; do
# AFTER:
for hook in state_reconciler_pre_commit.sh brief_sop_check.sh; do
```

**Step 7 — Add Part 5 to baker-master `.githooks/pre-commit`:**

Append after Part 4 (around line 80+, after the render-env-guard block). Add inline call to the external script:

```bash
# ---------------------------------------------------------------------------
# Part 5: /write-brief SOP enforcement on staged brief files (bypass via
# commit-msg trailer `Brief-SOP-bypass: <reason>` or env BAKER_BRIEF_SOP_BYPASS=1)
# Director-ratified 2026-05-23 evening (AH2 bus #790).
# MIRROR canonical at baker-vault/.githooks/brief_sop_check.sh.
# ---------------------------------------------------------------------------
if [ -x "$REPO_ROOT/.githooks/brief_sop_check.sh" ]; then
    "$REPO_ROOT/.githooks/brief_sop_check.sh" || exit $?
fi
```

### Key Constraints

- **Fail-open posture on hook errors** — ERR trap exits 0. Gate-logic bugs must not block legitimate commits.
- **Mirror drift mitigation** — both vault and baker-master have separate test harnesses (Feature 3). Each harness runs against its own copy of the script; CI-time drift surfaces as test divergence.
- **<1s completion** — regex-only, no LLM, no network. Verified against ~10KB brief files.
- **`--diff-filter=AM`** — Added + Modified only. Renames + Deletes don't fire (no content to scan in DELETE).
- **Bypass paths:** trailer (audit-permanent, preferred) OR env var (for `-m`/`-F` flows where COMMIT_EDITMSG isn't written before pre-commit per `feedback_chanda_4_hook_stage_bug.md`).
- **Section regex must be line-anchored** (`^##`) — don't match inline `## Context` mentions inside code fences.
- **Excluded paths** — same as Layer 2: `_reports/*` and `_tasks/CODE_*_<state>.md` are not formal briefs.
- **Use `git show :<path>`** to read staged blob, NOT on-disk file — pre-commit blocks PRE-commit, on-disk and staged may differ.

### Verification

```bash
# Manual smoke: stage a fake brief missing 4 sections, expect block.
mkdir -p /tmp/sop-test && cd /tmp/sop-test && git init -q
mkdir -p briefs && cat > briefs/BRIEF_FAKE_1.md <<'EOF'
# BRIEF: FAKE_1

## Context
Only one section.
EOF
git add briefs/BRIEF_FAKE_1.md
cp ~/baker-vault/.githooks/brief_sop_check.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
git commit -m "test" 2>&1 | tail -10
# Expected: BLOCKED message + non-zero exit

# Bypass smoke
git commit -m "test - Brief-SOP-bypass: smoke test" 2>&1 | tail -5
# Expected: INFO bypass log + commit success
cd ~ && rm -rf /tmp/sop-test
```

---

## Fix/Feature 3: Test harnesses (12 cases total)

### Implementation

**Step 8 — Layer 2 test harness `~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh`:**

```bash
#!/usr/bin/env bash
# test_write_brief_sop_enforcer.sh — 6 test cases for the Layer 2 PreToolUse hook.
#
# Run: bash ~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh
# Output: literal pass/fail per case. NO "by inspection" — every assertion is
# a real exit-code + stderr check (Lesson #8).

set -u

HOOK="$(dirname "$0")/../write_brief_sop_enforcer.sh"
[ -x "$HOOK" ] || { echo "FAIL [setup]: hook missing or not executable at $HOOK" >&2; exit 1; }

PASS=0
FAIL=0
TMPDIR_T="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_T"' EXIT

# Helper: build a fake transcript JSONL with optional /write-brief skill use.
make_transcript() {
    local path="$1"
    local include_skill="$2"  # "yes" or "no"
    if [ "$include_skill" = "yes" ]; then
        cat > "$path" <<'EOF'
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"write-brief"}}]}}
EOF
    else
        cat > "$path" <<'EOF'
{"type":"assistant","message":{"content":[{"type":"text","text":"hello"}]}}
EOF
    fi
}

assert_exit() {
    local case_name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "PASS: $case_name (exit $actual)"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $case_name (expected exit $expected, got $actual)" >&2
        FAIL=$((FAIL + 1))
    fi
}

# Case 1: brief path + no skill invocation → blocks (exit 2)
TR1="$TMPDIR_T/t1.jsonl"; make_transcript "$TR1" "no"
ACT1=$(printf '{"tool_name":"Write","tool_input":{"file_path":"/x/briefs/BRIEF_X.md","content":"x"},"transcript_path":"%s"}' "$TR1" | bash "$HOOK" 2>/dev/null; echo $?)
ACT1="${ACT1##*$'\n'}"
assert_exit "1 brief-path+no-skill blocks" "2" "$ACT1"

# Case 2: brief path + write-brief skill in transcript → passes (exit 0)
TR2="$TMPDIR_T/t2.jsonl"; make_transcript "$TR2" "yes"
ACT2=$(printf '{"tool_name":"Write","tool_input":{"file_path":"/x/briefs/BRIEF_X.md","content":"x"},"transcript_path":"%s"}' "$TR2" | bash "$HOOK" 2>/dev/null; echo $?)
ACT2="${ACT2##*$'\n'}"
assert_exit "2 brief-path+skill passes" "0" "$ACT2"

# Case 3: non-brief path → passes regardless
ACT3=$(printf '{"tool_name":"Write","tool_input":{"file_path":"/x/outputs/dashboard.py","content":"x"},"transcript_path":"%s"}' "$TR1" | bash "$HOOK" 2>/dev/null; echo $?)
ACT3="${ACT3##*$'\n'}"
assert_exit "3 non-brief-path passes" "0" "$ACT3"

# Case 4: bypass env set → passes regardless
ACT4=$(BAKER_BRIEF_SOP_BYPASS=1 printf '{"tool_name":"Write","tool_input":{"file_path":"/x/briefs/BRIEF_X.md","content":"x"},"transcript_path":"%s"}' "$TR1" | BAKER_BRIEF_SOP_BYPASS=1 bash "$HOOK" 2>/dev/null; echo $?)
ACT4="${ACT4##*$'\n'}"
assert_exit "4 bypass-env passes" "0" "$ACT4"

# Case 5: ship report path → passes
ACT5=$(printf '{"tool_name":"Write","tool_input":{"file_path":"/x/briefs/_reports/B1_foo.md","content":"x"},"transcript_path":"%s"}' "$TR1" | bash "$HOOK" 2>/dev/null; echo $?)
ACT5="${ACT5##*$'\n'}"
assert_exit "5 ship-report path passes" "0" "$ACT5"

# Case 6: dispatch envelope CODE_*_PENDING.md → passes
ACT6=$(printf '{"tool_name":"Edit","tool_input":{"file_path":"/x/briefs/_tasks/CODE_1_PENDING.md","old_string":"a","new_string":"b"},"transcript_path":"%s"}' "$TR1" | bash "$HOOK" 2>/dev/null; echo $?)
ACT6="${ACT6##*$'\n'}"
assert_exit "6 dispatch-envelope passes" "0" "$ACT6"

echo
echo "Layer 2: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
```

**Step 9 — Layer 3 test harness `~/baker-vault/.githooks/tests/test_brief_sop_check.sh`:**

```bash
#!/usr/bin/env bash
# test_brief_sop_check.sh — 6 test cases for the Layer 3 pre-commit hook.
#
# Run: bash ~/baker-vault/.githooks/tests/test_brief_sop_check.sh
# Output: literal pass/fail per case. Builds an ephemeral git repo per case,
# stages files, runs the hook from the staged-blob path. NO "by inspection".

set -u

CANONICAL_HOOK="$(dirname "$0")/../brief_sop_check.sh"
[ -x "$CANONICAL_HOOK" ] || { echo "FAIL [setup]: hook missing or not executable at $CANONICAL_HOOK" >&2; exit 1; }

PASS=0
FAIL=0
TMPDIR_T="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_T"' EXIT

setup_repo() {
    local name="$1"
    local d="$TMPDIR_T/$name"
    mkdir -p "$d"
    git -C "$d" init -q
    git -C "$d" config user.email "test@test.local"
    git -C "$d" config user.name "Test"
    cp "$CANONICAL_HOOK" "$d/.git/hooks/pre-commit"
    chmod +x "$d/.git/hooks/pre-commit"
    echo "$d"
}

assert_exit() {
    local case_name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "PASS: $case_name (exit $actual)"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $case_name (expected exit $expected, got $actual)" >&2
        FAIL=$((FAIL + 1))
    fi
}

# Helper: write a full brief with all 5 sections
write_full_brief() {
    local path="$1"
    cat > "$path" <<'EOF'
# BRIEF: TEST_FULL

## Context
Full context.

## Fix/Feature 1

### Problem
P.

## Files Modified
- x.py

## Verification
Tests pass.

## Quality Checkpoints
All green.
EOF
}

# Case 1: full brief → passes
D1="$(setup_repo case1)"
mkdir -p "$D1/briefs"
write_full_brief "$D1/briefs/BRIEF_FULL.md"
git -C "$D1" add briefs/BRIEF_FULL.md
ACT1=$(git -C "$D1" commit -m "full" 2>&1 >/dev/null; echo $?)
assert_exit "1 full brief passes" "0" "$ACT1"

# Case 2: brief with only 2 sections (3+ missing) → blocks
D2="$(setup_repo case2)"
mkdir -p "$D2/briefs"
cat > "$D2/briefs/BRIEF_PARTIAL.md" <<'EOF'
# BRIEF: PARTIAL

## Context
ctx

## Files Modified
- x.py
EOF
git -C "$D2" add briefs/BRIEF_PARTIAL.md
ACT2=$(git -C "$D2" commit -m "partial" 2>&1 >/dev/null; echo $?)
[ "$ACT2" != "0" ] && ACT2_NORM="nonzero" || ACT2_NORM="0"
assert_exit "2 partial brief (3+ missing) blocks" "nonzero" "$ACT2_NORM"

# Case 3: partial brief + bypass trailer → passes
D3="$(setup_repo case3)"
mkdir -p "$D3/briefs"
cat > "$D3/briefs/BRIEF_PARTIAL.md" <<'EOF'
# BRIEF: PARTIAL
## Context
ctx
EOF
git -C "$D3" add briefs/BRIEF_PARTIAL.md
ACT3=$(git -C "$D3" commit -m "$(printf 'partial\n\nBrief-SOP-bypass: archival edit\n')" 2>&1 >/dev/null; echo $?)
assert_exit "3 partial brief + bypass trailer passes" "0" "$ACT3"

# Case 4: non-brief file (outputs/dashboard.py) → passes regardless of content
D4="$(setup_repo case4)"
mkdir -p "$D4/outputs"
echo "x" > "$D4/outputs/dashboard.py"
git -C "$D4" add outputs/dashboard.py
ACT4=$(git -C "$D4" commit -m "non-brief" 2>&1 >/dev/null; echo $?)
assert_exit "4 non-brief file passes" "0" "$ACT4"

# Case 5: ship report → passes regardless
D5="$(setup_repo case5)"
mkdir -p "$D5/briefs/_reports"
echo "minimal" > "$D5/briefs/_reports/B1_foo.md"
git -C "$D5" add briefs/_reports/B1_foo.md
ACT5=$(git -C "$D5" commit -m "report" 2>&1 >/dev/null; echo $?)
assert_exit "5 ship report passes" "0" "$ACT5"

# Case 6: dispatch envelope CODE_1_PENDING.md → passes regardless
D6="$(setup_repo case6)"
mkdir -p "$D6/briefs/_tasks"
echo "minimal" > "$D6/briefs/_tasks/CODE_1_PENDING.md"
git -C "$D6" add briefs/_tasks/CODE_1_PENDING.md
ACT6=$(git -C "$D6" commit -m "dispatch" 2>&1 >/dev/null; echo $?)
assert_exit "6 dispatch envelope passes" "0" "$ACT6"

echo
echo "Layer 3: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
```

### Verification

```bash
chmod +x ~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh
chmod +x ~/baker-vault/.githooks/tests/test_brief_sop_check.sh

bash ~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh
bash ~/baker-vault/.githooks/tests/test_brief_sop_check.sh

# Expected: 6/6 PASS each (Layer 2 + Layer 3 = 12 total). Paste literal output
# verbatim in ship report (Lesson #8 — no "by inspection").
```

---

## Fix/Feature 4: lessons.md append

### Implementation

**Step 10 — Append to `~/bm-b3/tasks/lessons.md`** (or wherever lessons.md lives — verify via `find`):

```markdown
### Two-layer harness enforcement for mandatory SOPs (WRITE_BRIEF_SOP_ENFORCER_HOOK_1, 2026-05-23)

When a memory/skill mandate keeps getting forgotten, single-point enforcement
isn't enough. Pattern parallels render_env_guard.py (Layer 2 wrapper) +
.githooks/pre-commit Part 4 (Layer 3 audit):

- **Layer 2 (in-session):** PreToolUse hook blocks at the tool-call boundary.
  Bypass via env var (friction-free, stderr-logged for audit).
- **Layer 3 (git-time):** pre-commit hook scans staged content. Bypass via
  commit-msg trailer (audit-permanent in git log).

Belt-and-braces. Layer 2 catches the Claude-Code path; Layer 3 catches `vim`,
`scp`, manual edits, bypass-env-set edits, edits from non-AH pickers.

Apply this pattern when:
- Director repeatedly reminds about a process rule
- Single mandate location (memory/skill/docs) is observably not enforcing
- Scar incident exists (render_env_guard: 2026-05-17 wipe; brief-SOP: weekly
  Director reminder cycle)

Anchor: Director chat 2026-05-23 evening; AH2 bus #788 (Layer 2) + bus #790
(Layer 3 amendment).
```

---

## Files Modified

**Layer 2 (8):**
- NEW `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh` — canonical script
- NEW `~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh` — 6 tests
- NEW `~/bm-aihead1/.claude/hooks/write_brief_sop_enforcer.sh` — copy
- NEW `~/bm-aihead1-cowork/.claude/hooks/write_brief_sop_enforcer.sh` — copy
- NEW `~/bm-aihead2/.claude/hooks/write_brief_sop_enforcer.sh` — copy
- NEW `~/bm-researcher/.claude/hooks/write_brief_sop_enforcer.sh` — copy
- NEW `~/Desktop/baker-code/.claude/hooks/write_brief_sop_enforcer.sh` — copy
- EDIT 5× `.claude/settings.json` (settings.local.json for researcher) — add PreToolUse entry alongside existing `ui-surface-prebrief-check.sh`

**Layer 3 (5):**
- NEW `~/baker-vault/.githooks/brief_sop_check.sh` — canonical
- NEW `~/baker-vault/.githooks/tests/test_brief_sop_check.sh` — 6 tests
- NEW `~/bm-aihead1/.githooks/brief_sop_check.sh` — mirror (header comment names canonical)
- EDIT `~/baker-vault/.githooks/pre-commit` — chain brief_sop_check.sh
- EDIT `~/bm-aihead1/.githooks/pre-commit` — add Part 5 invoking brief_sop_check.sh

**Docs (1):**
- APPEND `tasks/lessons.md` (in baker-master) — Layer 2 vs Layer 3 pattern lesson

## Do NOT Touch

- B-code pickers `~/bm-b{1-4}/.claude/settings.json` — don't author briefs
- Global `~/.claude/settings.json` — avoid catching Director's ad-hoc Claude Code sessions
- `~/.claude/skills/write-brief/SKILL.md` — enforces existing SOP, does not modify it
- Other pre-commit Parts: vault (state_reconciler / cascade_backprop / gold_drift); baker-master (Parts 1-4)
- `.githooks/commit-msg` hooks — Layer 3 fires at pre-commit, not commit-msg
- `tasks/lessons.md` existing entries — append-only

## Quality Checkpoints

1. Layer 2 hook script syntax-checks: `bash -n ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh`
2. Layer 3 hook script syntax-checks: `bash -n ~/baker-vault/.githooks/brief_sop_check.sh`
3. Mirror byte-identical (except header comment): `diff <(tail -n +3 ~/baker-vault/.githooks/brief_sop_check.sh) <(tail -n +3 ~/bm-aihead1/.githooks/brief_sop_check.sh)` returns empty
4. Layer 2 tests: `bash ~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh` — 6/6 PASS (literal output in ship report)
5. Layer 3 tests: `bash ~/baker-vault/.githooks/tests/test_brief_sop_check.sh` — 6/6 PASS (literal output in ship report)
6. Picker hook copies all executable: `for p in ~/bm-aihead1 ~/bm-aihead1-cowork ~/bm-aihead2 ~/bm-researcher ~/Desktop/baker-code; do test -x "$p/.claude/hooks/write_brief_sop_enforcer.sh" && echo "OK: $p" || echo "FAIL: $p"; done` — all OK
7. Each picker's settings.json (or settings.local.json) parses as valid JSON: `for p in ~/bm-aihead1/.claude/settings.json ~/bm-aihead1-cowork/.claude/settings.json ~/bm-aihead2/.claude/settings.json ~/bm-researcher/.claude/settings.local.json ~/Desktop/baker-code/.claude/settings.json; do jq -e . "$p" >/dev/null && echo "OK: $p" || echo "FAIL: $p"; done` — all OK
8. baker-vault pre-commit chains brief_sop_check.sh: `grep -q 'brief_sop_check.sh' ~/baker-vault/.githooks/pre-commit`
9. baker-master pre-commit invokes brief_sop_check.sh: `grep -q 'brief_sop_check.sh' ~/bm-aihead1/.githooks/pre-commit`
10. Dog-food: this brief itself (`briefs/BRIEF_WRITE_BRIEF_SOP_ENFORCER_HOOK_1.md`) was authored via /write-brief invocation. Verify via session transcript before B-code starts (this brief was authored 2026-05-23 evening by AH1-T during a session that invoked `Skill(skill="write-brief")` at the top of the brief-authoring turn — see commit message anchor).
11. Layer 2 manual smoke (post-install in b3's own picker): create `/tmp/briefs/BRIEF_SMOKE.md` write attempt without `/write-brief` invocation in a fresh session → blocked. Then bypass env → passes.
12. Layer 3 manual smoke: stage a partial brief in a sandbox repo + run hook → blocks. Add bypass trailer → passes.

## Acceptance criteria

- **AC1** — Layer 2 hook installed at canonical `~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh` + 5 picker copies; all executable.
- **AC2** — Layer 2 path filter regex matches `briefs/BRIEF_*.md` + `_ops/briefs/BRIEF_*.md`; excludes `_reports/*` and `_tasks/CODE_*_*.md`. Verified by test cases 5 + 6.
- **AC3** — Layer 2 block message names the skill verbatim, instructs `Skill(skill="write-brief")`, names bypass env. Captured in test case 1 stderr.
- **AC4** — Layer 2 bypass env `BAKER_BRIEF_SOP_BYPASS=1` works + logs to stderr. Verified by test case 4.
- **AC5** — Layer 2 installed in 5 picker `.claude/settings.json` (or `settings.local.json`) files: AH1-T, AH1-cowork, AH2, Researcher, legacy AH1-T. NOT installed in B-code pickers or global. Verified by quality checkpoint 7.
- **AC6** — Layer 2 test harness at `~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh` covers 6 cases; literal `6/6 PASS` output in ship report.
- **AC7** — Literal bash test-run output pasted in ship report (Layer 2 + Layer 3 combined). NO "by inspection".
- **AC8** — This brief itself authored via /write-brief invocation. Verified at commit time (this brief's authoring session transcript will be archived in baker-master git history as the first compliance test).
- **AC9** — Layer 3 hook installed at `~/baker-vault/.githooks/brief_sop_check.sh` + mirror at `~/bm-aihead1/.githooks/brief_sop_check.sh`. Detects 3+ of 5 missing canonical section headers; blocks with descriptive stderr.
- **AC10** — Layer 3 bypass via commit-msg trailer `Brief-SOP-bypass: <reason>`. Verified by test case 3.
- **AC11** — Layer 3 test harness covers 6 cases; `6/6 PASS` literal output in ship report.
- **AC12** — Layer 3 chained into baker-vault pre-commit + invoked from baker-master pre-commit Part 5. Verified by quality checkpoints 8 + 9.
- **AC13** — Combined literal test output (12 cases / 2 harnesses) pasted verbatim in ship report.

## Verification (post-deploy)

```bash
# Vault canonical hook executable
test -x ~/baker-vault/_ops/hooks/write_brief_sop_enforcer.sh && echo "L2 canonical OK"
test -x ~/baker-vault/.githooks/brief_sop_check.sh && echo "L3 canonical OK"

# Picker installs all executable
for p in ~/bm-aihead1 ~/bm-aihead1-cowork ~/bm-aihead2 ~/bm-researcher ~/Desktop/baker-code; do
    test -x "$p/.claude/hooks/write_brief_sop_enforcer.sh" && echo "L2 picker OK: $p" || echo "L2 picker FAIL: $p"
done

# Pre-commit chains
grep -q 'brief_sop_check.sh' ~/baker-vault/.githooks/pre-commit && echo "L3 vault chain OK"
grep -q 'brief_sop_check.sh' ~/bm-aihead1/.githooks/pre-commit && echo "L3 baker-master chain OK"

# Run both test harnesses (literal output mandatory)
bash ~/baker-vault/_ops/hooks/tests/test_write_brief_sop_enforcer.sh
bash ~/baker-vault/.githooks/tests/test_brief_sop_check.sh
```

## Reply target

```yaml
dispatched_by: lead
dispatched_at: <ISO timestamp on dispatch>
ship_report_routes_to: lead
```

## Gate chain (AH2 cross-lane review per #788/#790)

MEDIUM trigger class (harness-control surface + cross-picker install).

- gate-1 architecture-review (AH2)
- gate-2 /security-review — hook scripts read transcript files + execute on every Write/Edit; expected NO_FINDINGS (no network, no auth, no secrets, read-only stdin)
- gate-3 picker-architect (cross-picker install verification)
- gate-4 feature-dev:code-reviewer 2nd-pass (AH2)
- gate-5 AH1 final merge

## Reference

- Parent brief request: bus #788 (AH2)
- Layer 3 amendment: bus #790 (AH2)
- Director chat 2026-05-23 evening: ratification anchor
- Existing PreToolUse precedent: `~/bm-aihead1/.claude/hooks/ui-surface-prebrief-check.sh`
- Existing pre-commit precedent: `~/baker-vault/.githooks/cascade_backprop_check.sh` + `~/bm-aihead1/.githooks/pre-commit` Part 4
- Layer-2-vs-Layer-3 parallel: `tools/render_env_guard.py` (wrapper) + `.githooks/pre-commit` Part 4 (audit)
- Anthropic hooks reference: https://code.claude.com/docs/en/hooks (verified ui-surface-prebrief hook structure 2026-05-19)
- Skill canonical: `~/.claude/skills/write-brief/SKILL.md`
