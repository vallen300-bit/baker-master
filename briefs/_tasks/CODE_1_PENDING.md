---
status: PENDING
brief: briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1_1.md
brief_id: CORTEX_DIRECTOR_CARD_V1_1
target_repo: baker-master
working_dir: ~/bm-b1
matter_slug: baker-internal
cross_matter_usage: [all-matters] (every Cortex cycle for every matter)
dispatched_at: 2026-05-20T22:30:00Z
dispatched_by: lead
director_auth: 2026-05-20 chat — "genini pro" (model swap ratification) + "1,2,3 approved, 4- no need to retranslate. go" (design choices)
trigger_class: MEDIUM
gate_chain:
  gate_1_static: REQUIRED (deputy)
  gate_2_security_review: REQUIRED (vendor swap + new query param)
  gate_3_cross_lane_architecture: NOT required (v1.1 amendment, no new architectural pattern)
  gate_4_2nd_pass_code_reviewer: NOT required
estimated_effort: 3h
working_branch_suggestion: b1/cortex-director-card-v1-1
reply_target: lead (bus topic `ship/cortex-director-card-v1-1`)
prior_dispatch_closeout: |
  CORTEX_DIRECTOR_CARD_V1 merged 2026-05-19 23:45Z — baker-master squash 5db210a (PR #226).
  Cortex Edit textarea hot-fix merged 2026-05-20 22:13Z — squash 266ca09 (PR #228).
  Mailbox flipped COMPLETE; this brief overwrites for next dispatch.
---

# CODE_1_PENDING — CORTEX_DIRECTOR_CARD_V1_1 — 2026-05-20

## Brief

See `briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1_1.md` (committed same turn as this dispatch).

## Summary

Amends v1.0 (PR #226 Phase 4.5 Director Card). Two bundled changes:

1. **Model swap** — Phase 4.5 translator: `claude-haiku-4-5-20251001` → `gemini-2.5-pro` (primary), with `claude-sonnet-4-6` as fallback on ANY Gemini call/parse/schema failure. Fail-open contract preserved. Director-ratified swap reason: Haiku-distrust on Director-facing surfaces.
2. **Smoke-cycle filter** — `/api/cortex/cycles/pending` gains `include_smoke: bool = False` query param. Backend computes per-cycle `is_smoke` from `triggered_by` / `signal_text` / synthesis `proposal_text` ILIKE patterns (smoke, health check, heartbeat, Smoke # marker). Frontend Pending tab gets a "Show all" toggle button inside the tab body (NOT the tab strip — PR #224 hitbox lesson). Default hides smoke; toggle reveals with smoke chips per cycle.

Director ratified design (2026-05-20):
1. Fallback to Sonnet 4.6 on Gemini failure — YES
2. API key via Google AI Studio direct (`GEMINI_API_KEY`) — YES
3. Smoke filter default-hide with "Show all" toggle — YES
4. NO backfill of existing 15 Haiku cards — grandfather

## Pre-flight (b1 must run before edits)

1. Verify `GEMINI_API_KEY` set on Render `baker-master` (helpers in `tools/render_env_guard.py`). If absent, STOP and bus-post `lead` with topic `blocker/cortex-director-card-v1-1-gemini-key`. Do NOT attempt to set env vars from b1 — AH1 handles via Tier-B with Director auth.
2. Run baseline tests: `pytest tests/test_cortex_phase4_5_director_card.py tests/test_dashboard_cortex_ratify.py -v` BEFORE any edits.

## Ship gate

- Literal `pytest` output (no "by inspection") — paste in ship report.
- `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase4_5_director_card.py', doraise=True); py_compile.compile('outputs/dashboard.py', doraise=True)"` clean.
- `bash scripts/check_singletons.sh` clean.
- Open PR titled `CORTEX_DIRECTOR_CARD_V1_1: Gemini 2.5 Pro swap + smoke filter`.
- Bus-post `lead` on PR open: topic `ship/cortex-director-card-v1-1`, body includes PR URL + 1-line green summary.

## Files in scope

- `orchestrator/cortex_phase4_5_director_card.py`
- `outputs/dashboard.py` (`list_cortex_cycles_pending` only)
- `outputs/static/app.js` (Pending tab body)
- `outputs/static/style.css`
- `outputs/static/index.html` (cache-bust)
- `tests/test_cortex_phase4_5_director_card.py`
- `tests/test_dashboard_cortex_ratify.py`
- `briefs/_reports/B1_cortex_director_card_v1_1_<YYYYMMDD>.md` (ship report)

## Do NOT touch

- `scripts/backfill_director_cards.py` — grandfather existing 15.
- `orchestrator/cortex_runner.py`, `orchestrator/gemini_client.py`.
- Migrations / `applied_migrations.lock` / `cortex_cycles` schema.

## Reporting

- PR open: bus-post `lead` topic `ship/cortex-director-card-v1-1`.
- Merge (will be done by AH1): bus-post `lead` topic `complete/cortex-director-card-v1-1-merged`.
- Mailbox flips COMPLETE same turn as merge.
