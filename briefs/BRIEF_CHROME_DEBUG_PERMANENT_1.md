---
brief: BRIEF_CHROME_DEBUG_PERMANENT_1
trigger_class: LOW
tier: B
target_files:
  - ~/Library/LaunchAgents/com.baker.chrome-debug.plist (NEW; user-private, not in repo)
  - ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/chrome-bridge.md (MODIFY)
  - ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md (MODIFY — index pointer only)
authored_by: AI Head B
created: 2026-05-02
companion_pr: none (no baker-master code change; user-side macOS config)
lane_recommendation: B3
retires_p4: chrome.brisen-infra.com / Cloudflare bridge — Dennis-flagged 2026-05-02 as 502/parked. NOT this brief's scope; this brief retires only the local-9222-auto-start half of that P4.
---

# BRIEF_CHROME_DEBUG_PERMANENT_1 — make local debug-Chrome (port 9222) auto-start at login

## Why

Code-side terminals (AH1, AH2, B1–B5) drive Chrome via Chrome MCP, which connects to `127.0.0.1:9222`. Today (2026-05-02) Director and AH-B discovered the debug port is NOT auto-started — first Code session of the day hits "Could not connect to Chrome" and has to manually relaunch via `open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir=~/.chrome-debug-profile`. This evaporates at next reboot.

The infrastructure pieces (Chrome profile + launch script) **already exist** from 2026-03-23 (`BROWSER-AGENT-1` Phase 1). What's missing is the **macOS LaunchAgent** that wraps the launch script as an auto-start service. The `memory/chrome-bridge.md` file (last updated 2026-03-26) claims the LaunchAgent exists at `com.baker.chrome-debug.plist`. **It does not.** This brief retires that gap.

This is a prerequisite for: Tier 4 of any future research brief (Grok Heavy via browser-drive — proven path 2026-05-02), Cowork-extension fallback when extension is unavailable, and any future Code-side browser automation (logged-in service scraping, dashboard verification, screenshot capture).

**Out of scope (parked P4):** Cloudflare tunnel `chrome.brisen-infra.com` → MacBook:9223 → chrome-proxy.py → 9222 chain. Dennis flagged 2026-05-02 as 502/broken; that path was Render-side Baker reaching MacBook Chrome and is **not** what this brief restores. If Director wants Render-side restoration, that's a separate brief.

Tier B / LOW. No API surface, no auth surface, no DB writes. macOS LaunchAgent (1 plist file) + 2 memory file edits.

## What already exists (do NOT recreate)

| Path | State |
|---|---|
| `~/.chrome-debug-profile/` | Persistent Chrome profile dir, populated 2026-03-23. Holds logged-in cookies for Grok Heavy (added 2026-05-02), Baker dashboard, WhatsApp Web, Gmail (vallen300), Dropbox, Cloudflare. **Do not touch contents.** |
| `~/.chrome-debug-profile/launch-chrome-debug.sh` | Executable, idempotent: checks `curl 127.0.0.1:9222` first; if up, exits 0; else `pkill -f "Google Chrome"` + relaunch with `--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins="*" --user-data-dir=~/.chrome-debug-profile`. **Do not modify; this brief wraps it.** |
| `~/.chrome-debug-profile/chrome-proxy.py` | Cloudflare-side Host-header rewriter. PARKED P4. Not touched by this brief. |

## Scope (do exactly this — 3 files)

### File 1 — `~/Library/LaunchAgents/com.baker.chrome-debug.plist` (NEW)

Plain macOS LaunchAgent plist. Runs the existing launch script at user login and after crash (NOT after user-initiated quit).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.baker.chrome-debug</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/dimitry/.chrome-debug-profile/launch-chrome-debug.sh</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>/Users/dimitry/.chrome-debug-profile/launchd.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/dimitry/.chrome-debug-profile/launchd.stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
```

**Key choices and why:**

- `RunAtLoad: true` — fires at user login (launchd loads user agents at GUI session start).
- `KeepAlive` is a dict, NOT a bool: `SuccessfulExit=false` + `Crashed=true` means launchd relaunches Chrome ONLY on crash. If user does `Cmd+Q`, launchd treats that as `SuccessfulExit=true` and does NOT relaunch (respects user intent). If Chrome crashes, launchd brings it back. This is the "respect manual quit" pattern — without it, KeepAlive=true would defeat Director's ability to quit Chrome ever.
- `ThrottleInterval: 30` — minimum 30s between relaunches. Prevents launchd from busy-looping if Chrome crashes immediately at start.
- `StandardOutPath` / `StandardErrorPath` — debug logs land next to the profile, easy to inspect when something goes wrong.
- `EnvironmentVariables.PATH` — launchd processes inherit a minimal PATH that misses `/opt/homebrew/bin`. Even though the launch script uses absolute path for Chrome, future edits or `which curl` calls should resolve. Defensive.
- **No `--remote-allow-origins` change needed** — already set in the launch script (line 19).

### File 2 — `memory/chrome-bridge.md` (MODIFY)

Path: `/Users/dimitry/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/chrome-bridge.md`

Replace the entire current file (currently 26 lines, last meaningful update 2026-03-26) with the following content. Keep the typed-memory frontmatter shape; this is a `reference` memory.

```markdown
---
name: Chrome debug bridge — local 9222 + parked Cloudflare tunnel
description: Local debug-Chrome stack on port 9222 (auto-started via LaunchAgent). Cloudflare bridge to Render is parked P4 (502 since pre-2026-05-02).
type: reference
---

