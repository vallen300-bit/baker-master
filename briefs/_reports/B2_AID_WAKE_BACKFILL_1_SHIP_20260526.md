---
dispatch: AID_WAKE_BACKFILL_1
to: b2
from: lead
shipped_by: b2
shipped_at: 2026-05-26T14:19Z
status: SHIPPED — awaiting deputy review + merge
target_repo: brisen-lab
pr: https://github.com/vallen300-bit/brisen-lab/pull/44
branch: b2/aid-wake-backfill-1
commit: a718dcae560853c4b65da9c60635b9d3f2b3be9f
ship_bus_msg: 1172
brief: /Users/dimitry/baker-vault/_ops/briefs/BRIEF_AID_WAKE_BACKFILL_1.md
anchor_incident: bus #1163 deputy AID_ON_BUS_1 post-merge defects 1+2
reply_target: lead
---

# B2 ship report — AID_WAKE_BACKFILL_1

## Outcome

PR https://github.com/vallen300-bit/brisen-lab/pull/44 open against `main`, branch `b2/aid-wake-backfill-1`, commit `a718dca`. Two-file backfill closing defects 1+2 from AID_ON_BUS_1 post-merge.

## Files modified

| File | Change |
|------|--------|
| `tools/wake-handler/wake-handler.applescript` | +1 line in `cwdForAlias` — `aid` → `~/Vallen Dropbox/Dimitry vallen/bm-aidennis-t` |
| `tools/wake-listener/wake-listener.py` | `"aid"` added to `ALLOWED_ALIASES` set |

Total diff: 2 insertions, 1 deletion.

## AC3 gate — literal output

```
wake-listener: compile-clean
wake-handler: compile-clean
```

(Captured from the exact AC3 commands; no "by inspection.")

## Bus posts

- #1172 — `ship/aid-wake-backfill-1` to `lead` at 2026-05-26T14:19:36Z.

## Out of scope (respected)

- `app.py` / `bus.py` / `static/*` / fnMap untouched (already wired in PR #41).
- No pytest added (out of scope per brief AC3).
- Baker-vault SOP update left to AH1.
- Mac Mini wake-listener mirror left to AH1 post-merge verification.
- `~/bm-aid` placeholder cleanup deferred.

## Gate chain remaining

1. ~~b2 self-test (compile gate) → PR open~~ ✅
2. Deputy (cross-lane) static review — pending.
3. `/security-review` (deputy or lead).
4. Lead merge on PASS / PASS-WITH-NITS.

## Anchor

Director directive 2026-05-26 ~09:10Z "go"; deputy bus #1163 surfaced defects + applied local fixes; this PR canonicalizes defects 1+2. Defect 3 (picker path realignment + pre-flight) codified separately by AH1 in baker-vault SOP.
