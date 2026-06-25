---
brief_id: BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1
worker: b3
attempt: 0
status: merged_done
updated_by: lead (arc closed — PR #420 merged @ 5266d9b, deploy live)
updated_at: 2026-06-25
---

# ROLLOVER CHECKPOINT — BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1

> No-bloat rollover is ENFORCED for this unattended arc (Director 2026-06-24).
> B3 does NOT compact. At ≥70% context after a milestone, or ~60–90 min unattended,
> REFRESH this file (bump `attempt:`, update the 5 fields + exact next command),
> `git add` + commit + push, then `scripts/respawn-request.sh`. At ≥85% the Stop
> hook hard-blocks — checkpoint, push, request respawn, exit. **Claim = the
> `attempt:` bump commit, not a bus ack.** A fresh session loads ONLY the 5 fields
> below — never old thread history.

## 1. Current brief
`briefs/_tasks/BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1.md` (full spec) +
`briefs/_tasks/CODE_3_PENDING.md` (dispatch envelope).

## 2. Checkpoint
This file (`briefs/_checkpoints/BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1.checkpoint.md`).

## 3. Branch / PR / status
- Branch: `b3/baker-dashboard-v2-marketing-noise-filter-1`
- PR: **#420** @ `da71f83` (G3 rework). Prior: `f8ad631` ship, `ba91f1f` G2 F1 fix.
- Status: **G3 rework applied, awaiting G2-light re-verify (deputy-codex) + G3-spot (deputy), then G4 lead /security-review + merge**.
- Code state (3 changes, all in `kbl/bridge/alerts_to_signal.py` + `tests/test_bridge_stop_list_additions.py`):
  - F1 institutional-sender: removed `no-reply` / `do-not-reply` / `notifications@` from
    `STOPLIST_MARKETING_PATTERNS`; kept `mailer-daemon` / `bounce@` / `newsletter@` / `marketing@`.
    Accepted under-filter (E+H `noreply-eh@` digest passes); court `notifications@gericht.at` passes.
  - F2 promo: `% off` requires a commerce context word ≤40 chars; `use code` requires a real code
    token matched CASE-SENSITIVELY via scoped `(?-i:[\x27"A-Z0-9]{3,})` (lead #4210 approved — his
    literal matched lowercase prose under the parent `re.IGNORECASE`). Reservation pattern stays
    sender-bound (`MOVIE Reservations`...`upcoming stay`).
  - Scope-extension (lead #4210 Option A): pre-existing `STOPLIST_TITLE_PATTERNS` `% off` decomposed
    into `\bsale\b` + `\b% discount\b` + contextual `% off` so `8% off asking price on Balgerstrasse`
    (live MRCI matter) passes. ONLY that one pre-existing line touched.
  - Gate conditions verified: `8% off asking price`→False; `MEGA SALE 50% off everything` /
    `FLIKISTART50` / `TAKEITOUTSIDE` / `sale 50% off` all stay True. **82 passed**; py_compile clean.

## 4. Last bus message IDs / ack state
- Dispatch #4195 (acked). Ship #4196 → lead (acked, #4199). Rollover #4199 (acked).
- G2 REQUEST_CHANGES #4202 (acked) → fixed @ ba91f1f. G2-light PASS #4205 (acked).
- G3 PASS-with-findings + HOLD #4208 (acked). Escalation (b3→lead) #4209. Lead decision #4210 (acked).
- G3 rework re-requests: G2-light (b3→deputy-codex) #4211; G3-spot (b3→deputy) #4212.
- Watch topic for verdicts: `gate-*/baker-dashboard-v2-marketing-noise-filter-1`.

## 5. Exact next command (for a respawned b3)
```
cd ~/bm-b3 && git checkout b3/baker-dashboard-v2-marketing-noise-filter-1 && git pull
# Read bus for verdicts on topic gate-*/baker-dashboard-v2-marketing-noise-filter-1.
# If a gate REQUESTED_CHANGES: apply the named fix, re-run
#   pytest tests/test_bridge_stop_list_additions.py tests/test_bridge_alerts_to_signal.py -v
#   then push (NEW commit, never amend) + re-request the gate on the bus.
# If all gates PASS: idle — deliverable shipped @ da71f83, await lead G4 + merge. Do NOT re-implement.
```
