---
status: PENDING
brief: briefs/BRIEF_DASHBOARD_CORTEX_RATIFY_PANEL_1.md
brief_id: DASHBOARD_CORTEX_RATIFY_PANEL_1
target_repo: baker-master
working_dir: ~/bm-b1
matter_slug: baker-internal
cross_matter_usage: [all-matters] (every matter's Cortex cycles ratify through this panel)
dispatched_at: 2026-05-19T12:55:00Z
dispatched_by: lead
director_auth: 2026-05-19 chat — "ratified , go ahead."
trigger_class: LOW-MEDIUM
gate_chain:
  gate_1_static: REQUIRED (deputy / AH2 cross-lane)
  gate_2_security_review: REQUIRED (touches dashboard frontend + new API routes)
  gate_3_cross_lane_architecture: NOT required (no auth/DB schema/architecture-affecting changes)
  gate_4_2nd_pass_code_reviewer: NOT required (no auth/DB schema/operation-ordering per SKILL.md trigger list)
estimated_effort: 3-5h (Tier 1 ~1.5h + Tier 2 ~2-3h)
working_branch_suggestion: b1/dashboard-cortex-ratify-panel-1
reply_target: lead (bus topic `ship/dashboard-cortex-ratify-panel-1`)
---

# CODE_1_PENDING — DASHBOARD_CORTEX_RATIFY_PANEL_1 — 2026-05-19

## Brief

`briefs/BRIEF_DASHBOARD_CORTEX_RATIFY_PANEL_1.md` (same commit). Read end-to-end before starting — Surface contract block at top has all verified `file:line` references for the endpoints.

## Working branch

`b1/dashboard-cortex-ratify-panel-1`. Cut from `main` after `git pull --ff-only origin main`.

## Pre-requisites

- `~/bm-b1` checkout sync'd to origin/main (`git fetch && git status` clean before branch cut — per 2026-05-03 local-checkout-drift lesson).
- `BAKER_KEY` env var available for smoke-test curls (B1 has it; if not, op CLI fetch from 1Password).
- A test cycle with `status='tier_b_pending'` in DB for manual smoke. If none exists in prod, use the mrci probe envelope `db3d43a3-a623-45e8-aa13-b43d0a55b37d` from 2026-05-18 night (still sitting pending per the prior handover § Live state).

## Scope summary (full detail in brief)

**Tier 1 (must-ship):** New "Pending" tab on Cortex Intent Feed card. List of `tier_b_pending` cycles. Per-row expansion shows full proposal text. Four buttons: Approve / Edit / Refresh / Reject. POST to existing `/cortex/cycle/{cycle_id}/action`.

**Tier 2 (must-ship in same PR):** Phase trace + specialist breakdown (read-only — no flag button in V1) + citations panel + cost telemetry. All under the expanded row, collapsible.

**New API routes (read-only, both):**
- `GET /api/cortex/cycles/pending`
- `GET /api/cortex/cycles/{cycle_id}/trace`

**Out of scope:** Tier 3-5 (gold-tag / devils-advocate fire / convert-to-brief / stale-cycle list inline / cost-cap monitor). Named explicitly in brief's `## Out of scope` — do not implement.

## Ship gate (literal)

1. `pytest tests/test_dashboard_cortex_ratify.py -v` — full literal output in ship report. No "pass by inspection."
2. `pytest tests/test_dashboard*.py -v` — confirm no regressions.
3. `bash scripts/check_singletons.sh` — clean.
4. Manual smoke per brief § Test plan step 2 — screenshot of new tab + curl-success log of both new endpoints included in ship report.

## Reporting

- Open PR with title `DASHBOARD_CORTEX_RATIFY_PANEL_1: web ratify panel for Cortex Tier-B proposals`.
- Bus-post `ship/dashboard-cortex-ratify-panel-1` to `lead` with: PR link, commit SHA, literal pytest output presence, 4-gate readiness (G3+G4 not required per trigger class), smoke screenshot path.
- Heartbeat every 12h while in progress per 2026-05-05 stall-chase protocol.

## Self-check before claiming ship

- [ ] Surface Contract block from brief is preserved unchanged in the PR description (so reviewers see it inline).
- [ ] Reviewer instructions per `ui-surface-prebrief` skill check 6 are quoted in PR description.
- [ ] Both new GET endpoints curl-tested locally with `X-Baker-Key` header → 200 + valid JSON shape.
- [ ] Each of the 4 action buttons clicked at least once on local dashboard against the test cycle → POST 200 + row removes.
- [ ] No removal or modification of the Slack ratify path in `orchestrator/cortex_phase4_proposal.py:175-188`.

## Anchors

- Brief: `briefs/BRIEF_DASHBOARD_CORTEX_RATIFY_PANEL_1.md`
- Skill that gated this brief (read for Surface Contract context): `~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md` (v1.1)
- Researcher market scan (informed scope — not blocking): `~/baker-vault/wiki/research/2026-05-19-ui-surface-prebrief-market-scan.md`
- Anchor incident: brisen-lab PR #22 shipped 2026-05-19 with broken "Open in baker-master" URL; this brief builds the destination that URL should have pointed at.
