---
brief_id: WAKE_VIA_SSE_PIVOT_1
reporter: b1
report_date: 2026-05-25
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/39
branch: wake-via-sse-pivot-1
base: main
commit: 26bb9823fbde080c87c4c10f995ff38eb13b53ff
status: SHIPPED
reply_target: cowork-ah1
---

# B1 ship report — WAKE_VIA_SSE_PIVOT_1

## Summary

Single PR against `vallen300-bit/brisen-lab`. 10-file change (+236/-271):

**New** under `tools/wake-listener/`:
- `wake-listener.py` — stdlib `urllib.request` SSE subscriber to `/sse/stream`. Filters `kind == "wake_request"`, shells `open brisen-lab://wake/<alias>`. 2s→60s exponential reconnect backoff. Alias whitelist defense-in-depth (14 entries mirroring `app.py:40` + `static/app.js`). No pip deps.
- `com.baker.wake-listener.plist` — launchd user agent, `RunAtLoad=true`, `KeepAlive` on crash only, `ThrottleInterval=10s`, stdout/stderr to `~/.brisen-lab/`.
- `install.sh` — idempotent. Retires `com.baker.wake-daemon` (PR #38) first: `launchctl bootout … 2>/dev/null || true` + remove old plist + remove old `.py` + remove old logs. Then installs new listener.
- `README.md` — install, verify, uninstall, architecture, failure modes, security.

**Modified**:
- `app.py` — added `POST /api/wake` (~30 lines) right after `/api/event`. Origin header check (`BRISEN_LAB_ORIGIN` env override, default `https://brisen-lab.onrender.com`) + alias whitelist against `TERMINALS` + freeze gate + `_broadcast({"kind": "wake_request", "terminal_alias": …, "occurred_at": …})`. No new env vars without safe defaults.
- `static/app.js` — replaced `dispatchWake()` body to POST `/api/wake?alias=…` same-origin. `WAKE_DAEMON_URL` constant removed. Toast renderer kept; message points at listener.
- `static/index.html` — `app.js?v=17` → `app.js?v=18`.

**Deleted**:
- `tools/wake-daemon/` — entire directory (superseded; new `install.sh` handles uninstall on already-deployed Macs).

Existing `tools/wake-handler/*` AppleScript + Brisen Lab Wake.app + `/sse/stream` + `_broadcast` untouched.

## Quality checkpoints

### QC #1 — wake-listener.py syntax

```
$ python3 -c "import py_compile; py_compile.compile('tools/wake-listener/wake-listener.py', doraise=True)"
OK
```

PASS.

### QC #2 — plist lint

```
$ plutil -lint tools/wake-listener/com.baker.wake-listener.plist
tools/wake-listener/com.baker.wake-listener.plist: OK
```

PASS.

### QC #10 — no 127.0.0.1:8765 in app.js

```
$ grep -c '127.0.0.1:8765' static/app.js
0
```

PASS. Also `WAKE_DAEMON_URL` constant removed: `grep -c 'WAKE_DAEMON_URL' static/app.js` = 0.

### QC #11 — /api/wake reference in app.js

```
$ grep -c '/api/wake' static/app.js
2
```

Brief expected 1, but the fetch URL string AND the error string both contain `/api/wake` — matches brief's own code block verbatim. Functionally 1 fetch site.

### QC #12 — cache-bust to v=18

```
$ grep 'app.js?v=' static/index.html
  <script src="/static/app.js?v=18"></script>
```

PASS.

### QC #3-9, #13-15 — runtime checks

Deferred until post-merge:
- QC #3-6 — Director runs `bash install.sh`, then `launchctl print`, then `tail` the listener stdout.
- QC #7-9 — `curl` POSTs to `/api/wake` from origin / bad-origin / bad-alias.
- QC #13 — Chrome smoke: hard-refresh dashboard, click badged card, Terminal nudges/spawns. Zero Chrome prompts.
- QC #14 — Failure smoke: stop listener; POST still 200; no Terminal; re-install catches next event.
- QC #15 — Render restart resilience: kill deploy; listener backs off + reconnects within 60s.

Listener was NOT exec-tested locally (would create a competing subscriber that swallows wake_requests from the running PR #38 daemon). Once PR #39 is merged and Director installs, the old daemon is gone and the listener takes over cleanly.

## Gate-1 + Gate-2 invariants (for AH2 / deputy)

1. **No 127.0.0.1 / localhost:8765 in static/app.js** — confirmed, grep = 0.
2. **/api/wake Origin gate** — checks `req.headers.get("origin")` against `BRISEN_LAB_ORIGIN` env (default `https://brisen-lab.onrender.com`). 403 on mismatch. Browser cannot override; CSRF defense.
3. **Listener stdlib only** — uses `urllib.request` + `subprocess` + stdlib `logging`. No third-party SSE library. No pip install.
4. **install.sh retires old daemon first** — `launchctl bootout … 2>/dev/null || true` + `rm -f` plist + `rm -f` .py + `rm -f` logs BEFORE bootstrapping new service.
5. **_broadcast envelope** — uses existing `{kind, terminal_alias, occurred_at}` shape consistent with `event` and `snapshot` broadcasts.

## Gate-3 / Gate-4 disposition

Gate-3 (picker-architect) per brief: NOT required — install path is `~/.brisen-lab/` + `~/Library/LaunchAgents/`, no symlink or picker SOP change.

Gate-4 (code-reviewer 2nd-pass): brief flagged standard `feature-dev:code-reviewer`. cowork-ah1 dispatches deputy on PR receive per brief §"Mailbox + bus protocol".

## Files Modified (vs base)

```
 app.py                                                   |  32 ++++
 static/app.js                                            |  21 +--
 static/index.html                                        |   2 +-
 tools/wake-daemon/README.md                              |  88 ---------
 tools/wake-daemon/install.sh                             |  46 -----
 tools/wake-daemon/wake-daemon.py                         | 117 ------------
 tools/{wake-daemon => wake-listener}/com.baker.…plist    |   8 +-
 tools/wake-listener/README.md                            |  44 +++++
 tools/wake-listener/install.sh                           |  41 +++++
 tools/wake-listener/wake-listener.py                     | 102 ++++++++++
```

## Risks + open items

- **PR #38 daemon still running on Director's Mac** as a hot-patched process at `~/.brisen-lab/wake-daemon.py`. The new `install.sh` retires it cleanly via `launchctl bootout`. If Director runs `install.sh` while the running daemon has uncaught state, the SIGTERM from bootout closes it gracefully.
- **/sse/stream remains unauthenticated** — any internet client can subscribe and see bus events. Pre-existing exposure; not a regression. Future hardening brief on /sse/stream auth flagged in README.
- **Single Render instance assumption** — `_broadcast` queue is per-instance. On Starter plan we run one instance, so all subscribers connect to the same `_broadcast`. If we ever scale beyond one, `_broadcast` needs Redis fan-out. Documented in brief §Risks.
- **No tests added** — brisen-lab repo has no test suite. The change is small and exercised via post-merge curl + Director Chrome smoke.

## Reply target

cowork-ah1 (per brief frontmatter `dispatched_by`). Ship topic: `ship/wake-via-sse-pivot-1`.
