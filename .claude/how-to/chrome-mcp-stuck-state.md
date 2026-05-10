---
name: chrome-mcp-stuck-state
description: Recover when chrome-devtools-mcp returns "The selected page has been closed" on every call (including list_pages). Bug is in Google's npm package, not Brisen infra; workaround is to end + restart the Claude Code session.
when_to_use: `mcp__chrome__*` returns "The selected page has been closed. Call list_pages to see open pages." on every call AND `list_pages` itself returns the same error. Confirm Chrome is alive separately before assuming MCP-layer bug.
---

# Chrome MCP server stuck state — recovery

**Sibling:** `chrome-debug-recovery.md` covers Chrome itself (port 9222, LaunchAgent). This file covers the MCP-server layer on top.

## What the bug is

`chrome-devtools-mcp` (Google's npm package, configured in `~/.claude.json` as `chrome` MCP) caches an internal `selectedPage` reference. When that page is closed (Chrome reap, external close, navigation), the package validates the stale pointer **before** executing the call — so even `list_pages` (whose job is recovery) fails the validation. The MCP wedges until the child process dies.

Each Claude Code session spawns its **own** `chrome-devtools-mcp` child via stdio. There is **no** central MCP server, **no** launchd supervision (only Chrome itself is supervised by `com.baker.chrome-debug`).

## Diagnose — two-step smoke test

```bash
# Step 1 — Chrome alive on port 9222?
curl -s http://127.0.0.1:9222/json/version | head -c 100
```

```
# Step 2 — MCP wedged?
mcp__chrome__list_pages
```

| Step 1 | Step 2 | Diagnosis |
|---|---|---|
| `{"Browser":"Chrome/...",...}` | page list returned | All good. Proceed. |
| `{"Browser":"Chrome/...",...}` | `"selected page has been closed"` | **MCP-layer wedge.** Restart session (below). |
| empty | n/a | Chrome itself down. Follow `chrome-debug-recovery.md`. |

Don't loop retries on wedged MCP — the cache won't clear without process restart.

## Recovery — restart the Code session

The MCP child process dies with its parent Claude Code session. So:

1. End the current Claude Code session (close the window / Ctrl+C the CLI).
2. Start a new session via the same picker folder (e.g., `~/Vallen Dropbox/Dimitry vallen/bm-aihead1/`).
3. New session → new `chrome-devtools-mcp` child → fresh selectedPage state.

That's it. No `launchctl`, no `pkill`, no `npm` command. ~30 seconds.

## Why not other approaches

- **`pkill chrome-devtools-mcp`** — would kill ALL sessions' MCP children indiscriminately. Don't.
- **`/mcp` slash command** — disconnect/reconnect untested for this bug; assume restart works, save the spelunking.
- **Patch the npm package locally** — third-party code, not ours to fork. Upstream-Google bug filing is parked low-priority (workaround is cheap).

## Zombie-process note

`ps aux | grep chrome-devtools-mcp | grep -v grep` will often show many processes — one set per past Code session. Most are harmless zombies; macOS GC eventually reaps. Don't kill manually unless port-binding issues surface.

## Provenance

- 2026-05-10 — bug surfaced when AID-T hit it on Director's openclaw X.com lookup; AID-T dispatched to AH1 via paste-block at `~/Vallen Dropbox/Dimitry vallen/_01_INBOX_FROM_CLAUDE/2026-05-10-chrome-mcp-stuck-state-dispatch-to-ah1.md`.
- AH1 diagnosis: `~/.claude.json` chrome MCP config inspected; 14 zombie `chrome-devtools-mcp` processes confirmed; Chrome itself healthy via curl on port 9222.
- AID-T deferred validation `project_pending_chrome_validation.md` closed by this finding (Chrome supervision works; MCP-layer wedge is the residual bug).
