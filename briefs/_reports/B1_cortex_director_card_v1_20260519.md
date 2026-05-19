---
brief_id: CORTEX_DIRECTOR_CARD_V1
status: SHIPPED — awaiting AH1 gate-chain
target_repo: baker-master
working_branch: b1/cortex-director-card-v1
shipped_by: b1
shipped_at: 2026-05-19T17:55:00Z
reply_to: lead
gate_chain:
  gate_1_static: PENDING (deputy)
  gate_2_security_review: PENDING (AH1 /security-review)
  gate_3_cross_lane_architecture: PENDING (architect)
---

# B1 ship report — CORTEX_DIRECTOR_CARD_V1 — 2026-05-19

## Summary

Adds a plain-English "Director Card" translation layer at the end of every Cortex cycle (new Phase 4.5). Replaces technical proposal_text as the primary view in the Pending tab; technical reasoning stays under a "Show full reasoning" toggle for AH1 / audit. Fail-open: card-gen failure NEVER blocks a cycle from reaching the Director.

5 design choices Director-ratified in chat (per brief §"Surface contract"):
1. Backfill the 18 pending cycles — YES (script ready, dry-run validated)
2. Show "What could go wrong" — always
3. Cost field — AI compute (EUR) + real-world money (EUR or "no money sent")
4. UI section header — "What I'm Asking"
5. Confidence (high/medium/low) — always shown

## Files changed

- `orchestrator/cortex_phase4_5_director_card.py` (NEW) — phase module: translate_to_director_card + persist_director_card + run_phase4_5_director_card. Haiku 4.5, temp 0.0, max 600 tokens, pinned prompt from brief.
- `orchestrator/cortex_runner.py` — adds `_phase4_5_director_card(cycle)` helper + hooks it after `_safe_emit_ratify_required` (post-tier_b_pending, never blocks ratify path).
- `outputs/dashboard.py` — extends `/api/cortex/cycles/pending` + `/api/cortex/cycles/{cycle_id}/proposal` to include `director_card` (null when absent for legacy cycles).
- `outputs/static/app.js` — new `_cortexDirectorCardHtml()` renderer + collapsible "Show full reasoning" toggle in `_cortexPendingExpansionHtml`; falls back to existing `md(proposal_text)` when no card.
- `outputs/static/style.css` — minimal mobile-aware CSS for `.cortex-director-card` (grid card-label/value, 480px breakpoint).
- `outputs/static/index.html` — cache-bust `app.js?v=115` → `?v=116`.
- `scripts/backfill_director_cards.py` (NEW) — idempotent backfill: scans tier_b_pending cycles, skips those already carded, hard exit on cost-cap.
- `tests/test_cortex_phase4_5_director_card.py` (NEW) — 10 cases covering happy path, fail-open paths (b/c/d), prompt-injection sanitization (e), determinism at temp 0 (f), persistence SQL shape.
- `tests/test_dashboard_cortex_ratify.py` — adds 2 cases (director_card present / null), bumps cache-bust assertion, adds `_cortexDirectorCardHtml` to helper-list guard.

## Ship gate

### 1. pytest — literal output (25/25 PASS)

