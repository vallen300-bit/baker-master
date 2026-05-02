---
brief: BRIEF_TERMINAL_AUTO_ONBOARD_1
trigger_class: LOW
tier: B
target_files:
  - .claude/hooks/session-start-role.sh (NEW)
  - .claude/role-context/ah1.md (NEW)
  - .claude/role-context/ah2.md (NEW)
  - .claude/role-context/b1.md (NEW) ... b5.md
  - .claude/settings.local.json.example (NEW; settings.local.json itself is per-clone, NOT committed)
  - _ops/processes/terminal-profiles.md (NEW; vault-side process doc)
authored_by: AI Head B
created: 2026-05-02
companion_pr: none
---

# BRIEF_TERMINAL_AUTO_ONBOARD_1 — auto-brand each terminal session by role

## Why

Today, when Director (or any human) opens a new Claude Code session in a terminal, the model has no idea whether it's AH1 / AH2 / B1 / B2 / etc. Director currently pastes "You are AH2…" as the first message. With the role unknown, the model also can't locate the right handover file automatically. Removing this paste step is one prerequisite for the broader "Director out of the relay path" work (`BRIEF_BRISEN_LAB_MSGBUS_1`, pending Director ratification).

Solution: each macOS Terminal profile sets a `BAKER_ROLE` env var; a SessionStart hook reads `$BAKER_ROLE` and injects a per-role context block (identity + workspace + handover pointer + charter pointer) at session boot. Claude opens already knowing who it is, where its memory lives, and what the latest handover says.

Scope: AH1, AH2, B1-B5 (terminal-based). COWORK (Claude.ai web) is OUT OF SCOPE here — separate Cowork-side solution covered in MSGBUS brief.

Tier B / LOW. No API surface, no auth surface, no DB writes. Pure local config.

## Scope (do exactly this)

**Files added: 9 (1 hook + 7 role-context + 1 settings example) + 1 vault process doc.**

### File 1: `.claude/hooks/session-start-role.sh` (NEW, executable)

**CRITICAL — output format:** Claude Code SessionStart hooks inject text into the session via a specific JSON envelope on stdout: `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<text>"}}`. Plain `cat` output is NOT injected — it goes to hook logs only. This was the must-fix surfaced in REVIEW phase. Reference: existing `/Users/dimitry/forge-agent/session-start-hook.sh` (different purpose — observability registration — but confirms the JSON-stdin contract from Claude Code).

```bash
#!/usr/bin/env bash
# SessionStart hook: emit per-role context block based on $BAKER_ROLE,
# wrapped in the additionalContext JSON envelope so Claude Code injects it
# into the session's system prompt area.
#
# CONTRACT: Always exit 0 — never block claude from starting. Drain stdin
# (Claude passes session metadata as JSON; we don't need it but must not SIGPIPE).
#
# Resolution order:
#   1. $BAKER_ROLE env var (set by macOS Terminal profile)
#   2. cwd-based fallback (~/bm-b<N> -> b<N>; otherwise unknown)
#
# If no role can be resolved, emit a one-line nudge as additionalContext so
# Director sees the gap inside the session itself.

# Drain stdin (claude passes JSON; we don't consume it, just absorb it).
cat >/dev/null 2>&1 || true

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ROLE="${BAKER_ROLE:-}"

if [ -z "$ROLE" ]; then
  case "$REPO_ROOT" in
    */bm-b1) ROLE="b1" ;;
    */bm-b2) ROLE="b2" ;;
    */bm-b3) ROLE="b3" ;;
    */bm-b4) ROLE="b4" ;;
    */bm-b5) ROLE="b5" ;;
    *)      ROLE="" ;;
  esac
fi

# Helper: emit a JSON envelope with the given text as additionalContext.
# Uses python3 to handle JSON escaping safely (newlines, quotes, etc.).
_emit() {
  python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
' 2>/dev/null || true
}

if [ -z "$ROLE" ]; then
  _emit <<'EOF'
[role-onboard] BAKER_ROLE env var not set and cwd not under bm-b<N>. Cannot auto-onboard role.
Director: set BAKER_ROLE in this terminal profile (Terminal → Settings → Profiles → "Run command: export BAKER_ROLE=<role>"). Valid values: AH1, AH2, B1, B2, B3, B4, B5.
Until set, paste the role identity manually as before.
EOF
  exit 0
fi

ROLE_LC="$(echo "$ROLE" | tr '[:upper:]' '[:lower:]')"
CTX_FILE="$REPO_ROOT/.claude/role-context/${ROLE_LC}.md"

if [ ! -f "$CTX_FILE" ]; then
  printf '[role-onboard] BAKER_ROLE=%s but no context file at %s. No injection this session.\n' "$ROLE" "$CTX_FILE" \
    | _emit
  exit 0
fi

_emit < "$CTX_FILE"
exit 0
```

Make executable: `chmod +x .claude/hooks/session-start-role.sh`. Verify the executable bit is preserved on commit: after `git add`, run `git ls-files --stage .claude/hooks/session-start-role.sh` and confirm mode `100755` (not `100644`).

