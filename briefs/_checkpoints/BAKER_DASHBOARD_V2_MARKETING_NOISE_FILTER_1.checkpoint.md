---
brief_id: BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1
worker: b3
attempt: 0
status: in_gates
updated_by: b3 (refresh — post G2 F1 rework)
updated_at: 2026-06-24
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
- PR: **#420** @ `ba91f1f` (G2 F1 rework commit; original ship was `f8ad631`).
- Status: **G2 F1 fixed, awaiting G2-light re-verify (deputy-codex) + G3 (deputy)**.
  Gate chain: G2 → G3 deputy → G4 lead /security-review → merge.
- Code state: 2 files additive. `kbl/bridge/alerts_to_signal.py` — `STOPLIST_MARKETING_PATTERNS`
  folded into `_STOPLIST_RE`. The reservation pattern is now **sender-bound**
  (`r"\bMOVIE Reservations\b.*\bupcoming stay\b"`), NOT subject-bound — G2 F1 fix so the
  real human reply (alert id=25645, sergey0569@gmail.com) is not over-filtered.
  `tests/test_bridge_stop_list_additions.py` — 5 marketing-drop positives + 7 matter-signal
  pass-through guards (incl. sergey0569 negative regression). 79 pass; guards hold.

## 4. Last bus message IDs / ack state
- Dispatch (lead→b3): #4195. Ship (b3→lead): #4196 (acked by lead, #4199).
- Rollover enforce (lead→b3): #4199 (acked). G2 REQUEST_CHANGES (lead→b3): #4202 (acked).
- G2-light re-request (b3→deputy-codex): #4203. G3 ping (b3→deputy): #4204.
- Watch topic for verdicts: `gate-*/baker-dashboard-v2-marketing-noise-filter-1`.

## 5. Exact next command (for a respawned b3)
```
cd ~/bm-b3 && git checkout b3/baker-dashboard-v2-marketing-noise-filter-1 && git pull
# Read bus for any REQUEST_CHANGES on topic gate-*/baker-dashboard-v2-marketing-noise-filter-1.
# If a gate REQUESTED_CHANGES: apply the named fix, re-run
#   pytest tests/test_bridge_stop_list_additions.py tests/test_bridge_alerts_to_signal.py -v
#   then push (NEW commit, never amend) + re-request the gate on the bus.
# If no open changes: idle — deliverable shipped @ ba91f1f, await lead merge. Do NOT re-implement.
```