```
============================= test session starts ==============================
tests/test_cortex_phase4_5_director_card.py::test_a_happy_path_returns_valid_9_field_card PASSED [  4%]
tests/test_cortex_phase4_5_director_card.py::test_b_empty_proposal_text_returns_none_without_calling_api PASSED [  8%]
tests/test_cortex_phase4_5_director_card.py::test_b_non_json_response_returns_none PASSED [ 12%]
tests/test_cortex_phase4_5_director_card.py::test_c_api_error_returns_none PASSED [ 16%]
tests/test_cortex_phase4_5_director_card.py::test_d_missing_field_in_response_returns_none PASSED [ 20%]
tests/test_cortex_phase4_5_director_card.py::test_d_schema_validator_direct PASSED [ 24%]
tests/test_cortex_phase4_5_director_card.py::test_e_prompt_injection_in_card_fields_is_stripped PASSED [ 28%]
tests/test_cortex_phase4_5_director_card.py::test_e_sanitize_string_unit PASSED [ 32%]
tests/test_cortex_phase4_5_director_card.py::test_f_deterministic_at_temperature_zero PASSED [ 36%]
tests/test_cortex_phase4_5_director_card.py::test_persist_director_card_writes_correct_artifact PASSED [ 40%]
tests/test_dashboard_cortex_ratify.py::test_pending_route_is_registered_in_dashboard_source PASSED [ 44%]
tests/test_dashboard_cortex_ratify.py::test_trace_route_is_registered_in_dashboard_source PASSED [ 48%]
tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html PASSED [ 52%]
tests/test_dashboard_cortex_ratify.py::test_cortex_ratify_js_helpers_exist PASSED [ 56%]
tests/test_dashboard_cortex_ratify.py::test_pending_returns_200_with_cycles PASSED [ 60%]
tests/test_dashboard_cortex_ratify.py::test_pending_returns_empty_when_no_cycles PASSED [ 64%]
tests/test_dashboard_cortex_ratify.py::test_pending_rejects_missing_api_key PASSED [ 68%]
tests/test_dashboard_cortex_ratify.py::test_pending_marks_has_proposal_false_when_no_synthesis PASSED [ 72%]
tests/test_dashboard_cortex_ratify.py::test_pending_returns_director_card_when_present PASSED [ 76%]
tests/test_dashboard_cortex_ratify.py::test_pending_director_card_null_when_absent PASSED [ 80%]
tests/test_dashboard_cortex_ratify.py::test_trace_returns_200_with_phase_outputs PASSED [ 84%]
tests/test_dashboard_cortex_ratify.py::test_trace_returns_400_on_bad_cycle_id PASSED [ 88%]
tests/test_dashboard_cortex_ratify.py::test_trace_returns_404_when_cycle_missing PASSED [ 92%]
tests/test_dashboard_cortex_ratify.py::test_trace_requires_api_key PASSED [ 96%]
tests/test_dashboard_cortex_ratify.py::test_action_endpoint_dispatches_each_canonical_action PASSED [100%]
======================== 25 passed, 7 warnings in 0.40s ========================
```

Broader cortex regression surface also green (58/58 incl. test_cortex_phase4_proposal + test_cortex_runner_phase126).

### 2. Local smoke — uvicorn :8085 against prod Neon (read-only join)

```
HTTP-200 OK; count=15
cycles with director_card populated: 1/15

First 3 cycles in pending:
  b0ba3d3b-605 matter='oskolkov' has_card=True  has_proposal=True
  7d9eb1d2-f71 matter='oskolkov' has_card=False has_proposal=True
  71a2450c-cbf matter='oskolkov' has_card=False has_proposal=True

POPULATED CARD (cycle_id=b0ba3d3b-605):
{
  "matter": "Oskolkov",
  "situation": "The system has completed a routine health check (Smoke #3) on the Oskolkov matter and found all systems operating normally.",
  "action": "No action required — the system is confirming the matter is ready and stable.",
  "rationale": "All validation checks passed: the matter's core data loaded correctly, system settings propagated without error, and no new issues were detected. The matter is locked and safe to proceed.",
  "downside": "If the system's checks were incomplete or missed a hidden problem, approving inaction could allow a latent issue to surface later.",
  "no_action_consequence": "The matter remains in its current stable state; no forward progress occurs until the next cycle or manual instruction.",
  "cost": { "ai_money_eur": 0.1561, "real_world_money_eur": null, "action_sends_money": false },
  "recommendation": "approve",
  "confidence": "high"
}
```

Confirms:
- Schema-valid response with all 9 required fields + cost sub-object.
- 14/15 cycles return `director_card: null` and `has_director_card: false` — graceful fallback path works (frontend renders existing technical proposal_text).
- 1/15 cycles carry the populated card produced by the 1-cycle live backfill (see §5 below).

### 3. Chrome MCP cursor click verification on `_cortexPendingExpansionHtml`

Opened http://127.0.0.1:8085/, clicked Pending tab, expanded the carded cycle `b0ba3d3b-…`.

Result:

```
card_rendered: true
card_header: "What I'm Asking"
label_count: 9
labels: ["Matter", "What's going on", "What I want to do",
        "Why I'm recommending this", "What could go wrong if you say yes",
        "What happens if you say no", "Cost", "Recommendation", "Confidence"]
value_preview_first: "Oskolkov"
has_full_reasoning_section: true
full_reasoning_label: "▸ Show full reasoning"
```

elementFromPoint on the "Show full reasoning" toggle (after scrollIntoView):

```
el_at_point_tag: "DIV"
el_at_point_classes: "cortex-pending-section-head"
el_is_toggle_or_ancestor: true
section_body_open_before_click: false
section_body_open_after_click:  true
inner_proposal_present: true
inner_proposal_text_len: 561
```

