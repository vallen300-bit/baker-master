---
status: PENDING
brief: briefs/_tasks/CODE_1_PENDING.md (this file IS the brief — small scope)
trigger_class: TIER_B_USER_GLOBAL_HOOK_INSTALL
dispatched_at: 2026-05-11
dispatched_by: ai-head-1 (AH1)
target: b1
director_ratification: Director 2026-05-11 ~15:30Z "go ahead. After we finish, let's proceed with installing codex as a judge" + "Send to B code build whenever you're ready. By bus."
priority: P1
phase: 1 of 1 (single PR)
unblocks:
  - Mechanical enforcement of "always include Recommendation" rule (today's repeated slip)
  - Mechanical enforcement of "fail loud" rule (sharper communication framing)
expected_pr_count: 1 (baker-master)
expected_branch_name: b1/stop-hooks-recommendation-and-fail-loud-1
expected_complexity: small (~2h)
mandatory_2nd_pass: FALSE  # scope <100 LOC bash, no auth/DB/concurrency surface; AH1 judgment per SKILL.md §Code-reviewer 2nd-pass Protocol
gate_to_merge: AH2 cross-lane review (no /security-review — diff is bash + json fixtures, no code path)
last_heartbeat: null
heartbeat_cadence_hours: 12
---

# CODE_1_PENDING — STOP_HOOKS_RECOMMENDATION_AND_FAIL_LOUD_1 — 2026-05-11

## Goal

Two Stop hooks that mechanically catch the two slip modes Director keeps catching:

1. **`recommendation-check.sh`** — scans the model's final response for `Recommendation:` line. If absent AND the response contains question marks or numbered options, emits a warning JSON to surface the gap.
2. **`fail-loud-check.sh`** — scans the model's final response for "completed" / "done" / "tests pass" / "shipped" claims. If found AND no explicit verification phrase ("0 skipped" / "X edge cases verified" / "literal pytest output: ...") in the same response, emits a warning.

Both are advisory (warn, not block) on first build. Director may flip to blocking later.

## Why

Today's session hit the recommendation slip on Q8 (caught manually by Director) AND has historically hit "completed" claims that turned out to be partial. Mnilax X article (May 2026, 30-codebase 6-week test) shows: rules in CLAUDE.md get ~80% compliance even when well-tuned. Hooks bring mechanically-checkable rules to ~100%. See `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/feedback_always_include_recommendation.md` + project CLAUDE.md §"ENGINEERING RULES" Fail-loud rule for source.

## Files to create / modify

**New (canonical sources in baker-master):**
- `tests/fixtures/recommendation-check.sh` — Stop hook bash script (~30 LOC). Reads stop-event JSON from stdin, parses `transcript_path`, reads last assistant message, applies the regex check, emits `{"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "<warning text>"}}` when gap detected. Exits 0 on every path.
- `tests/fixtures/fail-loud-check.sh` — same pattern.
- `tests/test_stop_hooks.py` — pytest with parametrized cases: (a) recommendation-check emits warning when assistant message has question + no Recommendation, (b) recommendation-check stays silent when Recommendation present, (c) fail-loud emits when "completed" with no verification phrase, (d) fail-loud stays silent when verification phrase present, (e) drift-detection test diff'ing fixtures against `~/.claude/hooks/<name>.sh` if those exist.

**Modify:**
- `~/.claude/settings.json` (user-global, OUTSIDE the repo) — register both hooks under `hooks.Stop` array. Pre-merge cp pattern: B1 cp's the fixtures to `~/.claude/hooks/<name>.sh` AND splices settings.json BEFORE merge so the drift-detection test passes locally. Pattern reference: `~/.claude/hooks/session-start-bus-drain.sh` (already cp'd this morning per BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1).

**Do NOT touch:**
- `outputs/dashboard.py` — orthogonal
- `kbl/`, `models/`, `triggers/`, `tools/`, `migrations/` — orthogonal
- Existing user-global hooks (`session-start-bus-drain.sh`) — separate concern

## Hook contract details

**Stop event input (from stdin, JSON):**
```json
{
  "hook_event_name": "Stop",
  "session_id": "...",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "..."
}
```

**Hook output (stdout, JSON):**
- Emit `{"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "<warning>"}}` when slip detected.
- Empty output (or no print) when clean.
- ALWAYS exit 0. Never block. Never crash. Never timeout (max 4s).

**Reading the last assistant message:**
- Parse `transcript_path` (JSONL — each line is a turn).
- Walk backwards from EOF, find last line where `type == "assistant"`, extract `message.content[].text` joined.
- Skip if no assistant message found.

**Recommendation-check regex:**
- TRIGGER condition: assistant text contains either `?` OR a numbered list (`^\d+\.` regex) OR phrase like "options" / "choose" / "which".
- ABSENT condition: assistant text does NOT contain `Recommendation:` (case-insensitive, line-anchored).
- WARN message: `Stop-hook: assistant response asks a question or presents options but contains no 'Recommendation:' line. Per project CLAUDE.md HARD RULE 2, every multi-option / multi-Q reply ends with explicit Recommendation.`

**Fail-loud-check regex:**
- TRIGGER condition: assistant text contains any of (case-insensitive): "completed", "done", "tests pass", "shipped", "merged", "all green".
- ABSENT condition: assistant text does NOT contain ANY of: digits + "skipped", "verified", "literal", "0 fail", "no edge case missed".
- WARN message: `Stop-hook: assistant response claims completion / pass / ship but contains no explicit verification phrase. Per project CLAUDE.md ENGINEERING RULES Fail-loud, surface uncertainty rather than hiding it.`

## Acceptance criteria

