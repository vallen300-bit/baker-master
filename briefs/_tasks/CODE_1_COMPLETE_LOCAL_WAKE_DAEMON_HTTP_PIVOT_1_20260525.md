---
dispatch: LOCAL_WAKE_DAEMON_HTTP_PIVOT_1
to: b1
from: cowork-ah1
dispatched_by: cowork-ah1
status: COMPLETE
shipped_at: 2026-05-25T09:05:00Z
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/38
ship_report: briefs/_reports/B1_LOCAL_WAKE_DAEMON_HTTP_PIVOT_1_20260525.md
authored: 2026-05-25
brief_path: /Users/dimitry/baker-vault/_ops/briefs/BRIEF_LOCAL_WAKE_DAEMON_HTTP_PIVOT_1.md
target_repo: brisen-lab (vallen300-bit/brisen-lab)
estimated_time: 4-6h
complexity: Low-Medium
---

# B1 dispatch — LOCAL_WAKE_DAEMON_HTTP_PIVOT_1

## What

Pivot click-to-wake dispatch from browser custom-URL-scheme → fetch to local Python HTTP daemon → `open` shell command. Bypasses Chrome's `protocol_handler.allowed_origin_protocol_pairs` allowlist that silently blocks `brisen-lab://` from `brisen-lab.onrender.com`. Existing wake-handler AppleScript untouched.

## Where

Full brief: `/Users/dimitry/baker-vault/_ops/briefs/BRIEF_LOCAL_WAKE_DAEMON_HTTP_PIVOT_1.md`

Read it end-to-end before starting. 6 Fix/Features. ~50-line Python HTTP server + launchd plist + install script + ~10-line frontend swap + cache-bust + failure toast.

## How

1. Branch off latest `main` in `~/brisen-lab-staging/` (or wherever your brisen-lab clone lives): `b1/brisen-lab-local-wake-daemon-http-pivot-1`.
2. Author 14 Quality Checkpoints worth of test evidence per brief §Quality Checkpoints (lines named QC1-14 in the brief).
3. Open PR to vallen300-bit/brisen-lab.
4. Bus-post cowork-ah1 with `ship/local-wake-daemon-http-pivot-1` topic; cowork-ah1 dispatches deputy for Gates 1+2+4, merges Gate-5 on PASS.
5. Ship report at `briefs/_reports/B1_LOCAL_WAKE_DAEMON_HTTP_PIVOT_1_<YYYYMMDD>.md`.

## Constraints (load-bearing)

- **Daemon binds to `127.0.0.1` only.** Never `0.0.0.0`. Security.
- **CORS allowlist origin literal `https://brisen-lab.onrender.com`** — no wildcard.
- **Alias validation: regex AND whitelist.** Double-layered injection defense.
- **stdlib-only Python.** No `pip install` deps. Use `http.server`.
- **Wake-handler AppleScript untouched.** Daemon invokes via `open brisen-lab://wake/<alias>` — Launch Services still routes to the existing handler app.
- **Toast on fetch failure.** Anti-pattern: silent failure accumulation. Director must see when the daemon is down.

## Reply target

`dispatched_by: cowork-ah1` — bus reports route back to cowork-ah1, not lead.

— cowork-ah1
