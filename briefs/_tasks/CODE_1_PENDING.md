---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_COWORK_AH1_VISIBILITY_1.md
brief_id: BRISEN_LAB_COWORK_AH1_VISIBILITY_1
target_branch: b1/brisen-lab-cowork-ah1-visibility-1
target_repo: brisen-lab (NOT baker-master) — work in ~/bm-b1-brisen-lab or fresh clone of https://github.com/vallen300-bit/brisen-lab
matter_slug: baker-internal
cross_matter_usage: [all-matter-desks]
dispatched_at: 2026-05-18T09:15:00Z
dispatched_by: lead
director_auth: 2026-05-18 chat — "start working on the items" (carry-over from PINNED §R, brief drafted 2026-05-17)
trigger_class: LOW (single-array additions to TERMINALS whitelist; no auth/DB schema/external surface change)
prior_brief_complete: |
  STATE_FILE_REFRESH_1 shipped + merged as PR #212 → 11c0b18 (round-2 after symlink gap fix).
  Mailbox slot reclaimed for this dispatch.
estimated_time: 20-30 min
---

# Dispatch: BRISEN_LAB_COWORK_AH1_VISIBILITY_1

B1 — full brief at `briefs/BRIEF_BRISEN_LAB_COWORK_AH1_VISIBILITY_1.md` (in this repo for visibility). Actual code work happens in **`brisen-lab` repo**, not baker-master.

**TL;DR:** Add `cowork-ah1` to the daemon's hardcoded `TERMINALS` whitelist in `app.py` (~L40) + `static/app.js` (~L9) + check `bus.py`. Closes the UI gap so dashboard renders 7 cards instead of 6 and `/api/snapshot` accepts cowork-ah1 (currently HTTP 400 every 30s in the log).

## Working repo

`brisen-lab` (separate repo from baker-master). Use existing clone `~/bm-b1-brisen-lab` if present; otherwise fresh-clone from `https://github.com/vallen300-bit/brisen-lab`. **Do NOT edit anything in baker-master for this brief.**

## Ship gate (literal)

1. `pytest tests/ -v` green output captured in ship report.
2. Smoke curl HTTP 200 captured in ship report (full command in brief §Acceptance criteria #4).
3. UI verification — load `https://brisen-lab.onrender.com/` post-deploy, confirm 7 cards including `cowork-ah1`.
4. Existing 6-card behavior preserved.

## Reporting

- Bus-post `lead` (per `dispatched_by:` field above) on PR open with topic `pr-open/brisen-lab-cowork-ah1-visibility-1`.
- AH1 runs cross-lane review chain (AH2 static; `/security-review` skip-eligible — internal-only changes).

## Anchors

- 2026-05-17 chat — Director surfaced the gap ("brisen lab will now show what ah1cowork is doing?").
- 2026-05-18 chat — Director: "start working on the items."
- Sister commits: baker-master `8d8adf9` + baker-vault `9562cad`.
