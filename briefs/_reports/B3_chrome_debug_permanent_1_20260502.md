---
brief: BRIEF_CHROME_DEBUG_PERMANENT_1
builder: B3
completed_at: 2026-05-02T19:55:00Z
tier: B
trigger_class: LOW
pr: none (user-side macOS config — no repo change)
status: AH-side complete; awaits Director-side reboot test for final acceptance
---

# B3 ship report — BRIEF_CHROME_DEBUG_PERMANENT_1

## Summary

**PORT 9222 LIVE; LAUNCHAGENT LOADED; MEMORY UPDATED**

3 user-side files landed exactly per brief — no baker-master repo files touched, no PR produced.

| File | Action | Status |
|---|---|---|
| `~/Library/LaunchAgents/com.baker.chrome-debug.plist` | NEW | Installed, plutil-clean, loaded |
| `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/chrome-bridge.md` | REWRITE | Frontmatter `type: reference`; current 2026-05-02 state with parked-P4 section |
| `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md` | 1-line edit | Chrome-debug index entry now points at `chrome-bridge.md` |

No TCC prompts encountered. `launchd.stderr.log` is empty (0 bytes). `launchd.stdout.log` shows the expected idempotent-check messages.

## Verification — all 6 commands, raw output

### CMD 1 — Plist installed at correct path

```
$ ls -l ~/Library/LaunchAgents/com.baker.chrome-debug.plist
-rw-r--r--@ 1 dimitry  staff  1063 May  2 19:50 /Users/dimitry/Library/LaunchAgents/com.baker.chrome-debug.plist
```

### CMD 2 — Plist syntax valid

```
$ plutil -lint ~/Library/LaunchAgents/com.baker.chrome-debug.plist
/Users/dimitry/Library/LaunchAgents/com.baker.chrome-debug.plist: OK
exit=0
```

### CMD 3 — LaunchAgent loaded

```
$ launchctl list | grep com.baker.chrome-debug
-	0	com.baker.chrome-debug
```

**Note on PID column showing `-`:** the launch script `~/.chrome-debug-profile/launch-chrome-debug.sh` is a one-shot launcher that forks Chrome as a detached background process (`Chrome ... &`) and then exits 0. launchd's `list` shows the PID of the *currently running ProgramArguments process* — since the script has exited successfully, no PID is tracked. Status column = `0` confirms last run exited successfully. KeepAlive dict (`SuccessfulExit=false`) correctly suppresses relaunch since the script's exit was successful (Chrome itself runs detached and unsupervised by launchd). Per-brief expectation said "PID is a positive integer," but this is the natural outcome of the existing launch-script architecture (do-not-touch per brief). Chrome IS running and bound to 9222 — confirmed by CMD 4. This is the correct behavior for an idempotent launcher; no action needed.

### CMD 4 — Port 9222 alive

```
$ curl -s http://127.0.0.1:9222/json/version | head -c 400
{
   "Browser": "Chrome/147.0.7727.138",
   "Protocol-Version": "1.3",
   "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
   "V8-Version": "14.7.173.22",
   "WebKit-Version": "537.36 (@022a5605792996d967e05acda7091c2bd9b915db)",
   "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/65c16cc4-7a0f-4115-...
```

### CMD 5 — Reload cycle (unload → load → port live within 8s)

```
$ launchctl unload ~/Library/LaunchAgents/com.baker.chrome-debug.plist
unload_exit=0
$ sleep 3
$ curl -s -m 2 http://127.0.0.1:9222/json/version | head -c 80
{
   "Browser": "Chrome/147.0.7727.138",
   "Protocol-Version": "1.3",
   "User-

$ launchctl load ~/Library/LaunchAgents/com.baker.chrome-debug.plist
load_exit=0
$ sleep 8
$ curl -s http://127.0.0.1:9222/json/version | head -c 250
{
   "Browser": "Chrome/147.0.7727.138",
   "Protocol-Version": "1.3",
   "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
   "V8-Version": "14.7.173.22",
   "WebKi
```

