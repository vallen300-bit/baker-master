---
status: PENDING
brief: briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md
brief_id: CORTEX_DIRECTOR_CARD_V1
target_repo: baker-master
working_dir: ~/bm-b1
matter_slug: baker-internal
cross_matter_usage: [all-matters] (every Cortex cycle for every matter)
dispatched_at: 2026-05-19T16:50:00Z
dispatched_by: lead
director_auth: 2026-05-19 chat — "ratified, go" + "ratified" (post-design-summary)
trigger_class: MEDIUM
gate_chain:
  gate_1_static: REQUIRED (deputy)
  gate_2_security_review: REQUIRED (prompt injection on proposal_text)
  gate_3_cross_lane_architecture: REQUIRED (new Cortex phase)
  gate_4_2nd_pass_code_reviewer: NOT required
estimated_effort: 3-4h
working_branch_suggestion: b1/cortex-director-card-v1
reply_target: lead (bus topic `ship/cortex-director-card-v1`)
prior_dispatch_closeout: |
  DASHBOARD_CORTEX_TAB_HITBOX_FIX_1 merged 2026-05-19 16:34Z — baker-master squash 269f45a (PR #224).
  Mailbox flipped COMPLETE; this brief overwrites for next dispatch.
---

# CODE_1_PENDING — CORTEX_DIRECTOR_CARD_V1 — 2026-05-19

## Brief

See `briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md` (committed same turn as this dispatch).

## Summary

Add a plain-English "Director Card" translation step at the end of every Cortex cycle so Director can ratify proposals without engineering jargon. Replaces the technical proposal as the primary view in the Pending tab; technical version stays under a "Show full reasoning" toggle for AH1 / audit.

5 design choices Director-ratified in chat (see brief §"Surface contract"):
1. Backfill the 18 pending cycles — YES
2. Show "What could go wrong" — always
3. Cost field — AI money + real-world money
4. UI section header — "What I'm Asking"
5. Confidence (high/medium/low) — always shown

## Key constraints

- **Fail-open.** Card-gen failure must NEVER block a Cortex cycle from reaching Director — frontend falls back to existing `proposal_text` rendering.
- **Model.** `claude-haiku-4-5-20251001`; temperature 0.0; max_tokens 600.
- **Latency.** ≤8s per cycle.
- **Cost.** ≤€0.02 per cycle.
- **Prompt pinned verbatim** in brief §"Prompt contract" — copy literally into module.
- **Backfill cap.** €1.00 hard exit + dry-run default.

## Ship gate (literal — abbreviated; see brief for full)

1. `pytest tests/test_cortex_phase4_5_director_card.py tests/test_dashboard_cortex_ratify.py -v` PASS.
2. Local smoke uvicorn :8085 against prod Neon read-only — `/api/cortex/cycles/pending` returns `director_card` field schema-valid.
3. Chrome MCP cursor click verification on `_cortexPendingExpansionHtml` — `elementFromPoint` on "Show full reasoning" toggle.
4. Cache-bust `app.js?v=115` → `?v=116`.
5. Backfill dry-run output attached to ship report; AH1 forwards 1-2 sample cards to Director before live-flag run.

## Reporting

Bus-post `ship/cortex-director-card-v1` to `lead` with PR link + 1-2 sample cards from dry-run.