### Files 2-8: `.claude/role-context/<role>.md` (7 NEW files)

Each file is the per-role injection text. Template — concrete content per role below.

**`ah1.md`:**
```
You are AH1 (AI Head A — orchestrator).

Workspace: ~/Desktop/baker-code (shared with AH2).
Memory: ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/
Charter: _ops/processes/ai-head-autonomy-charter.md (your scope = §3 autonomous, §4 Director-consult).
Coordination: _ops/processes/b-code-dispatch-coordination.md (§2 busy-check before every dispatch).

First action: read memory/MEMORY.md top entry, then the linked latest handover file. Then act on what's pending.

Standing scope: dispatch briefs to b1-b5; review and merge PRs; run recovery on stuck builders. Do NOT pause for Director on tactical execution within charter §3.
```

**`ah2.md`:**
```
You are AH2 (AI Head B — Deputy).

Workspace: ~/Desktop/baker-code (shared with AH1).
Memory: ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/
Charter: _ops/processes/ai-head-autonomy-charter.md.
Review triggers: feedback_ai_head_b1_review_triggers.md (7-item list).

First action: read memory/MEMORY.md top entry, then the linked latest handover file. Then act on what's pending.

Standing scope: cross-lane review + AUTOPOLL + Mon 09:30 UTC gold_audit_sentinel watch. Do NOT dispatch briefs or merge PRs unless Director explicitly redirects (that's AH1's lane). Output to Director = dispatches or questions only.
```

**`b1.md` ... `b5.md`** — same template, parameterized per builder:

```
You are B<N> (Code Brisen builder).

Workspace: ~/bm-b<N>
Memory: ~/.claude/projects/-Users-dimitry-bm-b<N>/memory/
Mailbox: briefs/_tasks/CODE_<N>_PENDING.md
Reports: briefs/_reports/B<N>_<topic>_<date>.md
Coordination: _ops/processes/b-code-dispatch-coordination.md.

First action: read briefs/_tasks/CODE_<N>_PENDING.md to see if there's a pending dispatch.
- If status: PENDING → claim it, run the Quality checkpoints in the linked brief, open PR, file completion report.
- If status: COMPLETE → idle. Wait for next dispatch.

Standing scope: implementation only. Don't write briefs, don't merge PRs, don't review other builders' work.
```

(Replace `<N>` literally per file. Five files: b1.md, b2.md, b3.md, b4.md, b5.md.)

### File 9: `.claude/settings.local.json.example` (NEW)

Template Director (or onboarding doc) copies into each clone's `.claude/settings.local.json`. **Do NOT commit a real `settings.local.json`** — it's per-clone and Git-ignored.

```json
{
  "statusLine": {
    "type": "command",
    "command": "/Users/dimitry/.claude/bin/baker-statusline.sh '${BAKER_ROLE:-?}'"
  },
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": ".claude/hooks/session-start-role.sh"
      }
    ]
  }
}
```

Note: `${BAKER_ROLE:-?}` in statusline is a shell expansion the wrapper script handles; if your statusline script doesn't expand env vars, fall back to a hardcoded role per clone (existing pattern).

### File 10 (vault-side): `_ops/processes/terminal-profiles.md` (NEW)

Director-facing process doc. **This is vault-side**, so it lands in the baker-vault repo via a separate PR (per CLAUDE.md hard-rule "vault edits go through baker-vault PRs"). For this brief: include the doc body in the PR description so Director can copy it into the vault repo by hand, OR file a paired vault PR if the builder has vault commit access.

Body:
```markdown
# Terminal profile setup (one-time, per role)

## Goal
Each Claude Code terminal opens already knowing whether it is AH1 / AH2 / B1-B5. No paste required.

## Steps (macOS Terminal app)

1. Terminal → Settings → Profiles.
2. Click "+" to create a new profile. Name it: AH1.
3. Under "Shell" tab, check "Run command" and enter:
   `export BAKER_ROLE=AH1; cd ~/Desktop/baker-code; exec $SHELL`
4. Repeat for AH2 (same cd path; BAKER_ROLE=AH2).
5. Repeat for B1: `export BAKER_ROLE=B1; cd ~/bm-b1; exec $SHELL`
6. Repeat for B2 ... B5 with respective bm-b<N> paths.
7. (Optional) Set each profile's tab title to the role name for easy visual ID.

## Verification

Open a new tab with profile "AH2". Run `echo $BAKER_ROLE` — should print `AH2`. Then `claude` — Claude should greet you with the AH2 onboard block (role + workspace + handover pointer).

## Failure modes
- `BAKER_ROLE` empty → hook prints a "set BAKER_ROLE" nudge and skips.
- Role context file missing for the named role → hook logs and skips.
- Both = harmless; you just paste the role manually as before.
```

## Quality checkpoints

