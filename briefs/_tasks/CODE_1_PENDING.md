# CODE_1_PENDING — DASHBOARD_WHOLE_CARD_WORKING_GLOW_1

status: COMPLETE
completed: 2026-06-02 — PR #58 merged abb3a9c (squash). G0 codex PASS-WITH-NOTE #1614 + G1 lead static PASS (compute glance once + classList.toggle glance-working on WORKING only; dot untouched; amber #d29922; cache-bust v20/v24) + G2 narrow /security-review PASS (no innerHTML/fetch/auth/storage/endpoint; CSS+class-toggle only). Tests: resolver 8/8 + toggle-contract 6/6. POST_DEPLOY_AC = Director visual judge (whole-card amber on live dashboard).
dispatched_by: lead
ship-report recipient: lead
repo: brisen-lab (your brisen-lab checkout; base current main 2d0fc42 — includes #55 dashboard card + #57)
task class: production implementation (dashboard UI, frontend-only)
gate plan: G0 codex (brief PASS-WITH-NOTE #1614) → G1 lead static → G2 narrow /security-review REQUIRED → merge → post-deploy AC (Director visual judge)
bus topics: ship/dashboard-whole-card-working-glow-1

## Context

Canonical brief (READ IN FULL FIRST): `~/baker-vault/_ops/briefs/BRIEF_DASHBOARD_WHOLE_CARD_WORKING_GLOW_1.md` (commit c280969; codex G0 PASS-WITH-NOTE #1614).

Director feedback 2026-06-02: the just-merged DASHBOARD_CARD_WORKSTATE_CLARITY_1 (#55) narrowed the work-state signal to a small dot near the name. Director wants the WHOLE CARD to light amber when an agent is working and go dark when done (the original plan). Restore the whole-card amber glow as the PRIMARY signal AND keep the dot (Director wants both).

## Problem

The work-state signal is now only the small dot. Restore a whole-card amber glow driven by the SAME `WORKING` glance-state; card extinguishes (no glow) when not WORKING.

## Files Modified

(per brief §Stable Paths) — `static/app.js` (`renderCard`: capture `const glance = computeGlanceState(alias)` once, pass to `renderStateDot`, AND `card.classList.toggle("glance-working", glance === "WORKING")`), `static/styles.css` (`.card.glance-working` amber `#d29922` rule + cache-bust → v20), `static/index.html` (`styles.css?v=20`, `app.js?v=24`).

Do NOT touch: `static/glance_state.js` (resolver correct + tested), `renderStateDot`/the dot (Director wants it kept), backend (`bus.py`/`app.py`/`db.py` — no data change).

## Quality Checkpoints (codex #1614 confirmed)

1. WORKING → whole-card amber glow; every other state → no glow ("extinguished"). codex confirmed `classList.toggle` in `renderCard` is the minimal correct hook.
2. Glow auto-extinguishes when WORKING ends — the existing renderCard re-eval (app.js ~1177-1179, "Re-eval card statuses every 5s") that decays the dot also removes the class. No stale-glow gap.
3. ONLY WORKING lights the card — NEW stays dot-only (Director: working→amber, finished→extinguished).
4. Dot unchanged; `node tests/test_glance_state_resolver.js` still 8/8 (regression).
5. Cortex card untouched (its resolver derives only NEW/DONE/IDLE, no WORKING).
6. Amber `#d29922` matches the dot; glow legible on dark bg, not overwhelming.

## Suggested CSS (refine as needed)

```css
.card.glance-working {
  border-color: #d29922;
  box-shadow: 0 0 0 1px #d29922, 0 0 16px rgba(210, 153, 34, 0.38);
  background: rgba(210, 153, 34, 0.07);
}
```

## G2 note (REQUIRED — narrow)

codex #1614: do NOT mark G2 globally N/A on a Tier-A merge. A NARROW /security-review is required confirming: no raw HTML / `innerHTML`, no new fetch/auth/storage, no endpoint/data change — CSS rule + `classList.toggle` only.

## Verification

Per brief §Acceptance. Literal `node tests/test_glance_state_resolver.js` (resolver untouched → 8/8) + a small assertion that `renderCard` toggles `glance-working` iff glance is WORKING (if feasible in the JS harness; else document manual check). Cache-bust every changed asset. Post-deploy: live dashboard working b-code = whole-card amber, dark within ~2 min of finishing → emit `POST_DEPLOY_AC_VERDICT v1` (Director is visual judge).

## Constraints

Frontend-only; no backend/DB/endpoint. Keep the dot. No secrets. No `--no-verify`. Ship to topic `ship/dashboard-whole-card-working-glow-1`; do NOT merge (lead gates). Ship report answers the done rubric + carries POST_DEPLOY_AC_VERDICT (DONE only at Director's live visual sign-off).
