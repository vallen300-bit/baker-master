---
dispatch: AID_WAKE_BACKFILL_1
to: b2
from: lead
dispatched_by: lead
status: SHIPPED
dispatched_at: 2026-05-26T09:15:00Z
shipped_at: 2026-05-26T14:19Z
authored: 2026-05-26
target_repo: brisen-lab
pr: https://github.com/vallen300-bit/brisen-lab/pull/44
branch: b2/aid-wake-backfill-1
commit: a718dcae560853c4b65da9c60635b9d3f2b3be9f
ship_bus_msg: 1172
ship_report: briefs/_reports/B2_AID_WAKE_BACKFILL_1_SHIP_20260526.md
estimated_time: 20 min
complexity: trivial
reply_to: lead
priority: tier-a
anchor_incident: bus #1163 deputy AID_ON_BUS_1 post-merge defects 1+2
sop_anchor: /Users/dimitry/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md
---

# B2 dispatch — AID_WAKE_BACKFILL_1

## Context

AID_ON_BUS_1 install (brisen-lab PR #41 + baker-vault PR #115, merged 2026-05-26) shipped through the 13-row install SOP but missed two non-SOP slug-lists in the brisen-lab repo. Deputy surfaced via bus #1163 after Director clicked the AID card on the dashboard 3 times and the click failed 3 distinct ways. Deputy applied both fixes locally on Director's MacBook; this brief upstreams the canonical patches.

## Scope

Two-file patch in brisen-lab. NO app.py / bus.py / static/* changes — those were correctly wired in PR #41.

### AC1 — wake-handler.applescript cwdForAlias backfill

File: `tools/wake-handler/wake-handler.applescript`

Current state (lines 41-57): `on cwdForAlias(a)` has 14 if-then entries (lead through hag-filer) but MISSING `aid`. Add the following line AFTER the `researcher` line (line 50), BEFORE the `CM-1` line (line 51), mirroring the `fnMap` order in `on open location`:

```applescript
    if a is "aid" then return "/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-aidennis-t"
```

**Rationale:** AID's live workspace is the legacy `bm-aidennis-t` Dropbox dir, NOT the SOP-default `~/bm-aid` (which is an empty placeholder). Director re-pointed locally and ratified the Dropbox path 2026-05-26 (#1163). The path contains spaces — AppleScript handles unquoted string literals correctly here; just use the path verbatim.

**Anchor comment** above the function (lines 38-40) already says "Keep in sync with fnMap in `on open location` when adding agents." — that comment IS the spec; PR #41 violated it.

### AC2 — wake-listener.py ALLOWED_ALIASES backfill

File: `tools/wake-listener/wake-listener.py`

Current state (lines 23-29): `ALLOWED_ALIASES` set has 14 slugs MISSING `aid`. Add `"aid",` to the third entry line (where `hag-desk, researcher` currently live) for consistency. Final state:

```python
ALLOWED_ALIASES = {
    "lead", "cowork-ah1", "deputy",
    "b1", "b2", "b3", "b4",
    "hag-desk", "researcher", "aid",
    "CM-1", "CM-2", "CM-3", "CM-4",
    "hag-filer",
}
```

**Rationale:** wake-listener filters SSE wake_request events by this allowlist; without `aid`, every wake fires `"ignored wake_request for unknown alias=aid"` (seen in `~/.brisen-lab/wake-listener.stdout.log`) and the click never reaches Wake.app. Deputy patched the deployed copy at `~/.brisen-lab/wake-listener.py:23` locally; canonical mirror in repo also needs it.

**Anchor comment** (lines 21-22): "Mirror app.py:40 TERMINALS list AND static/app.js:9 TERMINALS list. Update all three when adding agents." — this allowlist is the third hardcoded slug-list. PR #41 covered the first two; this is the third miss.

### AC3 — Syntax-only gate (no unit tests cover these files)

Both files lack pytest coverage. Use literal output of these two commands as the gate:

```bash
cd ~/bm-b2/brisen-lab
python3 -c "import py_compile; py_compile.compile('tools/wake-listener/wake-listener.py', doraise=True)" && echo "wake-listener: compile-clean"
osacompile -o /tmp/wake-handler-check-$(date +%s).scpt tools/wake-handler/wake-handler.applescript && echo "wake-handler: compile-clean"
```

Paste BOTH literal stdout/stderr lines into PR description. NO "compile by inspection."

### AC4 — PR open

- Branch: `b2/aid-wake-backfill-1`
- Title: `AID_WAKE_BACKFILL_1: backfill aid in wake-handler cwdForAlias + wake-listener allowlist`
- Body MUST reference:
  - (a) anchor bus #1163 deputy dispatch
  - (b) defects 1+2 from AID_ON_BUS_1 post-merge
  - (c) literal AC3 compile output
  - (d) note that defect 3 (picker path realignment) is local-only and codified in baker-vault SOP separately by AH1
- Base: `main`
- Target reviewer: deputy (cross-lane gate per autonomy charter)

## Out of scope

- baker-vault SOP update (AH1 handles directly — Row 13 split + Row 14 + foot-gun + AC additions, separate commit).
- Mac Mini wake-listener mirror (AH1 verifies post-PR-merge whether Mac Mini runs the listener).
- `~/bm-aid` placeholder cleanup (deferred per #1163 closing line).
- Tests: do NOT add pytest unit tests for these files in this PR — out of scope. Fast-follow can add coverage later if Director ratifies.

## Files Modified
- `tools/wake-handler/wake-handler.applescript` — one new if-then line in cwdForAlias.
- `tools/wake-listener/wake-listener.py` — one new entry in ALLOWED_ALIASES.

## Do NOT Touch
- `app.py`, `bus.py`, `static/index.html`, `static/app.js` — already correctly wired for `aid` in PR #41.
- `on open location` fnMap — already correctly wired for `aid` in PR #41 (line 136).
- Any test files — out of scope per AC3.

## Ship gate

REQUEST_CHANGES if AC3 output is not literal compile-clean output. NO "compile by inspection."

## Reply target

Bus-post to `lead` on PR open + on ship-report. Topic: `ship/aid-wake-backfill-1`.

## Anchor

Director ratified action stack via "go" in chat 2026-05-26 ~09:10Z. Deputy dispatch bus #1163 anchored the 3 defects + local fixes. PR canonicalizes defects 1+2; defect 3 (existing-workspace-path pre-flight) codified in SOP by AH1.