# Chrome Bridge — current state (verified 2026-05-02)

## What works (used by Code-side Chrome MCP)

```
Code-side terminal (AH1/AH2/B1–B5) → Chrome MCP → 127.0.0.1:9222 → Chrome (debug profile)
```

- **Profile**: `/Users/dimitry/.chrome-debug-profile` — persistent, Grok Heavy + Baker dashboard + WhatsApp Web + Gmail + Dropbox + Cloudflare logins.
- **Launch script**: `/Users/dimitry/.chrome-debug-profile/launch-chrome-debug.sh` — idempotent; checks `curl 127.0.0.1:9222` first.
- **LaunchAgent**: `~/Library/LaunchAgents/com.baker.chrome-debug.plist` — runs launch script at login + relaunches on crash. Installed via `BRIEF_CHROME_DEBUG_PERMANENT_1` (PR-less; user-side config).
- **Logs**: `/Users/dimitry/.chrome-debug-profile/launchd.stdout.log` + `.stderr.log`.

### Manual control
- **Reload after plist edit**: `launchctl unload ~/Library/LaunchAgents/com.baker.chrome-debug.plist && launchctl load ~/Library/LaunchAgents/com.baker.chrome-debug.plist`
- **Stop / start without unload**: `launchctl stop com.baker.chrome-debug` / `launchctl start com.baker.chrome-debug`
- **Verify loaded**: `launchctl list | grep com.baker.chrome-debug`
- **Verify port live**: `curl -s http://127.0.0.1:9222/json/version`

