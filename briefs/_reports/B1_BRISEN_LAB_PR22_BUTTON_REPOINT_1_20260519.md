---
brief_id: BRISEN_LAB_PR22_BUTTON_REPOINT_1
agent: b1
status: SHIPPED
target_repo: brisen-lab
pr: https://github.com/vallen300-bit/brisen-lab/pull/24
branch: b1/pr22-button-repoint-1
working_dir: ~/bm-b1-brisen-lab
shipped_at: 2026-05-19T13:30:00Z
trigger_class: LOW
diff_loc: 2
gates_required: [gate-1-deputy, gate-2-security-review (skip-eligible)]
gates_passed: [self-pretest]
---

# B1 SHIP REPORT — BRISEN_LAB_PR22_BUTTON_REPOINT_1

## TL;DR

PR #22 "Open in baker-master" button pointed at the wrong endpoint (`/api/cortex/gate/decide?cycle_id=<id>` — pre-cycle cost gate, expects `signal_id`+HMAC, returns HTTP 400 on every click). Re-pointed at `https://baker-master.onrender.com/` (dashboard root) per dispatching brief's fallback clause, because the merged ratify panel (baker-master squash `1264ca8`) has no deep-link support. Cache-bust `v=11` → `v=12`. 2 LOC, PR #24 open on brisen-lab.

## Diff

```
 static/app.js     | 2 +-
 static/index.html | 2 +-
 2 files changed, 2 insertions(+), 2 deletions(-)
```

`static/app.js:391` — `"https://baker-master.onrender.com/api/cortex/gate/decide?cycle_id=" + encodeURIComponent(cycleId)` → `"https://baker-master.onrender.com/"`.
`static/index.html:77` — `app.js?v=11` → `app.js?v=12`.

## Deep-link verification (per brief)

Verified the merged ratify panel does NOT support deep-linking before falling back to root URL:

- `outputs/static/index.html:236` — Pending tab button uses `onclick="_cortexTab('pending')"` (no anchor target).
- `outputs/static/app.js:10354` — pending row markup uses `data-cycle="<id>"`, NOT `id="cortex-pending-<id>"`.
- `_cortexTab()` defined at `outputs/static/app.js:10263` — does not read `location.hash` or `URLSearchParams`.
- Repo-wide grep on `cortex-pending-` / `cortex_cycle=` / `cortexTabPending` confirms no router-side handling of either fragment or query.

Conclusion: dashboard root is the right destination today. The Pending tab is one manual click away after landing.

## Fast-follow candidate flagged

`BRIEF_DASHBOARD_CORTEX_RATIFY_DEEPLINK_1` — add fragment-anchor or query-string handling to baker-master dashboard so a specific `cycle_id` can be deep-linked (auto-switch to Pending tab + scroll target row into view + expand body). Tier 1 of that follow-up makes the "Open in baker-master" button behave as the original Surface Contract intended.

## Test plan execution

- **Pre-flight baseline:** `python3 -m pytest tests/ -v` on brisen-lab → `120 skipped, 1 warning in 0.26s`. (DB-gated suite; env not set on this machine; same posture for the post-patch run.)
- **Post-patch:** `python3 -m pytest tests/ -v` → `120 skipped, 1 warning in 0.15s`. No regressions, no new failures.
- **Static-serve smoke:**
  - `python3 -m http.server 8899` on `~/bm-b1-brisen-lab/static/`
  - `curl /index.html` → `<script src="/static/app.js?v=12"></script>` ✅
  - `curl /app.js` → patched block shows `window.open("https://baker-master.onrender.com/", "_blank", "noopener,noreferrer")` ✅
- **Manual browser click-test on deployed lab:** NOT executed by B1. Requires a live `tier_b_pending` Cortex cycle in brisen-lab's ratify inbox to render a button; that's a Director / lead path. Reviewer should execute per the Surface Contract reviewer instruction (clarified in PR description: confirm new tab opens at root, dashboard loads — cycle-row focus is fast-follow scope).

## Mailbox state

`briefs/_tasks/CODE_1_PENDING.md` flipped `PENDING` → `CLAIMED` on baker-master main (commit `15e5f72`, pushed) at dispatch claim. Lead can flip to `COMPLETE` (or replace with next dispatch) after merge.

## Gates

- **Gate-1 (deputy static):** AWAITING. PR #24 ready for review.
- **Gate-2 (`/security-review`):** skip-eligible per brisen-lab UI-only-diff precedent (2-LOC URL string + cache-bust, no auth/DB/external surface). Surface to AH1 if uncertain — flagged in PR description.
- **Gate-3 (cross-lane architecture):** NOT required (no architecture-affecting change).
- **Gate-4 (2nd-pass code reviewer):** NOT required (no auth/DB schema/operation-ordering touch).

## Anchors

- PR: https://github.com/vallen300-bit/brisen-lab/pull/24
- Branch: `b1/pr22-button-repoint-1` (commit `65b5370`)
- Dispatching brief: `~/baker-vault/_ops/briefs/BRIEF_BRISEN_LAB_PR22_BUTTON_REPOINT_1.md`
- Source-of-bug PR: brisen-lab #22 commit `dac3b90` (`BRIEF_BRISEN_LAB_CORTEX_DRILLDOWN_1`)
- Destination panel: baker-master squash `1264ca8` (PR #223, `BRIEF_DASHBOARD_CORTEX_RATIFY_PANEL_1`)
- Anchor incident: 2026-05-19 ~07:45Z Director smoke-test of PR #22 drilldown caught the broken URL.
