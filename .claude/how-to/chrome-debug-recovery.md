---
name: chrome-debug-port-9222-recovery
description: How to recover Chrome debug port 9222 when Chrome MCP can't connect. Auto-starts at login via LaunchAgent, but Cmd+Q on the debug window kills it until next login.
when_to_use: Chrome MCP returns "Could not connect to Chrome" / `curl http://127.0.0.1:9222/json/version` returns empty / debug Chrome window was closed.
---

# Chrome debug port 9222 — recovery

**Setup:** LaunchAgent `com.baker.chrome-debug` (installed 2026-05-02 via `BRIEF_CHROME_DEBUG_PERMANENT_1`) auto-starts debug Chrome on port 9222 at every login + relaunches on crash. Profile dir: `~/.chrome-debug-profile/` (holds Grok Heavy + Baker dashboard + WhatsApp Web + Gmail + Dropbox logins). Detail: `memory/chrome-bridge.md`.

## Diagnose first — is it actually down?

```bash
curl -s http://127.0.0.1:9222/json/version | head -c 100
```

- Returns `{"Browser": "Chrome/...", ...}` → port is live, problem is elsewhere (MCP config, network, etc.).
- Returns empty → port is dead, follow recovery below.

## Recovery — pick by symptom

### Case 1: Director Cmd+Q'd the debug Chrome (most common)

The plist's `KeepAlive` is `{SuccessfulExit: false, Crashed: true}` — launchd respects user-initiated quit and does NOT relaunch. By design (otherwise Chrome would be impossible to ever quit).

**Fix (no reboot):**
```bash
launchctl kickstart -k gui/$(id -u)/com.baker.chrome-debug
```

Then re-verify with the curl above. Should be live within 8s.

### Case 2: LaunchAgent unloaded / disappeared

```bash
launchctl list | grep com.baker.chrome-debug
```

- Empty output → agent unloaded. Reload:
  ```bash
  launchctl load ~/Library/LaunchAgents/com.baker.chrome-debug.plist
  ```
- Shows agent but Status column is non-zero → check stderr log:
  ```bash
  tail -50 ~/.chrome-debug-profile/launchd.stderr.log
  ```

### Case 3: Plist file missing

```bash
ls -l ~/Library/LaunchAgents/com.baker.chrome-debug.plist
```

If missing, the brief needs re-running. Body of the plist is verbatim in `briefs/BRIEF_CHROME_DEBUG_PERMANENT_1.md` §Scope File 1. Re-create with that content, then `launchctl load ...`.

### Case 4: TCC / Files-and-Folders permission blocked Chrome

Symptom: `launchd.stderr.log` shows "Operation not permitted".

Director-side fix only: System Settings → Privacy & Security → Files and Folders → grant Google Chrome. Then `launchctl kickstart -k gui/$(id -u)/com.baker.chrome-debug`.

### Case 5: Port 9222 bound by something else

Rare. Check:
```bash
lsof -i :9222
```

If a non-Chrome process holds it, kill that process or pick a different port and update plist + launch script + memory.

## What NOT to do

- Don't `pkill -f "Google Chrome"` blindly — kills your everyday Chrome too if running.
- Don't manually `open -na "Google Chrome" --args --remote-debugging-port=9222 ...` — the LaunchAgent already wraps the launch script; double-launching can confuse port binding. Use `launchctl kickstart` instead.
- Don't edit `~/.chrome-debug-profile/launch-chrome-debug.sh` — works as-is from BROWSER-AGENT-1 (Mar 2026). The brief explicitly leaves it alone.
- Don't touch `~/.chrome-debug-profile/chrome-proxy.py` or `~/.cloudflared/` — Cloudflare bridge half (`chrome.brisen-infra.com`) is parked P4 (502/broken). Local 9222 is the supported path.

## Two Chrome icons in dock — known split

Debug Chrome (with `--user-data-dir=~/.chrome-debug-profile`) is a **separate** process from everyday Chrome. Don't Cmd+Q the debug one for normal browsing. If unsure which is which:
```bash
ps aux | grep "remote-debugging-port=9222"
```

The PID with that flag is the debug Chrome.

## Final acceptance test (after any recovery)

```bash
curl -s http://127.0.0.1:9222/json/version | head -c 100
```

Expected: `{"Browser": "Chrome/147...", ...}` within 8s. If still dead after kickstart, escalate to AH and check `launchd.stderr.log`.

## Provenance

- 2026-05-02 — LaunchAgent installed via `BRIEF_CHROME_DEBUG_PERMANENT_1` (Tier B, no PR, user-side macOS config). Ship report: `briefs/_reports/B3_chrome_debug_permanent_1_20260502.md`.
- 2026-05-02 — Director reboot test passed; port 9222 returned Chrome/147 JSON within login window.
- Pre-2026-03-23 infrastructure (profile dir + launch script) from `BROWSER-AGENT-1` Phase 1.
