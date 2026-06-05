---
status: AC_PENDING
brief_id: COCKPIT_UX_S4_S3_FIX_1
dispatch: COCKPIT_UX_S4_S3_FIX_1
to: b1
from: lead
dispatched_by: lead
task_class: presentation-only UX fix (CSS)
harness_v2: applies (small/presentation — light gate)
spec_source: bus #1910 (inline dispatch IS the authoritative spec — no separate brief file written)
gate_plan: G1 lead 20/20 PASS -> light G2 CLEAR (CSS-only) -> MERGED PR #299 (8b4822c) -> POST_DEPLOY_AC pending b1 (verify v80 css live @1280/1440)
prior_envelope: OCR_REEXTRACT_MISSING_1 (PR #294 a34f1ed) — COMPLETE + POST_DEPLOY_AC PASS (#1914); superseded by this dispatch
---

# B1 dispatch — COCKPIT_UX_S4_S3_FIX_1

**Authoritative spec = bus #1910 (inline). No separate brief file exists — confirmed not in git or local (b1 #1919, lead #1923).** Two presentation-only Cockpit UX fixes from a live Nielsen heuristic eval, Director-ratified.

## Scope
- **S4 (catastrophe):** Critical card column clipped off viewport at 1280px, no scroll affordance. Reflow the container to fit. DevTools-confirm the live class first — candidate `.board-view` (`outputs/static/style.css:819`; `app.js:4098` sets `className board-view`).
- **S3 (major):** `.scheduler-banner` `#dc3545` alarm-red for routine auto-restart (`outputs/static/style.css:7`; `app.js` banner logic ~7969). Downgrade to amber/info.

## Constraints
- Surgical CSS only. No data / query / endpoint change.
- Cache-bust `style.css`.
- Fail loud: screenshots at 1280px AND 1440px; report literal pytest output.
- Ship-report to `lead` with PRs / SHA / screenshots; write `CODE_1_RETURN.md`.

Est: ~1-1.5h, Low.
