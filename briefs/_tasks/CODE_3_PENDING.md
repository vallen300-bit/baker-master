---
status: OPEN
brief: briefs/BRIEF_CHROME_DEBUG_PERMANENT_1.md
trigger_class: LOW
dispatched_at: 2026-05-02T19:30:00Z
dispatched_by: ai-head-b
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
pr: null
autopoll_eligible: false
notes: User-side macOS config dispatch — produces NO PR. Completion = ship_report file at briefs/_reports/B3_chrome_debug_permanent_1_20260502.md with all 6 verification command outputs pasted, then mailbox flips to COMPLETE.
---

# CODE_3 — DISPATCH (BRIEF_CHROME_DEBUG_PERMANENT_1)

**Status:** OPEN — 2026-05-02T19:30Z by AI Head B (overwrites prior CODE_3 closure on TERMINAL_AUTO_ONBOARD_1 / PR #149 merged 2026-05-02)
**Brief:** `briefs/BRIEF_CHROME_DEBUG_PERMANENT_1.md` (LOW, ~30 min, Tier B)
**Builder:** B3
**Branch:** N/A — no baker-master code change. User-side macOS config only.
**Tier:** **Tier B** — autonomous merge / completion on green per `_ops/processes/ai-head-autonomy-charter.md` §3
**autopoll_eligible:** false — paste-block dispatch; cold-start required

## Why this exists

Today (2026-05-02) Director and AH-B discovered debug Chrome on port 9222 is NOT auto-started. First Code session of the day hits "Could not connect to Chrome" until a manual `pkill + open -na` cycle re-binds the port. Manual fix evaporates at next reboot. Memory file `chrome-bridge.md` claims a LaunchAgent already exists at `com.baker.chrome-debug.plist` — it doesn't (verified 2026-05-02). This brief retires that gap.

Infrastructure pieces (Chrome profile + idempotent launch script) **already exist** from BROWSER-AGENT-1 (Mar 2026). What's missing is the macOS LaunchAgent wrapper. **B3 must NOT recreate the launch script or profile dir** — see brief's "What already exists" table.

Cloudflare bridge half (`chrome.brisen-infra.com`) is **out of scope** — Dennis flagged 2026-05-02 as parked P4 (502/broken). Brief explicitly carves it out.

## Task summary

3 user-side files (NO repo files modified):

1. **NEW**: `~/Library/LaunchAgents/com.baker.chrome-debug.plist` — macOS LaunchAgent. Plist body provided verbatim in brief §Scope File 1. RunAtLoad + KeepAlive-on-crash-only (respects Cmd+Q via `SuccessfulExit=false`).
2. **MODIFY**: `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/chrome-bridge.md` — full-file rewrite to current 2026-05-02 verified state. Body provided verbatim in brief §Scope File 2.
3. **MODIFY**: `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md` — single-line correction of the "Chrome debug" line in `## Local Infrastructure` block. Old/new line provided in brief §Scope File 3.

**Critical: do NOT touch:**
- `~/.chrome-debug-profile/launch-chrome-debug.sh` — works as-is.
- `~/.chrome-debug-profile/chrome-proxy.py` — Cloudflare bridge piece, parked P4.
- `~/.chrome-debug-profile/` profile contents (cookies, settings).
- `~/.cloudflared/` — parked P4.
- Render env var `CHROME_BROWSER_URL`.
- Any baker-master code (no API/MCP/dashboard changes).
- `tasks/lessons.md` existing entries (append-only).

## Verification (run all 6 commands, paste exact output into ship_report)

See brief §Verification — 6 commands covering: plist installed, plist syntax-valid, agent loaded, port live, unload/load cycle, memory files updated.

**Director-side reboot test** is the FINAL acceptance — Director will manually verify port 9222 alive within 30s of next login. Ship_report closes the AH-side loop; reboot test closes the Director-side loop.

## Reporting

This dispatch produces NO PR (user-side files only).

On completion, B3 writes `briefs/_reports/B3_chrome_debug_permanent_1_20260502.md` containing:

- All 6 verification command outputs pasted verbatim from terminal.
- Confirmation that plist file exists, loads with PID > 0, port 9222 returns JSON within 8s of `launchctl load`.
- Note any TCC prompts encountered (none expected).
- Summary line: `PORT 9222 LIVE; LAUNCHAGENT LOADED; MEMORY UPDATED` or specific failure mode.

Then this mailbox flips to `status: COMPLETE`. AH1 or AH2 reads the report and accepts.

## Blocker policy

If TCC blocks Chrome at launchd-spawn time (Lesson #43 — `launchd.stderr.log` shows "Operation not permitted"), STOP and surface in `blocker_question` field. Director-side System Settings grant required (Files-and-Folders → Google Chrome). Do not attempt workaround; just flag.

If anything else surprising surfaces (e.g., `pkill -f "Google Chrome"` in launch script kills Director's everyday Chrome during a KeepAlive relaunch), document in ship_report's "follow-up" section and propose a follow-up brief tightening the pkill match. Do not modify launch script in this dispatch.