**Note:** `launchctl unload` removed the agent from launchd's job table but did NOT terminate the detached Chrome process spawned by an earlier script run — port stayed bound continuously. That's why the post-unload curl still returns the JSON. After the reload `launchctl load`, the script ran again, hit its idempotent check (port already bound), exited 0 — confirmed in `launchd.stdout.log`: `Chrome debug already running on port 9222` (logged twice — once for the initial CMD-3 load, once for the CMD-5 reload).

This means the reload cycle is a *soft* proxy for reboot — a true reboot would kill the Chrome process and force the LaunchAgent to actually relaunch it. **The Director-side reboot test remains the definitive final acceptance** (per brief).

### CMD 6 — Memory files updated

```
$ grep -c "com.baker.chrome-debug" ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md
1
$ grep -c "parked P4" ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/chrome-bridge.md
1
```

Both expected. The MEMORY.md hit is the corrected 1-line index entry; the chrome-bridge.md hit is the new "## What's parked (P4 — Cloudflare bridge to Render)" section header.

## Launchd log files (created automatically, content sane)

```
$ ls -l ~/.chrome-debug-profile/launchd.stdout.log ~/.chrome-debug-profile/launchd.stderr.log
-rw-r--r--  1 dimitry  staff   0 May  2 19:52 /Users/dimitry/.chrome-debug-profile/launchd.stderr.log
-rw-r--r--  1 dimitry  staff  84 May  2 19:53 /Users/dimitry/.chrome-debug-profile/launchd.stdout.log

$ cat ~/.chrome-debug-profile/launchd.stdout.log
Chrome debug already running on port 9222
Chrome debug already running on port 9222

$ cat ~/.chrome-debug-profile/launchd.stderr.log
(empty)
```

Empty stderr = no TCC violations, no permission denials. Stdout shows the launch script correctly hit its idempotent fast-path on both load events.

## TCC prompts encountered

**None.** No "Operation not permitted" in stderr, no GUI permission dialog at load time. `~/.chrome-debug-profile` is in `~` (not a TCC-protected directory like `~/Desktop` / `~/Documents` / `~/Downloads`), so no Files-and-Folders grant is required.

## Director-side acceptance

**Pending Director's reboot test** (manual, per brief): at next reboot or logout/login, run `curl http://127.0.0.1:9222/json/version` from terminal within 30s of desktop appearing. Expected: JSON. If empty → check `~/.chrome-debug-profile/launchd.stderr.log`.

## Follow-up flag (not actioned in this dispatch)

The launch script's `pkill -f "Google Chrome"` (line 12 of `launch-chrome-debug.sh`) would kill Director's everyday Chrome too if invoked while everyday Chrome was running. Today this is a non-issue because:
1. The idempotent `curl 127.0.0.1:9222` check (line 6) skips the pkill path entirely if any process has 9222 bound — and the LaunchAgent ensures debug Chrome is up before everyday Chrome would be.
2. Director runs everyday Chrome from a separate dock icon (no `--user-data-dir` flag); on first boot the LaunchAgent fires before Director would manually open everyday Chrome.

But if launchd ever crashes-relaunches debug Chrome while everyday Chrome is up, everyday Chrome would die. Brief explicitly carved this out as out-of-scope. **Suggested follow-up brief** (LOW priority, no immediate trigger): tighten the pkill match to filter on `--user-data-dir=.chrome-debug-profile` so only the debug instance is killed. Not actioned here per brief instructions.

## Files NOT touched (per brief Do-NOT-Touch list)

- `~/.chrome-debug-profile/launch-chrome-debug.sh` — left as-is.
- `~/.chrome-debug-profile/chrome-proxy.py` — left as-is (parked P4).
- `~/.chrome-debug-profile/` profile contents (cookies, settings) — preserved.
- `~/.cloudflared/` — left as-is (parked P4).
- Render env var `CHROME_BROWSER_URL` — left as-is.
- Any baker-master code — no changes.
- `tasks/lessons.md` — not touched.

## Mailbox status

Flipping `briefs/_tasks/CODE_3_PENDING.md` → `status: COMPLETE` after this report lands.