| AC | Test | Verification |
|---|---|---|
| A1 | `tests/fixtures/recommendation-check.sh` exists, exec bit set, exits 0 on every path | `chmod +x` confirmed, file exists, `bash -n` syntax check passes |
| A2 | recommendation-check warns on slip case | `tests/test_stop_hooks.py::test_recommendation_check_warns_on_question_without_recommendation` GREEN |
| A3 | recommendation-check silent on clean case | `test_recommendation_check_silent_with_recommendation_line` GREEN |
| A4 | `tests/fixtures/fail-loud-check.sh` exists, exec bit set, exits 0 on every path | same as A1 |
| A5 | fail-loud warns on slip case | `test_fail_loud_warns_on_completed_without_verification` GREEN |
| A6 | fail-loud silent on clean case | `test_fail_loud_silent_with_verification_phrase` GREEN |
| A7 | Both hooks registered in user-global `~/.claude/settings.json` Stop array | manual verification — B1 splices + commits a settings.json snapshot to `tests/fixtures/settings-stop-hooks-snapshot.json` for drift detection |
| A8 | Drift-detection test passes | `test_drift_detection` diffs `tests/fixtures/<name>.sh` vs `~/.claude/hooks/<name>.sh`, GREEN |
| A9 | Full suite no regressions | `pytest tests/ -v` GREEN, no other test broken |
| A10 | Live behavior verified — open a fresh AH1 session, intentionally write a Director-facing reply with options + no Recommendation; hook should warn in early system context | Manual smoke test, B1 documents in PR description |

## Sequencing

1. `cd ~/bm-b1 && git fetch origin main && git checkout main && git pull --ff-only`. Confirm HEAD `1aa778e` or newer.
2. Branch: `git checkout -b b1/stop-hooks-recommendation-and-fail-loud-1`.
3. Write `tests/fixtures/recommendation-check.sh` (~30 LOC) + `tests/fixtures/fail-loud-check.sh` (~30 LOC). Reference: `tests/fixtures/session-start-bus-drain.sh` for the hook contract pattern (`_emit` helper, JSON envelope, `cat >/dev/null` stdin drain on no-op paths).
4. Write `tests/test_stop_hooks.py` — pytest with the 8 cases above.
5. `pytest tests/test_stop_hooks.py -v` GREEN.
6. `pytest tests/ -v` GREEN (no regressions).
7. `chmod +x tests/fixtures/recommendation-check.sh tests/fixtures/fail-loud-check.sh`.
8. Pre-merge cp: `cp tests/fixtures/recommendation-check.sh ~/.claude/hooks/recommendation-check.sh && cp tests/fixtures/fail-loud-check.sh ~/.claude/hooks/fail-loud-check.sh`. Run drift-detection test locally to confirm.
9. Splice both hooks into `~/.claude/settings.json` Stop array via `jq` (NOT raw edit — preserve existing keys). Save snapshot to `tests/fixtures/settings-stop-hooks-snapshot.json`.
10. A10 manual smoke test — open a fresh AH1 session in another terminal, write a sample Director-facing message, confirm hook output appears.
11. Open PR to baker-master `main`. Title: `feat(hooks): Stop hooks for recommendation enforcement + fail-loud claim verification (STOP_HOOKS_RECOMMENDATION_AND_FAIL_LOUD_1)`.
12. Ship via bus to /msg/lead with brief PR summary + commit SHA + literal pytest output. NO fenced PL paste-block (Rule retired 2026-05-11 per `feedback_no_pl_ship_report_paste_block.md`). NO wake-paste at end of dispatch (Rule 0.5 retired 2026-05-11 per `feedback_no_wake_paste_b_code_dispatch.md`).

## Critical do-NOTs

- Do NOT make either hook BLOCKING on first build. Both warn-only. Director will flip to blocking later if compliance still erodes.
- Do NOT exceed 4s wall time per hook (Claude Code hook timeout). Keep regex checks simple; skip transcript walk if file >10MB (degrade gracefully).
- Do NOT crash or non-zero exit. Every path exits 0. Errors emit short status to additionalContext, not stderr-blocking.
- Do NOT splice settings.json with raw text edit — use `jq` to preserve other keys (Forge, bus-drain, future hooks).
- Do NOT touch `~/.claude/hooks/session-start-bus-drain.sh` — separate hook, separate fixture, separate concern.
- Do NOT add the hooks to `bm-b<N>/.claude/settings.json` — user-global only. Picker scopes don't carry hooks today.

## Anchor

- Director directive 2026-05-11 ~15:30Z "go ahead" + "Send to B code build whenever you're ready. By bus."
- Mnilax X article: `https://x.com/Mnilax/status/2053116311132155938` (30-codebase 6-week test, 41% → 3% mistake rate with rule + hook combo)
- Recommendation slip incident: today's Q8 codex-judge surfacing where Q5/Q6/Q7 had defaults but Q8 dropped the recommendation; Director caught it
- Fail-loud framing: project CLAUDE.md §"ENGINEERING RULES" added today (commit `1aa778e`)
- Bus-drain hook reference pattern: `tests/fixtures/session-start-bus-drain.sh` + `~/.claude/hooks/session-start-bus-drain.sh` (drift-detection precedent)

— AH1 (lead, AH1-Terminal)

---

## Prior CODE_1 task (archive reference)

BRIEF_PLAUD_TRIGGER_FIX_1 — COMPLETE 2026-05-07. PR #168 merged 2026-05-07 ~07:20Z. 5-patch fix for Plaud transcripts arriving as header-only DB shells (silent failure since 2026-04-17). Ship report: `briefs/_reports/B1_plaud_trigger_fix_1_20260507.md`.
