---
brief_id: CORTEX_DIRECTOR_CARD_V1
status: DRAFT_PENDING_DIRECTOR_RATIFICATION
target_repo: baker-master
matter_slug: baker-internal
cross_matter_usage: [all-matters] (every Cortex cycle for every matter routes through the card layer)
authored_by: AH1
director_auth: 2026-05-19 chat — 5-choice design ratified ("ratified, go")
trigger_class: MEDIUM (new Cortex phase, paid per-cycle API call, Director-facing surface, backfill against live data)
estimated_effort: 3-4h
working_branch_suggestion: b<N>/cortex-director-card-v1
reply_target: lead (bus topic `ship/cortex-director-card-v1`)
gate_chain:
  gate_1_static: REQUIRED (deputy)
  gate_2_security_review: REQUIRED (AI prompt injection risk on proposal_text → card-generation pass)
  gate_3_cross_lane_architecture: REQUIRED (new Cortex phase touches phase-runner architecture)
  gate_4_2nd_pass_code_reviewer: NOT required (no auth/DB schema/operation-ordering changes — additive phase + additive table row)
---

# BRIEF_CORTEX_DIRECTOR_CARD_V1 — 2026-05-19

## Problem

The Cortex ratify panel (PR #223 merged 1264ca8) is live and clickable, but the proposal_text rendered to the Director is written by domain specialists (legal / finance / tax / game-theory capabilities) in agent-to-agent technical depth. Director cannot read it. Quote: "I cannot make much of what these cards are saying. Language is technical, full of jargon. So I don't understand any of these cards. I only understand that it works. For the future, I need to have plain English, no jargon. What do I need to approve, reject, refresh, or Edit. Otherwise, I don't know what I am Approving."

This blocks the daily 5-min queue-clear pattern. 18 cycles are currently waiting; Director cannot act on them.

## Goal

Add a final translation step at the end of every Cortex cycle that converts the technical proposal into a structured plain-English "Director Card" the Director can read in ≤30 seconds and ratify with confidence. Technical proposal stays accessible behind a "Show full reasoning" toggle for AH1 / auditors.

### Surface contract (ui-surface-prebrief skill, v1.1)

**1. User action.** Director opens the Pending tab in the Cortex card on the dashboard at `baker-master.onrender.com`, clicks a cycle row to expand it, and reads the new "What I'm Asking" card. Decides to press Approve / Edit / Refresh / Reject based on plain-English content.

**2. Frontend rendering surface.** `outputs/static/app.js:_cortexPendingExpansionHtml` (currently at app.js:~10380 — verify line at brief-pickup time; outputs/dashboard.py is volatile). Replace the current `md(proposalText)` block with a structured card renderer that pulls from the new `director_card` artifact. Keep the existing `md()` block underneath, gated behind a collapsible "Show full reasoning" toggle (`_collapsibleSection` helper exists at app.js — verify name).

**3. Backend route.** Extend `GET /api/cortex/cycles/pending` (outputs/dashboard.py:~4546) to include the `director_card` payload alongside `proposal_text`. No new endpoint needed.

**4. Cache-bust.** Bump `app.js?v=115` → `?v=116` in outputs/static/index.html.

**5. Section header in UI.** "What I'm Asking" (Director-ratified naming choice).

**6. Card fields rendered (in this order).**
- **Matter:** [matter name in plain language, not slug]
- **What's going on:** [one sentence]
- **What I want to do:** [one sentence — the action being proposed]
- **Why I'm recommending this:** [two sentences max]
- **What could go wrong if you say yes:** [one line — always shown, per Director Q2 ratification]
- **What happens if you say no:** [one line]
- **Cost:** AI compute (€X.XX) + real-world money the action sends (€Y if any, else "no money sent")
- **Recommendation:** Approve / Reject / Edit
- **Confidence:** High / Medium / Low (always shown — Director Q5 ratification)

## Acceptance criteria

1. **New phase module** `orchestrator/cortex_phase4_5_director_card.py` exists, with one entry point: `translate_to_director_card(cycle_id: str, proposal_text: str, matter_slug: str, cost_telemetry: dict) -> dict`. Returns a JSON object matching the 9-field schema in §"Card fields" above.

2. **Model + prompt.** Uses `claude-haiku-4-5-20251001` per env config (`ANTHROPIC_MODEL_HAIKU` if set, fallback to constant). System prompt is hardcoded in the module and pinned in this brief — see §"Prompt contract" below. Max tokens output: 600. Temperature: 0.0 (deterministic for audit).

3. **Pipeline integration.** `orchestrator/cortex_runner.py` calls `translate_to_director_card` AFTER Phase 4 (synthesis writes `proposal_text`) and BEFORE the cycle transitions to `tier_b_pending`. Writes the card to `cortex_phase_outputs` as a new row with `artifact_type='director_card'` and `payload` = the returned JSON. Existing `proposal_text` artifact is unchanged.

4. **Backend exposure.** `/api/cortex/cycles/pending` response includes `director_card` as a nested object (read via the same join pattern as `proposal_text` — see dashboard.py:~4570 for the subselect pattern). Field is `null` when no director_card exists (legacy cycles pre-this-PR).

5. **Frontend rendering.** `_cortexPendingExpansionHtml` renders the card structure first when `director_card` is present; falls back to existing `md(proposal_text)` rendering when null. Tier-2 toggle "Show full reasoning" reveals the technical `proposal_text` underneath the card. All HTML interpolation via existing `esc()` / `escAttr()` helpers — no new escape paths.

6. **Backfill script** `scripts/backfill_director_cards.py` runs against current `tier_b_pending` cycles, calls `translate_to_director_card` on each, writes the new artifact row. Idempotent: skip cycles that already have a `director_card` artifact. Dry-run flag default true; live flag explicit. Cost cap: hard exit if estimated total spend exceeds €1.00 (~280 cycles).

7. **Fail-open.** If card generation raises an exception OR returns a payload that fails schema validation, the cycle proceeds without a card (status flips to `tier_b_pending` normally). Frontend falls back to `proposal_text`. Card generation must NEVER block a Cortex cycle from reaching the Director.

8. **Latency budget.** Card generation adds ≤8 seconds per cycle (Haiku typical: 2-4s). Cycle absolute timeout (300s) unchanged.

9. **Cost budget.** Card generation costs ≤€0.02 per cycle (Haiku 4.5 typical: ~€0.003). Backfill of current 18 cycles costs ≤€0.50 total.

10. **Tests.**
    - `tests/test_cortex_phase4_5_director_card.py` — 6 cases: (a) happy path returns valid 9-field JSON; (b) malformed proposal_text returns fail-open + sentinel; (c) Haiku API error returns fail-open + sentinel; (d) schema validation catches missing field; (e) prompt-injection in proposal_text (e.g. `[Approve](javascript:...)`) does not produce executable HTML in card output; (f) deterministic output at temperature 0 (same input → same output across two runs).
    - `tests/test_dashboard_cortex_ratify.py` — add 2 cases: pending endpoint returns `director_card` when present; null when absent. Existing 13 tests must continue passing.

## Prompt contract (pinned in this brief, copy verbatim into module)

```
You translate technical AI-generated proposals into plain English for a non-technical executive (Chairman of a real-estate / capital group) who must ratify or reject each proposal in under 30 seconds.

Output ONLY a JSON object with these 9 fields. No prose, no markdown, no explanation. If you cannot extract a field from the input, write "unclear — needs Director review" — never invent.

{
  "matter": "<matter name in plain English, not a slug>",
  "situation": "<one sentence: what's going on right now>",
  "action": "<one sentence: what the system wants to do>",
  "rationale": "<two sentences maximum: why this action makes sense>",
  "downside": "<one line: the worst plausible outcome if the Chairman approves>",
  "no_action_consequence": "<one line: what happens if the Chairman rejects or does nothing>",
  "cost": {
    "ai_money_eur": <float, AI compute cost in EUR>,
    "real_world_money_eur": <float or null, money the action sends/spends>,
    "action_sends_money": <true|false>
  },
  "recommendation": "approve|reject|edit",
  "confidence": "high|medium|low"
}

Rules:
- Plain English. No jargon. No agent / system / pipeline / capability terminology.
- Use the matter's plain name, never the slug.
- "downside" and "no_action_consequence" are mandatory and always populated.
- "confidence" reflects the underlying proposal's internal confidence, not your translation confidence.
- Never embed HTML, markdown links, or JavaScript in any field. Strip them from the source if present.
```

## File:line anchors (verify at brief-pickup; file is volatile)

- `orchestrator/cortex_runner.py` — Phase 4 → 5 transition (grep for `_phase5_act` or `tier_b_pending` write).
- `outputs/dashboard.py:4546` — `list_cortex_cycles_pending` endpoint (PR #223 added).
- `outputs/dashboard.py:4620` — `get_cortex_cycle_trace` endpoint (PR #223 added).
- `outputs/static/app.js:10380` — `_cortexPendingExpansionHtml` (PR #223 added).
- `outputs/static/index.html:14` — cache-bust `app.js?v=115`.
- `migrations/` — NO migration needed; `cortex_phase_outputs` table already accepts any `artifact_type` string.

## Out of scope

- Tier 3-5 dashboard features (flag specialist, edit-then-approve, multi-decision batch) — separate briefs.
- Slack ratify fallback — untouched. The card layer is dashboard-only.
- Backfill of `tier_a_acted` historical cycles — only `tier_b_pending` cycles backfilled (~18 today).
- Director Card on brisen-lab side — separate brief.
- Direct LLM streaming of card to frontend — write-then-read pattern only.

## Ship gate (literal)

1. `pytest tests/test_cortex_phase4_5_director_card.py tests/test_dashboard_cortex_ratify.py -v` — all PASS.
2. **Mandatory local smoke** against prod-like config: spin up local uvicorn on port 8085 against prod Neon read-only, hit `/api/cortex/cycles/pending`, confirm `director_card` field present + schema-valid for at least one cycle (after running backfill in dry-run mode to populate test data).
3. **Mandatory Chrome MCP cursor click verification** on `_cortexPendingExpansionHtml`: confirm the "What I'm Asking" header renders, all 9 fields present, "Show full reasoning" toggle reveals technical proposal_text. Use `elementFromPoint` for the toggle click (skill v1.1 lesson).
4. Cache-bust `app.js?v=115` → `?v=116`.
5. Backfill script dry-run output attached to ship report — Director reviews 1-2 sample cards before live-flag run.

## Reporting

- Bus-post `ship/cortex-director-card-v1` to `lead` with PR link + 1-2 sample Director Cards rendered from real proposals in the dry-run.

## Anchors

- Director ratification: 2026-05-19 chat ("ratified, go" after 5-choice design)
- Origin scar: Director feedback after smoke test of PR #223 — "Language is technical, full of jargon. I don't understand any of these cards."
- ui-surface-prebrief skill v1.1: ~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md
- ui-surface-prebrief V2 hook: ~/baker-vault/_ops/hooks/ui-surface-prebrief-check.sh (gated this brief's creation — first real fire of the hook in production, 2026-05-19 16:48Z; caught `##` vs `###` heading level mismatch immediately)
- Related fast-follow queue: md() XSS allowlist (downside text could contain LLM-injected markdown links → would render through esc-only path; card schema's "no HTML in fields" rule defends against this).