Toggle is reachable + clicks expand the section + the technical `proposal_text` renders inside. (Note: when the toggle sits below the viewport, you must `scrollIntoView` first — same v1.1 lesson PR #224 documented for the tab buttons.)

### 4. Cache-bust v=115 → v=116

`outputs/static/index.html` — confirmed in served HTML during Chrome MCP smoke (`app_js_version: ["/static/app.js?v=116"]`). Test guard updated in `test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html`.

### 5. Backfill — dry-run + 1-cycle live for smoke

**Dry-run (all 15 candidates, no API spend):**

```
found 15 cycle(s) needing director_card; estimated total cost ≈ €0.0750 (cap €1.00)
DRY-RUN: would translate 15 cycles. Pass --live to execute.
  - cycle_id=b0ba3d3b-…  matter=oskolkov  proposal_len=660
  - cycle_id=7d9eb1d2-…  matter=oskolkov  proposal_len=1269
  - cycle_id=71a2450c-…  matter=oskolkov  proposal_len=939
  - cycle_id=c4242a20-…  matter=oskolkov  proposal_len=13544
  - cycle_id=3523b694-…  matter=oskolkov  proposal_len=13877
  - ... (10 more)
```

15 candidates (brief said ~18; 3 may have folded between brief drafting and ship). All `tier_b_pending` matter=oskolkov. Estimated total ≈ €0.075 — well under the €1.00 cost cap.

**1-cycle live run** (to populate test data for the smoke + Chrome MCP verification — one card persisted):

```
found 1 cycle(s) needing director_card; estimated total cost ≈ €0.0050 (cap €1.00)
HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
wrote director_card for cycle_id=b0ba3d3b-6058-40a8-a903-827a8e37da79 — matter='Oskolkov' reco='approve' confidence='high'
DONE: wrote=1 skipped=0 failed=0 actual_total≈€0.0015
```

Actual cost €0.0015 (3× cheaper than the conservative pre-estimate). Sample card already shown in §2.

## Sample card #2 — for Director review before AH1 fires live backfill on remaining 14

(Captured during the live run; see §2 above for the rendered JSON.)

**Cycle:** `b0ba3d3b-6058-40a8-a903-827a8e37da79` · **Matter:** Oskolkov · **Recommendation:** approve · **Confidence:** high.

The technical proposal_text was a Smoke #3 health-check; the card translates it into a plain-English ratify view (matter / situation / action / rationale / downside / no_action_consequence / cost / recommendation / confidence). Director can ratify or reject without reading the technical underlay.

## Risk surface

- **Fail-open** is the load-bearing invariant. Three layers: (1) translate function returns None on any exception, (2) runner wrapper swallows even import-time errors, (3) frontend renders existing `md(proposal_text)` whenever `director_card` is null. The cycle status flip to `tier_b_pending` and the `ratify_required` signal both happen BEFORE phase 4.5 fires, so a slow / failed Haiku call cannot delay or block the Director-facing view.
- **Prompt-injection defense.** Three-stage strip on every card string field (markdown links → label only, HTML tags removed, `javascript:` schemes nuked) BEFORE schema validation. Front-end re-runs `esc()` on every rendered field (defense-in-depth). Test `test_e_prompt_injection_in_card_fields_is_stripped` covers the worst-case poisoned proposal.
- **Migration-bootstrap drift.** No new column / table — `cortex_phase_outputs.artifact_type` is free-form TEXT, `phase` CHECK allows 'propose'. `_persist_director_card` writes `phase='propose', phase_order=9, artifact_type='director_card'` (phase_order 7=proposal_card, 8=dry_run_marker, 9=director_card).

## Out of scope (confirmed — separate briefs)

- Tier 3-5 dashboard features (flag specialist, edit-then-approve, multi-decision batch).
- Slack ratify fallback — untouched.
- Backfill of `tier_a_acted` historical cycles — only `tier_b_pending` cycles in scope.
- Director Card on brisen-lab side.
- Direct LLM streaming to frontend — write-then-read pattern only.

## PR

To be opened on `b1/cortex-director-card-v1` against `main` after this report is committed.

## Next steps (for AH1)

1. Gate-1 (deputy /static review).
2. Gate-2 (AH1 /security-review — prompt-injection surface on card-gen pass).
3. Gate-3 (architect cross-lane — new Cortex phase touches runner architecture).
4. On Gate-pass merge: Render auto-deploys. AH1 then runs `python3 scripts/backfill_director_cards.py --live` to translate the remaining 14 cycles (est. €0.07) and forwards 1-2 cards to Director for review.
