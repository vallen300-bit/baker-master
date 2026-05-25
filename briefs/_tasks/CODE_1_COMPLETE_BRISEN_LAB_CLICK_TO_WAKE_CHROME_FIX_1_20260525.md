---
brief_id: BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1
title: Dashboard click-to-wake fails silently in Chrome — replace window.location.href with anchor-click
status: COMPLETE
shipped_at: 2026-05-25T00:00:00Z
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/37
ship_report: briefs/_reports/B1_BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1_20260525.md
dispatched_at: 2026-05-25T01:35:00Z
dispatched_by: cowork-ah1
brief_path: briefs/BRIEF_BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1.md
target_repos:
  - brisen-lab (single PR)
expected_time: ~20min
complexity: Low
director_ratified: 2026-05-25 (cowork-ah1 chat — Director-observed Chrome reproduction)
authored_by: cowork-ah1
reply_target: cowork-ah1
target: b1
prior_mailbox_state: WAKE_NUDGE_PIVOT_1 shipped + flipped to CODE_1_COMPLETE_BRISEN_LAB_WAKE_NUDGE_PIVOT_1_20260525.md
---

# CODE_1_PENDING — BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1

## Read first

1. The brief: `briefs/BRIEF_BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1.md` — full spec end-to-end.
2. Predecessor mailboxes (yours, just completed):
   - `briefs/_tasks/CODE_1_COMPLETE_BRISEN_LAB_CLICK_TO_WAKE_1_20260524.md` — PR #34
   - `briefs/_tasks/CODE_1_COMPLETE_BRISEN_LAB_WAKE_NUDGE_PIVOT_1_20260525.md` — PR #36
3. Current production `static/app.js?v=15` lines 895-911 — see brief §Fix/Feature 1 §Current state.

## Working directory

`~/bm-b1-brisen-lab/` — your existing brisen-lab clone. Pull main first (`git checkout main && git pull --rebase`), then branch `b1/brisen-lab-click-to-wake-chrome-fix-1`. Single PR against `vallen300-bit/brisen-lab` main.

## Sequence

1. Read the brief end-to-end.
2. Apply the anchor-click pattern from Fix/Feature 1 to `static/app.js`.
3. Bump `index.html` cache-bust per Fix/Feature 2.
4. Locally smoke-test in your Chrome: open the deployed-after-merge dashboard (or the dev preview if you have one), click a badged card with DevTools console open, confirm no `"user gesture required"` error + handler fires.
5. Open PR. Ship report under `briefs/_reports/B1_BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1_<YYYYMMDD>.md` with literal output for each verification case.
6. Bus-post cowork-ah1 on ship.

## Gate chain (your trigger after ship)

- Gate-1 architecture: deputy (AH2)
- Gate-2 `/security-review`: deputy (AH2)
- Gate-3 picker-architect: SKIP
- Gate-4 code-reviewer 2nd-pass: deputy (AH2)
- Gate-5 merge: cowork-ah1 (first-AH1-wins; lead quiet on this thread)

## Reply target

Post ship report to **cowork-ah1**.

## Director context

Director ran live-Chrome diagnostic this session. The wake handler app + URL scheme registration both confirmed working end-to-end via direct `open` invocation. The dashboard click is the only broken surface — Chrome silently blocks `window.location.href = "<custom-scheme>://..."` even from a real user click. Without this fix, click-to-wake is dead-on-arrival in Chrome and Director keeps typing `check bus` manually.

## What NOT to do

- Do NOT change the wake handler app — it's correct.
- Do NOT change the badge-gating condition or the detail-modal fallback.
- Do NOT defer `.remove()` of the synthetic anchor — keep it synchronous.
- Do NOT ship without testing in Chrome itself; Safari-only confirmation is insufficient.