### Adding a new logged-in service to the profile
1. Director: open the debug Chrome window (already running via LaunchAgent — find it in dock; it's the one with `--user-data-dir=~/.chrome-debug-profile`).
2. Navigate to the service, log in normally, complete any 2FA.
3. Cookie persists in the profile dir; future Code sessions can drive it via Chrome MCP.

## What's parked (P4 — Cloudflare bridge to Render)

```
Render Baker → HTTPS → chrome.brisen-infra.com → Cloudflare Named Tunnel → MacBook:9223 → chrome-proxy.py → Chrome:9222
```

- Status: **502 / broken** since pre-2026-05-02 (Dennis flagged in chat). Replaced functionally by Ollama (`ollama.brisen-infra.com`) for Baker's RAG path.
- Components still on disk (do NOT touch — restoration brief if needed):
  - `/Users/dimitry/.chrome-debug-profile/chrome-proxy.py` — Host-header rewrite + WebSocket passthrough on port 9223.
  - `~/.cloudflared/config.yml` — ingress rule for `chrome.brisen-infra.com → localhost:9223`.
  - Cloudflare named tunnel `baker-chrome-bridge` (ID: `e877040a-3207-4d1b-aa5c-1f843a7e2759`).
  - Render env var `CHROME_BROWSER_URL=https://chrome.brisen-infra.com` (still set; reads-as-broken).
- LaunchAgent for the Cloudflare tunnel (`com.baker.cloudflared` or `com.baker.cloudflare-tunnel`): may or may not exist. Verify before relying.

## Key gotchas (2026-03 → 2026-05 lessons)

- `--user-data-dir` is required — Chrome 146+ silently refuses debug port on the default user profile (security guard). DevToolsActivePort gets written but no TCP listener binds. Symptom seen 2026-05-02 before this brief shipped.
- `--remote-allow-origins="*"` is required — Chrome 146+ blocks WebSocket connections from non-default origins without it. Set in launch script.
- `--remote-debugging-address=0.0.0.0` (in launch script) lets the chrome-proxy.py rewrite reach Chrome; harmless when only localhost MCP is used.
- Chrome rejects non-localhost `Host:` headers on the debug port — that's why `chrome-proxy.py` exists in the parked Cloudflare path. NOT a problem for direct localhost MCP.
- Launch debug Chrome **before** starting Claude Code only matters on first install / if LaunchAgent failed. Once the LaunchAgent is loaded, port 9222 is live by login.
- TCC permissions: launchd-spawned Chrome runs without GUI parent context; if Chrome ever needs Files-and-Folders permission for a TCC-protected dir, Director must grant manually (System Settings → Privacy & Security → Files and Folders → Google Chrome). Lesson #43 from `tasks/lessons.md`.
```

### File 3 — `memory/MEMORY.md` (MODIFY — single-line correction in the existing index)

Path: `/Users/dimitry/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md`

Find this exact line (currently around line 56 in `## Local Infrastructure (Director's MacBook)` block):

```
- **Chrome debug**: LaunchAgent at `~/Library/LaunchAgents/com.baker.chrome-debug.plist` (port 9222).
```

Replace with:

```
- **Chrome debug**: LaunchAgent `com.baker.chrome-debug` at `~/Library/LaunchAgents/com.baker.chrome-debug.plist` runs `~/.chrome-debug-profile/launch-chrome-debug.sh` at login. Profile preserves Grok Heavy + Baker + WhatsApp Web + Gmail logins. Detail: `chrome-bridge.md`. Cloudflare tunnel half (`chrome.brisen-infra.com`) is parked P4 — local 9222 is the supported path.
```

This stays an index entry (one line, ~150 char-ish — the old line was misleading; this one points at chrome-bridge.md for detail and flags the Cloudflare half as parked).

**Do not write content blocks into MEMORY.md** (rule from `CLAUDE.md`: it's an index, detail goes in typed files). The detail belongs in `chrome-bridge.md` per File 2 above.

## Verification (B3 runs these; pastes output into PR-less completion report)

```bash
# 1. Plist file installed at correct path
ls -l ~/Library/LaunchAgents/com.baker.chrome-debug.plist

# 2. Plist syntax valid (plutil exits 0)
plutil -lint ~/Library/LaunchAgents/com.baker.chrome-debug.plist

# 3. LaunchAgent loaded
launchctl list | grep com.baker.chrome-debug
# Expected: PID Status Label  — PID is a positive integer, Status is 0 (success).

# 4. Port 9222 alive
curl -s http://127.0.0.1:9222/json/version | head -c 200
# Expected: JSON with "Browser": "Chrome/<version>"

# 5. Reload cycle (proxy for reboot)
launchctl unload ~/Library/LaunchAgents/com.baker.chrome-debug.plist
sleep 3
launchctl load ~/Library/LaunchAgents/com.baker.chrome-debug.plist
sleep 8
curl -s http://127.0.0.1:9222/json/version | head -c 200
# Expected: same JSON. Chrome restarted automatically; port live within ~8s of load.

# 6. Memory files updated
grep -c "com.baker.chrome-debug" ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md
# Expected: 1
grep -c "parked P4" ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/chrome-bridge.md
# Expected: at least 1
```

**Director-side verification (manual, after B3 completes):** at next reboot or logout/login, within ~30s of desktop appearing, run `curl http://127.0.0.1:9222/json/version` from terminal. Expected: JSON. If empty → check `~/.chrome-debug-profile/launchd.stderr.log`.

## Files Modified
- NEW: `~/Library/LaunchAgents/com.baker.chrome-debug.plist`
- MODIFY: `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/chrome-bridge.md` (rewrite with current 2026-05-02 state)
- MODIFY: `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md` (one-line correction in existing index)

## Do NOT Touch
- `~/.chrome-debug-profile/launch-chrome-debug.sh` — works as-is; brief just wraps it.
- `~/.chrome-debug-profile/chrome-proxy.py` — Cloudflare bridge piece, parked P4.
- `~/.chrome-debug-profile/` profile contents (cookies, settings) — preserves logged-in sessions.
- `~/.cloudflared/` — Cloudflare tunnel config, parked P4.
- Render env var `CHROME_BROWSER_URL` — leave as is (the broken-readback is the indicator P4 is parked).
- Any baker-master code (no API/MCP/dashboard changes; this is user-side macOS config).
- `tasks/lessons.md` existing entries (append-only).
- baker-master commit history (this brief produces no PR; user-side files only).

## Quality Checkpoints

1. `plutil -lint` exits 0 on the new plist (syntax-valid).
2. `launchctl list | grep com.baker.chrome-debug` shows the agent loaded with PID > 0 and Status 0.
3. `curl http://127.0.0.1:9222/json/version` returns JSON within 8s of `launchctl load`.
4. After `launchctl unload && launchctl load` cycle, port comes back live within 8s (proxy for reboot survival).
5. After `Cmd+Q` on Chrome, launchd does NOT immediately relaunch (verify by `ps aux | grep "remote-debugging-port=9222"` shows no Chrome). KeepAlive correctly distinguishes user quit from crash.
6. After manually `kill -9 <chrome-pid>` (simulated crash), launchd DOES relaunch within `ThrottleInterval` (30s).
7. `~/.chrome-debug-profile/launchd.stdout.log` is created on first run and shows "Chrome debug started on port 9222" or "Chrome debug already running on port 9222".
8. Memory files: `chrome-bridge.md` has the new content (frontmatter `type: reference` + parked-P4 section); `MEMORY.md` line corrected and points at `chrome-bridge.md`.
9. Director-side reboot test (manual, by Director, not B3): port 9222 alive within 30s of next login. Pasted curl output into PR-less completion report closes the loop.

## Risks / known-edge-cases

- **TCC / Files-and-Folders permission for Chrome.** If launchd-spawned Chrome ever tries to read a TCC-protected dir (`~/Desktop`, `~/Documents`, `~/Downloads`) and is blocked, the symptom is Chrome silently failing at startup. The `~/.chrome-debug-profile` dir is in `~`, NOT TCC-protected, so this should not fire — but if `launchd.stderr.log` shows "Operation not permitted" in the early phase, Director must grant Files-and-Folders to Google Chrome in System Settings, then `launchctl kickstart -k gui/$(id -u)/com.baker.chrome-debug`. Reference: `tasks/lessons.md` Lesson #43.
- **Stale Chrome process from a non-LaunchAgent launch (e.g., Director double-clicks the Chrome dock icon for everyday browsing).** The launch script's `pkill -f "Google Chrome"` would kill that everyday Chrome too if the script is invoked while everyday Chrome is running. Mitigation: launch script's `curl 127.0.0.1:9222` check exits 0 if any process (debug or not) has 9222 bound — so if everyday Chrome happens to start with 9222 bound (unlikely on first launch in a `--user-data-dir`-free profile), no relaunch. **Best-effort only.** Director should run the everyday browser as the *non-debug* Chrome (the one without `--user-data-dir=~/.chrome-debug-profile`). Two icons in dock — known intentional split, mentioned in chat 2026-05-02.
- **Port 9222 in use by another tool.** If something else binds 9222 first (no known case), Chrome fails to bind; `launchd.stderr.log` shows the failure. Director picks a different port and updates plist + launch script + memory.
- **Chrome auto-update.** Chrome auto-updates can briefly invalidate the running process; KeepAlive=Crashed handles this within ThrottleInterval.

## Anti-patterns explicitly avoided (lessons.md cross-checks)

- **Already-implemented brief** (Lesson: TRAVEL_DB_PRIMARY was 100% done): explicitly listed pieces that already exist (launch script + profile dir) so B3 doesn't recreate them.
- **Brief premises that reference Mac-Mini-disk-only state are unverifiable from the repo** (Lesson #40): this brief's premises are user-side MacBook state. **Pre-merge verification is the §Verification block above** — B3 runs the commands and pastes output into the completion report; AH1 reads the output before declaring done. Lives outside the repo intentionally (no merge gate exists for user-side files).
- **TCC blocks launchd binaries from Desktop** (Lesson #43): explicitly called out in §Risks — Director-side prerequisite if `launchd.stderr.log` shows "Operation not permitted."

## Reporting

This brief produces NO PR (user-side macOS config files; nothing in repo). On completion, B3 writes:
- `briefs/_reports/B3_chrome_debug_permanent_1_20260502.md` with:
  - All 6 verification command outputs pasted (copy-paste from terminal).
  - Confirmation that the plist file exists, loads, and port comes back after unload/load cycle.
  - Note any TCC prompts encountered (none expected, but document if seen).
  - Summary line: "PORT 9222 LIVE; LAUNCHAGENT LOADED; MEMORY UPDATED" or specific failure.

Then AH1 (or AH2 if AH1 redirects) reads the report, accepts, and closes the dispatch ticket. Director's reboot test is the final acceptance — Director pings AH-A on next reboot.
