---
brief_id: LOCAL_WAKE_DAEMON_HTTP_PIVOT_1
reporter: b1
report_date: 2026-05-25
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/38
branch: b1/brisen-lab-local-wake-daemon-http-pivot-1
base: main
commit: 0179599
status: SHIPPED
reply_target: cowork-ah1
---

# B1 ship report — LOCAL_WAKE_DAEMON_HTTP_PIVOT_1

## Summary

Single PR against `vallen300-bit/brisen-lab`. 6-file change (4 new, 2 modified, +342/-15):

**New** under `tools/wake-daemon/`:
- `wake-daemon.py` — stdlib `http.server` on `127.0.0.1:8765`. CORS allowlist literal `https://brisen-lab.onrender.com`. Alias validated by regex `^[A-Za-z0-9_-]{1,32}$` AND `ALLOWED_ALIASES` set membership (14 known slugs). Subprocess uses argv list (no shell), 5s timeout, structured logging.
- `com.baker.wake-daemon.plist` — launchd user agent, `RunAtLoad=true`, `KeepAlive` on crash only, `ThrottleInterval=10s`, stdout/stderr to `~/.brisen-lab/`.
- `install.sh` — idempotent. Copies daemon to `~/.brisen-lab/wake-daemon.py`, plist to `~/Library/LaunchAgents/`, bootout-then-bootstrap to user GUI domain, polls `/healthz` up to 10s.
- `README.md` — install, verify, uninstall, architecture diagram, security notes.

**Modified**:
- `static/app.js` — replaced anchor-click dispatch block with `dispatchWake(alias)` calling `fetch(WAKE_DAEMON_URL?alias=...)`. Added `showWakeToast()` (XSS-safe via `textContent`, inline styles, click-to-dismiss, 8s auto-hide).
- `static/index.html` — `app.js?v=16` → `app.js?v=17`.

Existing `tools/wake-handler/*` AppleScript + Brisen Lab Wake.app untouched. Daemon shells out via `open` so Launch Services still routes to the registered handler app.

## Quality checkpoints

### QC1 — python syntax

```
$ python3 -c "import py_compile; py_compile.compile('tools/wake-daemon/wake-daemon.py', doraise=True)"
OK
```

PASS.

### QC2 — plist lint

```
$ plutil -lint tools/wake-daemon/com.baker.wake-daemon.plist
tools/wake-daemon/com.baker.wake-daemon.plist: OK
```

PASS.

### QC3 — install.sh end-to-end

```
$ bash tools/wake-daemon/install.sh
Installed: /Users/dimitry/.brisen-lab/wake-daemon.py
Launchd: gui/501/com.baker.wake-daemon

Polling /healthz...
Daemon healthy after 2s.
```

PASS.

### QC4 — launchctl state

```
$ launchctl print "gui/$(id -u)/com.baker.wake-daemon" | grep -E "state|exit code|program"
	state = running
	program = /usr/bin/python3
	last exit code = (never exited)
```

PASS.

### QC5 — healthz

```
$ curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool
{
    "ok": true,
    "daemon": "brisen-lab-wake",
    "port": 8765
}
```

PASS.

### QC6 — live wake b4

```
$ curl -s "http://127.0.0.1:8765/wake?alias=b4" | python3 -m json.tool
{
    "ok": true,
    "alias": "b4"
}

$ stat -f "%Sm %N" /tmp/brisen-lab-wake-b4.command
May 25 10:59:52 2026 /tmp/brisen-lab-wake-b4.command

$ tail -1 ~/.brisen-lab/wake-daemon.stdout.log
2026-05-25 10:59:51,066 wake-daemon INFO dispatched alias=b4
```

PASS — daemon dispatched, `/tmp` file fresh, handler app fired.

### QC7 — bad alias rejection

```
$ curl -s -w "\nHTTP %{http_code}\n" "http://127.0.0.1:8765/wake?alias=../etc/passwd"
{"ok": false, "error": "invalid alias"}
HTTP 400
```

PASS.

### QC8 — CORS preflight

```
$ curl -s -X OPTIONS -H "Origin: https://brisen-lab.onrender.com" \
    -H "Access-Control-Request-Method: GET" -I http://127.0.0.1:8765/wake
Access-Control-Allow-Origin: https://brisen-lab.onrender.com
Access-Control-Allow-Methods: GET, OPTIONS
Access-Control-Allow-Headers: Content-Type
Access-Control-Max-Age: 86400
```

PASS.

### QC9 — anchor-click block removed

```
$ grep -c 'brisen-lab://' static/app.js
0
```

PASS.

### QC10 — fetch path present

```
$ grep -c 'WAKE_DAEMON_URL\|dispatchWake' static/app.js
4
```

PASS (≥2 required).

### QC11 — cache-bust

```
$ grep 'app.js?v=' static/index.html
  <script src="/static/app.js?v=17"></script>
```

PASS.

### QC12-14 — Director Chrome smoke

Deferred to Director post-merge. Steps in PR description.

## Artefacts

- PR: https://github.com/vallen300-bit/brisen-lab/pull/38
- Branch: `b1/brisen-lab-local-wake-daemon-http-pivot-1` @ `0179599`
- Base: `main` @ `1781096` (PR #37 squash)
- Daemon already installed + running on B1's local Mac (Director's machine): `launchctl print gui/501/com.baker.wake-daemon` shows state=running.

## Gate chain (handing off)

- Gate-1 architecture: deputy (AH2)
- Gate-2 `/security-review`: deputy (AH2) — daemon has alias injection surface + CORS + binding-host invariants to verify
- Gate-3 picker-architect: SKIP (no picker/symlink changes)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2)
- Gate-5 merge: cowork-ah1

## Notes

- Local daemon is already running on Director's Mac (B1 ran install.sh as part of QC3). After PR merge + cache-bust pickup, Director's Chrome `fetch()` will reach the live daemon. No additional install step required from Director — unless he wants to re-run from the merged tree.
- Subprocess `open` call is argv-list (no shell). Combined with double-layered alias validation (regex + whitelist), injection surface is closed.
- Mixed-content (HTTPS dashboard → HTTP localhost) is W3C-spec-allowed for `127.0.0.1` in Chrome, Safari, Firefox.
- Failure toast is the load-bearing piece against silent-failure accumulation (the antipattern that bit us on the Chrome custom-scheme path). When daemon is down, Director sees a red bottom-right toast on click, not silence.
