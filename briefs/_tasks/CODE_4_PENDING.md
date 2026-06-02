# CODE_4_PENDING — FORGE_HEARTBEAT_TURN_GATED_1

status: PENDING
dispatched_by: lead
ship-report recipient: lead
repo: forge instrumentation on THIS Mac (~/forge-agent/ + ~/.claude/settings.json) — on-disk, NOT git-tracked. Edit in place.
task class: production implementation (agent telemetry, local instrumentation)
gate plan: G0 codex (brief PASS-WITH-NOTES #1634) → G1 lead static (review 3 scripts + settings.json diff) → G2 N/A (no repo/endpoint) → live AC (Director visual judge)
bus topics: ship/forge-heartbeat-turn-gated-1

## Context

Canonical brief (READ IN FULL FIRST): `~/baker-vault/_ops/briefs/BRIEF_FORGE_HEARTBEAT_TURN_GATED_1.md` (commit cf6a9eb; codex G0 PASS-WITH-NOTES #1634 — both notes folded: printf-not-echo + stale-flag caveat).

Director bug 2026-06-02: your #56 heartbeat made the dashboard amber = "session window OPEN," not "actively working." b1 + b4 stayed amber while idle (windows open ~50 min); only closing the window cleared it. Live API confirmed is_working=True for idle-open b1/b4. Director wants amber = working NOW, extinguished when the task finishes (window can stay open).

## Problem

`~/forge-agent/heartbeat-ticker.sh` beats `/api/heartbeat` unconditionally every 45s while the parent session lives → last_seen_at always fresh → is_working=True forever → amber never extinguishes.

## Files Modified

(per brief §Stable Paths — all on-disk, NOT git-tracked):
- `~/forge-agent/heartbeat-ticker.sh` — beat ONLY when the turn-flag `~/forge-agent/active/<session_uuid>` exists; clear own flag on parent-exit.
- NEW `~/forge-agent/turn-start-hook.sh` — UserPromptSubmit → `: > ~/forge-agent/active/<session_id>`. Self-gate on $FORGE_TERMINAL, exit 0 always. **Parse stdin with `printf '%s' "$INPUT" | python3` (NOT echo).**
- NEW `~/forge-agent/turn-stop-hook.sh` — Stop → `rm -f ~/forge-agent/active/<session_id>`. Self-gate, exit 0, printf.
- `~/.claude/settings.json` — ADDITIVELY wire turn-start-hook.sh into UserPromptSubmit + turn-stop-hook.sh into Stop. **Back up first (`cp settings.json settings.json.bak-turn-gated`), validate with `python3 -m json.tool`, do NOT remove/reorder any existing hook.**

Do NOT touch: brisen-lab repo / `/api/heartbeat` endpoint, `is_working`/`WORKING_FRESH_THRESHOLD_S`, session-start-hook.sh register/spawn logic.

## Quality Checkpoints (codex #1634)

1. Amber ON only during an active turn (incl reasoning); OFF ~≤120s after the turn ends with the window still OPEN. This is the Director fix (AC2).
2. Both hooks self-gate on $FORGE_TERMINAL + `exit 0` on every path — never block any agent's turn (mirror session-start-hook.sh discipline; no `set -e`).
3. settings.json edited ADDITIVELY, JSON valid, existing hooks (recommendation-check, laconic, etc.) intact, backup kept.
4. Flag keyed by session_id → concurrent b-codes independent.
5. printf not echo for hook JSON parse.
6. Stale-flag caveat (abnormal turn where Stop doesn't fire — interrupt/API error — can leave the flag until next Stop/session-exit): acceptable for v1, ticker clears own flag on parent-exit; document in ship report. TTL sweep = v2 follow-up, out of scope.

## Verification (live — no repo, no deploy)

settings.json hooks load at SessionStart → after wiring, RESTART one watched b-code session to test. Then:
- AC1: mid-turn (running tools/reasoning) → card amber; is_working=True on /api/v2/terminals.
- **AC2 (the fix):** finishes the turn, sits idle with window OPEN → within ~2 min card goes grey (is_working=False). No window close needed.
- AC3: next task → amber returns.
- AC4: a non-watched session (lead) unaffected — hooks no-op, no errors.
- AC5: two watched b-codes mid-turn → both amber independently; one finishing doesn't extinguish the other.
Literal evidence: is_working transitions + the flag file appearing/clearing under ~/forge-agent/active/.

## Constraints

Local instrumentation only; no PR, no /security-review. Fail-safe (exit 0 always). No secrets in logs. Ship report answers the done rubric (terminal state = Director-observed stuck-amber gone on live dashboard) + documents the stale-flag caveat. Writeback `_ops/processes/autonomous-delegated-loop-spec.md` §Status (amber now = actively working) — flag for lead to land (vault-side, not your commit lane). Ship to topic ship/forge-heartbeat-turn-gated-1.
