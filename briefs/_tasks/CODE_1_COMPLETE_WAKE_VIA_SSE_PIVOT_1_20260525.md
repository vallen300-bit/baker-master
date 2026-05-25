---
dispatch: WAKE_VIA_SSE_PIVOT_1
to: b1
from: cowork-ah1
dispatched_by: cowork-ah1
status: COMPLETE
shipped_at: 2026-05-25T13:30:00Z
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/39
ship_report: briefs/_reports/B1_WAKE_VIA_SSE_PIVOT_1_20260525.md
authored: 2026-05-25
brief_path: /Users/dimitry/baker-vault/_ops/briefs/BRIEF_WAKE_VIA_SSE_PIVOT_1.md
target_repo: brisen-lab (vallen300-bit/brisen-lab)
estimated_time: 3-4h
complexity: Low-Medium
---

# B1 dispatch — WAKE_VIA_SSE_PIVOT_1 (pivot #3 on click-to-wake)

## What

Drop PR #38's localhost HTTP daemon entirely. New path: dashboard click → POST `/api/wake` to Brisen Lab on Render (same-origin) → server calls existing `_broadcast({"kind": "wake_request", "terminal_alias": alias, ...})` → existing `/sse/stream` propagates → new local Python listener subscribed via `urllib.request` catches it → shells out to `open brisen-lab://wake/<alias>`.

Wake-handler AppleScript stays untouched (third time). Existing `_broadcast`/`/sse/stream` infrastructure stays untouched.

## Where

Full brief: `/Users/dimitry/baker-vault/_ops/briefs/BRIEF_WAKE_VIA_SSE_PIVOT_1.md`

Read it end-to-end before starting. 6 Fix/Features, 15 Quality Checkpoints.

## Why this is the last pivot

Three pivots in 36h (PR #34, #36, #37, #38). Each one addressed a real defect surfaced by the previous one. The current PR #38 daemon hangs on browser fetch even after a hot-patch to `ThreadingHTTPServer` + HTTP/1.1 + PNA + `Connection: close` (the patched daemon is currently running on Director's Mac at `~/.brisen-lab/wake-daemon.py`). The HTTPS-page → localhost dispatch path is structurally fragile — every Chrome version tightens it. Same-origin POST to Render is the most stable web primitive that exists; if it breaks, the rest of the dashboard breaks first.

## Constraints (load-bearing)

- **Same-origin POST.** No CORS, no PNA, no mixed content. Just `fetch('/api/wake?alias=...', {method: 'POST'})`.
- **Origin header check on server.** Browser auto-sets it; cross-origin attackers can't override via fetch. Defense-in-depth: alias must be in TERMINALS whitelist.
- **stdlib-only listener.** No `pip install`. `urllib.request` for SSE subscription.
- **Listener auto-reconnects** with 2s→60s exponential backoff. Render restart should be transparent.
- **install.sh retires old wake-daemon** (PR #38) before installing wake-listener. `launchctl bootout … 2>/dev/null || true` + remove old plist + remove old .py + remove old logs.
- **Wake-handler AppleScript untouched.** Listener invokes via `open brisen-lab://wake/<alias>` — same as the PR #38 daemon did.
- **Toast renderer kept** but message updated to point at listener (not daemon).

## Reply target

`dispatched_by: cowork-ah1` — bus reports route back to cowork-ah1, not lead.

— cowork-ah1
