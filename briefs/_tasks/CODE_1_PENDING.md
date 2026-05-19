---
status: PENDING
brief: _ops/briefs/BRIEF_BRISEN_LAB_PR22_BUTTON_REPOINT_1.md (baker-vault)
brief_id: BRISEN_LAB_PR22_BUTTON_REPOINT_1
target_repo: brisen-lab
working_dir: ~/bm-b1-brisen-lab
matter_slug: baker-internal
cross_matter_usage: [all-matters] (every matter's Cortex cycles route through brisen-lab card → baker-master ratify panel)
dispatched_at: 2026-05-19T13:00:00Z
dispatched_by: lead
director_auth: 2026-05-19 chat — "ratified , go ahead." (covers chain including this fast-follow per brief HOLD-trigger convention)
trigger_class: LOW
estimated_effort: 15-30 min
working_branch_suggestion: b1/pr22-button-repoint-1
reply_target: lead (bus topic `ship/brisen-lab-pr22-button-repoint-1`)
prior_dispatch_closeout: |
  DASHBOARD_CORTEX_RATIFY_PANEL_1 merged 2026-05-19 — squash commit 1264ca8 on baker-master main.
  PR #223 closed. Mailbox previously held CLAIMED status; now flipped to PENDING for fast-follow dispatch.
---

# CODE_1_PENDING — BRISEN_LAB_PR22_BUTTON_REPOINT_1 — 2026-05-19

## Brief

`~/baker-vault/_ops/briefs/BRIEF_BRISEN_LAB_PR22_BUTTON_REPOINT_1.md`. Pre-authored 2026-05-19 ~13:40Z when the destination didn't yet exist; now activated post-merge. Read end-to-end — Surface Contract block at top has all verified `file:line` references including the destination URL pattern.

## What ships

1-3 line patch in `app.js` (brisen-lab repo) — change the "Open in baker-master" anchor URL from `/api/cortex/gate/decide?cycle_id=<id>` (wrong endpoint, returns 400) to the new ratify panel destination. Plus cache-bust `index.html` (current `v=11` → `v=12`).

## Destination URL — verify before patching

The new baker-master ratify panel is the Pending tab on the Cortex Intent Feed card. **B1 must verify the actual anchor/query convention in the merged commit (1264ca8) BEFORE writing the URL.** Read `outputs/static/index.html:233-237` for the tab button id `cortexTabPending` + `outputs/static/app.js` for the `_cortexTab('pending')` JS — confirm whether the panel responds to a fragment anchor (e.g., `#cortex-pending-<cycle_id>`) or a query string (e.g., `?cortex_cycle=<cycle_id>`) for deep-linking to a specific cycle row.

If neither anchor nor query is currently supported (likely — the panel was built without deep-link support), the simplest right answer is: re-point at the dashboard root (`https://baker-master.onrender.com/`) and let Director click the Pending tab manually. Tag a fast-follow brief candidate `BRIEF_DASHBOARD_CORTEX_RATIFY_DEEPLINK_1` in your ship report if you take this path.

## Working dir / branch

- **Repo:** brisen-lab.
- **Working dir:** `~/bm-b1-brisen-lab`.
- **Branch:** `b1/pr22-button-repoint-1` cut from brisen-lab `main` after `git pull --ff-only origin main`.

## Pre-flight

1. `cd ~/bm-b1-brisen-lab && git pull --ff-only origin main && git status` (clean).
2. `cd ~/bm-aihead1 && git log --oneline -5` to see the merged baker-master commit `1264ca8` — confirm the Pending tab + new endpoints landed.
3. Read the new code in baker-master at the file:line refs above before deciding destination URL pattern.

## Test plan

1. Local smoke: load brisen-lab on local server (uvicorn or equivalent) → click "Open in baker-master" on a tier_b_pending cycle card → confirm browser navigates to baker-master Pending tab (or root if no deep-link).
2. Screenshot of destination after click included in ship report.
3. No new automated tests required (15-LOC UI patch under existing render path).

## Ship gate

- Manual click-test confirmed (screenshot in ship report).
- `pytest tests/ -v` on brisen-lab side — confirm no regressions.
- Cache-bust version incremented.

## Gate chain

- Gate-1 (deputy static) + Gate-2 (`/security-review` skip-eligible per existing brisen-lab UI-only-diff precedent — B1 surfaces to AH1 if uncertain).
- Gate-3 + Gate-4 NOT required.

## Reporting

- Bus-post `ship/brisen-lab-pr22-button-repoint-1` to `lead`.
- Heartbeat unnecessary for sub-30-min brief.

## Anchors

- Brief: `~/baker-vault/_ops/briefs/BRIEF_BRISEN_LAB_PR22_BUTTON_REPOINT_1.md`
- Source brief that introduced the bug: `briefs/BRIEF_BRISEN_LAB_CORTEX_DRILLDOWN_1.md` (commit dac3b90 on brisen-lab main)
- Destination brief that created the correct URL: now-merged baker-master commit `1264ca8` (PR #223)
- Skill that gated this fast-follow: `~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md` (v1.1)
- Anchor incident: 2026-05-19 ~07:45Z Director smoke-test of PR #22 drilldown caught the broken URL
