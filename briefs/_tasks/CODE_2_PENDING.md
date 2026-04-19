# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab — prior brief-review + plist-audit sanity tabs both standing down)
**Task posted:** 2026-04-19 (late afternoon)
**Status:** OPEN — two queued reviews, run in order

---

## Task 1 (first): Re-review KBL_PIPELINE_SCHEDULER_WIRING brief (v2)

Your initial review (commit `273487e`) was REDIRECT on S1 + S2. AI Head folded both in at commit `cdaea58`. §Scope.6 "Pre-merge Mac Mini verification" added with explicit ssh checks. Test plan expanded from 4 → 7 (circuit-breaker precedes env-gate + Step-5 paused_cost_cap clean exit + Step-6 finalize_failed clean exit).

- Re-read `briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` (head `cdaea58`).
- Diff vs prior: only §Scope.5 (tests 4→7) + new §Scope.6 (pre-merge ssh gate).
- Verdict: APPROVE or 2nd REDIRECT.
- File at `briefs/_reports/B2_scheduler_wiring_brief_rereview_20260419.md`.
- ~5 min per your own recommendation.

On APPROVE: AI Head dispatches the brief to B1 for PR #18 impl. Your PR review comes next cycle.

---

## Task 2 (second): PR #17 KBL_PIPELINE_DASHBOARD_MVP review

B1 shipped at commit `1ce3ade` on branch `kbl-pipeline-dashboard-mvp`. PR #17 open, mergeable=MERGEABLE. 8/8 endpoint tests + 78/78 pipeline regression green.

- Standard PR review per the reviewer-separation matrix.
- Scope focus: 4 widgets (signals / cost rollup / Silver landed / Mac Mini heartbeat), 4 API endpoints under `/api/kbl/*`, new "KBL Pipeline" nav tab (last position), empty-state rendering per widget, X-Baker-Key auth pattern match.
- CHANDA audit: Q1 (Loop Test — read-only dashboard, no Leg touched) + Q2 (Wish Test — gives Director real visibility into compounding loop) + Inv 4/8/9/10 (all pass by construction since it's read-only).
- Specific landmines to check:
  - **No write endpoints.** Verify all 4 endpoints are `GET`-only. No admin controls.
  - **LIMIT bounds on queries** (50 for signals, 10 for Silver, rolling 24h for cost). No full-table scans.
  - **Empty-state templates** — all 4 widgets must render gracefully on zero rows.
  - **Mac Mini heartbeat age bands** — green <2 min, yellow 2-5 min, red >5 min.
  - **Auth parity** — same `X-Baker-Key` pattern as other `/api/*` endpoints.
- Verdict: APPROVE or REDIRECT with inline fixes. Small-surface fixes → B1 amends on same branch.
- File at `briefs/_reports/B2_pr17_dashboard_review_20260419.md`.
- ~25-35 min.

On APPROVE + MERGEABLE: AI Head auto-merges per durable authority. Dashboard goes live on Render within minutes.

---

## Working-tree reminder

Work in `~/bm-b2`. Fresh tab (prior two standing down per memory-hygiene). **Quit tab after both reviews ship** — prior sessions noted ~95 GB Terminal footprint if tabs linger.

---

*Posted 2026-04-19 by AI Head. Two tasks queued to land within ~40 min in one tab.*
