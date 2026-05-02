# B3 — Ship report: BRIEF_TERMINAL_AUTO_ONBOARD_1

**Builder:** B3
**Date:** 2026-05-02
**Brief:** `briefs/BRIEF_TERMINAL_AUTO_ONBOARD_1.md`
**Branch:** `b3/terminal-auto-onboard-1`
**PR:** https://github.com/vallen300-bit/baker-master/pull/149
**Tier:** B / LOW (autonomous-merge-on-green per ai-head-autonomy-charter §3)
**Status:** SHIPPED — waiting on AI Head A merge

## What shipped

9 in-repo files added + brief copy + mailbox overwrite (11 files total in commit `2d7937d`):

| Path | Mode | Purpose |
|---|---|---|
| `.claude/hooks/session-start-role.sh` | `100755` | SessionStart hook; emits per-role JSON envelope |
| `.claude/role-context/ah1.md` | `100644` | AH1 (orchestrator) injection text |
| `.claude/role-context/ah2.md` | `100644` | AH2 (deputy) injection text |
| `.claude/role-context/b1.md` | `100644` | B1 builder injection text |
| `.claude/role-context/b2.md` | `100644` | B2 builder injection text |
| `.claude/role-context/b3.md` | `100644` | B3 builder injection text |
| `.claude/role-context/b4.md` | `100644` | B4 builder injection text |
| `.claude/role-context/b5.md` | `100644` | B5 builder injection text |
| `.claude/settings.local.json.example` | `100644` | Template (real settings.local.json gitignored) |
| `briefs/BRIEF_TERMINAL_AUTO_ONBOARD_1.md` | `100644` | Brief itself (authored AI Head B, dispatched AI Head A) |
| `briefs/_tasks/CODE_3_PENDING.md` | (modified) | Mailbox overwrite (prior was VAULT_WRITE_FOLLOWUP_NITS_1 COMPLETE → now PENDING for this brief) |

`.claude/settings.json` (existing per-clone forge-agent observability hook from BRISEN_LAB_1) was deliberately NOT committed — doc-noted only per `_ops/processes/brisen-lab-session-start-hook.md` "Why this is a doc-note, not tracked config".

## Quality checkpoints — all passed

```bash
bash -n .claude/hooks/session-start-role.sh        # ✅ syntax ok
chmod +x .claude/hooks/session-start-role.sh       # ✅ exec bit preserved (git ls-files --stage → 100755)
```

### 4 manual unit tests (per brief §Quality checkpoints)

All produce a valid JSON object on stdout with `hookSpecificOutput.hookEventName == "SessionStart"` and exit 0:

| # | Input | `additionalContext` | exit |
|---|---|---|---|
| 1 | `echo '{}' \| BAKER_ROLE=AH2 .claude/hooks/session-start-role.sh` | `ah2.md` body (full) | 0 ✅ |
| 2 | `echo '{}' \| BAKER_ROLE=B3 .claude/hooks/session-start-role.sh` | `b3.md` body (full) | 0 ✅ |
| 3 | `echo '{}' \| env -u BAKER_ROLE .claude/hooks/session-start-role.sh` (run from `/tmp`) | "set BAKER_ROLE" nudge | 0 ✅ |
| 3b | same as 3 but run from `~/bm-b3` | `b3.md` body via cwd-fallback | 0 ✅ |
| 4 | `echo '{}' \| BAKER_ROLE=NONSENSE .claude/hooks/session-start-role.sh` | "no context file at .../nonsense.md" | 0 ✅ |
| neg | every branch — confirmed exit=0 | — | 0 ✅ |

Note on test 3: the brief writer's expected nudge is reachable only when neither `$BAKER_ROLE` is set nor cwd matches `bm-b<N>`. Running the literal command from inside `~/bm-b3` produces the b3 cwd-fallback (test 3b). Both behaviors are correct per the resolution-order spec; report includes both runs to remove ambiguity.

### Smoke test (per brief §Quality checkpoints)

```bash
# Wired SessionStart hook into local .claude/settings.local.json (gitignored)
BAKER_ROLE=B3 claude --print --debug=hooks "what is your role per SessionStart context block?"
```

Output (turn 1, fresh session):

> "I am B3 (Code Brisen builder #3), implementation-only — read mailbox, claim PENDING dispatches, run Quality checkpoints, open PRs, file completion reports."

✅ Hook fired. JSON envelope parsed by Claude Code. `b3.md` body was injected into the model's context. Turn 1 correctly self-identified as B3 — confirms the end-to-end auto-onboard flow works.

## Acceptance criteria — all met

- ✅ 9 files added (1 hook + 7 role-context + 1 settings example).
- ✅ Hook executable (`100755` per `git ls-files --stage`).
- ✅ All 4 manual unit tests produce valid JSON envelopes.
- ✅ Hook exits 0 in every branch (set / unset / unknown / missing-file).
- ✅ Smoke test passed — fresh `BAKER_ROLE=B3` session self-identified in turn 1.
- ✅ PR #149 opened with brief link in body + vault doc body inline (Director can copy into baker-vault when convenient).
- ✅ Tier B autonomous-merge on green.
- ✅ This ship report at `briefs/_reports/B3_terminal_auto_onboard_1_20260502.md`.

## Notes for AI Head A reviewer

1. **Lesson #54 precheck:** ran `gh pr list --state open --limit 20 --search "head:b3/terminal-auto-onboard-1 OR head:terminal-auto-onboard"` — empty (no overlapping branch).
2. **Out-of-scope confirmations** (per brief):
   - No SessionEnd hook (covered by `/handover` slash command).
   - No COWORK role context (separate `BRIEF_BRISEN_LAB_MSGBUS_1`).
   - No real `settings.local.json` committed (gitignored — only `.example`).
   - Did not touch `.claude/hooks/block-secrets.sh`, `syntax-check.sh`, or `~/.claude/bin/baker-statusline.sh`.
3. **Vault-side doc:** body in PR description for Director to copy into baker-vault as `_ops/processes/terminal-profiles.md` (separate PR — Director-side, low priority; hook works without it).
4. **Local clone state:** my own `~/bm-b3/.claude/settings.local.json` now contains the SessionStart hook entry (the auto-onboard one), so future B3 cold-starts in this clone will fire the hook. The example template was used as the wiring reference.

## On merge

1. AI Head A merges (autonomous Tier B per charter §3).
2. Mailbox `briefs/_tasks/CODE_3_PENDING.md` flips to `status: COMPLETE` with PR link (will be done in the same merge commit's mailbox follow-up, or by AI Head A's standard post-merge workflow).
3. Director adopts terminal profiles per the PR-description process doc (one-time setup; can wait until convenient).
4. Future cold-starts in any clone with `BAKER_ROLE` set + `.claude/settings.local.json` wired will auto-onboard.