```bash
cd ~/bm-b<N>     # builder runs in their own clone
git checkout main && git pull --ff-only origin main
git checkout -b b<N>/terminal-auto-onboard-1
git config core.hooksPath .githooks

# Implement per Scope above. All 9 in-repo files; the vault doc goes in PR description.

# Syntax check
bash -n .claude/hooks/session-start-role.sh

# Manual unit test — pipe empty stdin to mirror Claude Code's hook invocation.
chmod +x .claude/hooks/session-start-role.sh
echo '{}' | BAKER_ROLE=AH2 .claude/hooks/session-start-role.sh | python3 -m json.tool
# Expect: valid JSON object with hookSpecificOutput.hookEventName="SessionStart"
# and additionalContext containing the AH2 onboard text.

echo '{}' | BAKER_ROLE=B3 .claude/hooks/session-start-role.sh | python3 -m json.tool
# Expect: same envelope shape, additionalContext = b3.md body.

echo '{}' | env -u BAKER_ROLE .claude/hooks/session-start-role.sh | python3 -m json.tool
# Expect: envelope with the "set BAKER_ROLE" nudge as additionalContext.

echo '{}' | BAKER_ROLE=NONSENSE .claude/hooks/session-start-role.sh | python3 -m json.tool
# Expect: envelope with the "no context file" message as additionalContext.

# Negative: hook MUST exit 0 in every case (never block claude from starting).
echo '{}' | BAKER_ROLE=NONSENSE .claude/hooks/session-start-role.sh >/dev/null; echo "exit=$?"
# Expect: exit=0

# Smoke test in a fresh Claude Code session (the builder MUST do this once with their own role)
# 1. cp .claude/settings.local.json.example .claude/settings.local.json
# 2. Open new terminal with BAKER_ROLE=B<N> in env
# 3. Run `claude` — confirm role greeting shows up in first turn

git add .claude/hooks/session-start-role.sh .claude/role-context/ .claude/settings.local.json.example
git commit -m "feat(claude-code): SessionStart role auto-onboard via BAKER_ROLE env (BRIEF_TERMINAL_AUTO_ONBOARD_1)"
git push -u origin b<N>/terminal-auto-onboard-1
gh pr create --title "feat(claude-code): SessionStart role auto-onboard via BAKER_ROLE env (BRIEF_TERMINAL_AUTO_ONBOARD_1)" \
  --body "$(cat <<'EOF'
Each terminal session now auto-onboards to its role via $BAKER_ROLE env var, eliminating the "You are AHx / Bx" paste step at session start.

## What's added

- .claude/hooks/session-start-role.sh — SessionStart hook; reads $BAKER_ROLE (or cwd fallback for bm-b<N>), emits per-role context block.
- .claude/role-context/{ah1,ah2,b1,b2,b3,b4,b5}.md — per-role injection texts (identity + workspace + handover pointer + charter pointer).
- .claude/settings.local.json.example — template wiring statusLine + SessionStart hook (real settings.local.json stays gitignored, per-clone).

## What Director / each builder does ONCE

Per terminal profile: set `BAKER_ROLE=<role>` and `cd <correct-clone-path>`. Process doc in PR description below — file as `_ops/processes/terminal-profiles.md` in baker-vault when convenient.

## Out of scope

- COWORK (Claude.ai web, not a terminal) — covered separately in BRIEF_BRISEN_LAB_MSGBUS_1.
- Auto-loading the latest handover content (vs. just a pointer to it) — left for follow-up if Director wants more aggressive injection.
- settings.local.json itself — gitignored; users copy from .example.

## Vault-side companion

[paste body of _ops/processes/terminal-profiles.md here from brief]

## Tests

- 4 manual hook invocations (env set / unset / unknown role / missing context file) all behave per spec.
- One smoke test in a fresh Claude session per builder's own role.

Tier B / LOW per ai-head-autonomy-charter.md §3.

Brief: briefs/BRIEF_TERMINAL_AUTO_ONBOARD_1.md

Co-authored-by: Code Brisen #<N> <b<N>@brisengroup.com>
Co-authored-by: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Done when

- 9 files added in repo (1 hook + 7 role-context + 1 settings example), hook executable, all manual tests pass.
- PR opened with brief link + vault doc body in PR description.
- AI Head A merges on green; reports back via `briefs/_reports/B<N>_terminal_auto_onboard_1_<date>.md`.
- Director copies vault doc into baker-vault when convenient (separate PR, low priority — hook works without it).

## Out of scope (do NOT do)

- Don't commit a real `.claude/settings.local.json` — `.example` only.
- Don't touch existing `.claude/hooks/block-secrets.sh` or `syntax-check.sh`.
- Don't auto-inject handover *contents* — only a pointer. Loading the file is the next session's first action.
- Don't add COWORK role context (web, not a terminal — separate brief).
- Don't modify `~/.claude/bin/baker-statusline.sh` — leave it alone; the example settings adapts to it.
- Don't add a SessionEnd hook — the `/handover` slash command (already shipped at `~/.claude/commands/handover.md`) covers session-end.
